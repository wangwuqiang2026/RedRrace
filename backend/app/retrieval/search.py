"""混合召回融合（阶段二 T4）：倒数排名融合 + 稀疏名额约束。

为什么单独成文件而不是塞进 `local.py`：融合规则要与「哪条通道来的、谁有相似度」绑定，
而这两件事在 T5 的阈值标定里会被反复引用（闸门只认 `Hit.score`）。单独一处实现，
换检索后端（RagFlow 适配器）时这条规则不用重写。

三条纪律（plan 步骤 4 与 4b，决策记录 006 第三节）：
1. **`Hit.score` 只承载相似度**（可跨请求比较的那把尺子）。融合分只用于排序，绝不写进 `score`；
   否则 T5 按 `Hit.score` 标定出来的阈值会在换融合参数时静默失效（规范 4.6）。
2. **稀疏名额上限 `k // 2`**：只靠 BM25 命中、没有相似度的候选不得超过一半，否则无分条目
   占满证据集会让闸门「无从判断」而全部放行（规范 4.7）。
3. **顺序稳定**：同分按 `doc_order` 升序，让 T5 的 MRR 可复现。
"""

from __future__ import annotations

from collections.abc import Iterable

from app.retrieval.backend import Hit

# 稀疏通道在最终 top-k 里的名额上限比例的分母：1/2 即 `k // 2`（规范 4.7）。
SPARSE_QUOTA_DIVISOR = 2


def sparse_quota(k: int) -> int:
    """稀疏-only 候选在最终结果里的名额上限（`k // 2`，至少留 0 个）。"""
    return max(0, k // SPARSE_QUOTA_DIVISOR)


def fuse(
    dense: Iterable[Hit],
    sparse: Iterable[Hit],
    *,
    k: int,
    rrf_constant: int,
    quota: int | None = None,
) -> list[Hit]:
    """倒数排名融合：`score_rrf = Σ 1 / (constant + rank)`，按 rrf 降序取前 k 条。

    参数纪律：`rrf_constant`（默认 60）来自 `Config.retrieval_rrf_constant`，**不是本模块内的
    常量**——它在 T5 的开发集上要扫两档定稿（plan 步骤 4 给了 60 这个起点，禁止清单 8.12
    要求不得把它当成本项目达标线）。

    `quota=None` 时按 `k // 2` 取上限；显式传值只用于测试构造「名额是否真被消费」的对照。
    """
    limit = sparse_quota(k) if quota is None else max(0, quota)
    merged: dict[int, dict[str, object]] = {}
    for rank, hit in enumerate(dense, start=1):
        merged[hit.claim_id] = {
            "hit": hit,
            "rrf": 1.0 / (rrf_constant + rank),
            "from_dense": True,
        }
    for rank, hit in enumerate(sparse, start=1):
        entry = merged.get(hit.claim_id)
        if entry is None:
            merged[hit.claim_id] = {
                "hit": hit,
                "rrf": 1.0 / (rrf_constant + rank),
                "from_dense": False,
            }
            continue
        entry["rrf"] = float(entry["rrf"]) + 1.0 / (rrf_constant + rank)
        existing = entry["hit"]
        # 两路都召回同一条目：相似度以稠密为准（尺子唯一，规范 4.6），稀疏分只做补充。
        if getattr(existing, "sparse_score", None) is None and hit.sparse_score is not None:
            existing.sparse_score = hit.sparse_score

    ordered = sorted(
        merged.values(),
        key=lambda e: (-float(e["rrf"]), getattr(e["hit"], "doc_order", 0)),
    )
    out: list[Hit] = []
    remaining = limit
    for entry in ordered:
        hit = entry["hit"]
        if not entry["from_dense"]:
            if remaining <= 0:
                # 名额用尽：这条纯关键词命中不进最终证据集（不是丢掉，而是留在融合结果里供
                # 自检比对——调用方要看得到「被名额截掉了多少」时可直接调 `fuse` 后比对长度）。
                continue
            remaining -= 1
        out.append(hit)
        if len(out) >= k:
            break
    return out
