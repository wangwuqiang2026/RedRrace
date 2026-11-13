"""问答接口的占位路由（阶段零F）。

存在的唯一理由：让 `AnswerOut` 等契约模型出现在 `/openapi.json` 里，前端类型才能由契约
生成而不是手写猜字段名。问答流水线在阶段三实现，届时替换函数体即可，**路径与响应模型
不得改动**。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.qa.schemas import AnswerOut, AskRequest

router = APIRouter(prefix="/api", tags=["问答"])


@router.post("/ask", response_model=AnswerOut)
def ask(payload: AskRequest) -> AnswerOut:
    """`POST /api/ask` 占位：契约已定，实现落在阶段三。"""
    raise HTTPException(status_code=501, detail="问答流水线在阶段三实现，当前只提供契约占位")
