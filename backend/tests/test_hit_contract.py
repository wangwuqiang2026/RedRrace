"""检索契约层（app.retrieval.backend / app.retrieval.errors）的锁测试。

出处：plan 阶段二「接口约定」与步骤 3b、4、4b（`.superpowers/sdd/plan/phase2-text.md:13,42-73,81-104`）、
task1-brief.md、决策记录裁决 D3/D4/D9/D11/D13（progress.md）。

本文件是 T2–T5 的地基：字段名、方法名、异常名一旦改动，这里立刻变红
（规范 6.1「字段可加不可改名不可删」、5.12「契约字段名用锁测试钉死」）。
不测任何检索行为——召回、融合、阈值分别属 test_search_recall.py 与 test_refusal_threshold.py
（规范 5.16），且本任务不得依赖真实库或网络（规范 5.17）。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from pathlib import Path
from typing import Literal

import pytest
from helpers import CONFIG_ENV_KEYS

from app.core.config import Config, get_config
from app.retrieval.backend import Hit, IndexStats, SearchBackend
from app.retrieval.errors import EmbeddingResponseError, RerankResponseError

# backend/ 目录：.env.example 的核对锚点（与 test_config.py:12 同一算法，规范 2.12）
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 一条最小可用的召回结果：BM25-only 形态（无向量相似度，依 4.7 显式为 None）。
# 用完整六字段字典而不是省略参数——契约要求「除确有缺省语义的字段外全部必填」（规范 6.4）。
SPARSE_ONLY_HIT = {
    "claim_id": 7,
    "card_id": 3,
    "score": None,
    "dense_score": None,
    "sparse_score": 12.5,
    "rerank_score": None,
}


# ── 配置参数：lead 裁决 D11 指派 T1 单点补进 Config，防 T4/T5 并发写同一文件 ──────────────
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """默认值断言不受宿主环境变量干扰（规范 5.5：键名从 Config.model_fields 派生，不手抄）。"""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_retrieval_tuning_defaults_match_plan_step_4():
    """三个检索参数的默认值必须等于 plan 步骤 4 写的「稠密 30 / 稀疏 30 / 常数 60」。

    不钉住会怎样：T4 把数字散写回实现里（规范 D11 禁止的做法），改一处不影响另一处，
    而阈值标定扫的就是这三档组合——参数与标定条件从此对不上。
    """
    cfg = get_config()
    assert cfg.retrieval_dense_top_k == 30, "稠密名额与 plan 步骤 4 不一致"
    assert cfg.retrieval_sparse_top_k == 30, "稀疏名额与 plan 步骤 4 不一致"
    assert cfg.retrieval_rrf_constant == 60, "RRF 常数是参考实现起点，改值须同步阈值文件里的标定条件"


@pytest.mark.parametrize("key", ["RETRIEVAL_DENSE_TOP_K", "RETRIEVAL_SPARSE_TOP_K", "RETRIEVAL_RRF_CONSTANT"])
def test_retrieval_tuning_is_env_overridable(monkeypatch, key):
    """三项必须是真配置项而非实现内常量：部署侧要能不改代码扫档（规范 D11 的后半句）。

    用 monkeypatch.setenv 而不是直接动 os.environ（规范 5.6）。
    """
    monkeypatch.setenv(key, "17")
    assert getattr(get_config(), key.lower()) == 17


def test_new_config_keys_are_present_in_env_example():
    """新增配置项必须同步 .env.example（规范 7.10 第④条），否则部署照样例复制就静默丢参。"""
    text = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8-sig")
    declared = {name.upper() for name in Config.model_fields}
    for key in ("RETRIEVAL_DENSE_TOP_K", "RETRIEVAL_SPARSE_TOP_K", "RETRIEVAL_RRF_CONSTANT"):
        assert f"{key}=" in text, f"{key} 未进 .env.example"
        assert key in declared, f"{key} 不是 Config 字段，不该出现在样例里"


# ── Hit 字段名与类型：唯一权威定义在本模块（规范 6.7、裁决 D4/D13）──────────────────────
def test_hit_field_names_are_locked():
    """六个语义字段的英文名一次定死；改名必须让这条红（规范 5.12、6.1）。"""
    names = {f.name for f in dataclasses.fields(Hit)}
    assert names == {"claim_id", "card_id", "score", "dense_score", "sparse_score", "rerank_score"}


def test_hit_field_order_and_types_are_locked():
    """顺序即 `Hit(1, 2, 0.8)` 这种位置构造的含义，也是 T5 读分数的顺序，不得悄悄重排。"""
    fields = dataclasses.fields(Hit)
    assert [f.name for f in fields] == [
        "claim_id",
        "card_id",
        "score",
        "dense_score",
        "sparse_score",
        "rerank_score",
    ]
    types = {f.name: f.type for f in fields}
    assert types["claim_id"] == "int"
    assert types["card_id"] == "int"
    assert types["score"] == "float | None"
    assert types["dense_score"] == "float | None"
    assert types["sparse_score"] == "float | None"
    assert types["rerank_score"] == "float | None"


def test_hit_is_mutable_dataclass_outside_openapi():
    """裁决 D13 + 规范 2.7：进程内中间产物用 `@dataclass`，且 HTTP 可见才进 `qa/schemas.py`。

    非 frozen 是必须的：rerank 通道要在融合之后回填 `rerank_score`（步骤 4b-1 只禁回写 score）。
    不进 OpenAPI 则由序列化侧证明——它不是 pydantic 模型，FastAPI 不会为它生成 schema。
    """
    assert dataclasses.is_dataclass(Hit)
    assert Hit.__dataclass_params__.frozen is False, "frozen 会让重排无法回填 rerank_score"
    assert not hasattr(Hit, "model_fields"), "Hit 本阶段不得提前做成 pydantic 契约模型（裁决 D13）"


# ── 无相似度 = None，不是 0.0、不是 -1（规范 4.7、8.14；brief 测试要求 1）────────────────
def test_missing_similarity_is_none_not_zero_or_sentinel():
    """缺向量相似度的候选必须显式 None。

    写成 0.0 或 -1 的后果（步骤 4b-2 原文）：前端出处卡把两把尺子显示在同一列，
    出现「0% 却被引用」这类无法解释的观感；而闸门按分数比较时，哨兵值会被当成真实低分。
    """
    hit = Hit(**SPARSE_ONLY_HIT)
    assert hit.score is None
    assert hit.dense_score is None
    assert hit.rerank_score is None
    assert hit.sparse_score == 12.5, "BM25 词频分照常保留，它只是不参与闸门"


def test_zero_is_a_valid_similarity_not_a_sentinel():
    """0.0 必须能构造出来：它是合法的低相似度下界，与「没有这个分数」（`None`）是两回事（依 4.7、8.14）。

    这是对 brief 测试要求 1 的必要更正：原文把 0.0 与 -1 并列为哨兵，但 cos 归一后落在 [0,1]，
    0.0 是一个真实分值。若照原文拒绝它，T5 就造不出「相似度恰好为 0」的负例，阈值扫描曲线低端出现空洞；
    反过来若实现用 `or` 把 0.0 当假值吞掉（规范 3 反例 B），合法的 0.0 会被静默换成另一把尺子的数。
    """
    hit = Hit(**{**SPARSE_ONLY_HIT, "dense_score": 0.0, "score": 0.0})
    assert hit.score == 0.0 and hit.dense_score == 0.0


@pytest.mark.parametrize("bad", [-1, -1.0, float("nan"), float("inf")])
def test_sentinel_scores_are_rejected(bad):
    """`-1` / `nan` / `inf` 不得用来表示「没有这个分数」（规范 8.14）。

    三种哨兵各自的失败形态不同，故各给一例：`-1` 混进分数列 → 前端出现「0% 却被引用」
    （步骤 4b-2 原文）；`nan` 参与比较恒 False → 闸门全放行；`inf` 恒为最大 → 一条脏数据顶掉整题判定。
    """
    with pytest.raises(ValueError, match="None"):
        Hit(**{**SPARSE_ONLY_HIT, "dense_score": bad})


@pytest.mark.parametrize("name", ["score", "dense_score", "sparse_score", "rerank_score"])
@pytest.mark.parametrize("bad", [-1, -0.5, float("nan"), "0.5", True])
def test_every_score_column_rejects_negative_and_non_numeric(name, bad):
    """四列各自都要拦住负数与非数值（依 5.9：不变式从破坏面各写一条，不接受只喂字面量的伪测试）。

    `-0.5` 单独一例是为了防「用 `if value:` 判空」的写法——负数走不进真值分支就会静默入库。
    `True` 是 int 的子类，若不显式拦住，`rerank_score=True` 会被当成 1.0 满分送进闸门。
    """
    payload = {"claim_id": 1, "card_id": 1, "score": None, "dense_score": None,
               "sparse_score": None, "rerank_score": None}
    payload[name] = bad
    with pytest.raises(ValueError, match=name):
        Hit(**payload)


def test_sparse_score_may_exceed_one_because_units_differ():
    """BM25 词频分无上界，不得按 [0,1] 归一（依 4.8「三种量纲不得混列」、步骤 4b-2）。

    不测会怎样：若实现把 sparse_score 也夹到 1.0，它就长得像相似度，
    T5 标定与阶段三闸门都可能拿它去比阈值——正是 §5.23「相关与不相关得分看起来差不多」的成因。
    """
    assert Hit(**{**SPARSE_ONLY_HIT, "sparse_score": 47.3}).sparse_score == 47.3
    with pytest.raises(ValueError, match="score"):
        Hit(claim_id=1, card_id=1, score=1.7, dense_score=None, sparse_score=None, rerank_score=None)


@pytest.mark.parametrize("name", ["score", "dense_score", "sparse_score", "rerank_score"])
def test_none_is_accepted_for_every_score_column(name):
    """四列都允许 None（依约束 6 / 裁决 D4：契约不得隐含要求向量必须存在）。"""
    payload = {"claim_id": 1, "card_id": 1, "score": None, "dense_score": None,
               "sparse_score": None, "rerank_score": None}
    payload[name] = None
    assert getattr(Hit(**payload), name) is None


def test_all_fields_are_required_no_defaults():
    """六个字段全部必填、不给默认值（规范 6.4）：漏填必须在构造时报错，而不是悄悄变成 None。

    危害：若 `rerank_score` 有默认值，重排通道忘回填与「确实没开重排」在数据上完全同形，
    步骤 4b 的对照测试就再也分辨不出「界面显示开启、实际空转」（规范 4.3 明令禁止的状态）。
    """
    for missing in ("claim_id", "card_id", "score", "dense_score", "sparse_score", "rerank_score"):
        payload = dict(SPARSE_ONLY_HIT)
        payload.pop(missing)
        with pytest.raises(TypeError, match=missing):
            Hit(**payload)
    assert all(f.default is dataclasses.MISSING for f in dataclasses.fields(Hit))


def test_no_factory_or_alias_helpers_on_hit():
    """契约层不提供具名构造器：类上除 dataclass 自动生成的四个 dunder 外不得有任何可调用成员。

    危害（依 4.8）：`Hit.sparse_only(...)` 这类便捷入口会让「BM25 分写进哪一列」变成实现细节，
    一旦有人再加一个 `Hit.dense_only(...)` 而把词频分填进 `dense_score`，量纲混列不会报错，
    只会让 T5 的阈值曲线低端凭空多出一段假正例。显式写全六字段是这里的唯一写法。
    """
    assert not hasattr(Hit, "sparse_only")
    assert not hasattr(Hit, "from_row")
    fields = {f.name for f in dataclasses.fields(Hit)}
    assert Hit(**{k: (0 if k.endswith("_id") else None) for k in fields}).claim_id == 0


def test_hit_equality_is_value_based():
    """dataclass 默认值相等：T4/T5 的对照测试要拿两个 Hit 直接比，不能靠 id()。"""
    a = Hit(1, 2, 0.5, 0.5, None, None)
    b = Hit(1, 2, 0.5, 0.5, None, None)
    assert a == b and a != Hit(1, 2, 0.6, 0.5, None, None)


def test_none_survives_serialization_round_trip():
    """落 JSON 再读回来仍是 null→None（规范 4.7 的可判定面）。

    若序列化把 None 变成 0.0，阶段三的出处卡就会显示「0%」，而这正是 §5.32 的事故形态。
    """
    hit = Hit(claim_id=1, card_id=2, score=0.42, dense_score=0.42, sparse_score=None, rerank_score=None)
    restored = Hit(**json.loads(json.dumps(dataclasses.asdict(hit))))
    assert restored.sparse_score is None
    assert restored.rerank_score is None
    assert restored.score == 0.42


def test_gate_fields_only_no_helpers():
    """闸门取数函数不提供（brief 测试要求 2 的第二种处置）：唯一尺子是 `Hit.score`。

    为什么不放一个 `gate_score()`：契约层给不出「参与闸门」的正确形态——阈值比较发生在
    T5 的标定与阶段三的拒答里，多一个入口就多一处可能被人改成拿 rerank_score 去比阈值
    （规范 4.6 明令禁止）。因此这里钉的是**字段名本身**：除 `score` 外没有任何字段名含
    "gate"/"threshold"；类上只允许具名构造器 `sparse_only`（它产出 None 分数，不产出分数），
    后人想换尺子只能显式改代码，改不动契约。
    """
    assert not hasattr(Hit, "gate_score"), "契约层不得提供闸门取数函数，理由见本用例 docstring"
    assert not hasattr(Hit, "threshold")
    gate_fields = [f.name for f in dataclasses.fields(Hit) if "gate" in f.name or "threshold" in f.name]
    assert gate_fields == [], f"出现了闸门专用字段，会让两套尺子并存：{gate_fields}"
    methods = sorted(n for n, v in vars(Hit).items() if callable(v) and not n.startswith("_"))
    assert methods == [], f"Hit 上长出了方法，等于开出第二把尺子的入口：{methods}"


def test_rerank_score_never_participates_in_the_gate():
    """开/关重排后参与闸门的那把尺子必须是同一个数（步骤 4b 的 `test_rerank_does_not_move_gate`）。

    契约层的体现形式：两个 Hit 只有 rerank_score 不同 → `max(h.score)` 逐位相同。
    若不钉这条，换成 reranker 后步骤 6 标出的阈值会静默失效（004 §三-3、参考实现 §5.9）。
    """
    base = {"claim_id": 1, "card_id": 1, "score": 0.61, "dense_score": 0.61, "sparse_score": 8.0}
    off = Hit(**base, rerank_score=None)
    on = Hit(**base, rerank_score=0.03)
    assert max(off.score, on.score) == 0.61, "重排改写了综合分，步骤 6 的阈值标定作废"
    assert on.rerank_score != on.score, "两条尺子必须各自独立，不得互相顶替"


# ── SearchBackend 抽象接口：步骤 3b/4b 要求的入口一次定死（brief「Ruling」）─────────────
def test_search_backend_method_names_are_locked():
    """四个检索入口 + index 的名字固定，T3/T4 只能在实现里追加私有辅助（规范 6.8）。"""
    public = {n for n in vars(SearchBackend) if not n.startswith("_")}
    assert public == {"index", "search", "search_bm25_only", "search_dense_only", "index_stats"}


def test_search_signature_has_keyword_only_rerank():
    """`search(query, k, *, rerank=True)`：rerank 必须是仅关键字参数（brief 给的调用形态
    `index.search(q, 8, rerank=False)` 出自步骤 4b 原文；规范 2.16 要求关键路径参数仅关键字）。"""
    params = inspect.signature(SearchBackend.search).parameters
    assert list(params)[:3] == ["self", "query", "k"]
    assert params["rerank"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["rerank"].default is True


@pytest.mark.parametrize("method", ["search", "search_bm25_only", "search_dense_only"])
def test_channel_probe_methods_take_positional_query_and_k(method):
    """两条自检通道与主入口同签名前缀，步骤 3b 的测试写法 `search_bm25_only("…", k=10)` 才走得通。"""
    params = list(inspect.signature(getattr(SearchBackend, method)).parameters)
    assert params[:3] == ["self", "query", "k"], f"{method} 的参数名与步骤 3b 的调用形态不符"


def test_index_signature_is_keyword_friendly():
    """`index()` 留给 T3 自由扩展（DB 路径、切块口径等），但必须是公开抽象方法（规范 6.8）。

    这里只钉「存在且为 abstract」，不钉参数名——brief 未规定其参数，提前定死反而挡住 T3。
    """
    assert "index" in SearchBackend.__abstractmethods__
    assert callable(SearchBackend.index)


def test_abstract_base_cannot_be_instantiated():
    """未实现的抽象接口不可实例化（brief 测试要求 3，能失败的形态）。"""
    with pytest.raises(TypeError, match="abstract"):
        SearchBackend()


def test_subclass_missing_any_method_cannot_be_instantiated():
    """子类漏实现任意一个方法即报错——防止 T3 少写 `search_dense_only` 却靠继承拿到空壳。"""
    class Partial(SearchBackend):
        def index(self, *args, **kwargs):
            return None

        def search(self, query, k, *, rerank=True):
            return []

        def search_bm25_only(self, query, k):
            return []

        # 故意不实现 search_dense_only / index_stats

    with pytest.raises(TypeError, match="abstract"):
        Partial()


def test_full_subclass_can_be_instantiated():
    """对照用例：补齐全部方法就能实例化，证明上一条的红来自缺失而不是 ABC 本身不可用。"""
    class Complete(SearchBackend):
        def index(self, *args, **kwargs):
            return None

        def search(self, query, k, *, rerank=True):
            return []

        def search_bm25_only(self, query, k):
            return []

        def search_dense_only(self, query, k):
            return []

        def index_stats(self):
            return IndexStats(dense_hits=0, sparse_hits=0)

    assert isinstance(Complete(), SearchBackend)


def test_retrieval_backend_alias_is_not_reused_as_class():
    """裁决 D9：`RetrievalBackend` 已被 config.py 占作档位别名并进了 /api/health，
    不得再当类名——同名异义会让人把「选哪一档」和「哪个实现类」混为一谈。"""
    from app.core import config as config_module

    assert config_module.RetrievalBackend == Literal["local", "ragflow"], "档位别名取值不得改动"
    assert not isinstance(config_module.RetrievalBackend, type), "档位别名不应是类"
    assert SearchBackend.__name__ == "SearchBackend"


# ── index_stats 返回结构：两条通道命中数的键名固定，供 T3/build_index.py 直接消费 ────────
def test_index_stats_channel_keys_are_locked():
    """键名 `dense_hits` / `sparse_hits` 一经确定不得随手改（规范 6.11）。"""
    names = {f.name for f in dataclasses.fields(IndexStats)}
    assert names == {"dense_hits", "sparse_hits", "total_docs", "index_built"}
    stats = IndexStats(dense_hits=3, sparse_hits=5)
    as_dict = dataclasses.asdict(stats)
    assert as_dict["dense_hits"] == 3 and as_dict["sparse_hits"] == 5


def test_index_stats_default_channels_are_zero_not_none():
    """计数默认 0：步骤 3b 判的是「任一侧长期为 0 即未生效」，None 会让那条判断变成永真。"""
    stats = IndexStats()
    assert stats.dense_hits == 0 and stats.sparse_hits == 0
    assert stats.total_docs == 0
    assert stats.index_built is False


# ── errors.py：两个异常集中一处且必须是 RuntimeError 子类（裁决 D3，brief 明确要求）─────
@pytest.mark.parametrize("exc_cls", [EmbeddingResponseError, RerankResponseError])
def test_response_errors_are_runtimeerror_subclasses(exc_cls):
    """改成 Exception 基类后，装配层 `except ValueError` / `except RuntimeError` 都拦不住，
    建索引会以裸 traceback 中止（规范 4.1 的「构造时 raise RuntimeError」口径）。"""
    assert issubclass(exc_cls, RuntimeError)
    assert exc_cls.__module__ == "app.retrieval.errors", "异常必须集中在 errors.py，不得各模块自造"


def test_embedding_error_is_not_a_valueerror():
    """反向断言（规范 5.11）：向量响应残缺不能被判成入参错误。

    规范 4.2 把 IO/编码/入参归一为 ValueError，而 4.4 的响应完整性属于外部服务故障族；
    两者混用的话，调用方按「用户输入有问题」提示，运维就去查语料了，实际该查的是 API 响应。
    """
    assert not issubclass(EmbeddingResponseError, ValueError)
    assert not issubclass(RerankResponseError, ValueError)


def test_two_errors_have_distinct_phrases():
    """同族故障措辞必须各异（规范 4.14）：「向量响应不完整」与「重排未生效」不得共用一句模糊提示。"""
    vector_msg = str(EmbeddingResponseError("向量响应不完整：返回 1 条，请求 2 条"))
    rerank_msg = str(RerankResponseError("重排未生效：返回条数与请求不符"))
    assert "向量" in vector_msg and "重排" not in vector_msg
    assert "重排" in rerank_msg and "向量" not in rerank_msg
    assert vector_msg != rerank_msg


def test_errors_are_importable_from_single_module():
    """T2/T4 import 的是同一对象，而不是各自造同名类（裁决 D3 的理由）。"""
    from app.retrieval import errors

    assert errors.EmbeddingResponseError is EmbeddingResponseError
    assert errors.RerankResponseError is RerankResponseError
    assert set(errors.__all__) == {"EmbeddingResponseError", "RerankResponseError"}
