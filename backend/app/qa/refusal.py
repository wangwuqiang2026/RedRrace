"""阶段三 T3-5：拒答闸门（plan 步骤 5 / 5b）。

四条硬要求：
1. **空证据不调模型**：`decide_refusal()` 在调模型之前判定，调用方见 `refuse=True` 即返回；
   调试模式下可把「证据为空却准备调用模型」写成异常（本模块提供 `assert_calling_allowed`）。
2. **可审计**：决策带 `retrieved_count` / `top_score` / `threshold` 三数字 + 原因码，写进 qa_logs。
3. **结构化语料放宽**：罕见实体词逐字命中 + 只出现在少数候选 + 表格式行，三条同时成立才降到
   `term_floor`；`term_floor=0` 关闭放宽，「图书馆」这类主题词不得误命中。
4. **可解释文案**：写明「当前最高匹配 0.xx，低于工作阈值 0.yy」。

闸门尺子只有 `top_score`（来自 `Hit.score`，阶段二 4b 的同一把尺），重排分永不参与（4.6）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.qa.constants import TERM_FLOOR

_CJK_WINDOW = re.compile(r"[\u4e00-\u9fff]{3,}")
_ALNUM_TOKEN = re.compile(r"[A-Za-z0-9]{3,}")


@dataclass(frozen=True)
class GateInput:
    question: str
    retrieved_count: int
    top_score: float | None
    threshold: float
    evidence: list[object]
    all_claims_rejected: bool = False


@dataclass(frozen=True)
class RefusalDecision:
    refuse: bool
    reason: str | None
    retrieved_count: int
    top_score: float | None
    threshold: float
    note: str


def _rare_terms(question: str) -> list[str]:
    """问句里的罕见实体词：3 字连续 CJK 窗口 + 3 位以上数字/拉丁 token（步骤 5b-3）。"""
    return _CJK_WINDOW.findall(question) + _ALNUM_TOKEN.findall(question)


def _is_tabular_row(text: str) -> bool:
    """表格式行：≥3 字段（逗号/制表符/中文逗号分隔），且 ≥60% 字段含数字。"""
    parts = [p.strip() for p in re.split(r"[,，\t]", text) if p.strip()]
    if len(parts) < 3:
        return False
    with_digit = sum(bool(re.search(r"\d", p)) for p in parts)
    return with_digit / len(parts) >= 0.6


def should_relax_for_tabular(
    question: str,
    candidates: list[str],
    row: str,
    *,
    term_floor: float = TERM_FLOOR,
) -> bool:
    """三条同时成立才放宽到 `term_floor`（步骤 5b-3）；`term_floor=0` 直接关闭。"""
    if term_floor <= 0:
        return False
    if not _is_tabular_row(row):
        return False
    for term in _rare_terms(question):
        if term not in row:
            continue
        # 只出现在少数候选中（≤30%）：否则它只是主题词，不是某一行的标识。
        hits = sum(term in doc for doc in candidates)
        if candidates and hits / len(candidates) <= 0.30:
            return True
    return False


def decide_refusal(gate: GateInput, *, model: object | None = None) -> RefusalDecision:
    """按「空证据 → 分数闸门 → 校验后无保留句」的顺序判定。

    `model` 参数只是为了让调用方把「不调模型」写成可测的不变量（测试传 FakeModel 计数）；
    本函数**绝不调用**它——decision.refuse=True 时调用方必须直接返回（步骤 5b-1）。
    """
    note = ""
    if gate.retrieved_count <= 0 or not gate.evidence:
        return RefusalDecision(True, "no_evidence", gate.retrieved_count, gate.top_score,
                               gate.threshold, "未检索到任何候选：检索或范围可能有问题，不调用生成模型")
    if gate.all_claims_rejected:
        return RefusalDecision(True, "all_claims_rejected", gate.retrieved_count, gate.top_score,
                               gate.threshold, "证据存在，但逐句引用校验后无保留句")
    # 结构化语料放宽：命中罕见实体词的表格式行按 term_floor 判；否则用主阈值。
    effective = gate.threshold
    if gate.top_score is not None:
        texts = [getattr(e, "reference_text", "") for e in gate.evidence]
        if should_relax_for_tabular(gate.question, texts, texts[0]):
            effective = TERM_FLOOR
            note = f"表格式行按 term_floor={TERM_FLOOR} 放宽"
    if gate.top_score is None:
        # 有候选但无相似度可用（BM25-only 档）：不拿 0.0 冒充低分，走 no_evidence 并留痕。
        return RefusalDecision(True, "no_evidence", gate.retrieved_count, None, gate.threshold,
                               "召回非空但没有可用的综合分（稠密通道不可用）")
    if gate.threshold > 0 and gate.top_score < effective:
        return RefusalDecision(True, "not_covered", gate.retrieved_count, gate.top_score,
                               gate.threshold, note or "最高综合分低于工作阈值")
    return RefusalDecision(False, None, gate.retrieved_count, gate.top_score, gate.threshold, note)


def gate_explanation(decision: RefusalDecision) -> str:
    """给前端 RefusalNotice 与审核台的一句话：当前最高匹配 x，低于工作阈值 y。"""
    score = f"{decision.top_score:.2f}" if decision.top_score is not None else "无可用相似度"
    return (
        f"知识库未收录或证据不足：当前最高匹配 {score}，低于工作阈值 {decision.threshold:.2f}。"
        f"（{decision.note}）"
    )


def assert_calling_allowed(gate: GateInput, decision: RefusalDecision) -> None:
    """本地调试断言：拒答了却还要调模型 → 立刻抛错，防止「检索挂了但答案看着正常」进演示。"""
    if decision.refuse:
        raise AssertionError(f"拒答路径不得调用生成模型（reason={decision.reason}）")
