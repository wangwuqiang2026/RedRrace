"""跨阶段唯一的文本归一与包含判定（阶段二 T4/T5 与阶段三共用）。

为什么必须只有一份实现（规范 6.9、plan 步骤 6b-3）：
- 检索评测要把「期望关键事实」与「真正送进证据集的文本」比对；
- 阶段三的引用校验要把「模型引用的句子」与「原文块」比对。
两处若各写一套归一逻辑，迟早漂移：一边把全角括号当有效字符、另一边不当，指标就会一半真一半假，
而且这种偏差不会有任何报错（参考实现 §9.1–9.3 踩过：文件名比较忽略标点、文本比较去掉所有空白，
两处口径不一致导致 Hit@k 与人工判断对不上）。

两条口径：
1. **标题/文件名比较**：NFKC 归一（全角括号、全角数字先变半角）→ 去掉除字母数字汉字外的一切
   字符 → 小写。用于「快照标题里的括号常被清洗掉」这类场景。
2. **正文比较**：NFKC 归一后去掉**所有空白**（OCR 与 HTML 缩进会在任意位置断行），保留标点
   ——引文逐字定位要求标点一致，那是「逐字」的一部分。
"""

from __future__ import annotations

import re
import unicodedata

# 标题归一：只留字母、数字、汉字（CJK 统一表意文字），其余（标点、空白、符号）全部丢弃。
_NON_ALNUM = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_WHITESPACE = re.compile(r"\s+")


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def normalize_title(text: str) -> str:
    """标题/文件名比较口径：NFKC + 小写 + 只留字母数字汉字。"""
    return _NON_ALNUM.sub("", _nfkc(text).lower())


def normalize_text(text: str) -> str:
    """正文比较口径：NFKC + 去掉所有空白（标点保留，逐字定位要用）。"""
    return _WHITESPACE.sub("", _nfkc(text))


def same_title(a: str, b: str) -> bool:
    """两个标题是否指同一样东西（忽略全半角标点、空白与大小写）。"""
    left, right = normalize_title(a), normalize_title(b)
    return bool(left) and left == right


def contains_fact(haystack: str, needle: str) -> bool:
    """关键事实是否出现在给定文本里（正文口径：忽略空白，其余逐字）。

    空 needle 一律判 False：空串「出现在任何地方」，让它通过等于给覆盖率指标开后门
    （规范 5.9：不允许永真断言进指标）。
    """
    target = normalize_text(needle)
    if not target:
        return False
    return target in normalize_text(haystack)
