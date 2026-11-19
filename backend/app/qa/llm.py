"""阶段三 T3-4：大模型调用双实现（plan 步骤 3：在线接口 + 本地 GGUF）。

两实现共用同一 `generate(question, evidence) -> 草稿字符串` 接口，流水线只依赖该接口；
换模型（含微调模型）只需实现同一接口，不改流水线（步骤 3 末句）。
在线档复用阶段一 `extract.py` 的 OpenAI 兼容调用形态（temperature=0、`enable_thinking`
显式发送、同一超时常量口径），不另造一套 HTTP 客户端。
本地档延迟导入 `llama_cpp`，缺依赖时点名安装命令并显式报错，不隐式换档（4.13）。
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.core.config import Config, get_config
from app.ingestion.extract import LLM_TIMEOUT_S
from app.qa.prompt import build_prompt


class QaModel(Protocol):
    name: str

    def generate(self, question: str, evidence: list[Any]) -> str: ...


class OnlineQaModel:
    """在线 OpenAI 兼容 `chat/completions`（配置 `llm_*` 三项）。"""

    name = "online"

    def __init__(self, config: Config | None = None, *, transport: Any | None = None):
        cfg = config if config is not None else get_config()
        missing = [
            name
            for name, value in (
                ("LLM_API_KEY", cfg.llm_api_key),
                ("LLM_BASE_URL", cfg.llm_base_url),
                ("LLM_MODEL", cfg.llm_model),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise RuntimeError(
                "QaModel 在线档缺少必需配置：" + "、".join(missing) + "。请补齐 backend/.env"
                "（参考 .env.example）；无 key 环境请显式改用本地档，生成后端不会自动切换（4.13）。"
            )
        self.cfg = cfg
        self._transport = transport

    def generate(self, question: str, evidence: list[Any]) -> str:
        prompt = build_prompt(question, evidence)
        with httpx.Client(transport=self._transport, timeout=LLM_TIMEOUT_S) as client:
            response = client.post(
                f"{self.cfg.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.cfg.llm_api_key}"},
                json={
                    "model": self.cfg.llm_model,
                    "temperature": 0,
                    # 与 extract.py 同款：供应商缺省开推理会拖慢并扰动 JSON，显式发送 False（007 五）。
                    "enable_thinking": bool(self.cfg.llm_enable_thinking),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])


class LocalQaModel:
    """本地 GGUF 模型兜底档：需 `llama-cpp-python`，本阶段不安装、不下载权重（8.3）。"""

    name = "local"

    def __init__(self, config: Config | None = None, *, loader: Any | None = None):
        self.cfg = config if config is not None else get_config()
        if loader is None:
            try:
                from llama_cpp import Llama
            except ImportError as exc:
                raise ImportError(
                    "本地问答档需要可选依赖 llama-cpp-python：请执行 pip install llama-cpp-python"
                    " 并自行取得 GGUF 权重（本阶段不下载，规范 8.3）。无依赖时请显式改用在线档，"
                    "生成后端不会自动切换（4.13）。"
                ) from exc
            self._loader: Any = Llama
        else:
            self._loader = loader

    def generate(self, question: str, evidence: list[Any]) -> str:
        prompt = build_prompt(question, evidence)
        model = self._loader(model_path=self.cfg.llm_model)
        result = model.create_completion(prompt, temperature=0, max_tokens=1024)
        return str(result["choices"][0]["text"])


def build_qa_model(config: Config | None = None, **kwargs: Any) -> QaModel:
    """按 `llm_backend` 显式选档；无 key / 无依赖时各档自己大声失败，不做隐式换档。"""
    cfg = config if config is not None else get_config()
    if cfg.llm_backend == "online":
        return OnlineQaModel(cfg, **kwargs)
    if cfg.llm_backend == "local":
        return LocalQaModel(cfg, **kwargs)
    raise RuntimeError(f"未知的 llm_backend={cfg.llm_backend!r}（合法值 online / local，4.13）")
