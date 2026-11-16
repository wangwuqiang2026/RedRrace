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
# 向量后端三档（决策记录 005 第四节）：api 走 OpenAI 兼容 /embeddings、
# local 自建权重（需自行下载，默认不用）、stub 无向量即退化 BM25-only。
# 三档必须同时存在：付费云服务不得为唯一路径（全局约束 6）。
EmbeddingBackend = Literal["api", "local", "stub"]
# 重排三档（决策记录 006 第八节）：api / local_lexical（零 key 零网络）/ off。
RerankBackend = Literal["api", "local_lexical", "off"]

# backend/ 目录。默认路径一律锚在这里而不是当前工作目录：
# 从仓库根启动 `uvicorn backend.app.main:app` 时，相对路径会解析到不存在的 ./data，
# 阶段一的语料路径与阶段二的索引路径都会踩坑。
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# .env 的路径，单独提为常量有两个用处：① 测试会话要把它临时置空以隔离本机部署配置
# （见 tests/conftest.py 的 isolate_dotenv——真实 key 一旦写进 .env，「缺配置必须报错」的
# 用例就再也造不出缺失，测试等于隐含依赖「仓库里没有 .env」这个脆弱前提）；
# ② 「默认锚在 backend/ 下、不随 cwd 漂移」这条断言应核常量本身，而不是被临时改过的 model_config。
ENV_FILE = BACKEND_ROOT / ".env"


class Config(BaseSettings):
    """运行配置。密钥与地址默认留空，由部署时注入。"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        # utf-8-sig：Windows 记事本另存 .env 默认写 BOM，用 utf-8 解析时首个键名被 BOM
        # 字符污染、整行静默失效（改了配置却按默认跑，比崩溃更难查）。无 BOM 的文件不受影响。
        env_file_encoding="utf-8-sig",
        # .env.example 的本意是「不用填的键留空」；若把空串当成已提供的值，
        # Literal 字段会直接 ValidationError，导致照文档 cp 一份 .env 就启动即崩。
        env_ignore_empty=True,
        extra="ignore",
    )

    llm_backend: LlmBackend = "online"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    # 混合思考模型开关（决策记录 007 第五节实测）：`qwen3.8-flash` 默认开启推理 token，
    # 实测仅回复「收到」二字即 completion_tokens=30 含 reasoning_tokens=26。本项目的抽取与
    # 受约束生成不需要自由推理，实测 enable_thinking=false 不降低 JSON 合规性、省约 1/3 时延。
    # 该参数是供应商扩展项，OpenAI 官方 schema 无此项，故换供应商须逐项确认（阶段八运行手册）。
    llm_enable_thinking: bool = False
    retrieval_backend: RetrievalBackend = "local"
    ragflow_base_url: str = ""
    ragflow_api_key: str = ""

    # —— 向量化（决策记录 005 第七节定名、007 第二节实测确认可用）——
    embedding_backend: EmbeddingBackend = "api"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024
    # 单次批量条数。服务端硬边界实测为 25（007 三-1，官方文档另称 20），取 16 留余量；
    # 校验逻辑不得把 21～25 条的批次判为非法。
    embedding_batch_size: int = 16
    embedding_timeout_s: float = 30.0
    # 入库与查询两侧一律显式传 text_type：实测两端点默认值相反（兼容层=query、
    # 原生=document），漏传即 cos≈0.925 地换掉向量空间且全程返回 200（007 第四节）。
    # 置空表示确实不传该参数——此时向量配置签名须记录「未声明」，索引判过期、阈值重标。
    embedding_text_type_document: str = "document"
    embedding_text_type_query: str = "query"
    # 发送前逐条预检线：服务端上下文边界实测 131,072 token 且超长明确 400、不静默截断
    # （007 三-2）；同批混入一条超长会整批失败 count=0（007 三-3），所以必须发前拦。
    embedding_max_tokens_per_line: int = 128000

    # —— 重排（决策记录 006 定路径与尺子隔离、007 第二节实测两模型名均可用）——
    rerank_backend: RerankBackend = "api"
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    rerank_timeout_s: float = 15.0
    # 单次请求文档条数上限；服务端硬边界实测 500（006 第八节已证实），60 为融合后送重排的窗口宽度。
    rerank_max_docs: int = 60
    # 单文档预检线；服务端实测 32,768 token（官方文档称 4,000，两者不符，以部署实测为准），取 30,000 留余量。
    rerank_max_tokens_per_doc: int = 30000

    data_dir: Path = BACKEND_ROOT / "data"


def get_config() -> Config:
    """配置工厂：按当前环境变量与 .env 装配配置对象。"""
    return Config()
