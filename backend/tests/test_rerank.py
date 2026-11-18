"""重排三档（阶段二 T4 步骤 4 / 4b）：API 重排、本地词法重排、关闭。

本文件守三条红线，每条都对应一个真实事故：
1. **尺子隔离**：重排只写 `Hit.rerank_score`，绝不回写 `Hit.score`（4.6）。参考实现踩过
   「换成 reranker 后按相似度标定的阈值静默失效」（004 §三-3）。
2. **失败可回退但不静默**：无 key / 超时 / 条数不符 → 打印 `重排未生效: 原因` 后按融合顺序
   返回（4.3）；参考实现的第一版是「界面显示开启、实际空转」。
3. **超限不截断、缺分不补齐**：单文档超预检线、返回条数不足，一律抛 `RerankResponseError`
   （4.4-①、4.5）。

不联网：API 档用 `httpx.MockTransport` 注入响应（规范 5.17）。
"""

from __future__ import annotations

import logging

import httpx
import pytest

from app.core.config import Config
from app.retrieval.backend import Hit
from app.retrieval.errors import RerankResponseError
from app.retrieval.rerank import (
    ApiReranker,
    LocalLexicalReranker,
    apply_rerank,
    build_reranker,
    describe,
)


def rerank_cfg(**over) -> Config:
    """三档里 api 档的最小可用配置（密钥一律假值，规范 8.6）。"""
    base = {
        "rerank_backend": "api",
        "rerank_base_url": "https://mock.example/compatible-api/v1",
        "rerank_api_key": "sk-test-not-a-real-key",
        "rerank_model": "qwen3-rerank",
        "rerank_max_docs": 60,
        "rerank_max_tokens_per_doc": 30000,
    }
    base.update(over)
    return Config(**base)


def make_hit(claim_id: int, *, dense: float | None = 0.5, order: int | None = None) -> Hit:
    hit = Hit(
        claim_id=claim_id,
        card_id=claim_id,
        score=dense,
        dense_score=dense,
        sparse_score=None,
        rerank_score=None,
    )
    hit.doc_order = claim_id if order is None else order  # type: ignore[attr-defined]
    return hit


def transport_returning(payload: dict, *, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def ok_payload(scores: list[float]) -> dict:
    return {
        "output": {
            "results": [
                {"index": i, "relevance_score": score} for i, score in enumerate(scores)
            ]
        }
    }


# ── 尺子隔离（红线 1）────────────────────────────────────────────────────────────────────
def test_apply_rerank_writes_only_rerank_score():
    """重排分写进 `rerank_score`，`score` / `dense_score` 一个字节不动（4.6）。"""
    hits = [make_hit(1, dense=0.30), make_hit(2, dense=0.80)]
    texts = {1: "讲习所条目正文", 2: "长征条目正文"}
    reranker = LocalLexicalReranker(rerank_cfg())
    result = apply_rerank(hits, "讲习所", reranker, text_of=lambda h: texts[h.claim_id])
    assert all(hit.rerank_score is not None for hit in result)
    assert [h.score for h in result] == [0.30, 0.80], "重排回写了综合分：阈值标定会静默失效"


def test_rerank_order_can_change_but_gate_scores_stay():
    """顺序可以变，闸门尺子不变：这正是「重排不参与拒答判定」的可断言形态。"""
    hits = [make_hit(1, dense=0.30), make_hit(2, dense=0.80)]
    texts = {1: "省立第一师范学校讲习所于一九二五年创设", 2: "完全无关的一段正文"}
    reranker = LocalLexicalReranker(rerank_cfg())
    result = apply_rerank(hits, "省立第一师范 创设", reranker, text_of=lambda h: texts[h.claim_id])
    assert [h.claim_id for h in result] == [1, 2], "词法重排没有把更相关的条目抬上来"
    assert max(h.score for h in result) == 0.80, "重排改动了闸门尺子"


def test_candidates_outside_window_keep_none_rerank_score():
    """窗口外的候选 `rerank_score` 保持 None：没打分不等于打 0 分（4.8、8.14）。"""
    hits = [make_hit(i, dense=0.9 - i * 0.01) for i in range(1, 5)]
    reranker = LocalLexicalReranker(rerank_cfg())
    result = apply_rerank(
        hits, "讲习所", reranker, text_of=lambda h: "正文内容", max_docs=2
    )
    assert [h.rerank_score is None for h in result].count(True) == 2, (
        f"窗口外候选被打了分：{[h.rerank_score for h in result]}"
    )


# ── 失败回退但不静默（红线 2）────────────────────────────────────────────────────────────
class BrokenReranker:
    name = "broken"

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        raise RerankResponseError("模拟：返回条数 2 != 请求条数 3")


def test_failed_rerank_falls_back_to_fusion_order_and_logs(caplog):
    """重排失败 → 原序返回 + 一行说明（4.3）。不是异常路径，但必须留痕。"""
    hits = [make_hit(1), make_hit(2), make_hit(3)]
    with caplog.at_level(logging.WARNING, logger="app.retrieval.rerank"):
        result = apply_rerank(hits, "查询", BrokenReranker(), text_of=lambda h: "正文")
    assert [h.claim_id for h in result] == [1, 2, 3], "重排失败后顺序被改动了"
    assert all(h.rerank_score is None for h in result)
    assert any("重排未生效" in record.message for record in caplog.records), (
        "失败没有打印「重排未生效: 原因」：界面会显示已开启而实际空转（参考实现第一版的事故）"
    )


def test_none_reranker_is_off_and_keeps_order():
    """`reranker=None`（off 档）等价于不重排，不写任何分数。"""
    hits = [make_hit(1), make_hit(2)]
    assert apply_rerank(hits, "查询", None, text_of=lambda h: "正文") is hits
    assert all(h.rerank_score is None for h in hits)


# ── API 档：配置纪律与响应完整性（红线 3）───────────────────────────────────────────────
@pytest.mark.parametrize(
    "field,env_name",
    [
        ("rerank_base_url", "RERANK_BASE_URL"),
        ("rerank_api_key", "RERANK_API_KEY"),
        ("rerank_model", "RERANK_MODEL"),
    ],
)
def test_api_reranker_names_missing_env(field, env_name):
    """缺配置在构造期报错并点名环境变量，不自己换档（4.1、4.13）。"""
    with pytest.raises(RuntimeError, match=env_name):
        ApiReranker(rerank_cfg(**{field: ""}))


def test_api_reranker_rejects_document_over_token_line():
    """单文档超预检线在客户端拦下：服务端超限明确 400、不静默截断（007 三-4）。"""
    reranker = ApiReranker(rerank_cfg(rerank_max_tokens_per_doc=5))
    with pytest.raises(RerankResponseError, match="预检线"):
        reranker.rerank("查询", ["这是一条明显超过五个 token 的长文档正文"])


def test_api_reranker_rejects_too_many_documents():
    """请求条数超窗口上限即报错，**不得**截断后发送。"""
    reranker = ApiReranker(rerank_cfg(rerank_max_docs=2))
    with pytest.raises(RerankResponseError, match="超过上限"):
        reranker.rerank("查询", ["一", "二", "三"])


def test_api_reranker_rejects_short_result_list():
    """返回条数 != 请求条数 → 抛错，不得用默认分补齐（4.4-①）。"""
    reranker = ApiReranker(rerank_cfg(), transport=transport_returning(ok_payload([0.9])))
    with pytest.raises(RerankResponseError, match="条数"):
        reranker.rerank("查询", ["一", "二"])


def test_api_reranker_rejects_out_of_range_score():
    """`relevance_score` 必须落在 [0,1]，越界即协议不符。"""
    reranker = ApiReranker(rerank_cfg(), transport=transport_returning(ok_payload([1.7])))
    with pytest.raises(RerankResponseError, match=r"\[0,1\]"):
        reranker.rerank("查询", ["一"])


def test_api_reranker_rejects_missing_index():
    """结果项的 index 越界或缺失 → 抛错（错位分数会把出处指到别的条目）。"""
    payload = {"output": {"results": [{"index": 3, "relevance_score": 0.5}]}}
    reranker = ApiReranker(rerank_cfg(), transport=transport_returning(payload))
    with pytest.raises(RerankResponseError, match="越界"):
        reranker.rerank("查询", ["一"])


def test_api_reranker_rejects_missing_index_field():
    """index 缺失同样判协议不符，不得按数组下标猜。"""
    payload = {"output": {"results": [{"relevance_score": 0.5}]}}
    reranker = ApiReranker(rerank_cfg(), transport=transport_returning(payload))
    with pytest.raises(RerankResponseError, match="越界"):
        reranker.rerank("查询", ["一"])


def test_api_reranker_happy_path_returns_scores_in_request_order():
    """正常响应按请求顺序返回分数（融合窗口与分数必须一一对应）。"""
    reranker = ApiReranker(
        rerank_cfg(), transport=transport_returning(ok_payload([0.2, 0.9]))
    )
    assert reranker.rerank("查询", ["一", "二"]) == [0.2, 0.9]


def test_api_reranker_http_400_raises_without_retry():
    """4xx 是请求本身的问题，重试无意义：立即抛错（不烧 token）。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"message": "invalid"})

    reranker = ApiReranker(rerank_cfg(), transport=httpx.MockTransport(handler))
    with pytest.raises(RerankResponseError, match="400"):
        reranker.rerank("查询", ["一"])
    assert calls["n"] == 1, f"4xx 被重试了 {calls['n']} 次：白烧配额（4.11 只约束可重试故障）"


# ── 档位选择 ───────────────────────────────────────────────────────────────────────────
def test_build_reranker_maps_three_backends():
    """三档显式映射：api / local_lexical / off（off → None），档位由配置决定（4.13）。"""
    assert isinstance(build_reranker(rerank_cfg()), ApiReranker)
    assert isinstance(
        build_reranker(rerank_cfg(rerank_backend="local_lexical")), LocalLexicalReranker
    )
    assert build_reranker(rerank_cfg(rerank_backend="off")) is None
    assert describe(None) == "未接入（off）"
    assert describe(LocalLexicalReranker(rerank_cfg())) == "local_lexical"


def test_build_reranker_rejects_unknown_backend():
    """拼错的档位立即报错，不回落（4.13：档位拼错了还照跑，产物与评测口径就不是一回事）。

    用假配置对象：`Config` 的 `Literal` 会在赋值期就挡住非法档位，那属于「更早一层」的防线；
    本用例守的是 `build_reranker` 自己被绕过时的分支（例如将来换配置来源）。
    """
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="未知的重排档"):
        build_reranker(SimpleNamespace(rerank_backend="api2"))


def test_local_lexical_reranker_scores_coverage():
    """本地词法档：覆盖率打分落在 [0,1]，且相关文档高于无关文档。"""
    reranker = LocalLexicalReranker(rerank_cfg(rerank_backend="local_lexical"))
    scores = reranker.rerank("讲习所 创设", ["省立第一师范学校讲习所于一九二五年创设", "长沙地方志"])
    assert 0.0 <= scores[0] <= 1.0 and 0.0 <= scores[1] <= 1.0
    assert scores[0] > scores[1], f"词法覆盖率没有区分度：{scores}"


def test_local_lexical_reranker_handles_empty_query():
    """空查询不打分（返回全 0），不抛异常：这是降级档，必须能跑通整条链路。"""
    reranker = LocalLexicalReranker(rerank_cfg(rerank_backend="local_lexical"))
    assert reranker.rerank("", ["正文"]) == [0.0]
