"""后端装配入口：创建 app、健康检查路由与问答契约占位路由。

阶段零装配 `/api/health`；阶段零F 注册 `/api/ask` **占位**路由（固定响应模型、返回 501），
唯一目的是让问答契约出现在 `/openapi.json` 里供前端生成类型，实现落在阶段三。
cards / timeline / geo 等其余路由在对应阶段注册。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_config
from app.qa.router import router as qa_router

app = FastAPI(title="RedTrace", version="0.1.0", description="红色文化知识库与可溯源问答系统")

# 契约占位路由：路径与字段名以 app/qa/schemas.py 为准，阶段三只替换实现
app.include_router(qa_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查：返回运行状态与当前生效的检索后端。"""
    # 阶段零刻意不写 `cfg: Config = Depends(get_config)`：ruff 0.17 默认规则集含 B008，
    # 会把默认参数里的函数调用判为缺陷。阶段三统一处理 api/ 的 ruff 规则集
    # （对 app/api/* 豁免 B008 是标准做法），见决策记录。
    cfg = get_config()
    return {"status": "ok", "retrieval_backend": cfg.retrieval_backend}
