"""重排三档（阶段二 T4）：API 重排 / 本地词法 / 关闭。

背景（决策记录 006 定路径、007 第二节实测）：定稿模型 `qwen3-rerank` 走 OpenAI 兼容的
`compatible-api/v1/reranks`（注意与 chat/embeddings 的 `compatible-mode` **不同前缀**）。
`gte-rerank-v2` 官方已下线，不得使用。

三条硬约束（plan 步骤 4 与 4b）：
1. **只写 `Hit.rerank_score`，绝不回写 `Hit.score`**：`relevance_score` 官方明示「本次请求的
   相对分数、不可跨请求比较」，而拒答阈值是跨题标定的量，两者性质上不可混用（4.6）。
2. **发送前逐条 token 预检，超限即跳过重排并报错，不得静默截断**：该部署实测单文档上限
   32,768 token（官方文档称 4,000，取严者以服务端 400 行为为准），预检线 30,000 留余量。
3. **校验返回条数 == 请求条数**，缺条目即抛 `RerankResponseError`，不得用默认分补齐。

失败回退是**默认行为而非异常路径**：参数缺失、超时、限流、条数不符，一律
`logger.warning("重排未生效: %s", reason)` 后按融合顺序返回（4.3）。禁止「界面显示开启、
实际空转」——参考实现的第一版就是这个状态（打印 "Skipping rerankings" 却仍显示开启）。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from app.core.config import Config
from app.retrieval.backend import Hit
from app.retrieval.embedding import estimate_tokens
from app.retrieval.errors import RerankResponseError

logger = logging.getLogger(__name__)

# 重试次数上限：首次 + 两次（对齐 `extract.py` 的 MAX_ATTEMPTS 口径，规范 4.11）。
MAX_ATTEMPTS = 3

# 送重排前逐条 token 预检线（服务端实测 32,768，见 007 第三节；30,000 留余量）。
DEFAULT_MAX_TOKENS_PER_DOC = 30000


class Reranker(Protocol):
    """重排器协议：给 query 与文档列表打分，返回与 documents 等长的分数列表。

    分数语义由实现自定（API 档是 0–1 相对分，本地档是 0–1 词法覆盖率），但**都只能写进
    `Hit.rerank_score`**：量纲不同、可否跨请求比较也无法统一，进闸门就是事故（4.6、4.8）。
    """

    name: str

    def rerank(self, query: str, documents: list[str]) -> list[float]: ...


class ApiReranker:
    """API 重排（`qwen3-rerank`，OpenAI 兼容 `compatible-api/v1/reranks`）。"""

    name = "api"

    def __init__(self, config: Config | None = None, *, transport: Any | None = None) -> None:
        from app.core.config import get_config

        cfg = config if config is not None else get_config()
        missing = [
            env
            for env, value in (
                ("RERANK_BASE_URL", cfg.rerank_base_url),
                ("RERANK_API_KEY", cfg.rerank_api_key),
                ("RERANK_MODEL", cfg.rerank_model),
            )
            if not str(value or "").strip()
        ]
        if missing:
            # 4.1：缺配置就在构造期大声报错，点名环境变量与补齐路径；本类不会自己换成别的档
            # （4.13：调用方必须能指出这一档是谁选的）。
            raise RuntimeError(
                f"API 重排缺少必需配置：{'、'.join(missing)}。请在 backend/.env 补齐"
                "（样例见 .env.example 的「重排」一节）；无 key 环境请显式改用 RERANK_BACKEND=local_lexical"
                " 或 off，不要指望本类自动降级。"
            )
        self.cfg = cfg
        self.max_docs = cfg.rerank_max_docs
        self.max_tokens = int(getattr(cfg, "rerank_max_tokens_per_doc", DEFAULT_MAX_TOKENS_PER_DOC))
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.cfg.rerank_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.cfg.rerank_api_key}"},
            timeout=self.cfg.rerank_timeout_s,
            transport=self._transport,
        )

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        if len(documents) > self.max_docs:
            raise RerankResponseError(
                f"送重排的文档数 {len(documents)} 超过上限 {self.max_docs}（服务端硬边界实测 500，"
                "本项目窗口取 RERANK_MAX_DOCS）——**不得**截断后发送，请调用方收窄窗口"
            )
        for index, document in enumerate(documents):
            tokens = estimate_tokens(document)
            if tokens > self.max_tokens:
                raise RerankResponseError(
                    f"第 {index} 条文档约 {tokens} token，超过预检线 {self.max_tokens}"
                    "（该部署服务端实测上限 32,768；超限服务端明确 400、不静默截断，"
                    "所以这里在客户端先拦下并跳过重排）"
                )
        payload = {
            "model": self.cfg.rerank_model,
            "input": {"query": query, "documents": documents},
        }
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with self._client() as client:
                    response = client.post("/reranks", json=payload)
                if response.status_code >= 400:
                    last_error = RerankResponseError(
                        f"重排接口返回 HTTP {response.status_code}：{response.text[:200]}"
                    )
                    if response.status_code < 500:
                        break  # 4xx 是请求本身的问题，重试没有意义
                    continue
                return self._parse_response(response.json(), expected=len(documents))
            except httpx.HTTPError as exc:  # 超时 / 连接失败 / 协议异常
                last_error = RerankResponseError(f"重排请求失败（第 {attempt}/{MAX_ATTEMPTS} 次）：{exc}")
        raise last_error or RerankResponseError("重排请求失败且没有留下原因")

    @staticmethod
    def _parse_response(payload: dict, *, expected: int) -> list[float]:
        results = ((payload or {}).get("output") or {}).get("results")
        if not isinstance(results, list):
            results = (payload or {}).get("results")
        if not isinstance(results, list):
            raise RerankResponseError(f"重排响应缺少 results 列表：{str(payload)[:200]}")
        if len(results) != expected:
            raise RerankResponseError(
                f"重排返回条数 {len(results)} != 请求条数 {expected}：缺条目不得用默认分补齐（4.4-①）"
            )
        scores: list[float | None] = [None] * expected
        for item in results:
            if not isinstance(item, dict):
                raise RerankResponseError(f"重排结果项不是对象：{item!r}")
            index = item.get("index")
            score = item.get("relevance_score")
            if not isinstance(index, int) or not 0 <= index < expected:
                raise RerankResponseError(f"重排结果 index 越界：{item!r}（期望 0..{expected - 1}）")
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise RerankResponseError(f"重排结果缺少 relevance_score：{item!r}")
            if not 0.0 <= float(score) <= 1.0:
                raise RerankResponseError(f"relevance_score 越出 [0,1]：{score!r}（契约要求 0–1 相对分）")
            scores[index] = float(score)
        if any(value is None for value in scores):
            missing = [i for i, value in enumerate(scores) if value is None]
            raise RerankResponseError(f"重排结果缺少这些文档的分数：{missing[:10]}（不得补默认分）")
        return [float(value) for value in scores if value is not None]


class LocalLexicalReranker:
    """本地词法重排：零 key、零网络，用查询词覆盖率给候选排序。

    为什么保留这一档（决策记录 006 第八节）：校园网或断网环境必须能跑完整条链路，
    而「无 key 就悄悄不重排」正是参考实现踩过的坑（§5.9）。它是**降级档不是默认档**。

    疑问词剔除（本项目实测的必要性）：问句里的「何时 / 什么 / 哪些」在语料正文里几乎不出现，
    留着会把覆盖率的分母撑大，让真正相关的条目拿到 0.0 而被纯关键词命中的条目压下去
    （真实索引上实测：`省立第一师范学校讲习所 何时创设` 对本该第一的条目给出 0.0）。
    剔除后覆盖率只按实词算，降级档才真的能用。
    """

    name = "local_lexical"

    # 中文问句里高频但无检索价值的词（不追求完整停用词表，只覆盖本项目的问法形态）。
    STOPWORDS = frozenset(
        {
            "何时",
            "什么时候",
            "什么",
            "哪些",
            "哪个",
            "谁",
            "怎样",
            "如何",
            "多少",
            "是否",
            "有没有",
            "是什么",
            "吗",
            "呢",
            "的",
        }
    )

    def __init__(self, config: Config | None = None, *, aliases_path: Any | None = None) -> None:
        self.cfg = config
        # 分词必须与索引侧同一套词典：索引里「省立第一师范」是一个 token，查询侧若不带词典
        # 会被切成「省立 / 第一 / 师范学校」，覆盖率算出来是假的（8.16 的同一条纪律）。
        self.aliases_path = aliases_path

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        from app.retrieval.local import tokenize

        query_tokens = [
            tok
            for tok in tokenize(query, aliases_path=self.aliases_path)
            if tok.strip() and tok not in {"｜"} and tok not in self.STOPWORDS and len(tok) >= 2
        ]
        wanted = set(query_tokens)
        if not wanted:
            return [0.0 for _ in documents]
        scores: list[float] = []
        for document in documents:
            doc_tokens = set(tokenize(document, aliases_path=self.aliases_path))
            hit = len(wanted & doc_tokens)
            scores.append(hit / len(wanted))
        return scores


def build_reranker(config: Config | None = None) -> Reranker | None:
    """按 `RERANK_BACKEND` 显式选档；`off` 返回 None（调用方据此走"不重排"分支）。

    不在这里做「缺 key 就换档」的兜底：选档是配置的责任，隐式换档会让降级演练时
    发现真实路径从没被验证过（4.13）。
    """
    from app.core.config import get_config

    cfg = config if config is not None else get_config()
    backend = cfg.rerank_backend
    if backend == "api":
        return ApiReranker(cfg)
    if backend == "local_lexical":
        return LocalLexicalReranker(cfg)
    if backend == "off":
        return None
    raise ValueError(f"未知的重排档 RERANK_BACKEND={backend!r}（合法值 api/local_lexical/off）")


def describe(reranker: Reranker | None) -> str:
    """自检用的一行描述（build_index.py 打印「重排档=…」）。"""
    return "未接入（off）" if reranker is None else reranker.name


def apply_rerank(
    hits: list[Hit],
    query: str,
    reranker: Reranker | None,
    *,
    text_of: Any,
    max_docs: int = 60,
) -> list[Hit]:
    """给候选打重排分并按其排序；失败时打印一行说明后按原序返回（回退是默认行为，4.3）。

    `text_of(hit) -> str` 由调用方提供（索引里的检索串正文），本模块不碰存储。
    未参与重排的候选 `rerank_score` 保持 `None` —— 「没打分」不等于「打 0 分」（4.8）。
    """
    if reranker is None or not hits:
        return hits
    window = hits[:max_docs]
    documents = [str(text_of(hit)) for hit in window]
    try:
        scores = reranker.rerank(query, documents)
    except (RerankResponseError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        logger.warning("重排未生效: %s", exc)
        return hits
    if len(scores) != len(window):
        logger.warning("重排未生效: 返回条数 %s != 请求条数 %s", len(scores), len(window))
        return hits
    for hit, score in zip(window, scores):
        hit.rerank_score = float(score)
    ordered = sorted(
        hits,
        key=lambda h: (
            h.rerank_score is None,
            -(h.rerank_score or 0.0),
            getattr(h, "doc_order", 0),
        ),
    )
    return ordered
