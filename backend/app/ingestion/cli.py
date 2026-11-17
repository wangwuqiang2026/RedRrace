"""批量入库命令行（阶段一步骤 9）。

用法（在 `backend/` 下）：

    python -m app.ingestion.cli --all
    python -m app.ingestion.cli --all --limit 5 --dry-run
    python -m app.ingestion.cli --source-id S013

统计口径（lead 2026-11-13 裁决，已落成 `test_cli_stats.py` 的断言，不是口头承诺）：

- **两栏分列**：`已可解析单元` 与 `已登记但无原件单元`；后者**不计入 ≥50 达标数**。
  现实数据就是这样：登记表 67 行里 `url_or_path` 全是远程 URL，9 部电子书连原件都没采到。
- **卡片与条目数一律以库里真实行数为准**（写完再 `COUNT(*)` 回读），桩件产出多少就报多少；
  不满 plan 的 120 张卡 / 400 条时照实打印缺口与原因，**不往桩件里塞条目凑数**。
- 无 LLM key 时只能显式用桩件，输出第一行就自报「抽取后端=stub」。
- **dry-run 的统计口径**（T1.5 修正，此前该假设是错的）：只做解析与统计，**不调用抽取后端**、
  不写库、不写 `data/parsed`。所以 dry-run 看到的卡片/条目数恒为 0，它回答的是「有多少单元能解析」，
  不是「能抽出多少条」。旧行为下 dry-run 与实跑一样全额付费（T0 报告 §2.2）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import BACKEND_ROOT, get_config
from app.db.migrate import migrate
from app.ingestion.extract import (
    CardDraft,
    Extractor,
    LlmExtractor,
    StubExtractor,
    extract_cards,
)
from app.ingestion.normalize import normalize_time
from app.ingestion.parse import parse_document, save_parsed
from app.ingestion.registry import (
    SourceRecord,
    default_whitelist_path,
    load_registry,
    load_whitelist,
)

# plan 步骤 9 的目标值（卡片 120 / 条目 400）与单元下限 50
TARGET_UNITS = 50
TARGET_CARDS = 120
TARGET_CLAIMS = 400

CARD_TYPE_ORDER = ("person", "event", "place", "time", "relation")

# 快照命名约定：采集侧按 <source_id> 落文件，登记表里 url_or_path 只存远程地址
SNAPSHOT_SUFFIXES = (".html", ".htm", ".pdf", ".epub", ".txt", ".docx")


@dataclass
class Stats:
    """入库统计。字段名会被报告脚本复用，不要随手改名。"""

    considered: int = 0
    parsed_units: int = 0
    units_without_original: int = 0
    failed_units: int = 0
    gate_units: int = 0
    cards: int = 0
    claims: int = 0
    parsed_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    backlog_ids: list[str] = field(default_factory=list)
    card_counts_by_source: dict[str, int] = field(default_factory=dict)
    cards_by_type: dict[str, int] = field(default_factory=dict)
    stub_backend: bool = False
    dry_run: bool = False

    def gap_lines(self) -> list[str]:
        """plan 目标没达成就照实报缺口，并说明原因。"""
        reason = "本轮为桩件演示口径（无 LLM key），不是真实抽取结果" if self.stub_backend else "真实抽取产出不足"
        lines = []
        if self.cards < TARGET_CARDS:
            lines.append(f"缺口: 卡片 {self.cards}/{TARGET_CARDS}，差 {TARGET_CARDS - self.cards}（{reason}）")
        if self.claims < TARGET_CLAIMS:
            lines.append(f"缺口: 事实条目 {self.claims}/{TARGET_CLAIMS}，差 {TARGET_CLAIMS - self.claims}（{reason}）")
        if self.gate_units < TARGET_UNITS:
            lines.append(
                f"缺口: 达标口径单元 {self.gate_units}/{TARGET_UNITS}，"
                f"差 {TARGET_UNITS - self.gate_units}（无原件的 {self.units_without_original} 个不计算在内）"
            )
        return lines

    def lines(self) -> list[str]:
        out = [
            "=== RedTrace 阶段一入库统计 ===",
            (
                "抽取后端=stub（无 LLM key，条目数为演示口径，不得用于达标判定）"
                if self.stub_backend
                else "抽取后端=llm（在线接口，条目数为真实抽取结果）"
            ),
        ]
        if self.dry_run:
            out.append(
                "模式=dry-run（只解析与统计：未调用抽取后端、未写库、未写 data/parsed；"
                "卡片与事实条目恒为 0，不是抽取产出）"
            )
        out += [
            f"本轮纳入单元: {self.considered}",
            f"已可解析单元: {self.parsed_units}",
            f"已登记但无原件单元: {self.units_without_original}（不计入 ≥{TARGET_UNITS} 达标数）",
            f"有原件但解析失败: {self.failed_units}",
            f"达标口径单元数: {self.gate_units}（目标 ≥{TARGET_UNITS}）",
            f"卡片总数: {self.cards}",
            f"事实条目总数: {self.claims}",
            "卡片类型分布: "
            + " / ".join(f"{t} {self.cards_by_type.get(t, 0)}" for t in CARD_TYPE_ORDER),
            f"待人工补录来源数: {len(self.backlog_ids)}",
        ]
        out += self.gap_lines()
        return out


def _candidate_paths(record: SourceRecord, data_dir: Path) -> list[Path]:
    """按约定列出可能的本地原件位置：先登记表声明的路径，再采集侧的快照命名。"""
    candidates: list[Path] = []
    declared = (record.url_or_path or "").strip()
    if declared and not declared.lower().startswith(("http://", "https://")):
        declared_path = Path(declared)
        if declared_path.is_absolute():
            candidates.append(declared_path)
        else:
            candidates.extend([BACKEND_ROOT / declared_path, data_dir / declared_path])
    sid = record.source_id
    for subdir in ("raw/articles", "raw/ebooks", "raw"):
        for suffix in SNAPSHOT_SUFFIXES:
            candidates.append(data_dir / subdir / f"{sid}{suffix}")
    return candidates


def resolve_source_path(record: SourceRecord, data_dir: Path) -> Path | None:
    """找到该来源的本地原件；找不到返回 None（即「已登记但无原件」）。"""
    for candidate in _candidate_paths(record, Path(data_dir)):
        if candidate.is_file():
            return candidate
    return None


def _relative(path: Path, data_dir: Path) -> str:
    """库里存相对 data_dir 的路径，便于整体迁移数据目录（DATA_DIR 口径）。"""
    try:
        return str(Path(path).resolve().relative_to(Path(data_dir).resolve()))
    except ValueError:
        return str(path)


def _whitelist_fields(record: SourceRecord, whitelist) -> dict:
    """从 Whitelist.entries 取 domain/sections/verified，不重新解析 YAML。"""
    from app.ingestion.registry import normalize_org

    entry = whitelist.entries.get(normalize_org(record.publisher)) or {}
    sections = entry.get("sections")
    return {
        "domain": entry.get("domain") or None,
        "sections": json.dumps(sections if isinstance(sections, list) else [], ensure_ascii=False),
        "verified": 1 if entry.get("verified") is True else 0,
    }


def _insert_source(conn: sqlite3.Connection, record: SourceRecord, whitelist, local_path: str) -> None:
    extra = _whitelist_fields(record, whitelist)
    conn.execute(
        """
        INSERT INTO sources (source_id, title, publisher, publish_date, url_or_path, access_date,
                             license_note, corpus_tier, media_type, domain, sections, verified, local_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            title=excluded.title, publisher=excluded.publisher, publish_date=excluded.publish_date,
            url_or_path=excluded.url_or_path, access_date=excluded.access_date,
            license_note=excluded.license_note, corpus_tier=excluded.corpus_tier,
            media_type=excluded.media_type, domain=excluded.domain, sections=excluded.sections,
            verified=excluded.verified, local_path=excluded.local_path
        """,
        (
            record.source_id,
            record.title,
            record.publisher,
            record.publish_date,
            record.url_or_path,
            record.access_date,
            record.license_note,
            record.corpus_tier,
            record.media_type,
            extra["domain"],
            extra["sections"],
            extra["verified"],
            local_path,
        ),
    )


def _insert_cards(conn: sqlite3.Connection, source_id: str, cards: list[CardDraft]) -> None:
    for card in cards:
        conn.execute(
            "INSERT OR IGNORE INTO cards (source_id, type, name, summary) VALUES (?, ?, ?, ?)",
            (source_id, card.type, card.name, card.summary),
        )
        card_id = conn.execute(
            "SELECT card_id FROM cards WHERE source_id=? AND type=? AND name=?",
            (source_id, card.type, card.name),
        ).fetchone()[0]
        for claim in card.claims:
            time_value = normalize_time(claim.value)
            conn.execute(
                """
                INSERT OR IGNORE INTO claims (card_id, source_id, subject, predicate, value, quote,
                                             locator, confidence, time_start, time_end,
                                             time_granularity, time_raw)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    source_id,
                    claim.subject,
                    claim.predicate,
                    claim.value,
                    claim.quote,
                    claim.locator.model_dump_json(),
                    claim.confidence,
                    time_value.start,
                    time_value.end,
                    time_value.granularity,
                    time_value.raw,
                ),
            )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT type, COUNT(*) FROM cards GROUP BY type").fetchall()
    return {row[0]: row[1] for row in rows}


def ingest(
    *,
    registry_path: Path,
    data_dir: Path,
    extractor: Extractor,
    whitelist_path: Path | None = None,
    db_path: Path | None = None,
    backlog_path: Path | None = None,
    limit: int | None = None,
    source_id: str | None = None,
    dry_run: bool = False,
) -> Stats:
    """读登记表 → 定位原件 → 解析 → 抽取 → 入库 → 回读计数。"""
    registry_path = Path(registry_path)
    data_dir = Path(data_dir)
    wl_path = default_whitelist_path() if whitelist_path is None else Path(whitelist_path)

    # 先整批校验（不合格即 ValueError，不写库），再做任何 IO 重的动作
    records = load_registry(registry_path, whitelist_path=wl_path)
    if source_id is not None:
        records = [r for r in records if r.source_id == source_id]
        if not records:
            raise ValueError(f"登记表里没有 source_id={source_id!r} 的行，检查编号是否填错")
    if limit is not None:
        if limit < 0:
            raise ValueError(f"--limit 不能为负：{limit}")
        records = records[:limit]

    whitelist = load_whitelist(wl_path)
    stub_backend = isinstance(extractor, StubExtractor)
    stats = Stats(stub_backend=stub_backend, dry_run=dry_run)
    backlog = Path(backlog_path) if backlog_path is not None else data_dir / "待人工补录.csv"

    conn: sqlite3.Connection | None = None
    if not dry_run:
        target = Path(db_path) if db_path is not None else data_dir / "redtrace.db"
        migrate(target)
        conn = sqlite3.connect(target)
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        for record in records:
            stats.considered += 1
            local = resolve_source_path(record, data_dir)
            if local is None:
                stats.units_without_original += 1
                stats.missing_ids.append(record.source_id)
                continue
            try:
                doc = parse_document(record, local)
            except (ValueError, ImportError) as exc:
                stats.failed_units += 1
                stats.failed_ids.append(record.source_id)
                print(f"[解析失败] {record.source_id}: {exc}")
                continue
            stats.parsed_units += 1
            stats.parsed_ids.append(record.source_id)
            # 解析产物落 `<data_dir>/parsed/<source_id>.json`（计划阶段一步骤 3；审查 I5 的缺口：
            # `save_parsed()` 此前在 CLI 没有任何调用点，跑完全量后目录仍为空，T0 试点那 11 个
            # JSON 是靠运行期注入既有函数才产出的，复现不出来）。
            # out_dir 显式传 `data_dir / "parsed"` 而不是留空走 `default_parsed_dir()`：后者读
            # `Config.data_dir`（即环境变量 `DATA_DIR`），与本次 `--data-dir` 是两份来源——外部设了
            # `DATA_DIR`、或同时给了 `--data-dir X` 时，产物会静默落到另一个目录（规范 8.13 禁止
            # 这种静默分叉）。同一函数的既有测试（`test_parse_locator.py:433`）已锁住「不传参时跟
            # DATA_DIR」，两条路径各有守卫。
            # dry-run 连这里也不写——它的承诺是「只统计、不落任何盘」。
            if not dry_run:
                save_parsed(doc, data_dir / "parsed")
            # dry-run **不调抽取后端**：`extract_cards` 每次都会打一次付费 LLM，原先它落在
            # dry_run 判断之外，于是「先 dry-run 看看规模再实跑」这个省钱假设根本不成立
            # （T0 报告 §2.2：dry-run 跑了 20 分钟无输出才被强制终止，期间每次调用都 140s+）。
            # 代价如实写进输出行：dry-run 看不到卡片与条目数，只能看解析覆盖率。
            if dry_run:
                continue
            cards = extract_cards(doc, record, extractor, backlog_path=backlog)
            if not cards:
                stats.backlog_ids.append(record.source_id)
                continue
            stats.card_counts_by_source[record.source_id] = len(cards)
            if conn is not None:
                _insert_source(conn, record, whitelist, _relative(local, data_dir))
                _insert_cards(conn, record.source_id, cards)
                conn.commit()
        if conn is not None:
            stats.cards = _count(conn, "cards")
            stats.claims = _count(conn, "claims")
            stats.cards_by_type = _count_by_type(conn)
        else:
            stats.cards = sum(stats.card_counts_by_source.values())
            stats.claims = 0
    finally:
        if conn is not None:
            conn.close()

    stats.gate_units = stats.parsed_units
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RedTrace 阶段一语料批量入库")
    parser.add_argument("--all", action="store_true", help="处理登记表全部行")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 行")
    parser.add_argument("--source-id", default=None, help="只处理指定编号的行")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "只解析与统计：不调用抽取后端（零 LLM 花费）、不写库、不写 data/parsed；"
            "因此「卡片总数 / 事实条目总数」恒为 0，不代表抽取产出"
        ),
    )
    parser.add_argument("--registry", default=None, help="登记表路径（默认 data/来源登记表.csv）")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 Config.data_dir）")
    parser.add_argument("--whitelist", default=None, help="白名单路径（默认 data_dir/来源白名单.yml）")
    parser.add_argument("--db", default=None, help="SQLite 库路径（默认 data_dir/redtrace.db）")
    parser.add_argument("--backlog", default=None, help="人工补录表路径（默认 data_dir/待人工补录.csv）")
    parser.add_argument(
        "--backend",
        choices=("stub", "llm"),
        default="stub",
        help="抽取后端；stub 为无 key 环境的演示口径，llm 需要 LLM_API_KEY 等配置",
    )
    parser.add_argument("--stub", default=None, help="桩件结果 JSON（仅 --backend stub 时使用）")
    return parser


def make_extractor(args: argparse.Namespace) -> Extractor:
    if args.backend == "llm":
        return LlmExtractor()
    stub_path = Path(args.stub) if args.stub else BACKEND_ROOT / "tests/fixtures/抽取桩件结果.json"
    return StubExtractor(stub_path)


# ── 数据目录默认值（评审 I-1 / 规范 8.7）──────────────────────────────────────────────
def _default_data_dir() -> Path:
    """`--data-dir` 省略时的落点：一律 `Config.data_dir`，不在此硬编码 `BACKEND_ROOT / "data"`。

    原先这里是硬编码，与同文件 `--data-dir` 的帮助文本「默认 Config.data_dir」自相矛盾；而本任务
    刚把 `save_parsed()` 接上，`data/parsed/` 从此是 T3 建索引与 T5 评测要读的**正式输入**。
    操作者照帮助文本设了 `DATA_DIR` 却忘了 `--data-dir` 时，产物会静默写进另一个目录，下游读到的
    不是这一批——数字复现不出来（计划 6b-4）。这也是 4.13 的反例：选了哪个目录，操作者无法从
    配置判断。优先级：显式 `--data-dir` > 环境变量 `DATA_DIR` > `BACKEND_ROOT/data`（最后一档由
    `config.py:27` 的 BACKEND_ROOT 锚定，保证不随 cwd 漂移，见 `test_config_data_dir_independent_of_cwd`）。
    """
    return get_config().data_dir


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.all or args.source_id):
        print("需要指定 --all 或 --source-id（避免误以为默认就是全量入库）")
        return 2

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir()
    registry = Path(args.registry) if args.registry else data_dir / "来源登记表.csv"
    whitelist = Path(args.whitelist) if args.whitelist else default_whitelist_path()
    db_path = Path(args.db) if args.db else data_dir / "redtrace.db"
    backlog = Path(args.backlog) if args.backlog else data_dir / "待人工补录.csv"

    try:
        extractor = make_extractor(args)
    except RuntimeError as exc:  # 缺 key 之类配置问题：报清楚，不降级
        print(f"[抽取后端不可用] {exc}")
        return 2

    try:
        stats = ingest(
            registry_path=registry,
            data_dir=data_dir,
            extractor=extractor,
            whitelist_path=whitelist,
            db_path=db_path,
            backlog_path=backlog,
            limit=args.limit,
            source_id=args.source_id,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"[登记表校验未通过] {exc}")
        return 2

    for line in stats.lines():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
