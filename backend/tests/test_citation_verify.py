"""阶段三 T3-3：三层引用校验（plan 步骤 4：编号 / 逐字 / 主体一致）。

任一句不通过即从答案剔除；引用全被剔除则由流水线转拒答（步骤 4 末段）。
共用 `retrieval.textmatch` 的归一口径，不在本模块重写一套（规范 6.9）。
"""

from __future__ import annotations

from app.qa.citation import Verdict, verify_answer
from app.qa.evidence import Evidence
from app.qa.schemas import Locator, SourceOut


def source(sid="S001"):
    return SourceOut(
        source_id=sid, title="校史", publisher="人民出版社", publish_date="1985",
        url_or_path="data/raw/articles/S001.html", access_date="2026-11-13",
        license_note="公开", corpus_tier="核心", media_type="文章",
    )


def ev(claim_id=1, subject="某校", quote="该校于一九二五年创设", sid="S001", **over):
    payload = {
        "claim_id": claim_id, "card_id": claim_id, "source_id": sid, "subject": subject,
        "predicate": "创设时间", "value": "一九二五年", "quote": quote, "score": 0.8,
        "source": source(sid), "locator": Locator(quote=quote, heading_path=["沿革"]),
    }
    payload.update(over)
    return Evidence(**payload)


# ── 第一层：编号合法性 ────────────────────────────────────────────────────────────────
def test_sentence_with_unknown_reference_number_is_dropped():
    """答案里标了 [9] 但证据集只有 [1] → 剔除（防张冠李戴第一层）。"""
    result = verify_answer("某校于一九二五年创设[9]。", [ev()])
    assert result.kept == []
    assert len(result.dropped) == 1
    assert result.dropped[0].verdict is Verdict.BAD_INDEX


def test_sentence_without_reference_is_dropped():
    """没有编号的结论句不可校验，一律剔除（不得让模型凭空断言）。"""
    result = verify_answer("某校于一九二五年创设。", [ev()])
    assert result.dropped[0].verdict is Verdict.NO_CITATION


def test_valid_reference_is_kept():
    result = verify_answer("某校于一九二五年创设[1]。", [ev()])
    assert len(result.kept) == 1
    assert result.kept[0].sentence == "某校于一九二五年创设[1]。"
    assert result.kept[0].citation_indexes == [1]


# ── 第二层：逐字定位 ──────────────────────────────────────────────────────────────────
def test_quote_must_be_found_in_source_text_after_normalization():
    """证据引文必须能在解析原文中逐字命中（忽略空白与全半角），否则该引用未通过。"""
    e = ev(quote="该校于一九二五年创设")
    # 原文里是全角数字 + 插入空白，归一后应与引文一致
    original = "该校 于 一九二五年创设"
    assert verify_answer("某校于一九二五年创设[1]。", [e], source_texts={1: original}).kept
    wrong = verify_answer("某校于一九二五年创设[1]。", [e], source_texts={1: "完全无关的原文"})
    assert wrong.dropped[0].verdict is Verdict.QUOTE_NOT_FOUND


def test_missing_source_text_fails_closed():
    """没有原文可核（source_texts 缺该条）时按未通过处理，不得默认放行。"""
    result = verify_answer("某校于一九二五年创设[1]。", [ev()], source_texts={})
    assert result.dropped[0].verdict is Verdict.QUOTE_NOT_FOUND


def test_source_texts_keyed_by_claim_id_not_reference_index():
    """source_texts 的键是 claim_id（pipeline 按 claim_id 现算），不是引用序号 [n]（smoke 实测缺口）。

    真实语料里 claim_id=150 但它是第 [1] 条证据；旧实现用 `source_texts.get(1)` 查，查不到 →
    引文逐字定位误判、真模型答案全被剔除。
    """
    evidence = [ev(claim_id=150, quote="自1934年10月起各路红军开启战略大转移。", subject="各路红军")]
    result = verify_answer(
        "各路红军自1934年10月起开启战略大转移[1]。", evidence,
        source_texts={150: "原文：自1934年10月起各路红军开启战略大转移。结尾"},
    )
    assert len(result.kept) == 1, f"按 claim_id 取原文应通过，实际 {result.dropped}"


# ── 第三层：主体一致 ──────────────────────────────────────────────────────────────────
def test_subject_mismatch_is_dropped():
    """答案句主语与条目主体不一致（讲甲却引乙）→ 剔除。"""
    result = verify_answer("复旦大学于一九二五年创设[1]。", [ev(subject="某校")], source_texts={1: "该校于一九二五年创设"})
    assert result.dropped[0].verdict is Verdict.SUBJECT_MISMATCH


def test_alias_subject_is_accepted():
    """别名表参与归一：旧校名与现校名指同一主体时通过（别名来自 aliases.yml）。"""
    e = ev(subject="省立第一师范学校")
    result = verify_answer(
        "省立一师于一九二五年创设[1]。", [e],
        source_texts={1: "该校于一九二五年创设"}, aliases={"省立一师": ["省立第一师范学校"]},
    )
    assert len(result.kept) == 1


# ── 汇总：全部剔除由流水线转拒答（这里只给信号）──────────────────────────────────────
def test_all_dropped_signals_refusal():
    result = verify_answer("未收录人物的事情[1]。", [ev()], source_texts={1: "无关原文"})
    assert result.all_rejected is True and result.kept == []


def test_partial_keep_does_not_signal_refusal():
    result = verify_answer("某校于一九二五年创设[1]。凭空断言[2]。", [ev()], source_texts={1: "该校于一九二五年创设"})
    assert result.all_rejected is False and len(result.kept) == 1 and len(result.dropped) == 1


def test_kept_citations_are_marked_verified():
    """保留句子引用的 Citation 必须 verified=True（未通过的不会出现）。"""
    result = verify_answer("某校于一九二五年创设[1]。", [ev()], source_texts={1: "该校于一九二五年创设"})
    assert result.kept[0].citation.verified is True
