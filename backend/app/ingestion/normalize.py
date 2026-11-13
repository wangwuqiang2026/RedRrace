"""时间归一与别名归一（阶段一步骤 5）。

时间口径（plan 阶段一步骤 5 的原话）：**解析失败就保留原文、把粒度标为 unknown，绝不猜**。
猜出来的时间要么造出假冲突，要么把真冲突掩盖掉，代价比「年代待考」大得多；阶段五的时间轴
会把 unknown 条目单列，不混进主体。

别名口径：归一**只用于检索与冲突比对**，展示仍用原文；别名表读不到时返回原值并警告一次，
不静默降级成「没有别名」。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

logger = logging.getLogger(__name__)

# 别名表默认路径：backend/data/aliases.yml
DEFAULT_ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "aliases.yml"

# 事件年窗口：史料里「发生了什么」的年份。与 app.ingestion.registry 里的出版年窗口
# （1840–2100，管「这本电子书出版得是否可信」）**不是同一回事，不要合并成一个常量**：
# 库里 S010 是明嘉靖《长沙府志》（16 世纪成书），按 1840 下限它的成书年会被误判 unknown。
EVENT_YEAR_MIN = 1
EVENT_YEAR_MAX = 2100

# 已知限制：**年号纪年不在解析范围内**。「嘉靖年间」「光绪二十年」「乾隆三年」这类
# 一律保持 unknown——换算要查年号对照表，而猜错年号会造出假时间，比「年代待考」危险得多。
# 该限制作为口径留给阶段九评测（见 task-F1A 报告第 4 节 R2/R7）。

Granularity = Literal["year", "month", "day", "range", "unknown"]


@dataclass
class TimeValue:
    """归一后的时间值。start/end 为 ISO 风格字符串（`1949`、`1949-05`、`1949-04-23`），
    粒度 unknown 时两者为 None，`raw` 恒为传入原文。"""

    start: str | None
    end: str | None
    granularity: Granularity
    raw: str


def _unknown(raw: str) -> TimeValue:
    return TimeValue(start=None, end=None, granularity="unknown", raw=raw)


_DIGIT_MAP = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_digits(text: str) -> int | None:
    """逐位中文数字：`一九四九` -> 1949。含「十」的组合读法不属于年份写法，判为不可解析。"""
    digits = ""
    for ch in text:
        if ch not in _DIGIT_MAP:
            return None
        digits += str(_DIGIT_MAP[ch])
    return int(digits) if digits else None


def _cn_number(text: str) -> int | None:
    """组合中文数：`二十`->20、`十二`->12、`二十三`->23、`四`->4。上限按 99 处理。"""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = 1 if not head else _DIGIT_MAP.get(head)
        ones = 0 if not tail else _DIGIT_MAP.get(tail)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return _DIGIT_MAP.get(text)


def _parse_year_token(token: str) -> int | None:
    """阿拉伯年份取 3–4 位（宋元纪年如 960 要能认）；1–2 位不认，理由见下方形状规则。"""
    if token.isdigit():
        return int(token) if 3 <= len(token) <= 4 else None
    return _cn_digits(token)


def _parse_small_token(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _cn_number(token)


def _days_in_month(year: int, month: int) -> int:
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    if month in (4, 6, 9, 11):
        return 30
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return 29 if leap else 28


# 裸写（不带「年」字）只认四位阿拉伯年份，避免「20」「199」这类片段被当纪年。
_YEAR_TOK = r"(?:[0-9]{4}|[零〇一二三四五六七八九]{2,4})"
# 带「年」字的日期结构里，三位年份也要认（如「960年」「1522年」）；
# 但 1–2 位数字加「年」在史料里多半是时长（「20年」＝二十年时间），一律不认。
_YEAR_TOK_IN_DATE = r"(?:[0-9]{3,4}|[零〇一二三四五六七八九]{2,4})"
_SMALL_TOK = r"(?:[0-9]{1,2}|[一二三四五六七八九十]{1,3})"

# 区间：两侧都得是四位年份，这样 1949-04-23 不会被当成区间
_RANGE_RE = re.compile(rf"^(?P<a>{_YEAR_TOK})\s*(?:[—–~]|至|到|-)\s*(?P<b>{_YEAR_TOK})$")
# 注意「四十年代」里的「十」属于数字本身，所以字面量只能是「年代」；
# 若把「十年代」当固定字面，正则回溯会把数字截成「四」，算出错半个年代的区间。
_CENTURY_RE = re.compile(
    r"^(?P<c>[零〇一二三四五六七八九十百]{1,4})世纪"
    r"(?:(?P<d>[一二三四五六七八九十]{1,3})年代)?"
    r"(?P<edge>末|初|前期|后期)?$"
)
_CN_DATE_RE = re.compile(
    rf"^(?P<y>{_YEAR_TOK_IN_DATE})\s*年"
    rf"(?:\s*(?P<m>{_SMALL_TOK})\s*月(?:\s*(?P<d>{_SMALL_TOK})\s*[日号])?)?\s*$"
)
_ISO_DATE_RE = re.compile(r"^(?P<y>[0-9]{4})(?:[-/.](?P<m>[0-9]{1,2})(?:[-/.](?P<d>[0-9]{1,2}))?)?$")
_YEAR_ONLY_RE = re.compile(rf"^{_YEAR_TOK}\s*年?$")


def _ok_year(year: int | None) -> bool:
    return year is not None and EVENT_YEAR_MIN <= year <= EVENT_YEAR_MAX


def _date_value(year: int, month: int | None, day: int | None, raw: str) -> TimeValue:
    """年月日都过了范围检查才落到这里；任何一处越界一律 unknown（绝不猜）。"""
    if month is None:
        return TimeValue(str(year), str(year), "year", raw)
    if day is None:
        stamp = f"{year}-{month:02d}"
        return TimeValue(stamp, stamp, "month", raw)
    stamp = f"{year}-{month:02d}-{day:02d}"
    return TimeValue(stamp, stamp, "day", raw)


def _from_date_match(match: re.Match, raw: str) -> TimeValue:
    year = _parse_year_token(match.group("y"))
    if not _ok_year(year):
        return _unknown(raw)
    month = _parse_small_token(match.group("m")) if match.group("m") else None
    day = _parse_small_token(match.group("d")) if match.group("d") else None
    if month is not None and not 1 <= month <= 12:
        return _unknown(raw)
    if day is not None and not 1 <= day <= _days_in_month(year, month or 1):
        return _unknown(raw)
    return _date_value(year, month, day, raw)


def _from_century(match: re.Match, raw: str) -> TimeValue:
    century = _cn_number(match.group("c"))
    if not century or century < 1:
        return _unknown(raw)
    base = (century - 1) * 100
    edge = match.group("edge")
    decade_text = match.group("d")
    if decade_text:
        decade = _cn_number(decade_text)
        if decade is None or not 0 <= decade <= 90:
            return _unknown(raw)
        start, end = base + decade, base + decade + 9
        # 「四十年代末」指这个十年里的后五年
        if edge in ("末", "后期"):
            start = end - 4
        elif edge in ("初", "前期"):
            end = start + 4
    else:
        # 「十九世纪末」指整个十九世纪的最后十年，不是最后五年
        if edge in ("末", "后期"):
            start, end = base + 90, base + 99
        elif edge in ("初", "前期"):
            start, end = base, base + 9
        else:
            start, end = base, base + 99
    if not (_ok_year(start) and _ok_year(end)):
        return _unknown(raw)
    return TimeValue(str(start), str(end), "range", raw)


def normalize_time(raw: str) -> TimeValue:
    """把中文史料里的时间写法归一为可比对的时间值；认不出就原样保留、粒度 unknown。"""
    text = unicodedata.normalize("NFKC", (raw or "").strip())
    if not text:
        return _unknown(raw)

    match = _RANGE_RE.match(text)
    if match:
        left, right = _parse_year_token(match.group("a")), _parse_year_token(match.group("b"))
        if _ok_year(left) and _ok_year(right) and left <= right:
            return TimeValue(str(left), str(right), "range", raw)
        return _unknown(raw)

    match = _CENTURY_RE.match(text)
    if match:
        return _from_century(match, raw)

    match = _CN_DATE_RE.match(text)
    if match:
        return _from_date_match(match, raw)

    match = _ISO_DATE_RE.match(text)
    if match:
        return _from_date_match(match, raw)

    match = _YEAR_ONLY_RE.match(text)
    if match:
        year = _parse_year_token(match.group(0).rstrip("年"))
        return TimeValue(str(year), str(year), "year", raw) if _ok_year(year) else _unknown(raw)

    return _unknown(raw)


# ── 别名归一 ──────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=32)
def _load_alias_file(path_str: str) -> dict:
    """读别名表并按路径缓存：读不到的警告只在首次发生，避免每次归一刷一行日志。"""
    path = Path(path_str)
    if not path.is_file():
        logger.warning("aliases 别名表不存在，人名与地名归一将原样返回：%s", path)
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("aliases 别名表读取失败，归一将原样返回：%s（%s）", path, exc)
        return {}
    if not isinstance(payload, dict):
        logger.warning("aliases 别名表结构不是映射，忽略：%s", path)
        return {}
    return payload


def load_aliases(aliases_path: Path | None = None) -> dict:
    """返回 {"person": {...}, "place": {...}}；文件缺失或坏损时两类都是空表。"""
    path = DEFAULT_ALIASES_PATH if aliases_path is None else Path(aliases_path)
    payload = _load_alias_file(str(path))
    person = payload.get("person")
    place = payload.get("place")
    return {
        "person": person if isinstance(person, dict) else {},
        "place": place if isinstance(place, dict) else {},
    }


def normalize_key(text: str) -> str:
    """别名比对用的键：全角转半角 + 去掉所有空白（吸收「红 星 中学」这类异写）。"""
    return "".join(unicodedata.normalize("NFKC", text or "").split())


def _canonical(name: str, category: str, aliases_path: Path | None) -> str:
    key = normalize_key(name)
    if not key:
        return name
    table = load_aliases(aliases_path)[category]
    for canonical, aliases in table.items():
        if key == normalize_key(canonical):
            return canonical
        if isinstance(aliases, str):
            aliases = [aliases]
        for alias in aliases or []:
            if key == normalize_key(alias):
                return canonical
    return name


def normalize_person(name: str, aliases_path: Path | None = None) -> str:
    """人名归一：命中别名返回规范名，未命中返回原值（展示一律用原文）。"""
    return _canonical(name, "person", aliases_path)


def normalize_place(name: str, aliases_path: Path | None = None) -> str:
    """地名归一（含旧称、简称）：命中别名返回规范名，未命中返回原值。"""
    return _canonical(name, "place", aliases_path)
