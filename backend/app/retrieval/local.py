"""实现 `LocalBackend`：稠密向量落 SQLite + BM25/jieba 中文稀疏通道（阶段二 T3）。

口径出处：plan 阶段二步骤 3 / **3b** / 3c（`.superpowers/sdd/plan/phase2-text.md:27-79`）、
`task3-brief.md`「来自 T1/T2 交付的硬事实」五条、编码规范基线 4.9 / 4.11 / 4.12 / 4.13 / 6.8 /
6.11 / 8.3 / 8.4 / 8.7 / 8.10 / 8.13 / 8.14 / 8.15 / 8.16，以及 lead 裁决 R18（复现线 0.998）、
R19（稠密一律 cosine）、评审 Important 2（`index_built=False` 必须显式报错并提示重建命令）。

三档依赖关系（本模块只装配、不选档）：向量后端由 `app.retrieval.embedding.build_embedder(cfg)` 按
`EMBEDDING_BACKEND` 显式决定（依 4.13），本文件里**不得**出现「无 key 就换 stub」这类隐式分支；
`Hit` / `IndexStats` / `SearchBackend` 一律 import 自 T1 的契约层（依 6.7，不自建同义 dataclass）。

已知限制（依 3.4 写在头部，不得藏进实现细节）：
- **本阶段不装 `retrieval` extra、不下载权重、不引入 FAISS**（规范 8.3、8.4）：向量以 JSONL 落
  `Config.data_dir/index/vectors.jsonl`，检索期全量线性扫 cos。条目量级小（试点 223 条），
  原计划即判定「规模小无需近似索引」；量级上升后换 FAISS 属内部实现替换，须另立决策记录。
- **重排接缝留给 T4**（依 R11：`local.py` 由 T3 建、T4 只接接缝）：T3 阶段没有重排器，
  `search(rerank=True)` 必须等价于不重排并留下可断言的痕迹（`rerank_note()`），禁止留 `pass`
  冒充实现（禁止清单 8.11）。
- **融合收窄不在本层**：RRF 融合与稀疏名额 `k // 2` 是 T4 的 `search.py` 的职责（依 4.7）。
  本文件的 `search()` 在 T4 接入前是一条「稠密优先 + 稀疏补位」的可跑通路，够 T3 的双通道自检
  与 T5 的分路评测用，不代表最终排序。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import Config, get_config
from app.db.migrate import default_db_path
from app.retrieval.backend import Hit, IndexStats, SearchBackend
from app.retrieval.embedding import build_embedder, cosine, estimate_tokens
from app.retrieval.errors import EmbeddingResponseError
from app.retrieval.rerank import apply_rerank
from app.retrieval.rerank import describe as describe_reranker
from app.retrieval.search import fuse

logger = logging.getLogger(__name__)

# ── 常量与档位 ───────────────────────────────────────────────────────────────────────────
# 切块两档（步骤 3c）：single = 一条事实条目一块；merged = 同卡片多条目合并成块。
# 只有这两档：试点语料 event 占 74%、time/place 极薄（task0-report 第 6.4 节第 9 条），
# 按卡片类型分路建索引对除 person/event 外的分路几乎没有测试价值，索引层保持不分路（YAGNI）。
BLOCK_MODES: tuple[str, str] = ("single", "merged")

# 合并档的实验上限（token）。危害口径照步骤 3c 末段：定稿模型单行 128,000 token 只消除
# 「检索串被截断」的风险，**不改善检索粒度**，而粒度才是命中率的主因——所以「模型吃得下整篇」
# 绝不等于「该把整篇喂进去」，这一档仍以 512 token 为上限，优劣判定归 T5 的开发集实测。
MERGED_BLOCK_TOKEN_LIMIT = 512

# 最小检索串长度（字符）。依据 task0-report 第 6.1 节实测：文本块 min=**1** 字符、中位 146。
# 1～2 字的块几乎无意义，却会稀释 IDF 并白占稠密名额，故建索引前拦住；阈值可由调用方覆盖
# （`min_search_text_chars`），默认值取 10 —— brief 第 21 行的建议值，也是试点语料最短检索串
# （实测 claim 级检索串 min=15 字符）之下的一档安全余量：拦得住脏数据，误杀不了正常条目。
DEFAULT_MIN_SEARCH_TEXT_CHARS = 10

# 可复现性判定线（cos ≥ 0.998，不是 0.999）。依据裁决 R18（2026-11-17）：007 六-1 的 0.999 出自
# 更早一轮读数 0.999095，T2 本轮真实冒烟实测同文本两次调用 cos=0.998869——同一部署存在波动，
# 拿 0.999 当硬门禁会让重建索引的复现校验随机假红。正式更正条文由 T6 写进决策记录 007（依 7.9：
# 不删原文、追加更正并注明日期）。**逐位相等一类断言禁止**（依 4.10、5.10）。
REPRODUCIBILITY_COS_FLOOR = 0.998

# 检索串四段的固定分隔符。为什么用全角竖线而不是空格或 `-`：段落之间必须有词边界，否则
# 「取值尾字 + 引文首字」会被 jieba 粘成一个假词，产生谁也查不到的 token；而 `-` 会出现在
# 拉丁缩写与日期里（`1934-1935`），空格本身就是分词边界但会被 strip 掉、看不出缺段。
FIELD_SEPARATOR = "｜"

# 别名表默认路径：**复用阶段一的唯一来源**，不在这里另抄一份路径口径（依 8.16「不得两套并行维护」）。
from app.ingestion.normalize import DEFAULT_ALIASES_PATH

# T3 阶段的重排痕迹文案（依 4.3：降级要打印一行说明；依 8.11：不得留空冒充正常）。
LOCAL_LEXICAL_RERANK_NOTE = "重排未生效：T3 尚未接入 reranker，已按稠密优先 + 稀疏补位顺序返回"

# 自检查询（`index_stats()` 不带参数时用）。为什么不能随便挑一句：它是「通道是否空转」的判据，
# 必须与语料同源且同时点亮两路——这句里的「省立第一师范学校讲习所」既是试点语料的常见专名形态，
# 又依赖别名表的词，词典没接上时稀疏一路会当场变 0（步骤 3b 的自检语义）。
DEFAULT_PROBE_QUERY = "省立第一师范学校讲习所 何时创设"

# 索引目录下的文件名。meta.json 存两个指纹与生效配置；documents.jsonl 存检索串与定位反查；
# vectors.jsonl 存稠密向量（依 8.4：SQLite/JSONL 级别存储，本阶段不上近似索引）。
META_FILENAME = "meta.json"
DOCUMENTS_FILENAME = "documents.jsonl"
VECTORS_FILENAME = "vectors.jsonl"


# ── 异常：三种失败必须各自独有短语（依 4.14，排查不能靠猜）───────────────────────────────
class IndexNotBuiltError(RuntimeError):
    """索引不存在 / 从未构建：报错点名重建命令（依 8.15、评审 Important 2）。

    为什么不返回空列表：空召回会被上层读成「库里没有答案」而落进拒答，把**数据缺失**伪装成
    **正确行为**——那正是本项目最贵的一类事故（步骤 3b 首段、参考实现 §5.9 同族）。
    """


class IndexStaleError(RuntimeError):
    """索引过期：语料指纹或向量配置签名与当前不符（依 4.9）。

    与上一个类的分工（依 4.14）：「没有索引」该跑一次 `--rebuild`，「索引过期」还得先确认是不是
    换了 embedding 配置或改了 text_type——后者沿用旧阈值会让拒答判定悄悄失真（007 第四节实测
    mean 0.3945 → 0.4694）。两者共用一句「索引失败」就得靠猜成因。
    """


def default_index_dir(config: Config | None = None) -> Path:
    """索引目录：`Config.data_dir / "index"`（依 8.7，与本仓 `default_db_path()` 同一范式）。

    为什么单独一支函数而不内联：`scripts/build_index.py` 与 `LocalBackend` 都要用它，两处各拼
    一次就会在有人改 `DATA_DIR` 时静默分叉（task-8 刚修过入库侧的同形缺陷：`_default_data_dir()`
    原先硬编码 `BACKEND_ROOT/data`，让 `DATA_DIR` 失效）。
    """
    cfg = config if config is not None else get_config()
    return Path(cfg.data_dir) / "index"


# ── 检索串拼装（步骤 3 第 1 项）──────────────────────────────────────────────────────────
def build_search_text(
    *,
    card_name: str,
    predicate: str,
    value: str,
    quote: str,
    heading_path: list[str] | None = None,
    subject: str | None = None,
) -> str:
    """把一条事实条目拼成检索串：卡片名 + 谓词 + 取值 + 原文引文（计划逐字）。

    四段一律用 `FIELD_SEPARATOR` 隔开且**缺一即报错**（依 4.12「宁可失败也不交半成品」）：
    静默跳过会让那条条目从索引里消失，而 `total_docs` 看着仍然像话——交付时「看起来跑通了」，
    真实语料一处都没进索引，正是规范 4.12 描述的事故形态。报错文案点名缺哪几段，
    调用方（`index()`）再补 `claim_id`，运维才知道去修哪一条。

    `heading_path` 只在**非空**时作为附加段落在末尾（不进四段必填校验）。依据 task0-report
    第 6.4 节第 4 条：试点语料有 10 条 `heading_path` 为空、其余多为单层，不得依赖它做分组；
    缺失时按既有定位口径显示，**不得静默当空串拼进检索串**（依 4.12）——那会在串里留下
    「｜｜」的空段，制造一个谁都查不到的假 token 边界。

    `subject`（主语）不是计划的四段之一，但试点语料里它是唯一的实体线索（如「毛泽东」「长沙知府」），
    丢了它就等于把「谁做了什么」问句的关键词通道关掉；因此**有值才拼**、空值不占位。
    """
    parts = [
        ("卡片名", card_name),
        ("谓词", predicate),
        ("取值", value),
        ("原文引文", quote),
    ]
    missing = [label for label, raw in parts if not (raw or "").strip()]
    if missing:
        raise ValueError(
            f"检索串缺少必填段落：{'、'.join(missing)}（依 4.12：空检索串条目在建索引时报错而不是跳过）。"
            f"四段口径来自 plan 步骤 3「卡片名 + 谓词 + 取值 + 原文引文」，实际收到 "
            f"卡片名={card_name!r} 谓词={predicate!r} 取值={value!r} 原文引文={quote!r}"
        )
    segments = [str(raw.strip()) for _, raw in parts]
    # 不做标题重复加权的理由（lead 裁决，见 task3-report）：plan 步骤 3 把检索串定义为
    # 「卡片名 + 谓词 + 取值 + 原文引文」四段各一次；重复标题属调参，而 BM25 的长度归一化
    # 本来就会让短文档上浮（实测「引文恰好含该别名」的条目能压过标题命中 0.006 分）。
    # 那属于算法既定行为，不是缺陷；检索结果是否"够用"由 T5 的三指标评测判定，
    # 不在索引层靠重复词偷偷改分布（8.12：不得为了让数字好看而改口径）。
    optional_subject = (subject or "").strip()
    if optional_subject:
        segments.insert(0, optional_subject)
    headings = [str(h).strip() for h in (heading_path or []) if str(h).strip()]
    if headings:
        segments.append(" ".join(headings))
    return FIELD_SEPARATOR.join(segments)


# ── 分词与用户词典（步骤 3b 的存在理由）─────────────────────────────────────────────────
@dataclass(frozen=True)
class TokenizerState:
    """一次分词装配的结果，供自检断言「词典真的进了分词器」（依 8.16）。"""

    user_dict_terms: tuple[str, ...]
    aliases_path: Path
    loaded: bool
    reason: str = ""


_USER_DICT_LOADED: dict[str, TokenizerState] = {}


def _alias_terms(aliases_path: Path) -> list[str]:
    """从 aliases.yml 取出全部词形（规范名 + 别名），作为 jieba 用户词典的候选。"""
    from app.ingestion.normalize import load_aliases

    table = load_aliases(aliases_path)
    terms: list[str] = []
    seen: set[str] = set()
    for category in ("person", "place"):
        for canonical, aliases in (table.get(category) or {}).items():
            for candidate in [canonical, *(aliases or [])]:
                text = str(candidate).strip()
                key = "".join(text.split())
                if not text or len(key) < 2 or key in seen:
                    continue
                seen.add(key)
                terms.append(text)
    return terms


def ensure_user_dict(aliases_path: Path | None = None) -> TokenizerState:
    """把 `data/aliases.yml` 灌进 jieba 用户词典（依 8.16、步骤 3b 配套要求）。

    为什么必须显式调用而不是指望 jieba 自己认得：参考实现的中文关键词通道恒 0 条，根因是
    「沿用按空格分词、中文整句被当成一个 token」（refimpl-notes 第 1 项）。本项目有 jieba 不等于
    有中文专名能力——「省立第一师范」这类旧称会被切成「省立 / 第一 / 师范」三个碎词，命中的是
    碰巧含碎词的块，与阶段一辛苦做的别名归一各用一套词，命中全靠运气。

    长度 < 2 的词不入典：jieba 对单字词不加权也不会切开它，加进去只会污染 `user_dict_terms()`
    这条自检（真正要防的是专名被切碎）。

    词典按路径缓存：jieba 的 `load_userdict` 是进程级全局状态，重复加载同一个文件只是白费时间；
    缓存键用绝对路径，换了文件（例如测试传 tmp_path）必然重新装配。
    """
    import jieba

    path = DEFAULT_ALIASES_PATH if aliases_path is None else Path(aliases_path)
    key = str(path.resolve())
    cached = _USER_DICT_LOADED.get(key)
    if cached is not None:
        return cached
    terms = _alias_terms(path)
    for term in terms:
        jieba.add_word(term, tag="nz")
    state = TokenizerState(
        user_dict_terms=tuple(terms),
        aliases_path=path,
        loaded=bool(terms),
        reason="" if terms else f"别名表为空或不可读：{path}",
    )
    _USER_DICT_LOADED[key] = state
    if not state.loaded:
        logger.warning("jieba 用户词典未装载任何别名（%s）：阶段一别名归一与检索将各用一套词", state.reason)
    return state


def tokenize(text: str, *, aliases_path: Path | None = None) -> list[str]:
    """BM25 用的分词：jieba 精确模式 + 别名用户词典，丢掉纯空白 token。

    为什么不用 `lcut_for_search`：搜索引擎模式会把长词再切一层碎词，短检索串（试点平均 24.6 字符）
    上会让同一个块被同一概念计两次词频，BM25 的长度归一化随之失真；碎词召回的损失交给别名表兜
    （依 8.16 的路子：把专名喂进词典，而不是把词表切细）。
    """
    import jieba

    ensure_user_dict(aliases_path)
    return [tok for tok in jieba.lcut(text) if tok.strip()]


# ── 索引记录 ─────────────────────────────────────────────────────────────────────────────
@dataclass
class IndexedDoc:
    """一个检索块：`single` 档对应一条事实条目，`merged` 档对应一张卡片。"""

    doc_id: int
    text: str
    claim_ids: tuple[int, ...]
    card_id: int
    source_id: str
    locator: dict[str, Any]
    vector: list[float] | None = None

    def as_record(self) -> dict[str, Any]:
        """给 `documents()` / 落盘用的字典形态（键名固定，T5 的评测脚本要消费，依 6.11）。"""
        return {
            "doc_id": self.doc_id,
            "text": self.text,
            "claim_ids": list(self.claim_ids),
            "claim_id": self.claim_ids[0],
            "card_id": self.card_id,
            "source_id": self.source_id,
            "locator": self.locator,
            "tokens": len(tokenize(self.text)),
        }


@dataclass
class BuildReport:
    """一次建索引的产出统计，供 `scripts/build_index.py` 打印（字段名会被报告脚本复用，依 6.11）。"""

    docs: int = 0
    vectors: int = 0
    postings: int = 0
    claims_in_db: int = 0
    empty_search_texts: int = 0
    skipped_short: int = 0
    dense_hits: int = 0
    sparse_hits: int = 0
    corpus_fingerprint: str = ""
    vector_signature: dict[str, Any] = field(default_factory=dict)
    backend_name: str = ""
    dense_available: bool = False
    elapsed_ms: int = 0
    total_tokens: int = 0
    requests: int = 0
    block_mode: str = "single"
    min_search_text_chars: int = DEFAULT_MIN_SEARCH_TEXT_CHARS


# ── LocalBackend ─────────────────────────────────────────────────────────────────────────
class LocalBackend(SearchBackend):
    """自研检索后端：稠密向量（SQLite/JSONL）+ BM25/jieba 稀疏（阶段二 T3）。

    构造期只做「取数与选档」，不做任何可用性探测后回落（依 4.13）：`embedder=None` 时走
    `build_embedder(config)`，由 `EMBEDDING_BACKEND` 显式决定是哪一档；api 档缺 key 就在
    `ApiEmbedder.__init__` 里大声 RuntimeError，本类不接手、不换档、不返回空结果冒充成功（依 4.1）。

    双指纹（依 4.9）：`corpus_fingerprint`（语料内容）+ `vector_signature.digest`（向量配置签名），
    任一变更即 `IndexStaleError`，报错给出重建命令与「重标阈值」提示。
    """

    def __init__(
        self,
        *,
        config: Config | None = None,
        embedder: Any | None = None,
        db_path: Path | None = None,
        index_dir: Path | None = None,
        aliases_path: Path | None = None,
        block_mode: str = "single",
        min_search_text_chars: int = DEFAULT_MIN_SEARCH_TEXT_CHARS,
        probe_query: str = DEFAULT_PROBE_QUERY,
        reranker: Any | None = None,
    ) -> None:
        if block_mode not in BLOCK_MODES:
            raise ValueError(
                f"未知的切块档位 block_mode={block_mode!r}（合法值 {'/'.join(BLOCK_MODES)}，见步骤 3c）。"
                "本类不会替你回落到 single（依 4.13）：档位拼错了还照跑，产出的索引与评测口径就不是同一回事。"
            )
        if min_search_text_chars < 0:
            raise ValueError(
                f"min_search_text_chars={min_search_text_chars} 不能为负（依 2.15 显式区间）："
                "负数等于取消过滤，1 字符的脏块会直接进索引污染 IDF（task0-report 6.1 实测 min=1）。"
            )
        self.cfg = config if config is not None else get_config()
        # 注入点只有一个（依 5.17）：测试传替身 embedder，生产不传、由 build_embedder 按配置选档。
        self.embedder = embedder if embedder is not None else build_embedder(self.cfg)
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.index_dir = Path(index_dir) if index_dir is not None else default_index_dir(self.cfg)
        self.aliases_path = (
            Path(aliases_path) if aliases_path is not None else Path(DEFAULT_ALIASES_PATH)
        )
        self.block_mode = block_mode
        self.min_search_text_chars = min_search_text_chars
        self.probe_query = probe_query
        # 重排器同样是注入点（依 4.13）：不传 = 本层不重排（等价 off），由上层 CLI / 标定脚本
        # 用 `build_reranker(config)` 显式选档后注入。缺 key 时 `ApiReranker.__init__` 自己大声报错，
        # 本类不接手、不换档、不把「没重排」伪装成「重排生效」（4.1、4.3）。
        self.reranker = reranker

        self._docs: list[IndexedDoc] = []
        self._bm25: Any | None = None
        self._corpus_fingerprint: str = ""
        self._signature: Any | None = None
        self._built = False
        self.skipped_short_count = 0
        self.empty_search_text_count = 0
        self.build_report = BuildReport(block_mode=block_mode, min_search_text_chars=min_search_text_chars)

    # ── 对外属性 ────────────────────────────────────────────────────────────────────────
    @property
    def doc_count(self) -> int:
        return len(self._docs)

    @property
    def index_built(self) -> bool:
        return self._built

    def user_dict_terms(self) -> tuple[str, ...]:
        """当前装载进 jieba 用户词典的别名词形（依 8.16 的可断言入口）。"""
        return ensure_user_dict(self.aliases_path).user_dict_terms

    def rerank_note(self) -> str:
        """重排档的实际可用性（brief 第④项：未接入要打印「未接入」，不得留空冒充正常，依 4.3）。

        T4 起：注入了重排器就报它的档名；没注入仍是「未接入」+ 原因（T3 阶段既有断言依赖这条）。
        """
        if self.reranker is None:
            return LOCAL_LEXICAL_RERANK_NOTE
        return f"重排档={describe_reranker(self.reranker)}"

    def documents(self) -> list[dict[str, Any]]:
        """索引内的检索块（含定位反查所需字段），供自检与评测脚本核对「条目是否真进了索引」。"""
        self.ensure_ready()
        return [doc.as_record() for doc in self._docs]

    def vector_for_claim(self, claim_id: int) -> list[float] | None:
        """按 claim_id 取该条目的稠密向量（复现性核对与调试用）。"""
        for doc in self._docs:
            if claim_id in doc.claim_ids and doc.vector is not None:
                return doc.vector
        return None

    def corpus_fingerprint(self) -> str:
        """语料指纹（依 4.9 第一个指纹）：卡片与事实条目的内容哈希，掺进切块口径与词典内容。

        为什么词典也进指纹：换了别名表 = 换了分词结果 = 换了倒排内容，属于「老库自动升级」要处理的
        同一类事件（refimpl-notes 第 1 项 1-4 的 marker 思路）；不记它就会出现「改了 aliases.yml
        却继续用旧倒排」的静默失配（依 8.16）。
        """
        self.ensure_ready()
        return self._corpus_fingerprint

    # ── 建索引 ──────────────────────────────────────────────────────────────────────────
    def index(self, *, force: bool = True) -> BuildReport:
        """全量重建索引：读库 → 拼检索串 → 向量化 → 落盘 → 装配 BM25。

        语料变更即重建、不做增量修补（`build_index.py` docstring 的既有约定）：量级小到不值得
        维护增量一致性，而增量最容易造出「部分块没更新」这种查不出来的缺口（依 8.13 不静默放行）。
        """
        started = _monotonic_ms()
        rows, cards_by_id = self._read_corpus()
        fingerprint = self._compute_corpus_fingerprint(rows, cards_by_id)

        records = self._assemble_records(rows, cards_by_id)
        self.empty_search_text_count = sum(1 for r in records if r["empty"])
        if any(r["empty"] for r in records):
            offenders = [r["claim_id"] for r in records if r["empty"]]
            reasons = sorted({r["empty_reason"] for r in records if r["empty"]})
            raise ValueError(
                f"{len(offenders)} 条事实条目的检索串为空（缺段落：{'、'.join(reasons)}），"
                f"claim_id={offenders[:10]}"
                "（依 4.12：建索引时空检索串条目必须报错，不得跳过；空串的稠密分数是垃圾进垃圾出的"
                "「看起来正常」，会污染阈值标定）。请先修语料侧或调整拼装口径。"
            )
        kept = [r for r in records if len(r["text"]) >= self.min_search_text_chars]
        self.skipped_short_count = len(records) - len(kept)
        if self.skipped_short_count:
            logger.warning(
                "已拦下 %s 条长度 < %s 字符的检索串（task0-report 6.1 实测文本块 min=1 字符，"
                "放过会稀释 IDF 并白占稠密名额）",
                self.skipped_short_count,
                self.min_search_text_chars,
            )
        if not kept:
            raise ValueError(
                f"过滤后没有任何检索块（原始 {len(records)} 条、阈值 {self.min_search_text_chars} 字符）："
                "宁可乐观地失败，也不交出一个空索引（依 4.12、8.15）。请检查 min_search_text_chars 与语料。"
            )

        signature = self.embedder.vector_signature()
        docs = self._attach_vectors(kept, signature)
        self._docs = docs
        self._corpus_fingerprint = fingerprint
        self._signature = signature
        self._build_bm25(docs)
        self._write_meta(force=force)
        self._built = True

        stats = self.index_stats(query=self.probe_query)
        report = BuildReport(
            docs=len(docs),
            vectors=sum(1 for d in docs if d.vector is not None),
            postings=len(self._postings()),
            claims_in_db=len(records),
            empty_search_texts=self.empty_search_text_count,
            skipped_short=self.skipped_short_count,
            dense_hits=stats.dense_hits,
            sparse_hits=stats.sparse_hits,
            corpus_fingerprint=fingerprint,
            vector_signature=signature.as_dict(),
            backend_name=getattr(self.embedder, "cfg", None) and signature.backend or signature.backend,
            dense_available=signature.backend != "stub",
            elapsed_ms=_monotonic_ms() - started,
            block_mode=self.block_mode,
            min_search_text_chars=self.min_search_text_chars,
        )
        self.build_report = report
        return report

    # ── 契约方法 ────────────────────────────────────────────────────────────────────────
    def search(self, query: str, k: int, *, rerank: bool = True) -> list[Hit]:
        """混合召回（T3 形态）：稠密 top-N 与稀疏 top-N 并列取回，按「有相似度优先、再按各自分数」。

        为什么 T3 就要一条能跑的通路而不等 T4：步骤 3b 的双通道自检、T5 的分路评测都直接调 `search`，
        而 RRF 融合与稀疏名额 `k // 2` 是 T4 `search.py` 的活（依 4.7）。本实现保证三件事：
        ① `Hit.score` 只可能来自稠密相似度，永不写 BM25 分（依 4.8）；
        ② `rerank=True/False` 完全等价并留下 `rerank_note()` 痕迹（依 4.3、8.11，不留 `pass`）；
        ③ 顺序稳定（同分按 doc_id 升序），避免平局抖动让 T5 的 MRR 无法复现。
        """
        self.ensure_ready()
        _validate_k(k)
        text = self._require_query(query)
        dense = self._dense_rank(text, limit=self.cfg.retrieval_dense_top_k)
        sparse = self._sparse_rank(text, limit=self.cfg.retrieval_sparse_top_k)
        # 融合规则统一在 `search.fuse`（RRF + 稀疏名额 k//2 + 稳定序），本层只提供两路候选。
        fused = fuse(
            dense,
            sparse,
            k=k,
            rrf_constant=self.cfg.retrieval_rrf_constant,
        )
        if not rerank or self.reranker is None:
            return fused
        # 重排只写 `Hit.rerank_score` 并据此重排，`Hit.score` 一个字节都不动（4.6）；
        # 失败时 `apply_rerank` 内部已打印「重排未生效: 原因」并按融合顺序返回（4.3）。
        return apply_rerank(
            fused,
            text,
            self.reranker,
            text_of=self._text_for_claim,
            max_docs=self.cfg.rerank_max_docs,
        )

    def _text_for_claim(self, hit: Hit) -> str:
        """按候选回捞索引正文（重排需要原文，不能只给编号）。"""
        for doc in self._docs:
            if hit.claim_id in doc.claim_ids:
                return doc.text
        return ""

    def search_bm25_only(self, query: str, k: int, *, claim_ids: Iterable[int] | None = None) -> list[Hit]:
        """只开稀疏的自检通道（步骤 3b 逐字形态）：`dense_score` / `score` 恒为 `None`（依 4.7）。

        `claim_ids` 是可选的范围限定（refimpl-notes 第 1 项 1-5 的教训：范围过滤器若在 FTS 之前
        下推，选集越小越哑）。本项目 BM25 是内存倒排、不存在下推分支，但试点先行（裁决 R7）的
        真实形态就是小选集，所以过滤发生在**取回之后、截断之前**，语义上等价于「先筛后截」。
        """
        self.ensure_ready()
        _validate_k(k)
        text = self._require_query(query)
        hits = self._sparse_rank(text, limit=max(k, self.cfg.retrieval_sparse_top_k))
        if claim_ids is not None:
            allowed = set(claim_ids)
            hits = [h for h in hits if h.claim_id in allowed]
        return hits[:k]

    def search_dense_only(self, query: str, k: int) -> list[Hit]:
        """只开稠密的对照通道（依 5.20「双通道分别单独跑通，不得只测混合结果」）。"""
        self.ensure_ready()
        _validate_k(k)
        text = self._require_query(query)
        return self._dense_rank(text, limit=k)

    def index_stats(self, *, query: str | None = None) -> IndexStats:
        """两条通道各自的命中数（步骤 3b 配套要求；键名依 6.11 固定）。

        命中数的定义是「自检查询在该通道上的返回条数」，不是索引规模——`total_docs` 才是规模。
        分开报出来才能让 T5 判断「稠密是否在做无用功」（brief 硬事实 1：条目级检索串平均只有
        24.6 字符，语义信息量薄，预期稀疏一路明显强于稠密一路，这不是 bug，但不能糊在一起看）。
        """
        probe = self.probe_query if query is None else query
        if not self._built:
            return IndexStats(total_docs=0, index_built=False)
        tokens_ok = bool(tokenize(probe, aliases_path=self.aliases_path))
        dense_hits = len(self._dense_rank(probe, limit=self.cfg.retrieval_dense_top_k)) if tokens_ok else 0
        sparse_hits = (
            len(self._sparse_rank(probe, limit=self.cfg.retrieval_sparse_top_k)) if tokens_ok else 0
        )
        return IndexStats(
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            total_docs=len(self._docs),
            index_built=True,
        )

    def ensure_ready(self) -> None:
        """检索前置闸门：索引必须在内存里且两个指纹都与当前一致（依 8.15、4.9）。"""
        if self._built:
            return
        meta_path = self.index_dir / META_FILENAME
        if not meta_path.is_file():
            raise IndexNotBuiltError(
                f"检索索引尚未建立：找不到 {meta_path}。请先运行 "
                "`cd backend && python scripts/build_index.py --rebuild`"
                "（依 8.15：不得假设索引已存在，禁止空索引静默返回 0 条再落进拒答——那会把数据缺失"
                "伪装成「库里没有答案」）。"
            )
        meta = self._load_meta(meta_path)
        expected_corpus = self._compute_corpus_fingerprint(*self._read_corpus())
        if meta.get("corpus_fingerprint") != expected_corpus:
            raise IndexStaleError(
                f"语料指纹与索引不符（索引 {meta.get('corpus_fingerprint')} ≠ 当前 {expected_corpus}）："
                "库里有条目改动或增删，沿用旧索引会让问答引用已经不存在的记载（依 4.9）。"
                "请重建：`python scripts/build_index.py --rebuild`，重建后须重标阈值。"
            )
        current = self.embedder.vector_signature()
        recorded = meta.get("vector_signature") or {}
        if recorded.get("digest") != current.digest:
            raise IndexStaleError(
                f"向量配置签名与索引不符（索引 {recorded.get('digest')!r} ≠ 当前 {current.digest!r}）："
                "换模型 / 换维度 / 换供应商基址 / 改 text_type 任一侧都会搬到另一个相似度分布"
                "（007 第四节实测 mean 0.3945 → 0.4694），沿用旧索引与旧阈值会让拒答判定静默失真"
                "（依 4.9）。请重建：`python scripts/build_index.py --rebuild`，并按新配置重标阈值。"
            )
        self._corpus_fingerprint = expected_corpus
        self._signature = current
        self._load_documents(meta)
        self._built = True

    # ── 取数与装配 ──────────────────────────────────────────────────────────────────────
    def _read_corpus(self) -> tuple[list[sqlite3.Row], dict[int, sqlite3.Row]]:
        """读卡片与事实条目（取数来源：`db/models.py` 的 cards / claims 两表）。"""
        path = Path(self.db_path)
        if not path.is_file():
            raise ValueError(
                f"数据库不存在：{path}。请先跑入库（`python -m app.ingestion.cli --all --backend llm`）"
                "或用 --db 指定路径（依 4.2：IO 问题归一为 ValueError 并给出下一步动作）。"
            )
        try:
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                cards = {row["card_id"]: row for row in conn.execute("SELECT * FROM cards")}
                sql = """
                    SELECT c.claim_id, c.card_id, c.source_id, c.subject, c.predicate,
                           c.value, c.quote, c.locator
                    FROM claims c
                    WHERE c.card_id IN ({})
                    ORDER BY c.claim_id
                    """.format(",".join("?" * len(cards)) if cards else "NULL")
                rows = conn.execute(sql, tuple(cards)).fetchall()
        except sqlite3.Error as exc:
            raise ValueError(f"读取语料失败：{path}（{exc}）；请确认该库已由 app.db.migrate 迁移过") from exc
        return rows, cards

    def _assemble_records(self, rows, cards_by_id) -> list[dict[str, Any]]:
        """按 block_mode 把条目组装成检索块（依 2.19：纯装配，不落盘）。"""
        records: list[dict[str, Any]] = []
        if self.block_mode == "single":
            for row in rows:
                card = cards_by_id[row["card_id"]]
                locator = _parse_locator(row["locator"], row["claim_id"])
                pieces = {
                    "card_name": card["name"],
                    "predicate": row["predicate"],
                    "value": row["value"],
                    "quote": row["quote"],
                    "heading_path": locator.get("heading_path") or [],
                    "subject": row["subject"],
                }
                empty = not all(
                    str(v).strip() for v in (pieces["card_name"], pieces["predicate"], pieces["value"], pieces["quote"])
                )
                text = "" if empty else build_search_text(**pieces)
                records.append(
                    {
                        "claim_id": row["claim_id"],
                        "claim_ids": (row["claim_id"],),
                        "card_id": row["card_id"],
                        "source_id": row["source_id"],
                        "locator": locator,
                        "text": text,
                        "empty": empty,
                        "empty_reason": _missing_pieces(pieces) if empty else "",
                    }
                )
            return records

        grouped: OrderedDict[int, list] = OrderedDict()
        for row in rows:
            grouped.setdefault(row["card_id"], []).append(row)
        for card_id, group in grouped.items():
            card = cards_by_id[card_id]
            chunks = _merge_group(card, group, self.min_search_text_chars)
            for chunk in chunks:
                records.extend(chunk)
        return records

    def _attach_vectors(self, kept: list[dict[str, Any]], signature: Any) -> list[IndexedDoc]:
        """稠密侧批量向量化并落盘（依 R19：相似度一律 cosine，端点返回未归一化向量）。"""
        docs = [
            IndexedDoc(
                doc_id=i,
                text=r["text"],
                claim_ids=tuple(r["claim_ids"]),
                card_id=r["card_id"],
                source_id=r["source_id"],
                locator=r["locator"],
            )
            for i, r in enumerate(kept)
        ]
        result = self.embedder.embed_documents([d.text for d in docs])
        total_tokens = getattr(result, "total_tokens", 0)
        requests = getattr(result, "requests", 0)
        if not getattr(result, "dense_available", False):
            # stub 档：合法降级路径（依 brief 硬事实 5、全局约束 6），不报错、不伪造向量（依 8.10）。
            logger.info("向量档=%s：稠密通道不可用，检索退化 BM25-only（依 4.3 已在自检里照实打印）", signature.backend)
            self._persist(docs)
            self.build_report.total_tokens = total_tokens
            self.build_report.requests = requests
            return docs
        if len(result.vectors) != len(docs):
            raise EmbeddingResponseError(
                f"向量响应不完整：入库条数 {len(result.vectors)} != 检索块数 {len(docs)}，"
                "终止建索引（依 4.4-①：缺条目不得用默认值补齐，错位向量会让答案指到错误出处）"
            )
        for doc, vector in zip(docs, result.vectors):
            doc.vector = list(vector)
        self._persist(docs)
        self.build_report.total_tokens = total_tokens
        self.build_report.requests = requests
        return docs

    def _build_bm25(self, docs: list[IndexedDoc]) -> None:
        """装配内存倒排（rank_bm25 + jieba）。分词结果与索引同源，不存在「查询侧另一套词」。"""
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(d.text, aliases_path=self.aliases_path) for d in docs]
        self._bm25 = BM25Okapi(corpus)
        self._doc_tokens = corpus

    def _postings(self) -> dict[str, list[int]]:
        postings: dict[str, list[int]] = {}
        for i, tokens in enumerate(getattr(self, "_doc_tokens", [])):
            for tok in set(tokens):
                postings.setdefault(tok, []).append(i)
        return postings

    # ── 打分 ────────────────────────────────────────────────────────────────────────────
    def _dense_rank(self, query: str, *, limit: int) -> list[Hit]:
        available = [d for d in self._docs if d.vector is not None]
        if not available:
            return []
        result = self.embedder.embed_query(query)
        if not getattr(result, "dense_available", False) or not result.vectors:
            return []
        qvec = list(result.vectors[0])
        scored: list[tuple[float, IndexedDoc]] = []
        for doc in available:
            # 依 R19：该端点返回未归一化向量（实测模长 1.000192），必须除以模长，
            # 直接内积会让 score > 1 并被契约层的 _check_score 拦在建索引中途。
            scored.append((cosine(qvec, doc.vector or []), doc))
        scored.sort(key=lambda pair: (-pair[0], pair[1].doc_id))
        hits: list[Hit] = []
        for similarity, doc in scored[:limit]:
            clipped = max(0.0, min(1.0, similarity))
            hits.append(
                Hit(
                    claim_id=doc.claim_ids[0],
                    card_id=doc.card_id,
                    score=clipped,
                    dense_score=clipped,
                    sparse_score=None,
                    rerank_score=None,
                )
            )
            self._remember_order(hits[-1], doc.doc_id)
        return hits

    def _sparse_rank(self, query: str, *, limit: int) -> list[Hit]:
        tokens = tokenize(query, aliases_path=self.aliases_path)
        if not tokens or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokens)
        order = sorted(
            range(len(scores)), key=lambda i: (-float(scores[i]), self._docs[i].doc_id)
        )
        hits: list[Hit] = []
        for i in order[:limit]:
            score = float(scores[i])
            if score <= 0.0:
                # BM25 分为 0 表示该块与查询无任何词面交集：它不是「低相关」而是「没命中」，
                # 计入命中数会让步骤 3b 的「稀疏 n」变成永真读数（依 5.19 反对的永真式）。
                break
            doc = self._docs[i]
            hits.append(
                Hit(
                    claim_id=doc.claim_ids[0],
                    card_id=doc.card_id,
                    score=None,
                    dense_score=None,
                    sparse_score=score,
                    rerank_score=None,
                )
            )
            self._remember_order(hits[-1], doc.doc_id)
        return hits

    @staticmethod
    def _remember_order(hit: Hit, doc_id: int) -> None:
        """记下块的 doc_id 作为稳定排序键（同分不改名次，T5 的 MRR 才可复现）。"""
        hit.doc_order = doc_id  # type: ignore[attr-defined]

    # ── 落盘与读回 ──────────────────────────────────────────────────────────────────────
    def _persist(self, docs: list[IndexedDoc]) -> None:
        """写 documents.jsonl / vectors.jsonl（UTF-8、不转义中文、带尾换行，依既有落盘口径）。"""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        with (self.index_dir / DOCUMENTS_FILENAME).open("w", encoding="utf-8", newline="\n") as fh:
            for doc in docs:
                record = doc.as_record()
                record.pop("tokens", None)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        with (self.index_dir / VECTORS_FILENAME).open("w", encoding="utf-8", newline="\n") as fh:
            for doc in docs:
                fh.write(
                    json.dumps({"doc_id": doc.doc_id, "vector": doc.vector}, ensure_ascii=False) + "\n"
                )

    def _write_meta(self, *, force: bool) -> None:
        """写 meta.json：两个指纹 + 生效配置 + 自检计数（doctor 六项的落盘部分，见 refimpl-notes 第 6 项）。"""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        signature = self.embedder.vector_signature()
        meta = {
            "schema_version": 1,
            "block_mode": self.block_mode,
            "min_search_text_chars": self.min_search_text_chars,
            "corpus_fingerprint": self._corpus_fingerprint,
            "vector_signature": signature.as_dict(),
            "total_docs": len(self._docs),
            "vectors": sum(1 for d in self._docs if d.vector is not None),
            "postings": len(self._postings()),
            "empty_search_texts": self.empty_search_text_count,
            "skipped_short": self.skipped_short_count,
            "probe_query": self.probe_query,
            "aliases_path": str(self.aliases_path),
            "db_path": str(self.db_path),
        }
        (self.index_dir / META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _load_meta(self, meta_path: Path) -> dict[str, Any]:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise IndexStaleError(
                f"索引元数据不完整或损坏：{meta_path}（{type(exc).__name__}: {exc}）。"
                "请重建：`python scripts/build_index.py --rebuild`（依 8.15：不得静默当成空索引）"
            ) from exc
        if not isinstance(meta, dict) or "corpus_fingerprint" not in meta:
            raise IndexStaleError(
                f"索引元数据缺少指纹字段：{meta_path}。这通常是上一版格式留下的老库，"
                "请重建：`python scripts/build_index.py --rebuild`（依 4.9 无指纹即无法判过期，等同空索引）"
            )
        return meta

    def _load_documents(self, meta: dict[str, Any]) -> None:
        """读回检索块与向量；条数不一致即判过期（依 refimpl-notes 第 6 项 6-2「文件是否真进了索引」）。"""
        docs_path = self.index_dir / DOCUMENTS_FILENAME
        vectors_path = self.index_dir / VECTORS_FILENAME
        if not docs_path.is_file():
            raise IndexNotBuiltError(
                f"索引元数据存在但缺少 {docs_path.name}：索引不完整。"
                "请重建：`python scripts/build_index.py --rebuild`（依 8.15）"
            )
        docs: list[IndexedDoc] = []
        try:
            for line in docs_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                docs.append(
                    IndexedDoc(
                        doc_id=int(record["doc_id"]),
                        text=record["text"],
                        claim_ids=tuple(record["claim_ids"]),
                        card_id=int(record["card_id"]),
                        source_id=record["source_id"],
                        locator=record["locator"],
                    )
                )
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
            raise IndexStaleError(
                f"索引文档不完整或损坏：{docs_path}（{type(exc).__name__}: {exc}）。"
                "请重建：`python scripts/build_index.py --rebuild`（依 8.15，禁止静默少一块）"
            ) from exc
        vectors: dict[int, list[float] | None] = {}
        if vectors_path.is_file():
            try:
                for line in vectors_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    vectors[int(item["doc_id"])] = item["vector"]
            except (json.JSONDecodeError, KeyError, ValueError, OSError) as exc:
                raise IndexStaleError(
                    f"索引向量不完整或损坏：{vectors_path}（{type(exc).__name__}: {exc}）。"
                    "请重建：`python scripts/build_index.py --rebuild`"
                ) from exc
        declared = meta.get("total_docs")
        if declared is not None and declared != len(docs):
            raise IndexStaleError(
                f"索引条目数与元数据不符：元数据 {declared} ≠ 实际 {len(docs)}（有块没进索引）。"
                "请重建：`python scripts/build_index.py --rebuild`（依 4.12 宁可失败也不交半成品）"
            )
        missing_vector = [d.doc_id for d in docs if vectors.get(d.doc_id) is None]
        has_vectors = any(v is not None for v in vectors.values())
        declared_vectors = meta.get("vectors")
        # meta 声明了向量条数、向量文件却是空的（或全缺）＝索引被截断，不是「stub 档无向量」：
        # 后者 meta 里 vectors 恒为 0（`_write_meta` 按实际写入条数计）。区分这两者才能让
        # 「文件被截断」当场报过期，而不是静默降级成 BM25-only 继续报成功（依 8.15、8.13）。
        expects_vectors = bool(declared_vectors) if isinstance(declared_vectors, int) else has_vectors
        if missing_vector and (has_vectors or expects_vectors):
            raise IndexStaleError(
                f"索引不完整或损坏：{len(missing_vector)} 个检索块有条目却无向量"
                f"（doc_id={missing_vector[:10]}）："
                "稠密通道会对这些块永久零命中却仍报告成功（依 refimpl-notes 第 6 项 6-2 判 FAIL）。"
                "请重建：`python scripts/build_index.py --rebuild`"
            )
        for doc in docs:
            doc.vector = vectors.get(doc.doc_id)
        self._docs = docs
        self._build_bm25(docs)

    # ── 校验小件 ────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _require_query(query: str) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError(
                f"查询串为空或纯空白：{query!r}（依 4.4-④：空输入客户端先拒，服务端对此会给一个"
                "「看起来正常」的无语义向量，属静默污染）"
            )
        return query

    def _compute_corpus_fingerprint(self, rows, cards_by_id) -> str:
        """语料指纹：全表内容哈希（量级小，可全表哈希；brief 第 45 行）。

        掺进 `block_mode` 与词典内容：换切块档或改别名表都会改变倒排，属同一类「老库要升级」。
        不掺时间戳——否则同数据重复构建指纹必然不同，「改一条引文才判过期」那条用例就废了（依 5.9）。
        """
        hasher = hashlib.sha256()
        hasher.update(self.block_mode.encode("utf-8"))
        hasher.update(FIELD_SEPARATOR.encode("utf-8"))
        for card_id in sorted(cards_by_id):
            card = cards_by_id[card_id]
            hasher.update(f"c\x1f{card_id}\x1f{card['source_id']}\x1f{card['type']}\x1f{card['name']}\n".encode())
        for row in rows:
            hasher.update(
                f"k\x1f{row['claim_id']}\x1f{row['card_id']}\x1f{row['subject']}\x1f{row['predicate']}"
                f"\x1f{row['value']}\x1f{row['quote']}\x1f{row['locator']}\n".encode()
            )
        for term in self.user_dict_terms():
            hasher.update(f"a\x1f{term}\n".encode())
        return hasher.hexdigest()[:32]


# ── 模块级小件（纯函数，便于单测）───────────────────────────────────────────────────────
def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError(f"k 必须是正整数，收到 {k!r}（依 2.15 显式区间：k<=0 会让 top-k 变成静默空结果）")


def _monotonic_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def _parse_locator(raw: str, claim_id: int) -> dict[str, Any]:
    """claims.locator 是 JSON 文本；解析失败即报错点名条目，不静默给空定位（依 4.2、8.13）。"""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            f"claim_id={claim_id} 的 locator 不是合法 JSON：{raw!r}（{exc}）。"
            "无定位的条目不得进索引——阶段三的逐字引文校验会无从下手（依 4.12）。"
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _missing_pieces(pieces: dict[str, Any]) -> str:
    """点名「四段里缺哪几段」（中文标签，依 5.11：报错信息本身是被测对象）。

    只报计划定义的四段（card_name / predicate / value / quote）；subject 与 heading_path 是可选段，
    缺了不算空检索串，但也没有理由把它们说成"缺失"。
    """
    labels = {
        "card_name": "卡片名",
        "predicate": "谓词",
        "value": "取值",
        "quote": "原文引文",
    }
    return "、".join(text for key, text in labels.items() if not str(pieces.get(key) or "").strip())


def _merge_group(card, group, min_chars: int) -> list[list[dict[str, Any]]]:
    """merged 档：按卡片把条目拼成块，超过 `MERGED_BLOCK_TOKEN_LIMIT` 就按条目边界另起一块。

    为什么不截断字符串：半句话的引文会让「关键事实覆盖率」出现假阴性（步骤 6b-3），而按条目边界
    分段永远保持每条事实完整——块粒度是命中率的主因（步骤 3c），完整性不是可以牺牲的那一项。
    """
    chunks: list[list[dict[str, Any]]] = []
    current_claims: list = []
    current_texts: list[str] = []
    for row in group:
        locator = _parse_locator(row["locator"], row["claim_id"])
        pieces = {
            "card_name": card["name"],
            "predicate": row["predicate"],
            "value": row["value"],
            "quote": row["quote"],
            "heading_path": locator.get("heading_path") or [],
            "subject": row["subject"],
        }
        empty = not all(
            str(v).strip()
            for v in (pieces["card_name"], pieces["predicate"], pieces["value"], pieces["quote"])
        )
        record = {
            "claim_id": row["claim_id"],
            "card_id": row["card_id"],
            "source_id": row["source_id"],
            "locator": locator,
            "empty": empty,
            "empty_reason": _missing_pieces(pieces) if empty else "",
            "text": "" if empty else build_search_text(**pieces),
        }
        if empty:
            record["claim_ids"] = (row["claim_id"],)
            chunks.append([record])
            continue
        candidate = "\n".join(current_texts + [record["text"]])
        if current_claims and estimate_tokens(candidate) > MERGED_BLOCK_TOKEN_LIMIT:
            chunks.append(_finalize_block(current_claims, current_texts, card))
            current_claims, current_texts = [], []
        current_claims.append(record)
        current_texts.append(record["text"])
    if current_claims:
        chunks.append(_finalize_block(current_claims, current_texts, card))
    return chunks


def _finalize_block(records: list, texts: list[str], card) -> list[dict[str, Any]]:
    """把一组条目合成一个块：卡片名只出现一次，条目段依次排列。"""
    name = str(card["name"]).strip()
    body = [name] + [t.split(FIELD_SEPARATOR, 1)[1] if t.startswith(name) else t for t in texts]
    text = FIELD_SEPARATOR.join(body)
    first = records[0]
    return [
        {
            "claim_id": first["claim_id"],
            "claim_ids": tuple(r["claim_id"] for r in records),
            "card_id": first["card_id"],
            "source_id": first["source_id"],
            "locator": first["locator"],
            "text": text,
            "empty": False,
            "empty_reason": "",
        }
    ]
