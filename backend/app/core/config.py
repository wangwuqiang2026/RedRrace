"""配置读取：环境变量与 .env 转为配置对象（阶段零步骤 1、4）。

键名与 backend/.env.example 一一对应（大小写不敏感匹配）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# 大模型后端：在线接口或本地 GGUF 小模型
LlmBackend = Literal["online", "local"]
# 检索后端：自研轻量管线或外部 RAGFlow 适配器
RetrievalBackend = Literal["local", "ragflow"]

# backend/ 目录。默认路径一律锚在这里而不是当前工作目录：
# 从仓库根启动 `uvicorn backend.app.main:app` 时，相对路径会解析到不存在的 ./data，
# 阶段一的语料路径与阶段二的索引路径都会踩坑。
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Config(BaseSettings):
    """运行配置。密钥与地址默认留空，由部署时注入。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_backend: LlmBackend = "online"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    retrieval_backend: RetrievalBackend = "local"
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""
    data_dir: Path = BACKEND_ROOT / "data"


def get_config() -> Config:
    """配置工厂：按当前环境变量与 .env 装配配置对象。"""
    return Config()
