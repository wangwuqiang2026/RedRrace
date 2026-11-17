"""批量入库与两栏统计（阶段一步骤 9）。

这条链是三处口径的交汇点，所以断言写得偏硬：

1. **两栏必须分开**（lead 裁决）：`已可解析` 与 `已登记但无原件`，后者**不计入 ≥50 达标数**；
2. **写了多少就是多少**：统计数必须等于库里真实行数，桩件产出不满 120/400 就照实报缺口，
   不许为了好看往桩件里塞条目（简报「达标口径（诚实线）」）；
3. **无 key 环境必须自报是桩件**，否则数字会被当成真实抽取结果。

抽取后端一律通过 `Extractor` 注入，统计函数不自己判断该用哪个后端。
"""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from helpers import row, write_registry, write_whitelist

from app.ingestion.cli import CARD_TYPE_ORDER, Stats, ingest, main, resolve_source_path
from app.ingestion.extract import VALID_CARD_TYPES, StubExtractor
from app.ingestion.registry import SourceRecord

STUB_FILE = Path("tests/fixtures/抽取桩件结果.json")

SNAPSHOT_HTML = """<!DOCTYPE html><html><body><article>
<h1 id="t">{title}</h1>
<p id="p1">{title}于一九三五年五月在此地渡河，部队伤亡三百余人。</p>
<p id="p2">此地此后被改为纪念场所，一九四九年四月正式开放。</p>
</article></body></html>
"""


def body_lines(title):
    """与 SNAPSHOT_HTML 逐字一致的两句正文（桩件引文必须原样命中）。"""
    return (
        f"{title}于一九三五年五月在此地渡河，部队伤亡三百余人。",
        "此地此后被改为纪念场所，一九四九年四月正式开放。",
    )


def stub_payload(source_ids):
    """给指定来源造一份「引文逐字对得上原文」的桩件条目。"""
    data = {}
    for sid in source_ids:
        title = f"文章{sid}"
        first, second = body_lines(title)
        loc1 = {"paragraph": 1, "heading_path": [title], "quote": first, "url_anchor": "p1"}
        loc2 = {"paragraph": 2, "heading_path": [title], "quote": second, "url_anchor": "p2"}
        data[sid] = [
            {
                "type": "event",
                "name": f"{sid} 渡河",
                "summary": "演示事件卡",
                "claims": [
                    {
                        "subject": title,
                        "predicate": "事件时间",
                        "value": "一九三五年五月",
                        "quote": first,
                        "locator": loc1,
                        "confidence": 0.9,
                    },
                    {
                        "subject": title,
                        "predicate": "事件地点",
                        "value": "此地",
                        "quote": first,
                        "locator": loc1,
                        "confidence": 0.7,
                    },
                ],
            },
            {
                "type": "place",
                "name": f"{sid} 纪念场所",
                "summary": "演示地点卡",
                "claims": [
                    {
                        "subject": "此地",
                        "predicate": "事件时间",
                        "value": "一九四九年四月",
                        "quote": second,
                        "locator": loc2,
                        "confidence": 0.8,
                    }
                ],
            },
        ]
    return data


def make_data_dir(tmp_path, articles=(), ebooks=()):
    """搭一个临时数据目录：登记表 + raw/articles 快照 + 白名单。"""
    data_dir = tmp_path / "data"
    (data_dir / "raw" / "articles").mkdir(parents=True, exist_ok=True)
    rows = []
    for sid in articles:
        rows.append(
            row(
                source_id=sid,
                title=f"文章{sid}",
                publisher="人民出版社",
                publish_date="1985",
                url_or_path="https://example.com/a.html",
                media_type="文章",
            )
        )
        (data_dir / "raw" / "articles" / f"{sid}.html").write_text(
            SNAPSHOT_HTML.format(title=f"文章{sid}"), encoding="utf-8"
        )
    for sid in ebooks:
        rows.append(
            row(
                source_id=sid,
                title=f"书{sid}",
                publisher="人民出版社",
                publish_date="1985",
                url_or_path="https://example.com/book.html",
                media_type="电子书",
            )
        )
    registry = write_registry(data_dir, *rows, name="来源登记表.csv")
    whitelist = write_whitelist(data_dir)
    return data_dir, registry, whitelist


def run_ingest(tmp_path, data_dir, registry, whitelist, articles, db_name="t.db", **over):
    kwargs = {
        "registry_path": registry,
        "data_dir": data_dir,
        "whitelist_path": whitelist,
        "db_path": data_dir / db_name,
        "extractor": StubExtractor(stub_payload(list(articles))),
    }
    kwargs.update(over)
    return ingest(**kwargs)


def count(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── 原件定位 ──────────────────────────────────────────────────────────────────────────
def test_resolve_prefers_declared_local_path(tmp_path):
    data_dir = tmp_path / "data"
    real = data_dir / "raw" / "custom.html"
    real.parent.mkdir(parents=True)
    real.write_text(SNAPSHOT_HTML.format(title="甲"), encoding="utf-8")
    record = SourceRecord(**row(media_type="文章", url_or_path=str(real)))
    assert resolve_source_path(record, data_dir) == real


def test_resolve_falls_back_to_snapshot_convention(tmp_path):
    """登记表里 url_or_path 全是远程 URL，本地快照按 raw/articles/<source_id>.html 找。"""
    data_dir, _, _ = make_data_dir(tmp_path, articles=["S101"])
    found = resolve_source_path(SourceRecord(**row(source_id="S101", media_type="文章")), data_dir)
    assert found is not None and found.name == "S101.html"


def test_resolve_returns_none_when_no_local_original(tmp_path):
    data_dir, _, _ = make_data_dir(tmp_path, articles=["S101"], ebooks=["S201"])
    ebook = SourceRecord(**row(source_id="S201", media_type="电子书"))
    assert resolve_source_path(ebook, data_dir) is None


# ── 两栏统计（lead 裁决的核心断言）─────────────────────────────────────────────────────
def test_parsed_and_missing_are_counted_separately(tmp_path):
    data_dir, registry, whitelist = make_data_dir(
        tmp_path, articles=["S101", "S102", "S103"], ebooks=["S201", "S202"]
    )
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101", "S102", "S103"], db_name="a.db")
    assert stats.parsed_units == 3
    assert stats.units_without_original == 2, "无原件必须单独一栏"
    assert stats.gate_units == 3, "≥50 达标数只算已可解析单元"
    assert stats.gate_units != stats.parsed_units + stats.units_without_original


def test_ebooks_without_original_never_land_in_parsed_column(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"], ebooks=["S201"])
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="b.db")
    assert "S201" not in stats.parsed_ids
    assert "S201" in stats.missing_ids
    assert stats.parsed_units == 1


def test_registry_is_validated_before_any_parsing(tmp_path):
    """登记表不合格就整批拒收：错误带行号、且不写库（三件事都要断言，见下方 db 不存在）。"""
    data_dir, _registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    bad = write_registry(
        tmp_path, row(source_id="S101"), row(source_id="S102", publish_date=""), name="坏登记表.csv"
    )
    db = data_dir / "bad.db"
    backlog = data_dir / "待人工补录.csv"
    with pytest.raises(ValueError, match="第 3 行") as exc:
        ingest(
            registry_path=bad,
            data_dir=data_dir,
            whitelist_path=whitelist,
            db_path=db,
            extractor=StubExtractor(stub_payload(["S101"])),
        )
    # 三件事都要锁住：整批拒收（异常）＋ 错误能定位到行 ＋ 完全没开始解析与写库
    assert "publish_date 不得留空" in str(exc.value), "错误信息要能指出是哪条规则没过"
    assert "S102" in str(exc.value), "要带上出错行的编号"
    assert not db.exists(), "校验没过就不许建库"
    assert not backlog.exists(), "校验没过就不许已经跑过抽取并写补录表"


# ── 写了多少就是多少 ──────────────────────────────────────────────────────────────────
def test_counts_match_rows_actually_written(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"])
    db = data_dir / "c.db"
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101", "S102"], db_name="c.db")
    assert count(db, "sources") == stats.parsed_units
    assert count(db, "cards") == stats.cards
    assert count(db, "claims") == stats.claims
    assert stats.parsed_units == 2, "入库来源数必须等于已可解析单元数"
    # 等式本身会被「整批没写库」骗过去（两边都是 0 也相等），所以再用确定值锚一次
    assert stats.cards == 4 and stats.claims == 6, "受控桩件应产出 2 源 × (2 卡 + 3 条)"
    assert count(db, "cards") == 4 and count(db, "claims") == 6


def test_sources_without_stub_entry_yield_zero_items_not_fabricated_ones(tmp_path):
    """桩件里没有的来源就是 0 卡 0 条：宁可报缺口，也不凭空造条目。"""
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102", "S103"])
    db = data_dir / "d.db"
    stats = ingest(
        registry_path=registry,
        data_dir=data_dir,
        whitelist_path=whitelist,
        db_path=db,
        extractor=StubExtractor(stub_payload(["S101"])),  # 只有 S101 有桩件
    )
    assert stats.parsed_units == 3
    assert list(stats.card_counts_by_source) == ["S101"]
    assert stats.cards == 2 and stats.claims == 3, "只算真产出的那一份，不按 3 个单元放大"
    assert set(stats.backlog_ids) == {"S102", "S103"}


def test_gap_is_reported_honestly_when_below_plan_targets(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="e.db")
    gaps = stats.gap_lines()
    assert any("120" in line for line in gaps)
    assert any("400" in line for line in gaps)
    assert any("缺口" in line for line in gaps)
    assert stats.stub_backend is True


# ── 落库内容 ──────────────────────────────────────────────────────────────────────────
def test_written_source_row_carries_whitelist_and_local_path(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    db = data_dir / "f.db"
    run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="f.db")
    with sqlite3.connect(db) as conn:
        row_db = conn.execute(
            "SELECT verified, local_path, media_type FROM sources WHERE source_id='S101'"
        ).fetchone()
    assert row_db[0] == 1, "白名单 verified 要落到来源表"
    assert row_db[1] and row_db[1].endswith("S101.html"), "原件落点要记下来"
    assert row_db[2] == "文章"


def test_claim_time_columns_are_normalized(tmp_path):
    """时间四列必须是归一后的值，否则阶段四冲突检测与阶段五时间轴无法比对。"""
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    db = data_dir / "g.db"
    run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="g.db")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT predicate, time_granularity, time_start, time_raw FROM claims"
        ).fetchall()
    assert rows
    times = [r for r in rows if r[0] == "事件时间"]
    assert times
    for _predicate, granularity, start, raw in times:
        assert granularity in ("year", "month", "day", "range", "unknown")
        assert raw, "无论能否解析，原文都要留在 time_raw"
        if granularity != "unknown":
            assert start


def test_locator_json_round_trips(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    db = data_dir / "h.db"
    run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="h.db")
    with sqlite3.connect(db) as conn:
        payload = conn.execute("SELECT locator, quote FROM claims LIMIT 1").fetchone()
    locator = json.loads(payload[0])
    assert locator["quote"] == payload[1]
    assert locator["paragraph"]


# ── dry-run / limit / source-id ───────────────────────────────────────────────────────
def test_dry_run_counts_but_writes_nothing(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"])
    db = data_dir / "i.db"
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101", "S102"], db_name="i.db", dry_run=True)
    assert stats.parsed_units == 2 and stats.dry_run is True
    assert not db.exists(), "dry-run 不得建库"


def test_limit_reduces_scope(tmp_path):
    data_dir, registry, whitelist = make_data_dir(
        tmp_path, articles=["S101", "S102", "S103", "S104"]
    )
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, [], db_name="j.db", limit=2,
                       extractor=StubExtractor(stub_payload(["S101", "S102"])))
    assert stats.considered == 2
    assert stats.parsed_units == 2


def test_source_id_filter_selects_single_unit(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"], ebooks=["S201"])
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S102"], db_name="k.db", source_id="S102")
    assert stats.considered == 1 and stats.parsed_units == 1


def test_unknown_source_id_is_reported(tmp_path):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    with pytest.raises(ValueError, match="S999"):
        run_ingest(tmp_path, data_dir, registry, whitelist, [], db_name="m.db", source_id="S999")


# ── T1.5 缺陷二：--dry-run 必须零 LLM 调用（P1）───────────────────────────────────────
class CountingExtractor:
    """计数替身：记录被调了几次抽取。

    「确实没被调用」只能靠显式计数断言（规范 5.18），不能靠耗时或输出反推——T0 队友就是
    以为 dry-run 省钱，跑了 20 分钟付费调用才被强制终止的（task0-report §2.2）。
    """

    def __init__(self, articles):
        self._payload = stub_payload(list(articles))
        self.calls = 0

    def extract(self, doc, source):
        self.calls += 1
        return copy.deepcopy(self._payload.get(doc.source_id) or [])


def test_dry_run_makes_zero_extractor_calls(tmp_path):
    """dry-run 只做解析与统计，一次模型都不调。"""
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"])
    counter = CountingExtractor(["S101", "S102"])
    stats = ingest(
        registry_path=registry,
        data_dir=data_dir,
        whitelist_path=whitelist,
        db_path=data_dir / "n.db",
        extractor=counter,
        dry_run=True,
    )
    assert stats.parsed_units == 2, "先锚定确定值：解析确实跑到了，否则 calls==0 是空转假绿（规范 5.13）"
    assert counter.calls == 0, f"dry-run 仍调用抽取后端 {counter.calls} 次：每一次都是付费调用"


def test_real_run_does_call_the_extractor(tmp_path):
    """反向对照：非 dry-run 必须真的调用。

    若把「跳过抽取」写成无条件分支，上一条会一起变绿——没有这条，前一条拦不住过度修复。
    """
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"])
    counter = CountingExtractor(["S101", "S102"])
    stats = ingest(
        registry_path=registry,
        data_dir=data_dir,
        whitelist_path=whitelist,
        db_path=data_dir / "o.db",
        extractor=counter,
        dry_run=False,
    )
    assert counter.calls == 2, f"实跑应当每单元调用一次，实际 {counter.calls}"
    assert stats.cards == 4 and stats.claims == 6, "桩件口径：2 源 × (2 卡 + 3 条)"


def test_main_dry_run_reports_no_llm_calls(tmp_path, capsys):
    """命令行层同样零调用，并在输出里自报口径，避免下一个人再按「dry-run 省钱」的假设踩坑。"""
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S001"])
    db = data_dir / "dry2.db"
    code = main(cli_args(tmp_path, registry, whitelist, data_dir, db, extra=["--dry-run"]))
    out = capsys.readouterr().out
    assert code == 0
    assert not db.exists(), "dry-run 不得建库"
    assert "未调用抽取后端" in out, (
        "dry-run 输出必须写明「不调模型、卡片条目为 0、不是抽取产出」，"
        "否则读输出的人会把它当成真实抽取结果（规范 4.3 禁止界面显示开启、实际空转）"
    )


# ── T1.5 缺陷三：save_parsed() 必须接进 CLI 正常路径（P2）─────────────────────────────
def test_ingest_writes_parsed_json_per_source(tmp_path):
    """解析产物落 `<data_dir>/parsed/<source_id>.json`，且内容可被重新解析（计划阶段一步骤 3）。

    T3/T5 的引文逐字定位与覆盖率口径依赖这份产物；试点那 11 个 JSON 是靠运行期注入既有函数
    才产出的，磁盘代码一行没改（task0-report §2.4），所以这里必须由正常路径产出。
    """
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101", "S102"], ebooks=["S201"])
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101", "S102"], db_name="redtrace.db")
    assert stats.parsed_units == 2, "先锚定两个已解析单元，否则下面的文件数断言可能是空目录巧合"

    parsed_dir = data_dir / "parsed"
    produced = sorted(p.name for p in parsed_dir.glob("*.json"))
    assert produced == ["S101.json", "S102.json"], (
        f"parsed 产物落点/数量不对：{produced}（应为每个已解析来源一个 <source_id>.json）"
    )
    assert not (parsed_dir / "S201.json").exists(), "无原件的来源不得凭空产出解析文件"

    payload = json.loads((parsed_dir / "S101.json").read_text(encoding="utf-8"))
    assert payload["source_id"] == "S101"
    first_quote, _second = body_lines("文章S101")
    assert any(b["text"] == first_quote for b in payload["blocks"]), (
        "解析产物必须原样保留文本块，否则阶段三逐字比对没有底本"
    )
    assert payload["full_text"] == "\n".join(b["text"] for b in payload["blocks"])
    text = (parsed_dir / "S101.json").read_text(encoding="utf-8")
    assert "\\u" not in text, "解析产物不得转义中文（规范 6.12 落盘口径：ensure_ascii=False）"
    assert text.endswith("\n"), "JSON 产物带尾换行，与既有落盘产物一致（规范 6.12）"

    locator = payload["blocks"][0]["locator"]
    assert locator["paragraph"] == 1 and locator["quote"] == first_quote


def test_dry_run_writes_no_parsed_artifacts(tmp_path):
    """dry-run 连解析产物也不写：它的承诺是「只统计不写任何东西」。"""
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S101"])
    stats = run_ingest(tmp_path, data_dir, registry, whitelist, ["S101"], db_name="p.db", dry_run=True)
    assert stats.parsed_units == 1
    assert not (data_dir / "parsed").exists(), "dry-run 不得往数据目录写解析产物"


def test_main_writes_parsed_into_data_dir(tmp_path, capsys):
    """走 `main()` 的完整命令行路径也要产出 parsed——这是采编实际用的入口，注入只在测试里有意义。

    `--stub` 指向仓库桩件（只覆盖 S001），所以夹具里的来源编号必须用 S001，
    否则抽取拿不到产出、卡片为 0，测的就不是「正常路径有产出」这件事了。
    """
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S001"])
    db = data_dir / "cli.db"
    code = main(cli_args(tmp_path, registry, whitelist, data_dir, db))
    assert code == 0
    assert (data_dir / "parsed" / "S001.json").is_file(), (
        "CLI 正常路径没有调用 save_parsed：跑完全量后 data/parsed/ 仍为空（审查 I5 缺口）"
    )


# ── 命令行输出 ────────────────────────────────────────────────────────────────────────
def cli_args(tmp_path, registry, whitelist, data_dir, db, extra=()):
    return [
        "--all",
        "--registry",
        str(registry),
        "--data-dir",
        str(data_dir),
        "--whitelist",
        str(whitelist),
        "--db",
        str(db),
        "--stub",
        str(STUB_FILE),
        *extra,
    ]


def test_main_prints_stub_declaration_and_two_columns(tmp_path, capsys):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S001"], ebooks=["S201"])
    db = data_dir / "cli.db"
    code = main(cli_args(tmp_path, registry, whitelist, data_dir, db))
    out = capsys.readouterr().out
    assert code == 0
    assert "抽取后端=stub" in out
    assert "不得用于达标判定" in out
    assert "已可解析" in out and "无原件" in out


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    data_dir, registry, whitelist = make_data_dir(tmp_path, articles=["S001"])
    db = data_dir / "dry.db"
    code = main(cli_args(tmp_path, registry, whitelist, data_dir, db, extra=["--dry-run"]))
    assert code == 0
    assert not db.exists()


def test_stats_dataclass_fields_are_locked():
    """统计对象会被报告脚本直接复用，字段名不许随手改。"""
    fields = set(Stats.__dataclass_fields__)
    assert {
        "parsed_units",
        "units_without_original",
        "gate_units",
        "cards",
        "claims",
        "stub_backend",
    } <= fields


def test_display_order_matches_validation_set():
    """展示用的类型顺序与校验用的类型集合是两份清单，必须锁成同一批值。"""
    assert set(CARD_TYPE_ORDER) == VALID_CARD_TYPES
