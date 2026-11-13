"""来源登记表读取与校验（阶段零：语料来源准入的代码闸门）。

规则来源：plan.md 阶段零步骤 4 与「全局约束」第 1 条；第 9 条见 lead 对阶段零的裁决（2026-11-13）。
九条校验规则：
1. source_id 唯一；
2. source_id / title / url_or_path / access_date 非空（编号还须全表唯一）；
3. publish_date 不得留空，允许字面值「年代不详」；
4. corpus_tier 只允许「核心」或「补充」；
5. media_type 只允许「电子书」或「文章」；
6. 电子书必须有出版社，且出版年必须是落在 1840–2100 的 ASCII 四位年份（不得为「年代不详」或混写；
   写了月/日则月须 1–12、日须 1–31）；
7. 发布者必须在权威来源白名单内（机构名做别名归一后比对）；
8. license_note 非空；
9. 白名单条目的 verified 必须为 true 才算有效准入；false、字段缺失、非布尔值一律视为不可入库。

准入只看 verified 与名称/别名命中：白名单条目的 domain 与 sections **不参与判定**。
空 domain 是合法状态（多数出版社无可直连的独立官网，准入依据是 verify_source 里的官方通报页），
sections 为空只是「栏目未实测」的采编提示，不是准入条件。
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.config import get_config

# publish_date 允许的唯一占位字面值
UNKNOWN_DATE = "年代不详"
CORPUS_TIERS = ("核心", "补充")
MEDIA_TYPES = ("电子书", "文章")

COLUMNS = (
    "source_id",
    "title",
    "publisher",
    "publish_date",
    "url_or_path",
    "access_date",
    "license_note",
    "corpus_tier",
    "media_type",
)

def default_whitelist_path() -> Path:
    """默认白名单路径：跟随 `Config.data_dir`。

    `DATA_DIR` 迁移时闸门必须一起走——否则登记表按新目录读、白名单还留在 backend/data，
    准入判定与运维认知脱节（终审 I-5；`data/README.md` 承诺 DATA_DIR 可整体迁移数据目录）。
    """
    return get_config().data_dir / "来源白名单.yml"

_YEAR_MIN = 1840
_YEAR_MAX = 2100

# 电子书出版年只接受干净的写法：ASCII 四位年份开头，尾部要么是中文年/月/日，要么是分隔符 + 月/日。
# 刻意不用「在串里搜四位数字」，否则 19850、198510、公元前1985、年代不详1985 都会钻过去。
# 刻意用 [0-9] 而不是 \d：\d 会放行全角「１９８５」与阿拉伯-印度数字「١٩٨٥」并原样入库，
# 而阶段一的元数据比对与阶段五时间轴都按 ASCII 解析，那些值会静默失配。
_EBOOK_DATE_RE = re.compile(
    r"""
    ^\s*
    (?P<year>[0-9]{4})\s*
    (?:
          年\s*(?:(?P<m_cn>[0-9]{1,2})\s*月(?:\s*(?P<d_cn>[0-9]{1,2})\s*[日号]?)?)?
        | [-/.]\s*(?P<m_sep>[0-9]{1,2})\s*(?:月|[-/.]\s*(?P<d_sep>[0-9]{1,2})\s*[日号]?)?
    )?
    \s*$
    """,
    re.VERBOSE,
)

# 白名单条目里可能表示机构名的键；YAML 由采编人员维护，容忍中英两种写法
_NAME_KEYS = ("name", "机构", "机构名称", "机构全称", "全称", "发布者", "publisher", "title")
_ALIAS_KEYS = ("aliases", "别名", "简称")
# 顶层为映射时，可能承载机构列表的键
_LIST_KEYS = ("institutions", "whitelist", "sources", "publishers", "organizations", "机构", "名单")
# 核验标记与核验日期的键名（agent B 的 yml 用 verified / verified_at）
_VERIFIED_KEYS = ("verified", "已核验", "核验")
_VERIFIED_AT_KEYS = ("verified_at", "核验日期", "verified_date")


@dataclass
class SourceRecord:
    """一行来源登记记录。"""

    source_id: str
    title: str
    publisher: str
    publish_date: str
    url_or_path: str
    access_date: str
    license_note: str
    corpus_tier: str
    media_type: str


@dataclass(frozen=True)
class Whitelist:
    """白名单比对结果。

    approved：verified 为 true 的条目里的机构全称与别名（归一后），算有效准入；
    pending：verified 为 false、字段缺失或非布尔的条目名 → 该条目的核验日期，
    单独保留是为了报错时能区分「机构不在名单」与「机构在名单但未核验」；
    entries：归一化名（主名与每个别名都算一个键）→ 该条目的原始字段。
    阶段四冲突判定要用 note、阶段七审核台要展示 domain 与 sections，这些信息必须留在
    契约里由本模块一次解析，不能让下游各自重解析 YAML（终审 I-8，plan 全局约束 10）。
    """

    approved: frozenset[str]
    pending: dict[str, str]
    entries: dict[str, dict] = field(default_factory=dict)


def normalize_org(name: str) -> str:
    """机构名归一：全角转半角、去掉所有空白与首尾句点，便于别名比对。

    NFKC 会把全角句点「．」(U+FF0E) 转成半角，但不处理中文句号「。」(U+3002)，
    所以两种句点都要显式去掉，否则「某某出版社。」会判成不在白名单内。
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(text.split())
    return text.strip(".。").strip()


def _ebook_date_fault(match: re.Match[str]) -> str:
    """月/日越界的说明文字；都合法（或没写月日）时返回空串。

    只做宽松的范围校验（1–12 / 1–31），不判大小月——2 月 30 日这类值不值得为此
    引入历法分支，且阶段一的时间归一另有自己的解析口径。
    """
    month = match.group("m_cn") or match.group("m_sep")
    day = match.group("d_cn") or match.group("d_sep")
    if month is not None and not 1 <= int(month) <= 12:
        return f"月份 {int(month)} 不合法（应为 1–12）"
    if day is not None and not 1 <= int(day) <= 31:
        return f"日期 {int(day)} 不合法（应为 1–31）"
    return ""


def _ensure_file(path: Path, purpose: str) -> None:
    """把「传了目录」「文件不存在」归一为 ValueError，别让 OSError 炸穿调用方。"""
    if path.is_dir():
        raise ValueError(f"{purpose}不是文件，是个目录：{path}")
    if not path.is_file():
        raise ValueError(f"{purpose}不存在：{path}")


def _read_registry_rows(csv_path: Path) -> list[dict[str, str]]:
    """读登记表 CSV 原始行，编码与列缺失都归一为可操作的 ValueError。"""
    _ensure_file(csv_path, "登记表")
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            missing = [col for col in COLUMNS if col not in header]
            if missing:
                raise ValueError(f"登记表缺少列：{', '.join(missing)}")
            return list(reader)
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"登记表不是 UTF-8 编码，无法读取：{csv_path}（{exc.reason}）；"
            f"Excel 另存时请选「CSV UTF-8」，默认的「CSV」在本机会存成 GBK"
        ) from exc


def _read_text(path: Path, purpose: str) -> str:
    """按 UTF-8（兼容 BOM）读文本，编码问题归一为 ValueError。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{purpose}不是 UTF-8 编码，无法读取：{path}（{exc.reason}）；请用 UTF-8 另存"
        ) from exc


def _iter_entries(payload: Any) -> list[Any]:
    """把 YAML 顶层结构归一为机构条目列表。"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        # 兜底：以机构名为键的映射 {人民出版社: {...}}
        return list(payload.keys())
    raise ValueError("whitelist 文件内容无法识别（既不是列表也不是映射）")


def _entry_names(entry: Any) -> list[str]:
    """取出一个白名单条目的机构全称与全部别名。"""
    if isinstance(entry, str):
        return [entry]
    if not isinstance(entry, dict):
        return []
    names: list[str] = []
    for key in _NAME_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value)
            break
    for key in _ALIAS_KEYS:
        aliases = entry.get(key)
        if isinstance(aliases, str) and aliases.strip():
            names.append(aliases)
        elif isinstance(aliases, list):
            names.extend(a for a in aliases if isinstance(a, str) and a.strip())
    return names


def _entry_verified_flag(entry: Any) -> bool:
    """条目是否算「已核验」：只认布尔 True。

    false、字段缺失、非布尔值（字符串 "true"、整数 1、"yes"）一律判为未核验，
    与白名单头部「verified: false 的条目一律不得入库」的承诺口径一致。
    """
    if not isinstance(entry, dict):
        return False
    for key in _VERIFIED_KEYS:
        if key in entry:
            return entry[key] is True
    return False


def _entry_verified_at(entry: Any) -> str:
    """取条目的核验日期用于报错提示；YAML 会把 YYYY-MM-DD 解析成 date，统一转字符串。"""
    if not isinstance(entry, dict):
        return ""
    for key in _VERIFIED_AT_KEYS:
        value = entry.get(key)
        if isinstance(value, bool) or value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _entry_primary_name(entry: Any) -> str:
    """只取条目声明的主名（`name` 键），与别名区分，供借道冲突判定的报错定位。"""
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        return ""
    for key in _NAME_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def load_whitelist(whitelist_path: Path) -> Whitelist:
    """读取白名单，分成「已核验可准入」与「未核验」两组归一化名。

    别名继承所属条目的 verified 状态：未核验条目的全称与全部别名都进 pending，
    否则换个写法就能绕过闸门。

    C-1：未核验条目的任何名字（主名或别名）若同时被某个 verified: true 的条目收录，
    说明名单自相矛盾——借道即可把未核验机构洗白，此时直接报错要求人工裁决，
    而不是按「以已核验为准」静默放行。只有重复发生在两条已核验条目之间时才照常共用。
    """
    _ensure_file(whitelist_path, "whitelist 文件")
    try:
        payload = yaml.safe_load(_read_text(whitelist_path, "whitelist 文件"))
    except yaml.YAMLError as exc:
        raise ValueError(
            f"whitelist 文件 YAML 语法错误，无法解析：{whitelist_path}（{exc}）"
        ) from exc
    if payload is None:
        raise ValueError(f"whitelist 文件为空：{whitelist_path}")
    approved: set[str] = set()
    pending: dict[str, str] = {}
    entries: dict[str, dict] = {}
    unverified_owner: dict[str, str] = {}  # 未核验条目的名字 -> 该条目主名，供报错定位
    for entry in _iter_entries(payload):
        names = [n for n in (normalize_org(x) for x in _entry_names(entry)) if n]
        primary = normalize_org(_entry_primary_name(entry))
        raw = entry if isinstance(entry, dict) else {"name": entry}
        for name in names:
            entries.setdefault(name, raw)
        if _entry_verified_flag(entry):
            approved.update(names)
        else:
            stamp = _entry_verified_at(entry)
            for name in names:
                pending.setdefault(name, stamp)
                unverified_owner.setdefault(name, primary or name)
    if not approved and not pending:
        raise ValueError(f"whitelist 文件未列出任何机构：{whitelist_path}")
    conflicts = sorted(approved & set(unverified_owner))
    if conflicts:
        detail = "、".join(f"「{c}」（属未核验条目「{unverified_owner[c]}」）" for c in conflicts[:5])
        more = "" if len(conflicts) <= 5 else f" 等 {len(conflicts)} 处"
        raise ValueError(
            f"whitelist 名单自相矛盾：{detail}{more} 同时被某个 verified: true 的条目收录，"
            f"借这个名字即可绕过 verified 闸门，须人工裁决（合并条目或删除该别名）：{whitelist_path}"
        )
    return Whitelist(frozenset(approved), pending, entries)


def load_registry(csv_path: Path, whitelist_path: Path | None = None) -> list[SourceRecord]:
    """读取来源登记表并逐行校验，任一行不合格即抛 ValueError。

    白名单采用惰性加载：仅在某行需要通过前面的字段校验、真正要比对发布者时才读取文件。
    这样「出版年留空」之类的错误会先于「白名单文件缺失」报出，报错更贴近实际问题。
    """
    explicit_path = None if whitelist_path is None else Path(whitelist_path)
    _cache: list[tuple[Path, Whitelist] | None] = [None]

    def whitelist() -> tuple[Path, Whitelist]:
        """惰性解析并加载白名单：默认路径要读配置，只在真正要比对发布者时才执行。

        惰性有两个好处：「出版年留空」之类的行级错误先于「白名单文件缺失」报出；
        不需要白名单的失败路径也不会去读 DATA_DIR。
        """
        if _cache[0] is None:
            path = explicit_path if explicit_path is not None else default_whitelist_path()
            _cache[0] = (path, load_whitelist(path))
        return _cache[0]

    raw_rows = _read_registry_rows(Path(csv_path))

    records: list[SourceRecord] = []
    seen_ids: dict[str, int] = {}
    for line_no, raw in enumerate(raw_rows, start=2):
        values = {col: (raw.get(col) or "").strip() for col in COLUMNS}
        where = f"第 {line_no} 行（{values['source_id'] or '无编号'}）"

        # 规则 2：编号、标题、链接或路径、获取日期非空（编号同时要求唯一，见规则 1）
        for col in ("source_id", "title", "url_or_path", "access_date"):
            if not values[col]:
                raise ValueError(f"{where}：{col} 不得留空")

        # 规则 3：出版年不得留空，允许字面值「年代不详」
        if not values["publish_date"]:
            raise ValueError(f"{where}：publish_date 不得留空（未知请填写「{UNKNOWN_DATE}」）")

        # 规则 8：授权或公开获取说明非空
        if not values["license_note"]:
            raise ValueError(f"{where}：license_note 不得留空")

        # 规则 4：语料层级枚举
        if values["corpus_tier"] not in CORPUS_TIERS:
            raise ValueError(f"{where}：corpus_tier 只能是 {' 或 '.join(CORPUS_TIERS)}")

        # 规则 5：载体类型枚举
        if values["media_type"] not in MEDIA_TYPES:
            raise ValueError(f"{where}：media_type 只能是 {' 或 '.join(MEDIA_TYPES)}")

        # 规则 6：电子书必须有出版社与非「年代不详」的四位年份出版年
        if values["media_type"] == "电子书":
            if not values["publisher"]:
                raise ValueError(f"{where}：电子书必须填写 publisher（出版社）")
            date_match = _EBOOK_DATE_RE.match(values["publish_date"])
            if date_match is None:
                raise ValueError(
                    f"{where}：电子书的 publish_date 必须是四位出版年（ASCII 数字，可带月日），"
                    f"不得为「{UNKNOWN_DATE}」或混写（当前值 {values['publish_date']!r}）"
                )
            fault = _ebook_date_fault(date_match)
            if fault:
                raise ValueError(
                    f"{where}：电子书的 publish_date {fault}（当前值 {values['publish_date']!r}）"
                )
            year = int(date_match.group("year"))
            if not _YEAR_MIN <= year <= _YEAR_MAX:
                raise ValueError(
                    f"{where}：电子书的 publish_date 年份 {year} 不在合理区间 "
                    f"{_YEAR_MIN}–{_YEAR_MAX}（当前值 {values['publish_date']!r}）"
                )

        # 规则 7 + 9：发布者必须在白名单内，且该条目 verified 为 true 才算有效准入
        publisher = normalize_org(values["publisher"])
        wl_path, wl = whitelist()
        if publisher not in wl.approved:
            if publisher in wl.pending:
                raise ValueError(
                    f"{where}：publisher「{values['publisher']}」在 whitelist 内但 verified 不为 "
                    f"true（verified_at: {wl.pending[publisher] or '未记录'}），"
                    f"待核验，补核后改 true 才能入库：{wl_path}"
                )
            raise ValueError(
                f"{where}：publisher「{values['publisher']}」不在权威来源 whitelist 内：{wl_path}"
            )

        # 规则 1：编号唯一
        if values["source_id"] in seen_ids:
            raise ValueError(
                f"{where}：source_id「{values['source_id']}」与第 {seen_ids[values['source_id']]} 行重复"
            )
        seen_ids[values["source_id"]] = line_no

        records.append(SourceRecord(**values))
    return records
