"""稠密向量的三档后端与响应完整性断言（阶段二 T2）。

本模块的口径来自 plan 阶段二步骤 3「向量按决策记录 005 走 API」与 **步骤 3b**
（`.superpowers/sdd/plan/phase2-text.md:29,56-73`）、task2-brief.md，以及编码规范基线
4.1 / 4.4 / 4.5 / 4.9 / 4.10 / 4.12 / 4.13 / 4.14 / 5.10 / 5.17 / 5.18 / 8.3 / 8.6 / 8.12 / 8.15。

三档同时存在（全局约束 6「付费云服务不得为唯一路径」、决策记录 005 第四节降级表）：

- `ApiEmbedder`：OpenAI 兼容 `POST {base_url}/embeddings`，定稿模型 `qwen3.7-text-embedding-flash` @ 1024 维；
- `LocalEmbedder`：自建权重兜底档。**本阶段不装 `[retrieval]` extra、不下载权重**（规范 8.3），
  所以它此刻的正确行为就是「显式报错并说清缺什么」，绝不隐式退回 api 或 stub（规范 4.13）；
- `StubEmbedder`：不产出向量，检索退化 BM25-only，且必须让 T3 区分「stub」与「api 失败」（brief 第 21 行）。

T3（`local.py` / `scripts/build_index.py`）消费本模块两样东西：
① `embed_documents()` / `embed_query()` 返回的 `EmbeddingResult`（含 `dense_available` 自报口径）；
② `vector_signature()` 返回的 `VectorSignature`——索引第二个指纹（向量配置签名）的材料来源，
   其中 `text_types` 字段就是「实际生效的 text_type 两侧组合」的只读访问方式（依 4.9、007 §四）；
   另有 `effective_text_types` / `text_type_declared` 两个只读属性供自检打印「请求实际发出的值」
   （plan:1097 ①）。

异常一律 import 自 `app.retrieval.errors`（裁决 D3）：响应残缺抛 `EmbeddingResponseError`，
配置缺失抛 `RuntimeError`，入参不合法抛 `ValueError`（依 4.2 与 4.4 的分工，措辞分道见 4.14）。

已知限制（依 3.4 显式写明，不得藏在实现细节里）：
- token 预检用**近似口径**（`estimate_tokens` docstring），不是服务端的分词结果，仅用于「别整批陪葬」；
- 重试次数沿用抽取侧的 `MAX_ATTEMPTS = 3`，因为 Config 里没有 `embedding_retry_*` 字段
  （brief 要求缺配置时报告 lead 而不是自己加）；退避策略留待阶段八步骤 4 的限流实测后补。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.core.config import Config, get_config
from app.retrieval.errors import EmbeddingResponseError

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────────────────
# 首次 + 重试两次：对齐 `extract.py:48` 的 MAX_ATTEMPTS=3 口径（依 4.11「重试次数写成大写常量、
# 耗尽后显式报错，禁止无限重试或吞异常返回空」）。005 第七节 7.3-2 明确限流与网络抖动
# 「仍要按 EMBEDDING_TIMEOUT_S / 重试逻辑处理」，而 Config 未提供 embedding_retry_* 字段。
MAX_ATTEMPTS = 3

# text_type 的合法取值。服务端实测非法值返回 400 并回显 `its value should be in ['document','query']`
# （007 第四节末条），所以拼错不会静默降级；本项目把这道校验前移到构造期，省掉一次必然失败的付费请求。
VALID_TEXT_TYPES = frozenset({"document", "query"})

# 置空 text_type 时在向量配置签名里落的字样。依据 config.py:75-77 与 007 第十一节：
# 「留空表示确实不传该参数，但此时签名仍记录『未声明』，索引判过期、阈值重标——不得静默沿用」。
TEXT_TYPE_UNDECLARED = "未声明"

# stub 档签名的 digest 前缀。为什么用前缀而不是再加一个布尔字段：T3 与自检命令要把签名原样打印进报告，
# 带 `no-vector` 前缀的 digest 让人一眼看出「这条线压根没有稠密通道」，
# 而 `dense_available=False` 只在 embed() 结果里，签名对象本身也需要同样的自报能力（依 4.12）。
STUB_SIGNATURE_PREFIX = "no-vector"

# 近似 token 口径的拉丁文除数（docstring 见 estimate_tokens：这是客户端保守估算，不是服务端口径）。
_LATIN_CHARS_PER_TOKEN = 4

# 「按字符计费」的字符类：汉字各区 + CJK 标点 + 假名 + 全角/半宽 + 通用标点。
# 为什么不写 `\w`：那会把拉丁字母一并算成「一字一 token」，让英文检索串的估算虚高到不可用。
# 2026-11-18 I-1 扩区（评审 task2-verdict.md I-1、规范 4.5/3.3）：旧口径只覆盖汉字三区，
# 中文标点（，。、《》、…—）、全角拉丁（ＡＢＣＤ）与假名都落进「每 4 字符 1 token」支；
# 检索串的主形态是「卡片名 + 谓词 + 取值 + 原文引文」，引文必带中文标点，混排串的估算
# 反而低于纯汉字串（评审实测 109,275 < 真实 ≥155,100）→ 客户端放行 → 服务端整批 400、count=0
# （007 三-3）。BPE 对这些字符普遍 1 token/字符甚至更多，故一律按 1 计，只朝不低估的方向取。
_CJK_RE = re.compile(
    "["
    "\u2000-\u206f"  # 通用标点（… —）
    "\u3000-\u303f"  # CJK 符号与标点（。，、《》「」；：？！中的全角形式）
    "\u3040-\u30ff"  # 平假名 + 片假名
    "\u3400-\u4dbf"  # CJK 扩展 A
    "\u4e00-\u9fff"  # CJK 基本区
    "\uf900-\ufaff"  # CJK 兼容表意
    "\uff00-\uffef"  # 全角 / 半宽形式（ＡＢＣＤ、；：？！（））
    "]"
)


# ── 产出物 ──────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class VectorSignature:
    """向量配置签名材料（依 4.9：`EMBEDDING_MODEL` + `EMBEDDING_DIM` + 供应商基址哈希 + `text_type` 两侧组合）。

    给 T3 的用法：把 `digest` 作为索引文件的第二个指纹落盘，任一字段变更即判过期重建并重标阈值。
    参考实现 §5.37 的实测事故是「向量缓存进程级、切模型后不失效」——本项目把它挡在指纹比对这一层。

    为什么 `base_url_hash` 只存哈希不存明文：签名会进索引文件与阈值文件的标定条件（规范 6.12），
    属于交付物可见范围；哈希足以支撑「换端点即过期」的判定，又不把内部域名原样带进答辩材料。
    """

    backend: str
    model: str
    dim: int
    base_url_hash: str
    text_types: tuple[str, str]
    """实际生效的 `(入库侧, 查询侧)` 组合；置空时为 `("未声明", "未声明")`（依 4.9 末段、007 十一）。"""

    digest: str

    def as_dict(self) -> dict[str, Any]:
        """供 `build_index.py` / `threshold.json` 直接 JSON 落盘的形态（依 6.11：键名固定）。"""
        return {
            "backend": self.backend,
            "model": self.model,
            "dim": self.dim,
            "base_url_hash": self.base_url_hash,
            "text_type_document": self.text_types[0],
            "text_type_query": self.text_types[1],
            "digest": self.digest,
        }


@dataclass(frozen=True)
class EmbeddingResult:
    """一次 `embed_documents()` / `embed_query()` 的产出物（T3 照此消费，字段名钉死依 6.1、5.12）。

    为什么把 `backend_name` 与 `dense_available` 放进结果本身而不是只放在实例上（依 brief 第 21 行
    「返回值必须让 T3 能区分 stub 与 api 失败」）：建索引是按批循环的，若档位信息只在构造期可见，
    某处把两批结果拼接时就再也看不出这批向量是谁产的——0 向量冒充真向量的危害正在于此。

    为什么 `requests` / `total_tokens` 也要带出来：005 第三节第 3 条把冷机指标改成度量
    「API 批量向量化的网络往返 + 限流 + 失败重试」，明确要求记录调用次数与输入 token 数；
    拿不到这两项，阶段八的成本单列就只能估（依 8.12 禁止把估的数字当达标依据）。
    """

    vectors: list[list[float]]
    backend_name: str
    dense_available: bool
    total_tokens: int = 0
    requests: int = 0
    text_types: tuple[str, str] = (TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED)


@runtime_checkable
class Embedder(Protocol):
    """向量后端协议：三档共同形状（依 2.8「可替换后端一律 Protocol + 三实现」）。

    为什么用 Protocol 而不是像 `SearchBackend` 那样用 ABC（对照裁决 D9 的处理）：
    `SearchBackend` 需要「子类漏实现即实例化报错」的强校验，而本层的三个实现由装配层按配置
    显式构造（依 4.13），调用方只做鸭子替换；`build_embedder()` 已经把「选档」收在唯一一处。
    """

    def embed_documents(self, texts: list[str]) -> EmbeddingResult: ...

    def embed_query(self, text: str) -> EmbeddingResult: ...

    def vector_signature(self) -> VectorSignature: ...


# ── 客户端预检：近似 token 口径与空白拦截 ───────────────────────────────────────────────
def estimate_tokens(text: str) -> int:
    """发送前的**近似** token 计数，用于逐条预检（依 4.5：超限即拦，不得静默截断）。

    口径（务必别当成服务端口径，规范 3.3 要求标注取证方式）：
    - CJK 汉字（基本区 / 扩展 A / 兼容区）、中文标点、假名、全角/半宽字符按每字符 1 token（见 `_CJK_RE`）；
    - 其余（主要是拉丁字母、数字、ASCII 标点）按每 `_LATIN_CHARS_PER_TOKEN`=4 个字符 1 token 向上取整。
    本机无 `tiktoken`，也不为本任务引入新依赖（brief 禁止事项 + 规范 8.3 的最小依赖纪律），
    故取可解释的启发式而非厂商分词器。

    余量落在**哪一层**（2026-11-17 T2 真实冒烟实测后写定，不得再含糊）：
    - 计数层几乎不放大：该部署对英文约 3.9 字符/token（78 字符 / `usage.total_tokens`=20），
      所以「每 4 字符 1 token」是贴着服务端口径取齐，而不是刻意高估；
    - 真正的余量在**预检线**：`embedding_max_tokens_per_line`=128,000 相对服务端实测边界
      131,072 留了 3,072（config.py:78-80、007 三-2）。
    为什么不能把计数也一并放大成「≥ 字符数」那种假保守：那等于把有效线压到约 1/4，
    会把本来能过的长检索串在客户端拦掉，直接伤召回（而拦截报错还会把人引向「缩短文本」的错误动作）。

    危害方向仍是单向的——**低估才致命**：服务端超长明确 400 且同批混入一条超长会
    **整批 400、count=0**（007 三-2/三-3），客户端一旦放行就是整批陪葬。
    因此本函数两处都朝不低估的方向取：CJK 一字一 token（BPE 对汉字常见 1～2 token/字，
    此处按 1 取下界，靠预检线的 3,072 余量吸收；若后续实测出现纯中文长串被服务端拒，
    正确修法是把除数调小或把线调低，**不是**静默跳过预检），非 CJK 一律向上取整。
    检索串由「卡片名 + 谓词 + 取值 + 引文」拼装，长度量级远小于该线（粒度另由步骤 3c 实测）。
    """
    cjk = _CJK_RE.findall(text)
    rest = len(text) - len(cjk)
    if not rest:
        return len(cjk)
    latin_tokens = -(-rest // _LATIN_CHARS_PER_TOKEN)  # 向上取整，避免整除丢余数造成低估
    return len(cjk) + latin_tokens


def _reject_blank_inputs(texts: list[str], side: str) -> None:
    """断言④ + I-4：空集合 / 空串 / 纯空白文本在客户端先拒（依 4.4-④、007 六-2、4.12、8.15）。

    实测 `input=[""]` 返回 HTTP 200 且 1024 个分量全非零——服务端「垃圾进、正常出」，
    所以「无空数组」那条断言防不住这种形态，必须在入口拦。
    空集合是另一族事故（I-4）：批循环 `range(0,0,size)` 不产生批次，却返回 `dense_available=True`
    的空向量列表，让空索引冒充成功。两种成因措辞分道（依 4.14）。
    报错用 ValueError（依 4.2：入参不合法归 ValueError），并点名是哪一条、哪一侧。
    """
    if not texts:
        raise ValueError(
            f"{side} 侧检索串集合为空：没有东西可进索引（依 4.12、8.15）。"
            "请先确认语料查询为何返回 0 条，不要用空结果冒充稠密通道可用。"
        )
    bad = [i for i, t in enumerate(texts) if not isinstance(t, str) or not t.strip()]
    if bad:
        raise ValueError(
            f"{side} 侧存在空或纯空白检索串，条目下标 {bad}（依 007 六-2：服务端对此返回 200 "
            "且向量全非零，属静默污染，客户端必须先拒）。建索引遇到空检索串条目要报错而不是跳过"
            "（依 4.12「宁可失败也不交半成品」）——请先修好语料侧的检索串拼装。"
        )


def _precheck_tokens(texts: list[str], limit: int) -> None:
    """断言配套的发送前逐条预检（依 4.5、007 三-2/3）。

    为什么不能「先发再看」：同批混入一条超长会整批 400、`count=0`，一条脏数据拖垮同批全部条目，
    索引缺一块却无人知晓（规范 4.5 的 bug 形态描述）。报错点名越界条目的下标与近似 token 数。
    """
    for i, t in enumerate(texts):
        used = estimate_tokens(t)
        if used > limit:
            raise ValueError(
                f"第 [{i}] 条检索串超出 token 预检线：近似 {used} > embedding_max_tokens_per_line={limit}"
                "（近似口径见 estimate_tokens docstring，非服务端口径）。依 007 三-3，同批混入一条超长"
                "会整批 400、count=0，故此处不发请求。请缩短该条检索串或调高预检线。"
            )


# ── api 档 ──────────────────────────────────────────────────────────────────────────────
class ApiEmbedder:
    """OpenAI 兼容 `/embeddings` 在线向量后端（决策记录 005 第五节定路径、007 第二节实测可用）。

    构造期就把配置查干净（依 4.1，范式 `extract.py:154-172`）：缺任一必需项直接 RuntimeError
    并点名环境变量，代码不自动换档、不返回空结果冒充成功（依 4.13）。
    """

    REQUIRED_ENV = ("EMBEDDING_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL")

    def __init__(self, config: Config | None = None, *, transport: httpx.BaseTransport | None = None):
        cfg = config if config is not None else get_config()
        missing = [
            name
            for name, value in (
                ("EMBEDDING_BASE_URL", cfg.embedding_base_url),
                ("EMBEDDING_API_KEY", cfg.embedding_api_key),
                ("EMBEDDING_MODEL", cfg.embedding_model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "ApiEmbedder 需要在线向量服务配置，以下环境变量为空：" + "、".join(missing) + "。"
                "请复制 backend/.env.example 为 backend/.env 并填入这三项"
                "（无 key 环境下请显式改用 StubEmbedder 或 LocalEmbedder，向量后端不会自动切换）。"
            )
        # 维度必须是正整数：0 或负数会让下面的维度断言变成永真/永假（依 2.15 显式区间）。
        if cfg.embedding_dim <= 0:
            raise RuntimeError(
                f"embedding_dim={cfg.embedding_dim} 不是正整数（依 4.4-②：每条向量的维度断言以此为基准，"
                "非正值会让该断言失去意义）。定稿值 1024；改维度须同步重建索引（007 六-3 MRL 截断不等价）。"
            )
        if cfg.embedding_batch_size <= 0:
            raise RuntimeError(
                f"embedding_batch_size={cfg.embedding_batch_size} 不是正整数，无法切批。"
                "注意服务端硬边界实测为 25 条（007 三-1，官方文档另称 20），"
                "本实现不把 21～25 判为非法，只按本配置值切批。"
            )
        if cfg.embedding_timeout_s <= 0:
            raise RuntimeError(f"embedding_timeout_s={cfg.embedding_timeout_s} 必须为正数（秒）。")
        if cfg.embedding_max_tokens_per_line <= 0:
            raise RuntimeError(
                f"embedding_max_tokens_per_line={cfg.embedding_max_tokens_per_line} 必须为正数，"
                "否则逐条预检形同虚设（依 4.5）。"
            )
        # text_type 合法性在构造期校验（依 4.4-⑤）：非法值在服务端是 400 并回显
        # `its value should be in ['document','query']`（007 四），转成显式配置错误而不是重试或忽略。
        self._text_types = self._resolve_text_types(cfg)
        self.cfg = cfg
        # transport 可注入是本层「测试不联网」的唯一通道（依 5.17）；生产默认走 httpx 标准传输。
        self._transport = transport

    @staticmethod
    def _resolve_text_types(cfg: Config) -> tuple[str | None, str | None]:
        """把两个配置项解析为「实际生效的组合」：留空 → None（确实不传），非空 → 校验后原样传。"""
        resolved: list[str | None] = []
        for env_name, raw in (
            ("EMBEDDING_TEXT_TYPE_DOCUMENT", cfg.embedding_text_type_document),
            ("EMBEDDING_TEXT_TYPE_QUERY", cfg.embedding_text_type_query),
        ):
            if not raw:
                resolved.append(None)
                continue
            if raw not in VALID_TEXT_TYPES:
                raise RuntimeError(
                    f"{env_name}={raw!r} 不在合法取值 ['document', 'query'] 内（依 4.4-⑤：服务端对该参数"
                    "的非法值返回 400 并回显 its value should be in ['document','query']，007 第四节实测）。"
                    "本项目在构造期拦住，不做重试也不回退默认值——静默回退等于换向量空间且不报错。"
                    "若确实不想传该参数，请把配置留空，向量配置签名会记作「未声明」。"
                    "补齐路径见 backend/.env.example 的 EMBEDDING_TEXT_TYPE_* 两行。"
                )
            resolved.append(raw)
        return (resolved[0], resolved[1])

    # ── 只读暴露给 T3 / 自检的签名材料 ──────────────────────────────────────────────────
    @property
    def effective_text_types(self) -> tuple[str | None, str | None]:
        """实际会发进请求体的 `(入库侧, 查询侧)` 值；`None` 表示该侧真的不带该字段。

        plan:1097 ① 要求阶段八自检打印「向量请求实际发出的 text_type 值，与配置不符或为 None 即判失败」，
        本属性就是那句话的取数入口（比从 vector_signature 反推更直白，也不混淆「未声明」的展示口径）。
        """
        return self._text_types

    @property
    def text_type_declared(self) -> bool:
        """两侧是否都显式声明了 text_type。任一侧留空即 False——那种索引必须重标阈值（依 4.9）。"""
        return all(v is not None for v in self._text_types)

    # ── 公开接口 ────────────────────────────────────────────────────────────────────────
    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """入库侧：按 `embedding_batch_size` 切批向量化，`text_type` 显式取 document 侧配置。

        顺序与条数严格对应输入（不去重、不重排）：T3 按 claim 顺序把向量写进 SQLite，
        错位比多花 token 严重得多（依 4.4-①「缺条目不得用默认分补齐」的同源纪律）。
        """
        if isinstance(texts, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法在本仓归一为 ValueError，CLI 只 except ValueError
                "embed_documents 需要字符串列表；单条请用 embed_query（依 4.2 入参归一）"
            )
        batched = list(texts)
        _reject_blank_inputs(batched, "入库")
        _precheck_tokens(batched, self.cfg.embedding_max_tokens_per_line)
        return self._embed(batched, self._text_types[0])

    def embed_query(self, text: str) -> EmbeddingResult:
        """查询侧：单条问句，`text_type` 显式取 query 侧配置（依 4.4-⑤，两处都不得依赖默认值）。"""
        if not isinstance(text, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法在本仓归一为 ValueError，CLI 只 except ValueError
                "embed_query 需要单个字符串；多条请用 embed_documents（依 4.2 入参归一）。"
                "这里不做静默摊平——查询侧与入库侧的 text_type 不同，混用即换向量空间（007 四）。"
            )
        _reject_blank_inputs([text], "查询")
        _precheck_tokens([text], self.cfg.embedding_max_tokens_per_line)
        return self._embed([text], self._text_types[1])

    def vector_signature(self) -> VectorSignature:
        """暴露给 T3 的向量配置签名材料（依 4.9；实际生效的 text_type 组合从这里只读获取）。"""
        types_pair = (
            self._text_types[0] or TEXT_TYPE_UNDECLARED,
            self._text_types[1] or TEXT_TYPE_UNDECLARED,
        )
        base_hash = hashlib.sha256(self.cfg.embedding_base_url.encode("utf-8")).hexdigest()[:16]
        return _signature("api", self.cfg.embedding_model, self.cfg.embedding_dim, base_hash, types_pair)

    # ── 内部实现 ────────────────────────────────────────────────────────────────────────
    def _embed(self, texts: list[str], text_type: str | None) -> EmbeddingResult:
        size = self.cfg.embedding_batch_size
        batches = [texts[i : i + size] for i in range(0, len(texts), size)]
        vectors: list[list[float]] = []
        total_tokens = 0
        calls = 0
        for batch in batches:
            payload, attempt_calls = self._post_with_retries(batch, text_type)
            vectors.extend(self._parse_response(payload, len(batch), text_type))
            total_tokens += self._usage_tokens(payload)
            calls += attempt_calls
        declared = text_type or TEXT_TYPE_UNDECLARED
        # 结果里的 text_types 保持「两侧组合」口径而不是本次单侧值：T3 要把它直接写进报告与
        # 阈值文件的标定条件（规范 6.12），每次调用都给同一份材料才不会被误读成「这次只声明了一侧」。
        pair = (
            self._text_types[0] or TEXT_TYPE_UNDECLARED,
            self._text_types[1] or TEXT_TYPE_UNDECLARED,
        )
        logger.debug("向量档=api，本批 %d 条，实际发出的 text_type=%s", len(texts), declared)
        return EmbeddingResult(
            vectors=vectors,
            backend_name="api",
            dense_available=True,
            total_tokens=total_tokens,
            requests=calls,
            text_types=pair,
        )

    def _post_with_retries(self, batch: list[str], text_type: str | None) -> tuple[Any, int]:
        """首次 + 重试两次（依 4.11）。返回（响应 JSON, 本次实际发出的请求数）。

        重试只覆盖**传输层**故障（连接错误 / 超时 / 429 / 5xx）：这三种都是「同一请求再来一次可能成」。
        响应残缺（`EmbeddingResponseError`）**不重试**——服务端已经给了 200 和一份坏数据，
        原样重发只会再烧一遍 token 而结果同形（依 4.4「任一不满足即抛错终止建索引」）。
        """
        body: dict[str, Any] = {
            "model": self.cfg.embedding_model,
            "input": batch,
            # dimensions 显式传给服务端：007 六-3 实测该参数是 MRL 前缀截断，
            # 不传时拿到的是模型默认维度，可能与 embedding_dim 不符而无人察觉。
            "dimensions": self.cfg.embedding_dim,
        }
        if text_type is not None:
            body["text_type"] = text_type
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with httpx.Client(
                    transport=self._transport,
                    timeout=httpx.Timeout(self.cfg.embedding_timeout_s),
                ) as client:
                    response = client.post(
                        f"{self.cfg.embedding_base_url.rstrip('/')}/embeddings",
                        headers={"Authorization": f"Bearer {self.cfg.embedding_api_key}"},
                        json=body,
                    )
            except (httpx.TransportError, OSError) as exc:
                last_error = exc
                logger.warning("向量请求第 %s/%s 次失败: %s", attempt, MAX_ATTEMPTS, exc)
                continue
            if response.status_code >= 400:
                if self._retryable_status(response.status_code) and attempt < MAX_ATTEMPTS:
                    logger.warning(
                        "向量接口 HTTP %s，准备重试（%s/%s）", response.status_code, attempt, MAX_ATTEMPTS
                    )
                    continue
                raise self._status_error(response, batch_len=len(batch))
            try:
                payload = response.json()
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise EmbeddingResponseError(
                    f"向量响应不完整：HTTP 200 但响应体不是 JSON（{exc}）。"
                    "多半是网关返回了错误页——请检查 EMBEDDING_BASE_URL 指向的服务（依 4.2 归一到向量族异常，"
                    "不让裸 JSONDecodeError 炸穿建索引）"
                ) from exc
            return payload, attempt
        raise EmbeddingResponseError(
            f"向量请求连续 {MAX_ATTEMPTS} 次尝试均失败（最后错误 "
            f"{type(last_error).__name__}: {last_error}；超时配置 embedding_timeout_s="
            f"{self.cfg.embedding_timeout_s}s）。依 4.12 宁可建索引失败，也不静默产出空向量；"
            "请检查网络通路，或显式改用 stub/local 档（向量后端不会自动切换）。"
        )

    @staticmethod
    def _retryable_status(status: int) -> bool:
        """哪些 HTTP 状态值得重试：429（限流，退避后再来可能成）与 5xx（服务端抖动）。

        其余 4xx 一律不重试：它们是配置或入参问题，重发只会重复失败并白烧 token（依 4.11）。
        """
        return status == 429 or 500 <= status < 600

    def _status_error(self, response: httpx.Response, *, batch_len: int) -> EmbeddingResponseError:
        """把状态码翻译成「成因 + 下一步动作」，四种故障各配独有短语（依 4.14）。"""
        status = response.status_code
        snippet = response.text[:200].replace("\n", " ")
        hints = {
            401: "鉴权失败：请核对 EMBEDDING_API_KEY（005 七-2 实测无 key 即 401 invalid_api_key）",
            403: "拒绝访问：确认该 key 是否已开通 EMBEDDING_MODEL 这个模型",
            404: "端点不存在：请核对 EMBEDDING_BASE_URL 是否为 OpenAI 兼容基址（应以 /v1 结尾）",
            429: (
                "限流：官方口径 RPM 24,000 / TPM 1,000,000（005 七-1，属外部资料），"
                "已重试仍未通过，请降低 EMBEDDING_BATCH_SIZE 或稍后重建"
            ),
            400: self._bad_request_hint(snippet),
        }
        hint = hints.get(status)
        if hint is None:
            hint = (
                f"服务端错误 HTTP {status}：稍后重试，或显式改用 local/stub 档"
                if status >= 500
                else f"未预期的 HTTP {status}"
            )
        return EmbeddingResponseError(f"向量接口返回 {hint}；本批 {batch_len} 条未获得向量。响应片段：{snippet}")

    @staticmethod
    def _bad_request_hint(snippet: str) -> str:
        """同为 400，成因至少两种，措辞必须分道（依 4.14）：配置拼错 vs 入参越界。

        两者都靠回显文本分辨（服务端在这两处都会把关键短语打出来，007 三-2/四 实测）：
        - `should be in ['document', 'query']` → text_type 非法，该查 .env 的两行配置；
        - `maximum context length` / `not be larger than` → token 或条数越界，该查语料与批次大小。
        认不出来时给通用提示，不猜成另一类。
        """
        lowered = snippet.lower()
        if "text_type" in lowered:
            return (
                "请求被拒：text_type 取值非法，请核对 EMBEDDING_TEXT_TYPE_DOCUMENT / EMBEDDING_TEXT_TYPE_QUERY"
                "（合法值只有 document / query，留空表示不传，007 四）"
            )
        if "maximum context length" in lowered or "not be larger than" in lowered:
            return (
                "请求被拒：超出服务端边界（单行 token 实测 131,072 / 单次条数实测 25，007 三-1/三-2）。"
                "客户端已按近似口径逐条预检，说明该条落在估算线内而服务端口径外——请缩短该条检索串"
            )
        return "请求被拒：多为入参越界（单行 token 超服务端边界，或批量条数/text_type 非法）"

    @staticmethod
    def _usage_tokens(payload: Any) -> int:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return 0
        total = usage.get("total_tokens")
        return int(total) if isinstance(total, (int, float)) and not isinstance(total, bool) else 0

    def _parse_response(self, payload: Any, expected: int, text_type: str | None) -> list[list[float]]:
        """五项响应完整性断言中的 ①②③ 与 ⑤ 的回显核对，全部在这里完成（依 4.4）。

        任一条不满足即抛 `EmbeddingResponseError` 终止建索引（依 4.12）：
        「宁可建索引失败，也不能让空向量把稠密通道变成零命中却报告成功」（步骤 3b 原文）。
        """
        if not isinstance(payload, dict):
            raise EmbeddingResponseError(
                f"向量响应不完整：响应体应为对象，实际是 {type(payload).__name__}（依 4.4）"
            )
        data = payload.get("data")
        if not isinstance(data, list):
            raise EmbeddingResponseError(
                "向量响应不完整：缺少 embedding 列表（顶层 `data` 键缺失或不是数组），"
                f"实际收到 {sorted(payload)[:6]}（依 4.4-③：只看 status_code 过关会让稠密通道静默变零命中）"
            )
        # 断言①：条数相等。
        if len(data) != expected:
            raise EmbeddingResponseError(
                f"向量响应不完整：返回条数 {len(data)} != 请求条数 {expected}（依 4.4-①，"
                "缺条目不得用默认值补齐——错位向量会让答案指到错误出处）"
            )
        dim = self.cfg.embedding_dim
        vectors: list[list[float]] = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise EmbeddingResponseError(
                    f"向量响应不完整：第 [{i}] 条不是对象，而是 {type(item).__name__}（依 4.4）"
                )
            vec = item.get("embedding")
            # 断言③：无空数组（官方明示传 output_type=sparse 时 200 却给空 embedding，005 §7.3-3）。
            if not isinstance(vec, list) or not vec:
                raise EmbeddingResponseError(
                    f"向量响应不完整：第 [{i}] 条 embedding 为空数组或缺失（依 4.4-③：兼容接口不支持稀疏输出，"
                    "这类 200 + 空向量正是「通道在跑却没结果」的最危险形态）"
                )
            # 断言②：维度相等。
            if len(vec) != dim:
                raise EmbeddingResponseError(
                    f"向量响应不完整：第 [{i}] 条维度 {len(vec)} != embedding_dim={dim}（依 4.4-②；"
                    "007 六-3 实测 dimensions 为 MRL 前缀截断，不同维度不等价，不得本地截断复用）"
                )
            clean: list[float] = []
            for j, v in enumerate(vec):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise EmbeddingResponseError(
                        f"向量响应不完整：第 [{i}] 条第 [{j}] 个分量不是数值（{v!r}），"
                        "下游点积会以裸 TypeError 中止（依 4.14 要能分辨成因）"
                    )
                # I-2（评审 task2-verdict.md）：JSON 的 NaN/Infinity 字面量 Python json 默认接受，
                # 五项断言全部通过却产出不可用向量（cos 为 NaN → 所有阈值比较恒 False，
                # 最坏情况是闸门「无从判断」而放行）。这里按 4.4 补上分量有限性校验，
                # 措辞与「不是数值」分道（4.14），并点名条号/分量号便于定位。
                if not math.isfinite(v):
                    raise EmbeddingResponseError(
                        f"向量响应不完整：第 [{i}] 条第 [{j}] 个分量不是有限数值（NaN/Inf，收到 {v!r}），"
                        "依 4.4/8.13：此类分量参与余弦会让比较恒 False，不得混入索引。"
                    )
                clean.append(float(v))
            # 全零检查（规范 5.10 允许的四类断言之列）：0 向量 cos 恒为 0，会被阈值标定当成真实负例。
            if all(x == 0.0 for x in clean):
                raise EmbeddingResponseError(
                    f"向量响应不完整：第 [{i}] 条为全零向量（依 007 第二节实测正常输出 1024 个分量全非零；"
                    "全零等价于「没有方向」，冒充真向量会污染阈值标定，依 4.12 禁止）"
                )
            echoed = item.get("text_type")
            if isinstance(echoed, str) and text_type is not None and echoed != text_type:
                raise EmbeddingResponseError(
                    f"向量响应不完整：服务端回显 text_type={echoed!r} 与请求 {text_type!r} 不一致（依 4.4-⑤："
                    "这说明请求里的 text_type 没生效，向量空间已被换成另一套而全程 200，007 第四节实测 cos≈0.925）"
                )
            vectors.append(clean)
        return vectors


# ── local 档 ────────────────────────────────────────────────────────────────────────────
class LocalEmbedder:
    """自建权重兜底档（决策记录 005 第四节：`api` → `local` → BM25-only 的第二级）。

    **本阶段不安装 `[retrieval]` extra、不下载任何模型权重**（规范 8.3、brief 环境事实），
    所以这个类现在的正确行为就是「显式报错并说清缺什么」：
    - 依赖缺失 → ImportError 点名 `pip install -e ".[retrieval]"`（依 2.18 延迟导入 + 可安装提示）；
    - 权重加载失败 → RuntimeError 点名权重路径与下一步（依 4.13：禁止悄悄退回 api 或 stub）。

    `loader` 形参是唯一的注入点：它让「依赖已装但权重没下载」这条分支能在不联网、
    不装 torch 的前提下被测到（依 5.17）；生产路径不传它，走 sentence-transformers 的真实加载。
    """

    def __init__(self, config: Config | None = None, *, loader=None):
        cfg = config if config is not None else get_config()
        if not cfg.embedding_model:
            raise RuntimeError(
                "LocalEmbedder 需要 EMBEDDING_MODEL 指定本地权重目录或标识符；该项为空。"
                "请补齐 backend/.env（参考 backend/.env.example），向量后端不会自动切换。"
            )
        # I-3（评审 task2-verdict.md）：依赖检查在两条路径都要过一遍。原先只在 else 支检查，
        # 传入 loader 的调用方可以静默跨过「装了 extra 才能用」这条纪律（规范 8.3/4.13）：
        # 生产调用方若注入 loader，会在没有 sentence-transformers 的机器上装作可用，
        # 直到 _encode 深处抛 AttributeError。注入点只用于「依赖在、权重没下载」的测试分支（5.17），
        # 不能成为绕过依赖前提的后门。
        if loader is None:
            load = self._load_sentence_transformer()
        else:
            self._assert_optional_dependency_present()
            load = loader
        try:
            self._model = load(cfg.embedding_model)
        except Exception as exc:  # 权重加载失败原因多样（缺文件/校验和不符/内存不足），一律归为配置类 RuntimeError
            raise RuntimeError(
                f"LocalEmbedder 无法加载 sentence-transformers 权重 {cfg.embedding_model!r}"
                f"（{type(exc).__name__}: {exc}）。"
                "本阶段按计划不下载模型权重（决策记录 005 第五节、规范 8.3）：如需离线向量，"
                '请执行 pip install -e ".[retrieval]" 并手动取得权重后重试；'
                "否则请显式把 EMBEDDING_BACKEND 改为 api 或 stub——向量后端不会自动切换（依 4.13）。"
            ) from exc
        self.cfg = cfg

    @staticmethod
    def _assert_optional_dependency_present() -> None:
        """两条构造路径共用的依赖守卫（I-3）：缺 sentence-transformers 即点名安装命令（规范 2.18/8.3）。

        单独抽成方法是为了让「注入 loader」与「真实加载」走同一句措辞（依 4.14 同族故障同提示），
        不许出现「注入路径就默默放宽」的分支。
        """
        # sys.modules[name] = None 是测试里屏蔽可选依赖的标准做法（monkeypatch.setitem），
        # 此时 find_spec 会因 __spec__ is None 抛 ValueError，而真实缺失是返回 None；
        # 两种形态都按「依赖缺失」处理（规范 5.17 的测试替身纪律不能反过来破坏守卫）。
        present = sys.modules.get("sentence_transformers", "SENTINEL") is not None
        if present:
            try:
                present = importlib.util.find_spec("sentence_transformers") is not None
            except (ImportError, AttributeError, ValueError):
                present = False
        if not present:
            raise ImportError(
                'LocalEmbedder 需要可选依赖 sentence-transformers：请执行 pip install -e ".[retrieval]"'
                "（决策记录 005 第五节的回滚路径）。本阶段默认不安装该 extra、不下载权重（规范 8.3），"
                "因此该档在当前环境本就不可用；请显式改用 api 或 stub 档，向量后端不会自动切换。"
            )

    @staticmethod
    def _load_sentence_transformer():
        LocalEmbedder._assert_optional_dependency_present()
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer

    @property
    def effective_text_types(self) -> tuple[None, None]:
        """本地档（bge-m3 一类）没有 text_type 这个参数（007 第四节末条）：一律 `None`。"""
        return (None, None)

    @property
    def text_type_declared(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        if isinstance(texts, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法归一为 ValueError，理由见 ApiEmbedder 同名分支
                "embed_documents 需要字符串列表；单条请用 embed_query（依 4.2）"
            )
        batched = list(texts)
        _reject_blank_inputs(batched, "入库")
        _precheck_tokens(batched, self.cfg.embedding_max_tokens_per_line)
        return self._encode(batched)

    def embed_query(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法归一为 ValueError，理由见 ApiEmbedder 同名分支
                "embed_query 需要单个字符串；多条请用 embed_documents（依 4.2）"
            )
        _reject_blank_inputs([text], "查询")
        _precheck_tokens([text], self.cfg.embedding_max_tokens_per_line)
        return self._encode([text])

    def _encode(self, texts: list[str]) -> EmbeddingResult:
        """本地编码后的校验与 api 档同形（依 4.4：断言属于「响应完整性」，不因来源而异）。

        本地档没有 HTTP 响应，也就没有条数断言的位置——条数由 `zip` 天然保证，
        维度与全零两项照旧拦，否则「本地建的索引被 API 档阈值判定」时缺口同样致命（依 4.9）。
        """
        raw = self._model.encode(texts)
        rows = [[float(x) for x in row] for row in raw]
        dim = self.cfg.embedding_dim
        if len(rows) != len(texts):
            raise EmbeddingResponseError(
                f"向量响应不完整：本地模型返回条数 {len(rows)} != 请求条数 {len(texts)}（依 4.4-①）"
            )
        for i, row in enumerate(rows):
            if len(row) != dim:
                raise EmbeddingResponseError(
                    f"向量响应不完整：本地模型第 [{i}] 条维度 {len(row)} != embedding_dim={dim}"
                    "（换本地模型等于换相似度分布，须同步改配置并重建索引，依 4.9）"
                )
            if all(x == 0.0 for x in row):
                raise EmbeddingResponseError(f"向量响应不完整：本地模型第 [{i}] 条为全零向量（依 4.12）")
        return EmbeddingResult(
            vectors=rows,
            backend_name="local",
            dense_available=True,
            total_tokens=0,
            requests=0,
            text_types=(TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED),
        )

    def vector_signature(self) -> VectorSignature:
        """本地档两侧 text_type 一律记「未声明」，使跨档混用在签名层面就不同构（依 4.9、007 四末条）。"""
        base_hash = hashlib.sha256(f"local::{self.cfg.embedding_model}".encode()).hexdigest()[:16]
        return _signature(
            "local",
            self.cfg.embedding_model,
            self.cfg.embedding_dim,
            base_hash,
            (TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED),
        )


# ── stub 档 ─────────────────────────────────────────────────────────────────────────────
class StubEmbedder:
    """无向量档：检索退化 BM25-only（决策记录 005 第四节第三级、全局约束 6 的离线线）。

    三条硬规矩：
    1. **不伪造向量**（依 brief 第 21 行、规范 8.10）：返回 `vectors=[]` 且 `dense_available=False`。
       0 向量冒充真向量的话，它的余弦相似度恒为 0，会被阈值标定当成「确实不相关」的负例吸收，
       标出的 tau 偏高一侧并开始误伤正例——这正是规范 4.12 禁止的「好看数字冒充产出」。
    2. **仍然做入参校验**：空/纯空白照拦，让降级演练走的也是同一条数据质量线（依 4.12）。
    3. **自报口径**：`requests=0 / total_tokens=0` 显式写出来，缺这两项的话
       「0 次调用」与「忘了统计」在报告里长得一样（依 4.12、5.18）。
    """

    def __init__(self, config: Config | None = None):
        self.cfg = config if config is not None else get_config()

    @property
    def effective_text_types(self) -> tuple[None, None]:
        return (None, None)

    @property
    def text_type_declared(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        if isinstance(texts, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法归一为 ValueError，理由见 ApiEmbedder 同名分支
                "embed_documents 需要字符串列表（依 4.2）"
            )
        _reject_blank_inputs(list(texts), "入库")
        return self._result(len(texts))

    def embed_query(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str):
            raise ValueError(  # noqa: TRY004  依 4.2：入参不合法归一为 ValueError，理由见 ApiEmbedder 同名分支
                "embed_query 需要单个字符串（依 4.2）"
            )
        _reject_blank_inputs([text], "查询")
        return self._result(1)

    def _result(self, n: int) -> EmbeddingResult:
        # 带上条数：降级演练的日志要能说清「多少条退化为 BM25-only」（评审 M-2）。
        logger.info(
            "抽取/检索后端=stub，本批 %d 条退化为 BM25-only，不得用于达标判定（依 4.3、cli.py:14 同一口径）",
            n,
        )
        return EmbeddingResult(
            vectors=[],
            backend_name="stub",
            dense_available=False,
            total_tokens=0,
            requests=0,
            text_types=(TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED),
        )

    def vector_signature(self) -> VectorSignature:
        digest = f"{STUB_SIGNATURE_PREFIX}:{self.cfg.embedding_dim}"
        return VectorSignature(
            backend="stub",
            model="none",
            dim=0,
            base_url_hash="",
            text_types=(TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED),
            digest=digest,
        )


# ── 共用的签名装配 ──────────────────────────────────────────────────────────────────────
def _signature(
    backend: str,
    model: str,
    dim: int,
    base_hash: str,
    types_pair: tuple[str, str],
) -> VectorSignature:
    """把四样材料拼成稳定摘要（依 4.9：模型 + 维度 + 基址哈希 + text_type 两侧组合）。

    分隔符用 `\\x1f`（单元分隔符）而不是 `-` 或 `|`：模型名与基址里都可能出现这些字符，
    用不可能出现在正常文本里的控制字符拼接才不会让两组不同配置撞出同一个摘要。
    """
    parts = [backend, model, str(dim), base_hash, *types_pair]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return VectorSignature(
        backend=backend,
        model=model,
        dim=dim,
        base_url_hash=base_hash,
        text_types=types_pair,
        digest=digest,
    )


# ── 装配：唯一一处「谁选的档」────────────────────────────────────────────────────────────
def build_embedder(config: Config | None = None, **kwargs: Any) -> ApiEmbedder | LocalEmbedder | StubEmbedder:
    """按 `embedding_backend` 显式选档（依 4.13：调用方必须能指出这一档是谁选的）。

    这里**不看有没有 key**、不做任何可用性探测后回落：无 key 时 api 档就该大声失败。
    隐式换档的后果写在规范 4.13 的 bug 形态里——无 key 机器上跑得通、有 key 机器上行为不同，
    降级演练时才发现真实路径从未被验证过。
    """
    cfg = config if config is not None else get_config()
    backend = cfg.embedding_backend
    if backend == "api":
        return ApiEmbedder(cfg, **kwargs)
    if backend == "local":
        return LocalEmbedder(cfg, **kwargs)
    if backend == "stub":
        return StubEmbedder(cfg)
    raise RuntimeError(
        f"未知的向量档位 embedding_backend={backend!r}（合法值 api / local / stub，见 core/config.py:20）。"
        "请修正 backend/.env；本函数不会替你挑选其他档位（依 4.13）。"
    )


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度，供「可复现性按 cos 阈值判」一类核对使用（依 4.10、5.10）。

    为什么单独提供这支函数并把全零当作错误：规范 4.10 规定索引可复现只能按 cos ≥ 0.998 判
    （R18：007 六-1 旧读数 0.999095、T2 真实冒烟读数 0.998869，同一部署存在波动，
    取 0.999 会随机假红），逐位相等的断言同理。
    全零向量分母为 0，返回 0.0 会让人误判「不可复现」，而真相是「这条向量压根没方向」，
    故显式报错而不是给出一个好看的数（依 8.13 不得静默放行）。

    **值域是 [-1, 1]，不是 [0, 1]**（评审 task2-verdict.md M-4）：反向向量得 -0.999…，
    `Hit.dense_score/score` 契约要求 [0, 1]（依 D4），调用方写入 Hit 前须按 007 口径映射/裁剪；
    本函数只负责「供复现核对」，不替调用方做有语义的归一化（否则掩盖真实夹角）。
    """
    if len(a) != len(b):
        raise ValueError(f"cosine 需要等长向量，收到 {len(a)} 与 {len(b)}（依 4.4-② 同源：维度不符即错）")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        raise ValueError(
            "cosine 的分母为 0：其中一侧是全零向量（无方向），不得拿来判可复现性（依 4.10、8.14）"
        )
    return dot / (na * nb)
