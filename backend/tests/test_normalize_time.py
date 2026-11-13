"""时间归一与别名归一（阶段一步骤 4–5）的测试。

plan 的硬口径是「解析失败则保留原文并把粒度标为未知——**绝不猜**」：阶段四的冲突检测完全
建立在时间可比之上，猜出来的时间会造出假冲突、或把真冲突掩盖掉，代价比「待考」大得多。
"""

import dataclasses

import pytest
from helpers import write_yaml

from app.ingestion.normalize import (
    TimeValue,
    load_aliases,
    normalize_person,
    normalize_place,
    normalize_time,
)


# ── plan 阶段一步骤 4 给定的三条用例，逐字照抄 ────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expect_start,expect_end",
    [
        ("1949年5月", "1949-05", "1949-05"),
        ("1949年4月23日", "1949-04-23", "1949-04-23"),
        ("二十世纪四十年代末", "1945", "1949"),
    ],
)
def test_normalize_time(raw, expect_start, expect_end):
    tv = normalize_time(raw)
    assert (tv.start, tv.end) == (expect_start, expect_end)


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("1949", ("year", "1949", "1949")),
        ("1949年", ("year", "1949", "1949")),
        ("1949年5月", ("month", "1949-05", "1949-05")),
        ("1949年4月23日", ("day", "1949-04-23", "1949-04-23")),
        ("1949-04-23", ("day", "1949-04-23", "1949-04-23")),
        ("1949/4/23", ("day", "1949-04-23", "1949-04-23")),
        ("1934—1936", ("range", "1934", "1936")),
        ("1934-1936", ("range", "1934", "1936")),
        ("二十世纪二十年代", ("range", "1920", "1929")),
        ("二十世纪五十年代", ("range", "1950", "1959")),
        ("二十世纪八十年代初", ("range", "1980", "1984")),
        ("十九世纪末", ("range", "1890", "1899")),
    ],
)
def test_normalize_time_granularity_and_bounds(raw, expect):
    granularity, start, end = expect
    tv = normalize_time(raw)
    assert (tv.granularity, tv.start, tv.end) == (granularity, start, end)


@pytest.mark.parametrize(
    "raw,start,end",
    [
        ("一九二五年", "1925", "1925"),
        ("一九四九年五月", "1949-05", "1949-05"),
        ("一九四九年四月二十三日", "1949-04-23", "1949-04-23"),
        ("一九四九年十二月一日", "1949-12-01", "1949-12-01"),
    ],
)
def test_normalize_time_chinese_numerals(raw, start, end):
    """语料里「一九四九年」这类逐位中文写法极常见，不认就等于全库待考。"""
    tv = normalize_time(raw)
    assert (tv.start, tv.end) == (start, end)
    assert tv.granularity in ("year", "month", "day")


def test_normalize_time_keeps_raw_verbatim():
    raw = "  一九四九年四月二十三日  "
    assert normalize_time(raw.strip()).raw == raw.strip()


# ── 绝不猜：解析不了就 unknown + 原文，且不抛异常 ─────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        "明天下午两点",
        "大约某年",
        "",
        "   ",
        "1949年13月",  # 月份越界
        "1949年4月31日",  # 日期越界
        "1949年闰二月",
        "公元前五世纪",
        "待考",
        "unknown",
    ],
)
def test_unparseable_input_is_unknown_and_never_raises(raw):
    tv = normalize_time(raw)
    assert tv.granularity == "unknown"
    assert tv.raw == raw
    assert (tv.start, tv.end) == (None, None)


def test_timevalue_is_a_dataclass_with_four_fields():
    fields = {f.name for f in dataclasses.fields(TimeValue)}
    assert fields == {"start", "end", "granularity", "raw"}


# ── 裁决 3：事件年窗口 1–2100，与 registry 的「出版年 1840–2100」不是同一回事 ──────────
@pytest.mark.parametrize(
    "raw,expect",
    [
        ("1522", ("year", "1522", "1522")),  # lead 指定的用例：明嘉靖《长沙府志》成书年
        ("1522年", ("year", "1522", "1522")),
        ("960年", ("year", "960", "960")),  # 宋元纪年，三位数年份
        ("1522年9月", ("month", "1522-09", "1522-09")),
        ("1644年4月25日", ("day", "1644-04-25", "1644-04-25")),
        ("1800—1850", ("range", "1800", "1850")),
    ],
)
def test_event_year_below_publication_floor_is_still_parsed(raw, expect):
    """库里 S010 是 16 世纪的《长沙府志》：按 1840 窗口它的成书年会被误判 unknown。"""
    granularity, start, end = expect
    tv = normalize_time(raw)
    assert (tv.granularity, tv.start, tv.end) == (granularity, start, end)


@pytest.mark.parametrize("raw", ["2101", "2500年", "9999年", "0", "0000"])
def test_event_year_above_ceiling_is_unknown(raw):
    assert normalize_time(raw).granularity == "unknown"


@pytest.mark.parametrize("raw", ["20年", "20", "五十年"])
def test_short_or_bare_numbers_are_not_guessed_as_years(raw):
    """「20年」在史料里多半是时长而非公元 20 年；形状不确定就不认，避免造出假时间。"""
    assert normalize_time(raw).granularity == "unknown"


@pytest.mark.parametrize("raw", ["嘉靖年间", "光绪二十年", "明嘉靖四十一年", "乾隆三年"])
def test_nianhao_era_dates_stay_unknown(raw):
    """已知限制：年号纪年要查对照表，本轮一律 unknown——猜错年号比 unknown 危险得多。"""
    tv = normalize_time(raw)
    assert tv.granularity == "unknown"
    assert tv.raw == raw


# ── 别名归一：读 aliases.yml，读不到就返回原值并只警告一次 ─────────────────────────────
def test_normalize_person_maps_alias(tmp_path):
    path = write_yaml(
        tmp_path,
        {"person": {"湖南师范大学": ["湖南国文公立师范学校", "省立湖南第一师范"]}, "place": {}},
    )
    assert normalize_person("省立湖南第一师范", aliases_path=path) == "湖南师范大学"
    assert normalize_person("湖南师范大学", aliases_path=path) == "湖南师范大学"


def test_normalize_place_maps_alias(tmp_path):
    path = write_yaml(
        tmp_path, {"person": {}, "place": {"长沙": ["长沙市", "潭州", "潭城"]}}
    )
    assert normalize_place("潭州", aliases_path=path) == "长沙"


def test_unknown_alias_returns_original_value(tmp_path):
    path = write_yaml(tmp_path, {"person": {"甲": ["乙"]}, "place": {}})
    assert normalize_person("查无此人", aliases_path=path) == "查无此人"
    assert normalize_place("查无此地", aliases_path=path) == "查无此地"


def test_missing_alias_file_warns_only_once(tmp_path, caplog):
    """读不到文件不得影响归一结果，但必须吭一声——而且只吭一次，不刷屏。"""
    missing = tmp_path / "没有这个文件.yml"
    assert normalize_person("张三", aliases_path=missing) == "张三"
    assert normalize_place("长沙", aliases_path=missing) == "长沙"
    assert normalize_person("李四", aliases_path=missing) == "李四"
    warnings = [r for r in caplog.records if r.levelname == "WARNING" and "aliases" in r.getMessage()]
    assert len(warnings) == 1, f"应当只警告一次，实际 {len(warnings)} 次"


def test_shipped_aliases_file_is_loadable():
    """仓库里的 backend/data/aliases.yml 是交付物，结构与占位键必须齐备。"""
    data = load_aliases()
    assert set(data) >= {"person", "place"}
    assert isinstance(data["person"], dict) and isinstance(data["place"], dict)
    assert data["person"], "至少要有旧校名→现校名一类占位条目，不能交空表"


def test_alias_lookup_is_whitespace_and_width_normalized(tmp_path):
    """机构与人名常因全半角、空格差异写成同名的不同形态，归一要能吸收。"""
    path = write_yaml(tmp_path, {"person": {"红星中学": ["  红 星 中 学（旧） "]}, "place": {}})
    assert normalize_person("红星中学（旧）", aliases_path=path) == "红星中学"
