"""问答接口路由（阶段零F 建占位，阶段三接真流水线）。

路径 `/api/ask` 与响应模型 `AnswerOut` 在阶段零F 定死，阶段三只替换函数体，
不改路径与响应模型（契约优先于实现，全局约束 10）。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.qa.pipeline import answer_question
from app.qa.schemas import AnswerOut, AskRequest

router = APIRouter(prefix="/api", tags=["问答"])


@router.post("/ask", response_model=AnswerOut)
def ask(payload: AskRequest) -> AnswerOut:
    """`POST /api/ask`：跑完整流水线（检索 → 证据 → 生成 → 校验 → 出处）。"""
    return answer_question(payload)
