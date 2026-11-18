"""拒答阈值标定（阶段二 T5，plan 步骤 5 / 6 / 6b）。

一个数决定阶段三「答还是不答」，所以这个文件的三条纪律比代码量重要：

1. **闸门只认 `Hit.score`**（可跨请求比较的稠密相似度）。`rerank_score` 官方明示「本次请求的
   相对分数、不可跨请求比较」，永不参与阈值比较（规范 4.6、决策记录 006 硬约束 1）。
2. **阈值不是拍的，是扫一条曲线选点**：`阈值 → 不可答题正确拒答率 / 可答题误拒率`，
   在可答误拒保持 0% 的一侧取拒答率最高的工作点（plan 6b-2）。扫描带 0.40–0.60
   **是本项目的起点，不是沿用参考实现的 0.45**（禁止清单 8.12）。
3. **阈值文件必须自带标定条件**（规范 6.12、D12）：模型名、维度、`text_type` 两侧组合、
   融合参数、top-k、生成时间、两个指纹。**无条件的阈值数字视为无效**——换模型即换相似度
   分布（007 第四节实测 mean 0.3945 → 0.4694），拿着旧数字继续用等于拒答判定静默失真。
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

THRESHOLD_FILENAME = "threshold.json"
DEFAULT_SWEEP_LO = 0.40
DEFAULT_SWEEP_HI = 0.60
DEFAULT_SWEEP_STEP = 0.01
DEFAULT_TOP_K = 8


@dataclass(frozen=True)
class DevItem:
    """开发集一题。可答题必须带 `expected_claim_ids`；不可答题两者皆空。"""

    qid: str
    question: str
    answerable: bool
    expected_claim_ids: tuple[int, ...] = ()
    expected_key_fact: str = ""
    card_type: str = ""
    note: str = ""


def load_devset(path: str | Path) -> list[DevItem]:
    """读开发集 CSV（`encoding="utf-8-sig"`，规范 5.14：禁止手工拆行）。"""
    items: list[DevItem] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            raw_ids = (row.get("expected_claim_ids") or "").strip()
            ids = tuple(int(part) for part in raw_ids.replace("|", ",").split(",") if part.strip())
            items.append(
                DevItem(
                    qid=row["qid"].strip(),
                    question=row["question"].strip(),
                    answerable=row.get("answerable", "0").strip() == "1",
                    expected_claim_ids=ids,
                    expected_key_fact=(row.get("expected_key_fact") or "").strip(),
                    card_type=(row.get("card_type") or "").strip(),
                    note=(row.get("note") or "").strip(),
                )
            )
    if not items:
        raise ValueError(f"开发集为空：{path}（阈值标定必须有题，空集标出来的任何 tau 都是假的）")
    return items


def max_gate_score(index: Any, question: str, *, k: int = DEFAULT_TOP_K) -> float | None:
    """一题在检索结果里的最高综合分（闸门判定用的那把尺子）。

    返回 `None` 表示该题没有任何候选带相似度（例如全走 BM25 命中）——这种题在阈值曲线上
    按「低于任何阈值」处理，即**会被拒答**。这是有意的：没有相似度就没有可比证据，
    放行等于用关键词巧合回答问题（4.7 的同源顾虑）。
    """
    hits = index.search(question, k, rerank=False)
    scores = [h.score for h in hits if h.score is not None]
    return max(scores) if scores else None


@dataclass(frozen=True)
class SweepRow:
    tau: float
    answerable_rejected: int
    answerable_total: int
    unanswerable_rejected: int
    unanswerable_total: int

    @property
    def unanswerable_reject_rate(self) -> float:
        return self.unanswerable_rejected / self.unanswerable_total if self.unanswerable_total else 0.0

    @property
    def answerable_misreject_rate(self) -> float:
        return self.answerable_rejected / self.answerable_total if self.answerable_total else 0.0

    def as_row(self) -> dict[str, Any]:
        return {
            "tau": round(self.tau, 4),
            "不可答题正确拒答率": round(self.unanswerable_reject_rate, 4),
            "可答题误拒率": round(self.answerable_misreject_rate, 4),
            "可答题误拒数": f"{self.answerable_rejected}/{self.answerable_total}",
            "不可答题正确拒答数": f"{self.unanswerable_rejected}/{self.unanswerable_total}",
        }


@dataclass
class Calibration:
    """一次标定的完整产物（阈值文件内容 + 内存里的曲线）。"""

    tau: float
    sweep: list[SweepRow] = field(default_factory=list)
    conditions: dict[str, Any] = field(default_factory=dict)
    answerable_scores: list[float | None] = field(default_factory=list)
    unanswerable_scores: list[float | None] = field(default_factory=list)

    def separability(self) -> dict[str, Any]:
        """两类分数的实测分布（分不开时这是唯一有诊断价值的证据，plan 6b-2）。"""
        ans = [s for s in self.answerable_scores if s is not None]
        un = [s for s in self.unanswerable_scores if s is not None]

        def stat(values: list[float]) -> dict[str, Any]:
            if not values:
                return {"n": 0, "min": None, "max": None, "mean": None}
            return {
                "n": len(values),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(sum(values) / len(values), 4),
            }

        if not ans and not un:
            verdict = "重叠"
        elif not un:
            # 不可答题一个带相似度的都没有：它们会被任何正阈值拒掉，属「可分」的极端形态。
            verdict = "可分"
        elif not ans:
            verdict = "重叠"
        else:
            verdict = "可分" if min(ans) > max(un) else "重叠"
        return {
            "可答题": stat(ans),
            "不可答题": stat(un),
            "可答题无相似度": sum(1 for s in self.answerable_scores if s is None),
            "不可答题无相似度": sum(1 for s in self.unanswerable_scores if s is None),
            "可分性": verdict,
        }


def sweep_thresholds(
    index: Any,
    devset: Iterable[DevItem],
    *,
    lo: float = DEFAULT_SWEEP_LO,
    hi: float = DEFAULT_SWEEP_HI,
    step: float = DEFAULT_SWEEP_STEP,
    k: int = DEFAULT_TOP_K,
) -> Calibration:
    """扫描阈值并选工作点：可答误拒 0% 的一侧里，不可答题拒答率最高的那个 tau。

    扫描带默认 0.40–0.60（plan 6b-2）。**不采用参考实现的 0.45**：那是它语料上的最优工作点
    （借鉴边界 2 明说数字只作方法学起点）。本项目 mini 语料自测的相关对落在 0.70–0.75、
    无关对均值 0.39，所以这条带覆盖得住；全量语料上若最优落在带外，`sweep_thresholds` 会
    如实返回带内的最佳点并把「带边界触顶」写进 conditions，交由人决定是否扩带。
    """
    items = list(devset)
    answerable = [item for item in items if item.answerable]
    unanswerable = [item for item in items if not item.answerable]
    if not answerable or not unanswerable:
        raise ValueError(
            f"开发集两类题必须都有（可答 {len(answerable)} / 不可答 {len(unanswerable)}）："
            "只有一类时任何阈值都能『全拒』或『全放』，标定没有意义（规范 5.19 反对的永真式）"
        )
    ans_scores = [max_gate_score(index, item.question, k=k) for item in answerable]
    un_scores = [max_gate_score(index, item.question, k=k) for item in unanswerable]

    rows: list[SweepRow] = []
    steps = round((hi - lo) / step) + 1
    for i in range(steps):
        tau = round(lo + i * step, 4)
        ans_rejected = sum(1 for score in ans_scores if score is None or score < tau)
        un_rejected = sum(1 for score in un_scores if score is None or score < tau)
        rows.append(SweepRow(tau, ans_rejected, len(ans_scores), un_rejected, len(un_scores)))

    zero_misreject = [row for row in rows if row.answerable_rejected == 0]
    chosen = max(zero_misreject, key=lambda r: (r.unanswerable_reject_rate, r.tau)) if zero_misreject else max(
        rows, key=lambda r: (r.unanswerable_reject_rate, -r.answerable_misreject_rate, r.tau)
    )
    conditions = {
        "top_k": k,
        "sweep": {"lo": lo, "hi": hi, "step": step},
        "selection_rule": "可答误拒 0% 一侧取不可答拒答率最高",
        "bounded_by_sweep": bool(zero_misreject) and chosen.tau in (rows[0].tau, rows[-1].tau),
    }
    return Calibration(
        tau=chosen.tau,
        sweep=rows,
        conditions=conditions,
        answerable_scores=ans_scores,
        unanswerable_scores=un_scores,
    )


def _index_conditions(index: Any) -> dict[str, Any]:
    """从索引侧取标定条件：两个指纹 + 生效的向量配置 + 融合参数（D12、6.12）。"""
    signature = getattr(index, "vector_signature", None)
    sig = signature() if callable(signature) else None
    cfg = getattr(index, "cfg", None)
    return {
        "corpus_fingerprint": index.corpus_fingerprint() if hasattr(index, "corpus_fingerprint") else None,
        "vector_signature": sig.as_dict() if sig is not None and hasattr(sig, "as_dict") else None,
        "retrieval_dense_top_k": getattr(cfg, "retrieval_dense_top_k", None),
        "retrieval_sparse_top_k": getattr(cfg, "retrieval_sparse_top_k", None),
        "retrieval_rrf_constant": getattr(cfg, "retrieval_rrf_constant", None),
        "block_mode": getattr(index, "block_mode", None),
        "doc_count": getattr(index, "doc_count", None),
    }


def write_threshold(index: Any, calibration: Calibration, index_dir: str | Path) -> Path:
    """把阈值与**它的标定条件**一起落盘（`data/index/threshold.json`，D12）。"""
    payload = {
        "tau": calibration.tau,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "conditions": {**_index_conditions(index), **calibration.conditions},
        "separability": calibration.separability(),
        "curve": [row.as_row() for row in calibration.sweep],
    }
    path = Path(index_dir) / THRESHOLD_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class ThresholdStaleError(RuntimeError):
    """阈值文件的条件与当前索引不符（换模型/换切块/换语料后沿用旧阈值）。"""


def calibrated_threshold(index_dir: str | Path | None = None, *, index: Any | None = None) -> float:
    """读回标定阈值，并核对它与当前索引是否同一套条件。

    为什么要核对：阈值是相似度尺子上的刻度，而尺子会因换模型、改 `text_type`、换切块、
    改语料而变（007 第四节实测同一模型两种 `text_type` 组合 mean 0.3945 → 0.4694）。
    无条件直接读数字，就是让拒答判定在换档后静默失真（规范 4.9）。
    """
    from app.core.config import get_config
    from app.retrieval.local import default_index_dir

    directory = Path(index_dir) if index_dir is not None else default_index_dir(get_config())
    path = directory / THRESHOLD_FILENAME
    if not path.is_file():
        raise ThresholdStaleError(
            f"阈值文件不存在：{path}。请先标定："
            "`python scripts/eval_retrieval.py --calibrate --out data/index`"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    tau = payload.get("tau")
    if not isinstance(tau, (int, float)):
        raise ThresholdStaleError(f"阈值文件缺少数值 tau：{path}")
    conditions = payload.get("conditions") or {}
    if index is not None:
        current = _index_conditions(index)
        for key in ("corpus_fingerprint", "block_mode", "retrieval_rrf_constant"):
            recorded, actual = conditions.get(key), current.get(key)
            if recorded is not None and actual is not None and recorded != actual:
                raise ThresholdStaleError(
                    f"阈值文件的条件与当前索引不符（{key}: {recorded!r} ≠ {actual!r}）："
                    "换语料 / 换切块 / 改融合参数后必须重标，否则拒答判定按旧刻度执行（4.9、6.12）"
                )
        recorded_sig = (conditions.get("vector_signature") or {}).get("digest")
        actual_sig = (current.get("vector_signature") or {}).get("digest")
        if recorded_sig and actual_sig and recorded_sig != actual_sig:
            raise ThresholdStaleError(
                f"向量配置签名与阈值文件不符（{recorded_sig!r} ≠ {actual_sig!r}）："
                "换模型 / 换维度 / 改 text_type 任一侧都会搬走相似度分布，旧阈值失效（007 第四节）"
            )
    return float(tau)
