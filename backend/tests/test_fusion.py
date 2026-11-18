"""混合召回融合：倒数排名融合与稀疏名额（阶段二 T4 步骤 4 / 4b）。

两类事故必须由本文件当场失败：
1. **稀疏分混进 `Hit.score`**：量纲与向量相似度不可比，混进去会让 T5 的阈值标定拿到两把尺子，
   换重排档时阈值静默失效（规范 4.6、4.8）；
2. **无分候选占满证据集**：稀疏-only 的候选没有相似度，闸门对它们「无从判断」就会全部放行，
   所以名额必须 `k // 2`（规范 4.7、plan 步骤 4b-2）。

全部用例纯对象构造，不建索引、不联网（规范 5.17）。
"""

from __future__ import annotations

import pytest

from app.retrieval.backend import Hit
from app.retrieval.search import SPARSE_QUOTA_DIVISOR, fuse, sparse_quota


def make_hit(claim_id: int, *, dense: float | None = None, sparse: float | None = None,
             order: int | None = None) -> Hit:
    """构造一个候选：`dense` 给了就有相似度（`score` 同源），否则两列都 None（4.7）。"""
    hit = Hit(
        claim_id=claim_id,
        card_id=claim_id,
        score=dense,
        dense_score=dense,
        sparse_score=sparse,
        rerank_score=None,
    )
    hit.doc_order = claim_id if order is None else order  # type: ignore[attr-defined]
    return hit


def test_rrf_puts_two_channel_agreement_first():
    """两路都召回的条目必须排在最前：RRF 的意义就是把「多个通道都说是它」抬上来。"""
    dense = [make_hit(2, dense=0.81), make_hit(1, dense=0.60)]
    sparse = [make_hit(1, sparse=9.0), make_hit(3, sparse=4.0)]
    result = fuse(dense, sparse, k=3, rrf_constant=60)
    assert result[0].claim_id == 1, (
        f"两路一致命中的条目没有排第一：{[h.claim_id for h in result]}（RRF 融合没生效）"
    )


def test_fused_hit_keeps_dense_similarity_as_gate_score():
    """融合后闸门尺子必须还是稠密相似度，不得被 RRF 分顶掉（规范 4.6）。"""
    dense = [make_hit(7, dense=0.73)]
    sparse = [make_hit(7, sparse=12.5)]
    fused = fuse(dense, sparse, k=1, rrf_constant=60)[0]
    assert fused.score == pytest.approx(0.73), (
        f"综合分被改写成 {fused.score!r}：闸门阈值是按相似度标定的，换尺子等于阈值作废"
    )
    assert fused.dense_score == pytest.approx(0.73)
    assert fused.sparse_score == pytest.approx(12.5), "稀疏分应当在融合后保留下来（只共列，不参与闸门）"


def test_sparse_only_hits_have_no_similarity():
    """只靠关键词命中的候选没有相似度：`score` 必须是 None 而不是 0.0（规范 4.7、8.14）。"""
    fused = fuse([], [make_hit(4, sparse=6.0)], k=2, rrf_constant=60)
    assert fused and fused[0].score is None, (
        f"稀疏-only 候选拿到了 {fused[0].score!r} 的综合分：0.0 与 None 混用会让阈值曲线失真"
    )


def test_sparse_quota_limits_keyword_only_candidates():
    """稀疏-only 名额上限 k // 2：无分条目不得超过一半（plan 步骤 4b-2）。"""
    dense = [make_hit(i, dense=0.9 - i * 0.01) for i in range(1, 4)]
    sparse = [make_hit(9 + i, sparse=9.0 - i) for i in range(1, 7)]
    fused = fuse(dense, sparse, k=6, rrf_constant=60)
    keyword_only = [h for h in fused if h.score is None]
    assert sparse_quota(6) == 3
    assert len(keyword_only) <= 3, (
        f"稀疏-only 占了 {len(keyword_only)} 个名额（上限 3）：无分条目占满证据集"
        "会让闸门无从判断而全部放行"
    )
    assert len(fused) == 6


def test_quota_is_one_half_of_k():
    """`k // 2` 的取值本身是可断言的（改分母等于改红线，须同时改测试）。"""
    assert SPARSE_QUOTA_DIVISOR == 2
    assert [sparse_quota(k) for k in (1, 2, 3, 8)] == [0, 1, 1, 4]


def test_equal_rrf_breaks_tie_by_doc_order():
    """同分按 doc_order 升序：平局抖动会让 T5 的 MRR 不可复现（承诺的稳定序）。"""
    dense = [make_hit(5, dense=0.5, order=2)]
    sparse = [make_hit(6, sparse=5.0, order=1)]
    fused = fuse(dense, sparse, k=2, rrf_constant=60)
    assert [h.claim_id for h in fused] == [6, 5], (
        f"同 rrf 时没有按 doc_order 稳定排序：{[h.claim_id for h in fused]}"
    )


def test_dense_candidates_are_not_quota_limited():
    """名额只约束稀疏-only：有相似度的候选全放行（否则等于把稠密通道也砍半）。"""
    dense = [make_hit(i, dense=0.9) for i in range(1, 7)]
    fused = fuse(dense, [], k=6, rrf_constant=60)
    assert len(fused) == 6
