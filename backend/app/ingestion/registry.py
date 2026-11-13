"""来源登记表读取与校验（阶段零：语料来源准入的代码闸门）。

规则来源：plan.md 阶段零步骤 4 与「全局约束」第 1 条；第 9 条见 lead 对阶段零的裁决（2026-11-13）。
九条校验规则：
1. source_id 唯一；
2. title / url_or_path / access_date 非空；
3. publish_date 不得留空，允许字面值「年代不详」；
4. corpus_tier 只允许「核心」或「补充」；
5. media_type 只允许「电子书」或「文章」；
6. 电子书必须有出版社，且出版年必须是落在 1840–2100 的四位年份（不得为「年代不详」或混写）；
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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

# 默认白名单路径：backend/data/来源白名单.yml
DEFAULT_WHITELIST_PATH = Path(__file__).resolve().parents[2] / "data" / "来源白名单.yml"

_YEAR_MIN = 1840
_YEAR_MAX = 2100

# 电子书出版年只接受干净的写法：四位年份开头，尾部要么是中文年/月/日，要么是分隔符 + 月/日。
# 刻意不用「在串里搜四位数字」，否则 19850、198510、公元前1985、年代不详1985 都会钻过去。
_EBOOK_DATE_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s*(?:"
    r"年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?)?"
    r"|[-/.]\s*\d{1,2}(?:\s*月|[-/.]\s*\d{1,2}\s*[日号]?)?"
    r")?\s*$"
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
    单独保留是为了报错时能区分「机构不在名单」与「机构在名单但未核验」。
    """

    approved: frozenset[str]
    pending: dict[str, str]


def normalize_org(name: str) -> str:
    """机构名归一：全角转半角、去掉所有空白与首尾句点，便于别名比对。

    NFKC 会把全角句点「．」(U+FF0E) 转成半角，但不处理中文句号「。」(U+3002)，
    所以两种句点都要显式去掉，否则「某某出版社。」会判成不在白名单内。
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = "".join(text.split())
    return text.strip(".。").strip()


def _ebook_publish_year(publish_date: str) -> int | None:
    """取电子书出版年里的四位年份；写法不干净（混字、粘连、多余数字）时返回 None。"""
    match = _EBOOK_DATE_RE.match(publish_date)
    return int(match.group("year")) if match else None


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


def load_whitelist(whitelist_path: Path) -> Whitelist:
    """读取白名单，分成「已核验可准入」与「未核验」两组归一化名。

    别名继承所属条目的 verified 状态：未核验条目的全称与全部别名都进 pending，
    否则换个写法就能绕过闸门。
    """
    if not whitelist_path.is_file():
        raise ValueError(f"whitelist 文件不存在：{whitelist_path}")
    payload = yaml.safe_load(whitelist_path.read_text(encoding="utf-8"))
    if payload is None:
        raise ValueError(f"whitelist 文件为空：{whitelist_path}")
    approved: set[str] = set()
    pending: dict[str, str] = {}
    for entry in _iter_entries(payload):
        names = [n for n in (normalize_org(x) for x in _entry_names(entry)) if n]
        if _entry_verified_flag(entry):
            approved.update(names)
        else:
            stamp = _entry_verified_at(entry)
            for name in names:
                pending.setdefault(name, stamp)
    if not approved and not pending:
        raise ValueError(f"whitelist 文件未列出任何机构：{whitelist_path}")
    for name in approved:
        pending.pop(name, None)  # 同名同时出现时以已核验为准
    return Whitelist(frozenset(approved), pending)


def load_registry(csv_path: Path, whitelist_path: Path | None = None) -> list[SourceRecord]:
    """读取来源登记表并逐行校验，任一行不合格即抛 ValueError。

    白名单采用惰性加载：仅在某行需要通过前面的字段校验、真正要比对发布者时才读取文件。
    这样「出版年留空」之类的错误会先于「白名单文件缺失」报出，报错更贴近实际问题。
    """
    wl_path = Path(whitelist_path) if whitelist_path is not None else DEFAULT_WHITELIST_PATH
    _cache: list[Whitelist | None] = [None]

    def whitelist() -> Whitelist:
        if _cache[0] is None:
            _cache[0] = load_whitelist(wl_path)
        return _cache[0]

    with Path(csv_path).open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [col for col in COLUMNS if col not in header]
        if missing:
            raise ValueError(f"登记表缺少列：{', '.join(missing)}")
        raw_rows = list(reader)

    records: list[SourceRecord] = []
    seen_ids: dict[str, int] = {}
    for line_no, raw in enumerate(raw_rows, start=2):
        values = {col: (raw.get(col) or "").strip() for col in COLUMNS}
        where = f"第 {line_no} 行（{values['source_id'] or '无编号'}）"

        # 规则 2：标题、链接或路径、获取日期非空
        for col in ("title", "url_or_path", "access_date"):
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
            year = _ebook_publish_year(values["publish_date"])
            if year is None:
                raise ValueError(
                    f"{where}：电子书的 publish_date 必须是四位出版年（可带月日），"
                    f"不得为「{UNKNOWN_DATE}」或混写（当前值 {values['publish_date']!r}）"
                )
            if not _YEAR_MIN <= year <= _YEAR_MAX:
                raise ValueError(
                    f"{where}：电子书的 publish_date 年份 {year} 不在合理区间 "
                    f"{_YEAR_MIN}–{_YEAR_MAX}（当前值 {values['publish_date']!r}）"
                )

        # 规则 7 + 9：发布者必须在白名单内，且该条目 verified 为 true 才算有效准入
        publisher = normalize_org(values["publisher"])
        wl = whitelist()
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
