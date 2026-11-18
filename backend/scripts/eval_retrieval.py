"""检索层评测（阶段二 T5，plan 步骤 6 / 6b / 6c）。

只跑检索、不调生成模型，所以零 token 成本（这是能反复换模型、换切块、换重排的前提，
参考实现 §9.1–9.3 的方法学）。三项指标一次全出：

- **Hit@1 / Hit@3 / Hit@8**：期望事实条目是否出现在前 k 条；
- **MRR**：区分「排第 1」与「排第 4」，未命中计 0；
- **关键事实覆盖率**：期望关键事实是否出现在**最终送进证据集的那段文本**里——不是「页对了就算」。
  本项目候选还要经过融合与稀疏名额裁剪，所以必须在裁剪**之后**取文本，否则测的是半个链路
  （`refimpl-notes.md` 第 4 节的推断，本文件照此实现）。

另有两个对照（plan 6c 与 T5 brief 第 5 项）：摊薄（迷你库 vs 全量库）与 `retrieval_rrf_constant`
两档。所有数字旁都印一条可复现命令（plan 6b-4：复现不出来的数字不得进报告）。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_config
from app.retrieval.calibrate import (
    DEFAULT_TOP_K,
    DevItem,
    load_devset,
    sweep_thresholds,
    write_threshold,
)
from app.retrieval.local import LocalBackend, default_index_dir
from app.retrieval.textmatch import contains_fact


@dataclass
class Metrics:
    label: str
    hit1: int = 0
    hit3: int = 0
    hit8: int = 0
    mrr: float = 0.0
    covered: int = 0
    total: int = 0

    def as_row(self) -> dict[str, object]:
        denom = self.total or 1
        return {
            "口径": self.label,
            "题数": self.total,
            "Hit@1": round(self.hit1 / denom, 4),
            "Hit@3": round(self.hit3 / denom, 4),
            "Hit@8": round(self.hit8 / denom, 4),
            "MRR": round(self.mrr / denom, 4),
            "覆盖率": round(self.covered / denom, 4),
        }


def evaluate(
    index: LocalBackend,
    items: list[DevItem],
    *,
    k: int = DEFAULT_TOP_K,
    label: str = "全量库",
    restrict: dict[int, set[int]] | None = None,
) -> Metrics:
    """跑一批可答题，算三指标 + 覆盖率。

    `restrict`：`{claim_id: 允许的 claim_id 集合}`，用于摊薄对照的「迷你库」口径——
    把候选限制在该题相关单元内，观察「名额被无关块分走」造成的差距（plan 6c）。
    """
    metrics = Metrics(label=label, total=len(items))
    docs_text = {d["claim_id"]: d["text"] for d in index.documents()}
    for item in items:
        if restrict is not None and item.expected_claim_ids:
            allowed = restrict.get(item.expected_claim_ids[0], set())
            hits = index.search_bm25_only(item.question, k=k, claim_ids=allowed)
        else:
            hits = index.search(item.question, k=k, rerank=False)
        ids = [hit.claim_id for hit in hits]
        expected = set(item.expected_claim_ids)
        rank = next((i for i, cid in enumerate(ids, start=1) if cid in expected), None)
        if rank is not None:
            metrics.hit8 += 1
            if rank <= 3:
                metrics.hit3 += 1
            if rank == 1:
                metrics.hit1 += 1
            metrics.mrr += 1.0 / rank
        evidence = " ".join(docs_text.get(cid, "") for cid in ids)
        if item.expected_key_fact and contains_fact(evidence, item.expected_key_fact):
            metrics.covered += 1
    return metrics


def build_restrict(index_path_db: Path) -> dict[int, set[int]]:
    """按「同一卡片内的全部条目」构造迷你库口径（与该题相关的单元集合）。"""
    import sqlite3

    mapping: dict[int, set[int]] = {}
    with sqlite3.connect(index_path_db) as conn:
        for claim_id, card_id in conn.execute("SELECT claim_id, card_id FROM claims").fetchall():
            mapping[claim_id] = {cid for cid, c in conn.execute(
                "SELECT claim_id, card_id FROM claims WHERE card_id = ?", (card_id,)
            ).fetchall()}
    return mapping


def _print_table(rows: list[dict[str, object]]) -> None:
    headers = list(rows[0].keys())
    widths = {h: max(len(str(h)), *(len(str(r[h])) for r in rows)) for h in headers}
    print(" | ".join(h.ljust(widths[h]) for h in headers))
    print("-+-".join("-" * widths[h] for h in headers))
    for row in rows:
        print(" | ".join(str(row[h]).ljust(widths[h]) for h in headers))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RedTrace 检索层评测（只跑检索、不调模型）")
    parser.add_argument("--devset", default=str(BACKEND_ROOT / "data" / "开发集-100题.csv"))
    parser.add_argument("--db", default=None, help="SQLite 主库（默认 Config.data_dir/redtrace.db）")
    parser.add_argument("--out", default=None, help="索引目录（默认 Config.data_dir/index）")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--rrf", type=int, default=None, help="覆盖 retrieval_rrf_constant（扫档用）")
    parser.add_argument("--block-mode", default=None, choices=["single", "merged"])
    parser.add_argument("--rerank-backend", default="off", choices=["api", "local_lexical", "off"])
    parser.add_argument("--calibrate", action="store_true", help="标定拒答阈值并写 threshold.json")
    parser.add_argument("--minimal", action="store_true", help="同时给出摊薄对照（迷你库口径）")
    args = parser.parse_args(argv)

    config = get_config()
    if args.rrf is not None:
        config = config.model_copy(update={"retrieval_rrf_constant": args.rrf})
    index_dir = Path(args.out) if args.out else default_index_dir(config)
    db_path = Path(args.db) if args.db else Path(config.data_dir) / "redtrace.db"
    if args.block_mode is not None:
        config = config.model_copy(update={"block_mode": args.block_mode})

    reranker = None
    if args.rerank_backend != "off":
        from app.retrieval.rerank import build_reranker

        reranker = build_reranker(config.model_copy(update={"rerank_backend": args.rerank_backend}))

    backend = LocalBackend(
        config=config,
        db_path=db_path,
        index_dir=index_dir,
        block_mode=args.block_mode or "single",
        reranker=reranker,
    )
    try:
        backend.ensure_ready()
    except Exception as exc:  # noqa: BLE001 - 过期/缺失都要给出可执行的下一步
        print(f"索引不可用：{exc}")
        print("提示：先跑 `python scripts/build_index.py --rebuild`；换了 block_mode 必须重建。")
        return 2

    devset = load_devset(args.devset)
    answerable = [item for item in devset if item.answerable]
    print(f"开发集：可答 {len(answerable)} 题 / 不可答 {len(devset) - len(answerable)} 题 → {args.devset}")
    print(
        f"索引：{backend.doc_count} 条，block_mode={backend.block_mode}，"
        f"rrf={config.retrieval_rrf_constant}，稠密/稀疏 top={config.retrieval_dense_top_k}/"
        f"{config.retrieval_sparse_top_k}，重排={backend.rerank_note()}"
    )

    rows = [evaluate(backend, answerable, k=args.k).as_row()]
    if args.minimal:
        restrict = build_restrict(db_path)
        rows.append(
            evaluate(
                backend, answerable, k=args.k, label="迷你库（仅相关单元·稀疏口径）", restrict=restrict
            ).as_row()
        )
    _print_table(rows)

    if args.calibrate:
        calibration = sweep_thresholds(backend, devset, k=args.k)
        path = write_threshold(backend, calibration, index_dir)
        print(f"\n阈值标定：tau={calibration.tau}（可分性：{calibration.separability()['可分性']}）")
        print("曲线（节选 0.05 步长）：")
        for row in calibration.sweep[::5]:
            print(f"  {row.as_row()}")
        print(f"已写入 {path}")
        if calibration.separability()["可分性"] == "重叠":
            print(
                "[警告] 两类分数区间重叠：tau 无法把可答与不可答完全分开。"
                "按 5.19 不放宽断言，请据上表分布决定补采语料或换检索口径。"
            )

    print("\n复现命令：")
    print(f"  cd backend && python scripts/eval_retrieval.py --k {args.k}"
          + (f" --rrf {args.rrf}" if args.rrf else "")
          + (" --minimal" if args.minimal else "")
          + (" --calibrate" if args.calibrate else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
