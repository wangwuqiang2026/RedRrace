"""文本归一与包含判定（阶段二 T5，规范 6.9）。

为什么这些用例值得写：这份归一化是**评测指标与阶段三引用校验共用的唯一实现**
（plan 步骤 6b-3 逐字要求）；它错一位，Hit@k 与「引文能不能在原文定位」会同时假绿或假红，
而且不会有任何报错。
"""

from __future__ import annotations

import pytest

from app.retrieval.textmatch import contains_fact, normalize_text, normalize_title, same_title


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("《长沙府志》（明嘉靖）", "长沙府志明嘉靖"),
        ("红军长征档案 数据库", "红军长征档案数据库"),
        ("ＡＢＣ　１２３", "abc123"),
        ("ＯＣＲ（识别）结果", "ocr识别结果"),
        ("", ""),
        ("——、。；", ""),
    ],
)
def test_normalize_title_strips_punct_and_width(raw, expected):
    """标题口径：全角转半角、小写、只留字母数字汉字（全角括号常被清洗掉，不能当有效字符）。"""
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("省立第一师范学校\n讲习所于１９２５年创设", "省立第一师范学校讲习所于1925年创设"),
        ("  OCR\n 缩进\t断行  ", "OCR缩进断行"),
        ("标点，保留。", "标点,保留。"),  # NFKC 统一全角标点为半角，但「是否保留标点」不变
    ],
)
def test_normalize_text_only_removes_whitespace(raw, expected):
    """正文口径：去掉所有空白但**保留标点**——引文逐字定位要求标点一致（宽度由 NFKC 统一）。"""
    assert normalize_text(raw) == expected


def test_same_title_ignores_width_and_punct():
    """同一标题的两种写法判等（快照标题里的括号、全角字符差异不得影响命中判定）。"""
    assert same_title("《长沙府志》编纂", "长沙府志(编纂)")
    assert not same_title("《长沙府志》编纂", "《长沙府志》出版")
    assert not same_title("", ""), "两个空标题不得判为同一标题（空串比较是永真式）"


def test_contains_fact_ignores_line_breaks():
    """关键事实落在断行处也要判命中：否则覆盖率会把真实命中算成漏。"""
    assert contains_fact("省立第一师范学校\n讲习所于一九二五年创设", "讲习所于一九二五年创设")
    assert not contains_fact("省立第一师范学校讲习所", "长沙府志")


def test_contains_fact_rejects_empty_needle():
    """空事实一律判 False：空串「出现在任何地方」，让它通过等于给覆盖率指标开后门。"""
    assert contains_fact("任何正文", "") is False
    assert contains_fact("任何正文", "   ") is False
