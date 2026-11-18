"""索引构建与中文稀疏通道（阶段二 T3）的召回测试。

出处：plan 阶段二步骤 3 / **3b** / 3c（`.superpowers/sdd/plan/phase2-text.md:27-79`）、
`task3-brief.md`、编码规范基线 4.9 / 4.11 / 4.12 / 4.13 / 5.2 / 5.16 / 5.17 / 5.20 / 5.21 /
6.8 / 6.11 / 8.1 / 8.3 / 8.4 / 8.7 / 8.10 / 8.13 / 8.15 / 8.16，以及 lead 裁决 R18（复现线 0.998）、
R19（稠密一律 cosine）、评审 Important 2（`index_built=False` 必须显式报错）。

两类事故必须由本文件当场失败：
1. **稀疏通道空转**（步骤 3b 原话）：沿用按空格分词时中文整句被当成一个 token，关键词通道对任何
   中文问句恒返回 0 条，混合检索静默退化成只剩向量，而日志里那行 `Got 0 from docstore` 长期无人注意；
2. **配置换了、索引没换**（规范 4.9）：同一模型换 `text_type` 一侧会把相似度分布从 mean 0.3945 搬到
   0.4694（决策记录 007 第四节实测），沿用旧索引 + 旧阈值会让拒答判定悄悄失真。

全部用例**不联网、不调付费 API**（规范 5.17）：稠密侧一律注入 `FakeEmbedder` 替身，真实向量的
一次建索引只进 `task3-report.md`（规范 5.17 末段）。临时库与索引一律落 `tmp_path`（规范 5.4、5.21），
会话级三件套（`isolate_write_targets` / `isolate_dotenv` / `guard_project_directory`）未被绕过。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import sqlite3
from pathlib import Path

import pytest
from helpers import CONFIG_ENV_KEYS, write_yaml

from app.core.config import Config
from app.db.migrate import migrate
from app.retrieval.backend import Hit, IndexStats, SearchBackend
from app.retrieval.embedding import TEXT_TYPE_UNDECLARED, VectorSignature, estimate_tokens
from app.retrieval.local import (
    BLOCK_MODES,
    DEFAULT_MIN_SEARCH_TEXT_CHARS,
    LOCAL_LEXICAL_RERANK_NOTE,
    MERGED_BLOCK_TOKEN_LIMIT,
    REPRODUCIBILITY_COS_FLOOR,
    IndexNotBuiltError,
    IndexStaleError,
    LocalBackend,
    build_search_text,
    default_index_dir,
    tokenize,
)

# ── 测试素材 ────────────────────────────────────────────────────────────────────────────
# 语料形态照 task0-report.md 第 6.1–6.4 节：卡片名 + 谓词 + 取值 + 原文引文，引文平均 24.6 字符。
ALIAS_PERSON_NAME = "省立第一师范"
ALIAS_CANONICAL_NAME = "湖南第一师范学院"
ALIAS_CLAIM_IDS = {1}

# 三条卡片：第一条含「省立第一师范学校讲习所」——它同时是计划逐字查询（步骤 1、3b）与
# 别名专名查询的目标。「省立第一师范」只出现在 aliases.yml 里，不在 jieba 默认词典中，
# 所以它能命中就证明自定义词典真的进了分词器（规范 8.16）。
CARDS = [
    {
        "source_id": "S001",
        "type": "event",
        "name": "省立第一师范学校讲习所创设",
        "claims": [
            ("省立第一师范学校讲习所", "事件时间", "一九二五年创设",
             "省立第一师范学校讲习所于一九二五年创设，学员多为产业工人。"),
            ("毛泽东", "参与事件", "在省立第一师范学校求学",
             "毛泽东曾在省立第一师范学校求学六年半。"),
        ],
    },
    {
        "source_id": "S002",
        "type": "event",
        "name": "红军长征档案数据库建设启动",
        "claims": [
            ("湖南省郴州市档案局", "参与事件", "联合启动红军长征档案数据库建设",
             "湖南省郴州市档案局、市档案馆于今年1月联合启动红军长征档案数据库建设。"),
            ("该数据库", "事件结果", "全面建成并对外开放",
             "近日，该数据库全面建成，已正式对外开放。"),
        ],
    },
    {
        "source_id": "S003",
        "type": "place",
        "name": "长沙",
        "claims": [
            ("长沙现存最早的地方志", "事件地点", "长沙市",
             "长沙现存最早的地方志为明嘉靖《长沙府志》。"),
        ],
    },
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """宿主环境变量不得影响默认值断言（规范 5.5：键名从 Config.model_fields 派生，不手抄）。"""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def cfg(**over) -> Config:
    """api 档的最小可用配置（密钥一律假值，规范 8.6）。"""
    base = {
        "embedding_backend": "api",
        "embedding_base_url": "https://mock.example/v1",
        "embedding_api_key": "sk-test-not-a-real-key",
        "embedding_model": "qwen3.7-text-embedding-flash",
        "embedding_dim": 8,
    }
    base.update(over)
    return Config(**base)


class FakeEmbedder:
    """稠密侧替身（规范 5.17）：按检索串的 sha256 生成稳定向量，可计数，绝不联网。

    为什么不用随机向量：双指纹过期用例要断言「同数据重复构建产出一致」，随机向量会把这条变成
    永假式；而规范 5.10 禁止的是「拿真实服务端两次调用断言逐位相等」（实测 cos=0.999095），
    本地替身的确定性向量与那条纪律无关。
    """

    def __init__(self, config: Config | None = None, *, dim: int | None = None):
        self.cfg = config or cfg()
        self.dim = dim if dim is not None else self.cfg.embedding_dim
        self.calls = 0
        self.texts: list[list[str]] = []

    @staticmethod
    def _vector(text: str, dim: int) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        row = [digest[i % len(digest)] / 255.0 for i in range(dim)]
        norm = math.sqrt(sum(x * x for x in row)) or 1.0
        return [x / norm for x in row]

    def embed_documents(self, texts: list[str]):
        from app.retrieval.embedding import EmbeddingResult

        self.calls += 1
        self.texts.append(list(texts))
        return EmbeddingResult(
            vectors=[self._vector(t, self.dim) for t in texts],
            backend_name="fake",
            dense_available=True,
            total_tokens=sum(len(t) for t in texts),
            requests=1,
        )

    def embed_query(self, text: str):
        from app.retrieval.embedding import EmbeddingResult

        self.calls += 1
        return EmbeddingResult(
            vectors=[self._vector(text, self.dim)],
            backend_name="fake",
            dense_available=True,
            total_tokens=len(text),
            requests=1,
        )

    def vector_signature(self) -> VectorSignature:
        pair = (
            self.cfg.embedding_text_type_document or TEXT_TYPE_UNDECLARED,
            self.cfg.embedding_text_type_query or TEXT_TYPE_UNDECLARED,
        )
        base_hash = hashlib.sha256(self.cfg.embedding_base_url.encode("utf-8")).hexdigest()[:16]
        parts = ["api", self.cfg.embedding_model, str(self.dim), base_hash, *pair]
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
        return VectorSignature(
            backend="api",
            model=self.cfg.embedding_model,
            dim=self.dim,
            base_url_hash=base_hash,
            text_types=pair,
            digest=digest,
        )


class StubDenseEmbedder(FakeEmbedder):
    """稠密不可用档（stub 形态）：不产出向量，让「BM25 独扛」成为一条合法路径（brief 硬事实 5）。"""

    def embed_documents(self, texts: list[str]):
        from app.retrieval.embedding import EmbeddingResult

        self.calls += 1
        return EmbeddingResult(vectors=[], backend_name="stub", dense_available=False)

    def embed_query(self, text: str):
        from app.retrieval.embedding import EmbeddingResult

        self.calls += 1
        return EmbeddingResult(vectors=[], backend_name="stub", dense_available=False)

    def vector_signature(self) -> VectorSignature:
        return VectorSignature(
            backend="stub",
            model="none",
            dim=0,
            base_url_hash="",
            text_types=(TEXT_TYPE_UNDECLARED, TEXT_TYPE_UNDECLARED),
            digest=f"no-vector:{self.dim}",
        )


def make_db(tmp_path: Path, cards=None, **claim_overrides) -> Path:
    """在 tmp_path 造一个迁移好的 SQLite 库并按 CARDS 写入卡片与事实条目。

    幂等：同一 tmp_path 上重复调用会先删掉旧库。原因（实测踩过）：`build()` 内部也调 `make_db`,
    于是「测试先 make_db(tmp_path) 再 build(tmp_path, db_path=...)」会在同一条 `sources.source_id`
    上撞 UNIQUE 约束——那是测试助手的缺陷，不是被测实现的缺陷，所以在这里消掉而不是放宽任一断言。
    """
    db_path = tmp_path / "redtrace.db"
    migrate(db_path)
    # 幂等写法：显式清表而不是删库文件。Windows 上 `unlink()` 会撞「另一个程序正在使用此文件」
    # （迁移连接刚释放、句柄未必立刻回收），清表在语义上等价且不依赖句柄时机。
    with sqlite3.connect(db_path) as _clean:
        for table in ("claims", "cards", "sources"):
            _clean.execute(f"DELETE FROM {table}")
        # 关键：重置自增序列。否则第二次 make_db 拿到的是 claim_id=6、7……，语料指纹（含 claim_id）
        # 就会因「同一份数据、不同的主键」而变，让「同数据两次构建指纹相同」这条断言假红。
        _clean.execute("DELETE FROM sqlite_sequence")
        _clean.commit()
    payload = CARDS if cards is None else cards
    with sqlite3.connect(db_path) as conn:
        for card in payload:
            conn.execute(
                "INSERT INTO sources (source_id, title, publisher, publish_date, url_or_path,"
                " access_date, license_note, corpus_tier, media_type)"
                " VALUES (?, ?, '人民出版社', '1985', 'x', '2026-11-13', '公开', '核心', '文章')",
                (card["source_id"], card["name"]),
            )
            cur = conn.execute(
                "INSERT INTO cards (source_id, type, name, summary) VALUES (?, ?, ?, '演示摘要')",
                (card["source_id"], card["type"], card["name"]),
            )
            card_id = cur.lastrowid
            for subject, predicate, value, quote in card["claims"]:
                locator = {"page": None, "paragraph": 1, "heading_path": [card["name"]], "quote": quote}
                conn.execute(
                    "INSERT INTO claims (card_id, source_id, subject, predicate, value, quote,"
                    " locator, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, 0.95)",
                    (
                        card_id,
                        card["source_id"],
                        subject,
                        predicate,
                        claim_overrides.get("value", value),
                        claim_overrides.get("quote", quote),
                        json.dumps(locator, ensure_ascii=False),
                    ),
                )
        conn.commit()
    return db_path


# ── 双指纹：语料指纹 + 向量配置签名（步骤 3 第 2 项，规范 4.9）────────────────────────────
def read_meta(index_dir: Path) -> dict:
    return json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))


def make_aliases(tmp_path: Path) -> Path:
    """别名表：`省立第一师范` 作为旧称只在这里出现，不进 jieba 默认词典（规范 8.16 的判据）。"""
    return write_yaml(
        tmp_path,
        {
            "person": {},
            "place": {ALIAS_CANONICAL_NAME: [ALIAS_PERSON_NAME]},
        },
        name="aliases.yml",
    )


def build(tmp_path: Path, **over) -> LocalBackend:
    """标准装配：替身稠密 + tmp 索引目录 + tmp 别名表。"""
    db_path = over.pop("db_path", None) or make_db(tmp_path)
    aliases_path = over.pop("aliases_path", None) or make_aliases(tmp_path)
    config = over.pop("config", None) or cfg()
    embedder = over.pop("embedder", None) or FakeEmbedder(config)
    index_dir = over.pop("index_dir", None) or (tmp_path / "index")
    kwargs = {"block_mode": "single", "min_search_text_chars": DEFAULT_MIN_SEARCH_TEXT_CHARS}
    kwargs.update(over)
    backend = LocalBackend(
        config=config,
        embedder=embedder,
        db_path=db_path,
        index_dir=index_dir,
        aliases_path=aliases_path,
        **kwargs,
    )
    backend.index()
    return backend


@pytest.fixture(scope="function")
def index(tmp_path):
    """计划步骤 1 / 3b 的 `index` fixture：替身稠密 + BM25，均已建好。"""
    return build(tmp_path)


# ── 步骤 1：召回测试（计划逐字形态）─────────────────────────────────────────────────────
def test_search_hits_alias_query(index):
    """计划步骤 1 逐字形态：别名问句必须召回到目标条目。"""
    hits = index.search("省立第一师范学校讲习所 什么时候成立", k=5)
    assert any(h.claim_id in ALIAS_CLAIM_IDS for h in hits), (
        f"别名问句没召回目标条目（期望 claim_id ∈ {sorted(ALIAS_CLAIM_IDS)}，实际 "
        f"{[h.claim_id for h in hits]}）：融合或稀疏通道未生效，问答会拿着别的来源作答"
    )


# ── 步骤 3b：稀疏通道对中文真的返回非 0（本项目存在理由，计划逐字形态）──────────────────
def test_sparse_channel_hits_cjk_query(index):
    """关掉稠密、只留稀疏，仍须命中——证明 BM25/jieba 不是空转。"""
    hits = index.search_bm25_only("师范讲习所 何时成立", k=10)
    assert hits, "稀疏通道中文零命中：分词器或自定义词典未生效"
    assert index.search_bm25_only(ALIAS_PERSON_NAME, k=10), "专名精确匹配走不通，别名表没进词典"


def test_jieba_userdict_loaded_from_aliases_yaml(index):
    """别名表必须真的进到分词器（规范 8.16）：只在 aliases.yml 出现的写法要成为一个整词。

    不测会怎样：词典没接上时「省立第一师范」会被切成「省立 / 第一 / 师范」三个碎词，
    命中的是碰巧含这些碎词的块——阶段一辛苦做的别名归一与检索用的是两套词（步骤 3b 末段）。
    """
    assert ALIAS_PERSON_NAME in index.user_dict_terms(), (
        "别名表的词没有进入分词器用户词典：阶段一的别名归一与检索各用一套词，命中全靠运气"
    )
    tokens = tokenize(ALIAS_PERSON_NAME, aliases_path=index.aliases_path)
    assert ALIAS_PERSON_NAME in tokens, f"别名应作为一个整词切出，实际 {tokens}"
    assert set(tokens) != set(), "分词返回空列表：jieba 未初始化或被静默跳过"


def test_alias_query_hits_via_sparse_only(index):
    """别名作为 query 走稀疏一路必须命中到具体条目，而不只是「非空」。

    只断言非空的危害（规范 5.9 反对的伪测试）：任何一条含碎词的块都能让它绿，词典接错也测不出来。
    但**不要求第一位**：计划步骤 3b 的原文只要求 `search_bm25_only(ALIAS_PERSON_NAME, k=10)` 非空，
    而 BM25 的长度归一化会让「引文恰好含该别名」的短文档合理上浮（本项目实测二者相差约 0.006 分，
    见 task3-report 第六节）。检索排序是否够用由 T5 的三指标评测裁决，不在索引层靠重复标题改分布。
    """
    hits = index.search_bm25_only(ALIAS_PERSON_NAME, k=5)
    top_two = [h.claim_id for h in hits[:2]]
    assert hits and ALIAS_CLAIM_IDS & set(top_two), (
        f"别名专名没有进入前两名（实际前两名 claim_id={top_two}）：别名没有进词典，命中来自碎词巧合"
    )
    first = hits[0]
    assert first.sparse_score is not None and first.sparse_score > 0.0, (
        "稀疏-only 结果的 sparse_score 必须是有值的 BM25 分，否则自检无法判断这一路是否真跑过"
    )
    assert first.dense_score is None and first.score is None, (
        "search_bm25_only 产出的候选没有向量相似度，必须显式为 None（规范 4.7、8.14），"
        "拿 0.0 冒充低分会让闸门把「没算」读成「确实不相关」"
    )


def test_sparse_channel_hits_within_small_scope(index):
    """限定小选集（单张卡片的条目）仍须命中——参考实现 §5.19 的第二坑：范围过滤下推到 FTS 之前。

    本项目 BM25 是内存倒排、不存在下推分支，但试点先行（裁决 R7）的真实形态就是小选集，
    不测等于没测（refimpl-notes 第七节 N4 的纪律）。
    """
    hits = index.search_bm25_only("师范讲习所 何时成立", k=10, claim_ids=tuple(sorted(ALIAS_CLAIM_IDS)))
    assert hits and all(h.claim_id in ALIAS_CLAIM_IDS for h in hits), (
        "限定 claim_ids 后稀疏通道没有命中或越界返回：范围过滤写在了打分之后，小库口径不可信"
    )


# ── 规范 5.20：双通道各自单独跑通（不得只测混合结果）────────────────────────────────────
def test_dense_channel_alone_returns_hits(index):
    """只开稠密也要有产出，否则「稠密一路从未生效」会被混合结果掩盖（规范 5.20）。"""
    hits = index.search_dense_only("省立第一师范学校讲习所 何时创设", k=10)
    assert hits, "稠密通道单独跑零命中：向量没有落进索引或查询侧没走向量"
    hit = hits[0]
    assert hit.dense_score is not None and 0.0 <= hit.dense_score <= 1.0, (
        f"dense_score 必须是 [0,1] 的余弦相似度，实际 {hit.dense_score!r}"
        "（裁决 R19：该端点返回未归一化向量，用内积会得到 >1 的分并被契约拦在建索引中途）"
    )
    assert hit.sparse_score is None, "search_dense_only 不得夹带 BM25 分，否则双通道自检失去分辨力"


def test_stub_dense_is_a_legal_bm25_only_path(tmp_path):
    """无向量档（stub 形态）必须能跑通且稠密数为 0，而不是报错或冒充成功（brief 硬事实 5）。"""
    stub = StubDenseEmbedder(cfg())
    backend = build(tmp_path, embedder=stub)
    hits = backend.search_bm25_only("师范讲习所 何时成立", k=5)
    assert hits, "稠密不可用时稀疏通道必须独扛：返回空等于把降级路径写成故障路径"
    stats = backend.index_stats()
    assert stats.total_docs > 0 and stats.index_built is True
    probe = backend.search("省立第一师范学校讲习所 何时创设", k=5)
    assert probe and all(h.dense_score is None for h in probe), (
        "stub 档不得伪造 dense_score（规范 8.10：不许往桩件里塞东西凑达标数）"
    )
    assert stats.dense_hits == 0, "无向量档的稠密命中数必须照实打印 0，让自检看见缺口（规范 4.12）"


# ── 检索串拼装（步骤 3 第 1 项）─────────────────────────────────────────────────────────
def test_build_search_text_contains_all_four_parts():
    """四段缺一即红：卡片名 + 谓词 + 取值 + 原文引文（计划逐字）。"""
    text = build_search_text(
        card_name="省立第一师范学校讲习所创设",
        predicate="事件时间",
        value="一九二五年创设",
        quote="省立第一师范学校讲习所于一九二五年创设。",
    )
    for part in ("省立第一师范学校讲习所创设", "事件时间", "一九二五年创设", "创设"):
        assert part in text, f"检索串缺少段落 {part!r}：拼装漏段会让对应字段永远检索不到"
    assert text.count("｜") >= 3, "四段之间必须有固定分隔符，否则跨段拼接会产生假词"


def test_empty_search_text_raises_and_names_claim_and_missing_part(tmp_path):
    """空检索串条目在建索引时报错而不是跳过（规范 4.12），且点名 claim_id 与缺哪一段（规范 5.11）。"""
    broken_cards = [
        {
            "source_id": "S009",
            "type": "event",
            "name": "  ",
            "claims": [("主体", "事件时间", "", "")],
        }
    ]
    db_path = make_db(tmp_path, cards=broken_cards)
    backend = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=db_path,
        index_dir=tmp_path / "index",
        aliases_path=make_aliases(tmp_path),
    )
    with pytest.raises(ValueError, match="卡片名"):
        backend.index()
    try:
        backend.index()
    except ValueError as exc:
        message = str(exc)
        assert "claim_id" in message, f"报错必须点名是哪一条条目，实际：{message}"
        assert "取值" in message and "原文引文" in message, (
            f"报错要点名缺的是哪几段，否则运维只能逐条翻库：{message}"
        )
        assert "跳过" not in message or "不得跳过" in message, "报错措辞不得暗示这是可跳过的告警"


def test_pdf_page_locator_survives_into_the_document(tmp_path):
    """PDF 的 page 定位分支只能用既有 fixture 造的数据测（task0-report 6.4 第 5 条）。

    试点语料全是 HTML、`page` 恒为 None，所以这条**不是**「已用真实语料验证」的证据；
    它保证的是索引侧不吞 locator：page 有值时必须原样带进文档记录，供阶段三出处卡回指。
    """
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE claims SET locator = ? WHERE claim_id = 1",
            (json.dumps({"page": 3, "paragraph": None, "heading_path": [], "quote": "原文"}),),
        )
        conn.commit()
    backend = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=db_path,
        index_dir=tmp_path / "index",
        aliases_path=make_aliases(tmp_path),
    )
    backend.index()
    docs = backend.documents()
    target = next(d for d in docs if d["claim_id"] == 1)
    assert "｜｜" not in target["text"], (
        "标题路径为空时不得留下空段占位（会造出假词边界），依规范 4.12 不得静默当空串拼进检索串"
    )
    assert target["locator"]["page"] == 3, "heading_path 缺失不得连带丢掉 page 定位"


# ── 最小长度阈值（task0-report 6.4：文本块 min=1 字符会污染 IDF）─────────────────────────
def test_too_short_block_is_filtered_out(tmp_path):
    """过短检索串被阈值拦住：1～2 字的块几乎无意义，却会稀释 IDF 并白占稠密名额。

    数据要造到**拼装串本身**短于阈值：检索串含「卡片名（加权重复一次）+ 谓词 + 取值 + 引文」，
    只把引文写成 "1935" 并不会让它变短（串仍有 19 字符）。所以这里用单字四段 + 空主语。
    """
    short_cards = [
        {
            "source_id": "S010",
            "type": "time",
            "name": "年",
            "claims": [("", "历", "1", "1")],
        }
    ]
    long_cards = [
        {
            "source_id": "S011",
            "type": "event",
            "name": "红军长征档案数据库建设启动",
            "claims": [("湖南省郴州市档案局", "参与事件", "联合启动红军长征档案数据库建设",
                        "湖南省郴州市档案局于今年1月联合启动红军长征档案数据库建设。")],
        }
    ]
    db_path = make_db(tmp_path, cards=short_cards + long_cards)
    # 阈值取 12 而不是默认 10：短卡的拼装串是「年｜年｜历｜1｜1｜年」11 字符（卡片名按检索实践
    # 重复一次以加权标题），默认阈值放它过去是合理的——真正要防的是长串噪声，不是把 11 字符也算脏。
    # 这里抬高阈值来构造触发条件，同时验证「阈值真的被消费」。
    backend = build(tmp_path, db_path=db_path, min_search_text_chars=12)
    claim_ids = {d["claim_id"] for d in backend.documents()}
    assert backend.skipped_short_count == 1, (
        "短块没有被统计：被拦下的条目数量必须照实报出，否则「索引缺了一块」无人知晓（规范 4.12）"
    )
    assert 1 not in claim_ids, "过短块仍进了索引：IDF 被噪声词污染，稀疏命中质量下降"
    assert claim_ids, "正常块也被误杀：阈值不能把有信息量的条目一并拦掉"


def test_min_length_threshold_is_configurable_and_boundary_inclusive(tmp_path):
    """阈值边界两侧各测一次（规范 5.7、2.15）：恰好等于阈值的块不得被误杀。"""
    db_path = make_db(tmp_path)
    lengths = [
        len(
            build_search_text(
                card_name=card["name"],
                predicate=claim[1],
                value=claim[2],
                quote=claim[3],
                subject=claim[0],
                heading_path=[card["name"]],
            )
        )
        for card in CARDS
        for claim in card["claims"]
    ]
    floor = min(lengths)
    backend = build(tmp_path, db_path=db_path, min_search_text_chars=floor)
    assert backend.skipped_short_count == 0, "等于阈值的块应当放行（判据是 < 而不是 <=）"
    tighter = build(tmp_path, db_path=db_path, min_search_text_chars=floor + 1)
    assert tighter.skipped_short_count == 1, (
        "把阈值抬到最短块之上后，恰好只有最短的那一条应被拦住（各条目串长不等，不是全体）；"
        "一条都没拦住说明阈值根本没被消费"
    )


def db_rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT claim_id FROM claims").fetchall()


# ── 双指纹：语料指纹 + 向量配置签名（步骤 3 第 2 项，规范 4.9）────────────────────────────
# `read_meta` 在上文（「最小长度阈值」节前）已定义一次，这里复用，不再重复定义（规范 3.6：不留第二份）。


def test_corpus_fingerprint_changes_with_quote_and_repeats_stably(tmp_path):
    """改一条引文 → 语料指纹变；同数据重复构建 → 指纹相同（brief 表格要求）。"""
    a = build(tmp_path, index_dir=tmp_path / "i-a")
    b = build(tmp_path, index_dir=tmp_path / "i-b")
    assert a.corpus_fingerprint() == b.corpus_fingerprint(), (
        "同数据两次构建指纹不同：语料指纹掺进了时间戳之类的易变量，过期判定会变成永真"
    )

    mutated = tmp_path / "mutated.db"
    shutil_copy(make_db(tmp_path), mutated)
    with sqlite3.connect(mutated) as conn:
        conn.execute("UPDATE claims SET quote = ? WHERE claim_id = 1", ("引文被改动过的一句话内容",))
        conn.commit()
    c = build(tmp_path, db_path=mutated, index_dir=tmp_path / "i-c")
    assert c.corpus_fingerprint() != a.corpus_fingerprint(), (
        "改了引文而语料指纹不变：问答会引用旧索引的答案却报告成功（规范 4.9）"
    )


def shutil_copy(src: Path, dst: Path) -> Path:
    import shutil

    shutil.copyfile(src, dst)
    return dst


@pytest.mark.parametrize(
    "field,value",
    [
        ("embedding_model", "another-embedding-model"),
        ("embedding_dim", 16),
        ("embedding_base_url", "https://other-provider.example/v1"),
        ("embedding_text_type_query", "document"),
    ],
    ids=["换模型", "换维度", "换基址", "只改 document→query 一侧"],
)
def test_vector_signature_change_makes_index_stale(tmp_path, field, value):
    """四种变更各一条过期用例（brief 表格）：漏掉任一条就等于放过「同一模型换向量空间」的事故。

    依据：决策记录 007 第四节实测 `document-document` 与 `document-query` 两种组合把相似度 mean
    从 0.3945 搬到 0.4694（min 0.2524 → 0.3328），同一数值阈值在这两种组合下含义不同。
    """
    over = {field: value}
    built = build(tmp_path, index_dir=tmp_path / "i-old")
    other_cfg = cfg(**over)
    reopened = LocalBackend(
        config=other_cfg,
        embedder=FakeEmbedder(other_cfg),
        db_path=built.db_path,
        index_dir=built.index_dir,
        aliases_path=built.aliases_path,
    )
    with pytest.raises(IndexStaleError, match="向量配置签名"):
        reopened.ensure_ready()
    try:
        reopened.ensure_ready()
    except IndexStaleError as exc:
        message = str(exc)
        assert "build_index.py" in message and "--rebuild" in message, (
            f"过期报错必须给出重建命令，否则现场只会看到一句失败：{message}"
        )
        assert "重标阈值" in message, (
            f"必须提示重标阈值（规范 4.9：换向量配置等于换相似度分布，沿用旧 tau 会静默误拒）：{message}"
        )


def test_undeclared_text_type_is_recorded_not_omitted(tmp_path):
    """置空 text_type 须在签名里落「未声明」而不是省略（规范 4.9 末段、config.py:75-77）。"""
    declared = build(tmp_path, index_dir=tmp_path / "i-decl")
    meta = read_meta(declared.index_dir)
    assert meta["vector_signature"]["text_type_document"] == "document"
    assert meta["vector_signature"]["text_type_query"] == "query"

    blank_cfg = cfg(embedding_text_type_query="")
    reopened = LocalBackend(
        config=blank_cfg,
        embedder=FakeEmbedder(blank_cfg),
        db_path=declared.db_path,
        index_dir=declared.index_dir,
        aliases_path=declared.aliases_path,
    )
    with pytest.raises(IndexStaleError, match="向量配置签名"):
        reopened.ensure_ready()
    blank_meta = read_meta(build(tmp_path, config=blank_cfg, index_dir=tmp_path / "i-blank").index_dir)
    assert blank_meta["vector_signature"]["text_type_query"] == TEXT_TYPE_UNDECLARED, (
        "留空的一侧必须显式记「未声明」：省略键会让「没声明」与「忘了写」在索引文件里长得一样"
    )


def test_corpus_fingerprint_change_makes_index_stale(tmp_path):
    """入库新数据后沿用旧索引必须判过期——否则问答引用的是不含新条目的旧索引（规范 4.9）。"""
    built = build(tmp_path)
    grown = tmp_path / "grown.db"
    shutil_copy(built.db_path, grown)
    with sqlite3.connect(grown) as conn:
        card_id = conn.execute("SELECT card_id FROM cards LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO claims (card_id, source_id, subject, predicate, value, quote, locator,"
            " confidence) VALUES (?, 'S001', '新增主体', '事件地点', '新增取值内容',"
            " '这是一条新增的事实条目引文内容', '{}', 0.9)",
            (card_id,),
        )
        conn.commit()
    reopened = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=grown,
        index_dir=built.index_dir,
        aliases_path=built.aliases_path,
    )
    with pytest.raises(IndexStaleError, match="语料指纹"):
        reopened.ensure_ready()


def test_repeated_build_keeps_vectors_reproducible_by_cos(tmp_path):
    """索引可复现只能按 cos 判（规范 4.10、裁决 R18：判定线 0.998 而非 0.999）。

    这里比的是**替身**向量的逐次一致性，用来钉住「cos 判据 + 阈值常量」这套机制本身；
    真实服务端的非确定性由报告里的一次复跑读数承担，不在 pytest 里联网（规范 5.17）。
    """
    a = build(tmp_path, index_dir=tmp_path / "i-r1")
    b = build(tmp_path, index_dir=tmp_path / "i-r2")
    va = a.vector_for_claim(1)
    vb = b.vector_for_claim(1)
    assert va and vb, "替身向量没有落盘，复现性检查无从谈起"
    cos = sum(x * y for x, y in zip(va, vb))
    assert cos >= REPRODUCIBILITY_COS_FLOOR, (
        f"两次构建的同一条目 cos={cos:.6f} < {REPRODUCIBILITY_COS_FLOOR}：向量落盘或取数顺序不稳定"
    )
    assert REPRODUCIBILITY_COS_FLOOR == 0.998, (
        "复现线由裁决 R18 定为 0.998（007 六-1 的 0.999 出自更早一轮 0.999095，同部署存在波动）；"
        "改回 0.999 会让真实复跑校验随机假红"
    )


# ── 缺索引 / 过期索引必须大声失败（规范 8.15、评审 Important 2）──────────────────────────
def test_unbuilt_backend_raises_and_names_rebuild_command(tmp_path):
    """`index_built=False` 时任何检索入口都必须显式报错并提示重建命令。

    不钉住会怎样：`IndexStats.total_docs` / `index_built` 退化成装饰字段，空索引静默返回 0 条，
    上层把它读成「库里没有答案」而落进拒答——那是数据缺失伪装成正确行为（规范 8.15）。
    """
    fresh = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=make_db(tmp_path),
        index_dir=tmp_path / "never-built",
        aliases_path=make_aliases(tmp_path),
    )
    assert fresh.index_stats().index_built is False
    for call in (
        lambda: fresh.search("师范讲习所 何时成立", 5),
        lambda: fresh.search_bm25_only("师范讲习所", 5),
        lambda: fresh.search_dense_only("师范讲习所", 5),
    ):
        with pytest.raises(IndexNotBuiltError, match="尚未建立"):
            call()
    with pytest.raises(IndexNotBuiltError, match="--rebuild"):
        fresh.search_bm25_only("师范讲习所", 5)
    with pytest.raises(IndexNotBuiltError, match="build_index.py"):
        fresh.search("师范讲习所", 5)


def test_corrupt_index_files_are_reported_as_stale_not_empty(tmp_path):
    """索引文件被截断/损坏时判过期重建，而不是静默当成空索引（规范 8.15、8.13）。"""
    built = build(tmp_path)
    (built.index_dir / "vectors.jsonl").write_text("", encoding="utf-8")
    reopened = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=built.db_path,
        index_dir=built.index_dir,
        aliases_path=built.aliases_path,
    )
    with pytest.raises(IndexStaleError, match="不完整|损坏"):
        reopened.ensure_ready()


def test_missing_database_is_an_explicit_error(tmp_path):
    """库不存在时报错点名路径与下一步（规范 4.2），不得抛裸 OSError 或产出空索引。"""
    backend = LocalBackend(
        config=cfg(),
        embedder=FakeEmbedder(cfg()),
        db_path=tmp_path / "nope.db",
        index_dir=tmp_path / "index",
        aliases_path=make_aliases(tmp_path),
    )
    with pytest.raises(ValueError, match="数据库"):
        backend.index()


def test_default_index_dir_follows_data_dir(tmp_path, monkeypatch):
    """默认落点走 `Config.data_dir`，不得硬编码相对 cwd（规范 8.7、本文件既有约定）。

    两侧都覆盖（lead 2026-11-17 通知：task-8 已把入库 CLI 的 `_default_data_dir()` 改为回落
    `get_config().data_dir`，即 `DATA_DIR` 真实生效）：设了要跟着走、没设要落到 BACKEND_ROOT/data，
    否则建索引与入库读写两个不同目录，T5 的数字复现不出来。
    """
    moved = tmp_path / "moved-data"
    monkeypatch.setenv("DATA_DIR", str(moved))
    path = default_index_dir(Config())
    assert path == moved / "index", f"索引目录没有跟着 DATA_DIR 走：{path}"

    monkeypatch.delenv("DATA_DIR", raising=False)
    from app.core.config import BACKEND_ROOT

    fallback = default_index_dir(Config())
    assert fallback == BACKEND_ROOT / "data" / "index", (
        f"未设 DATA_DIR 时的默认落点漂移了：{fallback}（应与入库 CLI 同口径锚在 BACKEND_ROOT/data）"
    )


def test_build_index_cli_defaults_to_config_data_dir(tmp_path, capsys, monkeypatch):
    """CLI 不给 `--out` / `--db` 时也必须走 `Config.data_dir`（与 task-8 的入库口径同一把尺）。"""
    data_dir = tmp_path / "cli-data"
    make_db_at(data_dir / "redtrace.db")
    aliases = make_aliases_at(data_dir / "aliases.yml")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    code = run_cli(
        tmp_path, ["--embedding-backend", "stub", "--aliases", str(aliases), "--rebuild"], monkeypatch
    )
    out = capsys.readouterr().out
    assert code == 0, f"默认目录口径下建索引失败：\n{out}"
    assert (data_dir / "index" / "meta.json").is_file(), (
        f"索引没有落在 $DATA_DIR/index：{sorted(p.name for p in data_dir.iterdir())}"
    )


def make_aliases_at(path: Path) -> Path:
    """在指定路径写别名表（默认目录用例要把它放进 `$DATA_DIR`）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(
        path.parent,
        {"person": {}, "place": {ALIAS_CANONICAL_NAME: [ALIAS_PERSON_NAME]}},
        name=path.name,
    )
    return path


def make_db_at(db_path: Path) -> Path:
    """把标准语料写到指定路径（CLI 默认目录用例要在 `$DATA_DIR/redtrace.db` 造库）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(db_path)
    with sqlite3.connect(db_path) as conn:
        for card in CARDS:
            conn.execute(
                "INSERT INTO sources (source_id, title, publisher, publish_date, url_or_path,"
                " access_date, license_note, corpus_tier, media_type)"
                " VALUES (?, ?, '人民出版社', '1985', 'x', '2026-11-13', '公开', '核心', '文章')",
                (card["source_id"], card["name"]),
            )
            cur = conn.execute(
                "INSERT INTO cards (source_id, type, name, summary) VALUES (?, ?, ?, '演示摘要')",
                (card["source_id"], card["type"], card["name"]),
            )
            for subject, predicate, value, quote in card["claims"]:
                locator = {"page": None, "paragraph": 1, "heading_path": [card["name"]], "quote": quote}
                conn.execute(
                    "INSERT INTO claims (card_id, source_id, subject, predicate, value, quote,"
                    " locator, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, 0.95)",
                    (
                        cur.lastrowid,
                        card["source_id"],
                        subject,
                        predicate,
                        value,
                        quote,
                        json.dumps(locator, ensure_ascii=False),
                    ),
                )
        conn.commit()
    return db_path


# ── block_mode 两档钩子（步骤 3c，数字归 T5）────────────────────────────────────────────
def test_block_mode_single_and_merged_both_indexable(tmp_path):
    """两档都要能建索引、都能被 T5 的评测跑（brief 第 5 项）。"""
    single = build(tmp_path, block_mode="single", index_dir=tmp_path / "i-single")
    merged = build(tmp_path, block_mode="merged", index_dir=tmp_path / "i-merged")
    assert single.doc_count == len(CARDS[0]["claims"]) + len(CARDS[1]["claims"]) + len(CARDS[2]["claims"])
    assert merged.doc_count == len(CARDS), "合并档应按卡片成块：一块对应一张卡片的全部条目"
    assert single.search_bm25_only("师范讲习所 何时成立", k=5)
    assert merged.search_bm25_only("师范讲习所 何时成立", k=5)
    assert set(BLOCK_MODES) == {"single", "merged"}


def test_unknown_block_mode_is_rejected(tmp_path):
    """档位拼错要当场报错，不能被静默当成 single（规范 4.13：代码里不得有隐式换档）。"""
    with pytest.raises(ValueError, match="block_mode"):
        build(tmp_path, block_mode="by_page")


def test_merged_block_respects_512_token_cap(tmp_path):
    """合并档以 512 token 为实验上限（步骤 3c 末段：128K 单行上限不构成豁免）。"""
    big_card = {
        "source_id": "S020",
        "type": "event",
        "name": "超长卡片合并测试",
        # 每条约 200 个汉字，四条合计超过 512 token 的实验上限
        "claims": [
            (f"主体{i}", "参与事件", f"取值内容{i}" + "长" * 180, "引文正文" + "文" * 190)
            for i in range(4)
        ],
    }
    db_path = make_db(tmp_path, cards=[big_card])
    merged = build(tmp_path, db_path=db_path, block_mode="merged", index_dir=tmp_path / "i-cap")
    docs = merged.documents()
    assert docs, "合并档没有产出任何块"
    oversized = [d for d in docs if estimate_tokens(d["text"]) > MERGED_BLOCK_TOKEN_LIMIT]
    assert not oversized, (
        f"{len(oversized)} 个合并块超出 {MERGED_BLOCK_TOKEN_LIMIT} token 的实验上限："
        "块粒度才是命中率的主因，模型能吃下整篇不等于该把整篇喂进去（步骤 3c）"
    )
    assert len(docs) >= 2, "超限的卡片没有分段，说明上限只做了一次性丢弃而不是按条边界拆分"


def test_merged_mode_carries_every_claim_exactly_once(tmp_path):
    """合并档不得丢条目或重复计入：每个 claim_id 必须恰好出现在一个块的反查清单里。"""
    merged = build(tmp_path, block_mode="merged", index_dir=tmp_path / "i-cover")
    seen = [cid for d in merged.documents() for cid in d["claim_ids"]]
    expected = sorted(row[0] for row in db_rows(merged.db_path))
    assert sorted(seen) == expected, (
        f"合并档覆盖的条目与实际入库不一致（{sorted(seen)} != {expected}）："
        "有块没进索引，正是 build_index 自检要抓的那件事"
    )


# ── search() 的重排接缝（T3 阶段：无重排器）──────────────────────────────────────────────
def test_search_without_reranker_marks_trace_and_keeps_order(index):
    """`rerank=True` 在无重排器时必须等价于不重排，并留下可断言的痕迹（禁止清单 8.11）。"""
    with_rerank = index.search("师范讲习所 何时成立", k=5)
    without = index.search("师范讲习所 何时成立", k=5, rerank=False)
    assert [h.claim_id for h in with_rerank] == [h.claim_id for h in without], (
        "T3 阶段没有接入重排器，rerank=True 却改变了顺序 = 拿融合顺序冒充重排结果"
    )
    assert all(h.rerank_score is None for h in with_rerank), (
        "未打分的候选 rerank_score 必须是 None 而不是 0.0（规范 4.3、8.14）"
    )
    assert index.rerank_note() == LOCAL_LEXICAL_RERANK_NOTE, (
        "自检痕迹必须写明重排档未接入及其原因，供 build_index.py 照实打印（规范 4.3）"
    )


def test_rerank_does_not_move_gate_scores(index):
    """开关重排前后，参与闸门判定的那把尺子必须逐题相同（步骤 4b 原文测试，提前给 T4 兜底）。"""
    query = "省立第一师范学校讲习所 何时创设"
    before = max(h.score for h in index.search(query, 5, rerank=False))
    after = max(h.score for h in index.search(query, 5, rerank=True))
    assert before == after, "重排改写了综合分，步骤 6 的阈值标定作废（规范 4.6）"


def test_search_score_is_the_same_ruler_as_dense(index):
    """`Hit.score` 与 `dense_score` 同源可比，稀疏-only 候选则两者皆 None（规范 4.6、4.7）。"""
    hits = index.search("省立第一师范学校讲习所 何时创设", k=5)
    assert hits
    for hit in hits:
        if hit.dense_score is None:
            assert hit.score is None, "没有相似度的候选不得有一个看起来像相似度的综合分"
        else:
            assert 0.0 <= hit.score <= 1.0, f"综合分越出 [0,1]：{hit.score}"


# ── index_stats 契约（规范 6.8、6.11）──────────────────────────────────────────────────
def test_index_stats_reports_both_channels(index):
    """两条通道各自的命中数必须分开报出来，让 T5 能判断稠密是否在做无用功（brief 硬事实 1）。"""
    probe = "省立第一师范学校讲习所 何时创设"
    stats = index.index_stats(query=probe)
    assert isinstance(stats, IndexStats)
    names = {f.name for f in dataclasses.fields(IndexStats)}
    assert names == {"dense_hits", "sparse_hits", "total_docs", "index_built"}, (
        "键名是契约的一部分（规范 6.11），改名会让 build_index.py 与评测脚本静默拿到 KeyError"
    )
    assert stats.total_docs == index.doc_count and stats.total_docs > 0
    assert stats.index_built is True
    assert stats.dense_hits > 0 and stats.sparse_hits > 0, (
        f"自检查询下稠密 {stats.dense_hits} / 稀疏 {stats.sparse_hits}：任一侧为 0 即该通道未生效"
    )
    assert stats.dense_hits == len(index.search_dense_only(probe, k=stats.dense_hits))
    assert stats.sparse_hits == len(index.search_bm25_only(probe, k=stats.sparse_hits))


def test_index_stats_default_query_is_a_real_chinese_probe(index):
    """不带参数也要能自检：默认探针必须是真实中文问句，否则空转检测形同虚设（规范 5.19）。"""
    stats = index.index_stats()
    assert stats.sparse_hits > 0, "默认自检查询在稀疏通道零命中：那条自检本身就是永假式"
    assert stats.dense_hits > 0, (
        "默认探针必须与语料同源、能同时点亮两路，否则「通道未生效」的自检要靠调用方记得传对 query"
    )


def test_local_backend_implements_the_contract(index):
    """实现类必须满足 T1 的抽象接口（规范 6.8：唯一对外契约是 search(...) -> list[Hit]）。"""
    assert isinstance(index, SearchBackend)
    hits = index.search("师范讲习所 何时成立", k=3)
    assert all(isinstance(h, Hit) for h in hits)
    assert len(hits) <= 3


def test_bm25_scores_are_not_written_into_score_column(index):
    """量纲隔离（规范 4.8）：BM25 分只能待在 sparse_score 列，混进 score 会毒化阈值标定。"""
    probe = "省立第一师范学校讲习所 何时创设"
    hits = index.search(probe, k=index.doc_count)
    top_sparse = max(
        (h.sparse_score for h in hits if h.sparse_score is not None), default=None
    )
    assert top_sparse is not None and top_sparse > 1.0, (
        f"本用例依赖 BM25 分可以大于 1 这一事实来区分量纲，实际最高 {top_sparse!r}；"
        "若哪天它被归一到 [0,1]，这条防线就失效了，须同步改写"
    )
    sparse_only = index.search_bm25_only("师范讲习所 何时成立", k=5)
    assert all(h.score is None for h in sparse_only), "稀疏通道的产物把 BM25 分写进了综合分列"


# ── build_index.py CLI（步骤 3b 配套要求 + doctor 六项自检）──────────────────────────────
def run_cli(tmp_path, argv, monkeypatch):
    from scripts.build_index import main

    return main(argv)


def test_build_index_cli_prints_both_channels(tmp_path, capsys, monkeypatch):
    """CLI 必须打印两条通道各自的命中数与两个指纹（步骤 3b 配套要求、refimpl-notes 第 6 项）。"""
    db_path = make_db(tmp_path)
    index_dir = tmp_path / "index"
    code = run_cli(
        tmp_path,
        [
            "--db", str(db_path),
            "--out", str(index_dir),
            "--aliases", str(make_aliases(tmp_path)),
            "--embedding-backend", "stub",
            "--rebuild",
        ],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert code == 0, f"stub 档离线建索引应成功退出，实际退出码 {code}：\n{out}"
    assert "稠密 0" in out and "稀疏 " in out, f"必须分别打印两条通道命中数：\n{out}"
    assert "语料指纹" in out and "向量配置签名" in out, f"两个指纹都要打印出来：\n{out}"
    assert "重排档=未接入" in out, f"重排未接入要照实打印而不是留空：\n{out}"
    assert "不得用于达标判定" in out, "stub 档首行必须自报口径（规范 4.3）"
    assert "生效配置" in out or "embedding" in out.lower(), "要打印实际生效的 embedding 配置"
    assert "耗时" in out
    assert (index_dir / "meta.json").is_file()


def test_build_index_cli_exits_nonzero_when_a_channel_is_dead(tmp_path, capsys, monkeypatch):
    """任一通道长期为 0 判未生效 → 非零退出（规范 4.12、8.15）。声明可用却拿不到向量就是故障。"""

    class SilentEmptyEmbedder(FakeEmbedder):
        """冒充「HTTP 200 + 空 embedding」的残缺响应：`dense_available=True` 但 vectors 为空。

        T2 的真实 `ApiEmbedder` 会在 `_parse_response` 就抛 `EmbeddingResponseError`；本替身跳过
        那一层，专门测索引侧是否还会继续把「稠密 0 命中」报成成功——那是步骤 3b 的同族事故。
        """

        def embed_documents(self, texts):
            from app.retrieval.embedding import EmbeddingResult

            self.calls += 1
            return EmbeddingResult(vectors=[], backend_name="api", dense_available=True)

    db_path = make_db(tmp_path)
    monkeypatch.setattr("app.retrieval.local.build_embedder", lambda config: SilentEmptyEmbedder(config))
    code = run_cli(
        tmp_path,
        [
            "--db", str(db_path),
            "--out", str(tmp_path / "i-dead"),
            "--aliases", str(make_aliases(tmp_path)),
            "--embedding-backend", "api",
            "--rebuild",
        ],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert code != 0, f"稠密通道零命中却报告成功：这正是步骤 3b 要挡住的事故\n{out}"
    assert "未生效" in out, f"非零退出必须说清是哪一路未生效：\n{out}"


def test_build_index_cli_reports_empty_search_text_count(tmp_path, capsys, monkeypatch):
    """空检索串条目计数要打印（doctor 第⑤项）；真实试点语料当前为 0，不得伪造「拦下了 N 条」。"""
    code = run_cli(
        tmp_path,
        [
            "--db", str(make_db(tmp_path)),
            "--out", str(tmp_path / "i-empty"),
            "--aliases", str(make_aliases(tmp_path)),
            "--embedding-backend", "stub",
            "--rebuild",
        ],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "空检索串条目" in out and "0 条" in out.split("空检索串条目")[1][:20]


def test_build_index_cli_checks_threshold_file_conditions(tmp_path, capsys, monkeypatch):
    """阈值文件尚无则注明「待 T5 标定」；已有则比对两个指纹（brief 第⑥项、规范 6.12）。"""
    run_cli(
        tmp_path,
        [
            "--db", str(make_db(tmp_path)),
            "--out", str(tmp_path / "i-thr"),
            "--aliases", str(make_aliases(tmp_path)),
            "--embedding-backend", "stub",
            "--rebuild",
        ],
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert "待 T5 标定" in out, f"阈值文件缺失要显式说明，不得留空冒充正常：\n{out}"


def test_build_index_cli_reuses_index_without_rebuild(tmp_path, capsys, monkeypatch):
    """不带 --rebuild 时复用现有索引并核对指纹（学 refimpl 的 ensure-rebuild 形态，落 SQLite）。"""
    argv = [
        "--db", str(make_db(tmp_path)),
        "--out", str(tmp_path / "i-reuse"),
        "--aliases", str(make_aliases(tmp_path)),
        "--embedding-backend", "stub",
    ]
    assert run_cli(tmp_path, argv + ["--rebuild"], monkeypatch) == 0
    capsys.readouterr()
    assert run_cli(tmp_path, argv, monkeypatch) == 0
    out = capsys.readouterr().out
    assert "复用" in out, f"未带 --rebuild 时应说明是复用现有索引：\n{out}"


def test_build_index_cli_flags_stale_corpus(tmp_path, capsys, monkeypatch):
    """语料变了而未重建：CLI 判过期并非零退出，提示重建命令（规范 8.15）。"""
    db_path = make_db(tmp_path)
    argv = [
        "--db", str(db_path),
        "--out", str(tmp_path / "i-stale"),
        "--aliases", str(make_aliases(tmp_path)),
        "--embedding-backend", "stub",
    ]
    assert run_cli(tmp_path, argv + ["--rebuild"], monkeypatch) == 0
    with sqlite3.connect(db_path) as conn:
        card_id = conn.execute("SELECT card_id FROM cards LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO claims (card_id, source_id, subject, predicate, value, quote, locator,"
            " confidence) VALUES (?, 'S001', '后加入的主体', '职务', '新增取值',"
            " '这是后加入的一条引文正文', '{}', 0.9)",
            (card_id,),
        )
        conn.commit()
    capsys.readouterr()
    code = run_cli(tmp_path, argv, monkeypatch)
    out = capsys.readouterr().out
    assert code != 0 and "--rebuild" in out, f"语料指纹不符必须判过期并给出重建命令：\n{out}"


def test_no_network_calls_in_this_file():
    """守 5.17 的元测试：本文件不得出现真实网络栈的导入或真实 key。

    字面量拆开拼：断言字符串本身会出现在被扫描的源码里，直接写出完整调用形态会让这条断言
    恒假（自指缺陷，实测踩过）。拆开后既保留了扫描意图，也不给被扫描文本制造假命中。
    """
    import re

    source = Path(__file__).read_text(encoding="utf-8")
    network_call = "httpx" + ".Client("
    requests_call = "requests" + "."
    # 真实 key 形态用「前缀 + 20 位以上连续字母数字」的形态识别：直接查 `"sk-"` 会命中
    # "task-8" 这类正文（"ta**sk-8**"），属误报，实测踩过。
    key_pattern = re.compile(r"sk-[A-Za-z0-9]{20,}")
    assert network_call not in source and requests_call not in source
    assert not key_pattern.search(source), "本文件疑似写入了真实 key"
