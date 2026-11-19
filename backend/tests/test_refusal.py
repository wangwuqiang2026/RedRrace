"""阶段三 T3-5：拒答闸门四条硬要求（plan 步骤 5 / 5b）。

1. 空证据不调模型（用假 LLM 计数断言 5.18）；
2. 三种原因码 + 三个审计数字（retrieved_count / top_score / threshold）；
3. 结构化语料 term_floor 放宽，边界实测（关掉「表格式行」不得被主题词误命中）；
4. 拒答文案给出「最高匹配 x / 阈值 y」的可解释说明。
"""

from __future__ import annotations

from app.qa.constants import TERM_FLOOR
from app.qa.evidence import Evidence
from app.qa.refusal import (
    GateInput,
    decide_refusal,
    gate_explanation,
    should_relax_for_tabular,
)
from app.qa.schemas import Locator, SourceOut


def source(sid="S001"):
    return SourceOut(
        source_id=sid, title="校史", publisher="人民出版社", publish_date="1985",
        url_or_path="data/raw/articles/S001.html", access_date="2026-11-13",
        license_note="公开", corpus_tier="核心", media_type="文章",
    )


def ev(claim_id=1, text="某校于一九二五年创设", subject="某校"):
    return Evidence(
        claim_id=claim_id, card_id=claim_id, source_id="S001", subject=subject,
        predicate="创设时间", value="一九二五年", quote=text, score=0.5, source=source(),
        locator=Locator(quote=text, heading_path=["沿革"]),
    )


class FakeModel:
    def __init__(self):
        self.calls = 0

    def generate(self, question, evidence):
        self.calls += 1
        return "不应被调用"


def gate(top_score=0.8, count=3, threshold=0.41, evidence=None, all_rejected=False, question=""):
    return GateInput(
        question=question, retrieved_count=count, top_score=top_score, threshold=threshold,
        evidence=evidence if evidence is not None else [ev()] if count else [],
        all_claims_rejected=all_rejected,
    )


def test_empty_retrieval_refuses_without_calling_model():
    """空召回即拒答，且调用方据此在调模型之前返回（步骤 5b-1）。"""
    model = FakeModel()
    decision = decide_refusal(gate(count=0, top_score=None), model=model)
    assert decision.refuse is True
    assert decision.reason == "no_evidence"
    assert model.calls == 0, "拒答路径仍在调用模型：检索失效就会退回凭记忆作答"


def test_low_top_score_refuses_as_not_covered():
    d = decide_refusal(gate(top_score=0.2, count=5))
    assert d.refuse is True and d.reason == "not_covered"
    assert d.retrieved_count == 5 and d.top_score == 0.2


def test_all_claims_rejected_reason():
    d = decide_refusal(gate(top_score=0.8, count=3, all_rejected=True))
    assert d.refuse is True and d.reason == "all_claims_rejected"


def test_above_threshold_passes():
    d = decide_refusal(gate(top_score=0.8, count=3))
    assert d.refuse is False and d.reason is None


def test_threshold_zero_still_refuses_empty_retrieval():
    """阈值设 0 只关分数闸门，空召回与空证据仍拒答（步骤 5b-1 口径）。"""
    d = decide_refusal(gate(top_score=0.9, count=0, threshold=0.0))
    assert d.refuse is True and d.reason == "no_evidence"


def test_explanation_contains_both_numbers():
    d = decide_refusal(gate(top_score=0.28, count=4))
    text = gate_explanation(d)
    assert "0.28" in text and "0.41" in text
    assert "阈值" in text or "工作阈值" in text, "用户与审核台要一眼看出是闸门判定"


def test_tabular_relax_requires_rare_term_and_table_row():
    """三条件同时成立才放宽：罕见实体词逐字命中 + 只出现在少数候选 + 表格式行。"""
    query = "张某，1928年，湖南"
    # 表格式行 ≥3 字段且 ≥60% 字段含数字：4 段中 3 段含数字（编号/年份/籍贯代码）。
    candidate = "编号001,职务,1928年,籍贯430000"
    # 罕见词只出现在 1/4 候选里（≤30% 上限才成立），其余为不含该年份的无关行。
    others = ["编号002,职务,1931年,籍贯110000", "编号003,职务,1949年,籍贯310000",
              "编号004,职务,1956年,籍贯510000"]
    assert should_relax_for_tabular(query, [candidate, *others], candidate, term_floor=TERM_FLOOR) is True


def test_tabular_relax_rejects_generic_topic_word():
    """「图书馆」这类主题词命中大量候选，不能触发放宽（步骤 5b-3 边界实测）。"""
    query = "图书馆一次最多能借几本书"
    docs = ["图书馆,开放时间,08:00,22:00", "图书馆,馆藏,100万册,2024", "图书馆,座位,200个,三层"]
    assert should_relax_for_tabular(query, docs, docs[0], term_floor=TERM_FLOOR) is False


def test_term_floor_zero_disables_relax():
    assert should_relax_for_tabular("张某，1928年", ["张某,1928年,湖南"], "张某,1928年,湖南", term_floor=0) is False


def test_gate_decision_is_dataclass_with_exact_fields():
    """审计决策的字段集合钉死（供 qa_logs 落盘与前端展示，规范 6.11）。"""
    d = decide_refusal(gate())
    assert {f for f in d.__dataclass_fields__} == {
        "refuse", "reason", "retrieved_count", "top_score", "threshold", "note"
    }
