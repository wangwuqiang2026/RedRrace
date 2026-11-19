"""阶段三 T3-4：受约束生成提示词（plan 步骤 3）。

硬约束（逐条写进提示词，模型违反时由 `citation.verify_answer` 在下游剔除）：
- 只允许使用给定证据编号，不得引用编号外的材料；
- 每个结论句句末用 `[n]` 标注；
- 证据不足时输出 `NO_EVIDENCE_MARK`；
- 不得推断、不得补充、不得改写原文含义。

提示词版本号从 `constants.PROMPT_VERSION` 取并写进提示词正文，便于问答日志事后复原用的哪版。
改提示词必须递增版本（规范 3.6：注明取证位置，不在多处复制版本号）。
"""

from __future__ import annotations

from app.qa.constants import PROMPT_VERSION
from app.qa.evidence import Evidence

NO_EVIDENCE_MARK = "【无证据】"

_SYSTEM = """你是红色文化知识库的问答助手。严格遵守：
1. 只能使用【证据】中给出的编号与内容，不得引用编号外的材料，不得使用你的预训练知识补充；
2. 每个结论句句末标注所用证据编号，形如「……[1]。」，多证据可标多个；
3. 证据不足、问题不在证据覆盖范围时，只输出「{mark}」，不要生成任何结论句；
4. 不得推断、不得补充、不得改写原文含义；引文与取值必须照证据原文；
5. 若两处证据取值不一致，说明「存疑」并分别列出两处来源编号，不自行选边。
提示词版本：{version}"""


def build_prompt(question: str, evidence: list[Evidence]) -> str:
    """组装 user 侧提示词：编号证据 + 问题；无证据时明确写「无证据」。"""
    if evidence:
        numbered = "\n".join(
            f"[{i}] {e.reference_text}（来源：{e.source.title}，{e.source_id}）"
            for i, e in enumerate(evidence, start=1)
        )
        evidence_block = f"【证据】\n{numbered}"
    else:
        evidence_block = f"【证据】\n{NO_EVIDENCE_MARK}（没有任何可用证据，禁止作答）"
    return (
        f"{_SYSTEM.format(mark=NO_EVIDENCE_MARK, version=PROMPT_VERSION)}\n\n"
        f"{evidence_block}\n\n【问题】\n{question}\n\n【回答】"
    )
