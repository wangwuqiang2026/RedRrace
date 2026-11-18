"""拒答阈值标定（阶段二 T5，plan 步骤 5 / 6 / 6b）。

三条被守住的纪律：
1. **可分性断言必须能因分布变化而失败**（规范 5.19）：`min(可答) > tau > max(不可答)` 写成一条
   断言并打印 tau，不接受「tau 在合理区间」这种永真式。
2. **阈值文件不能只有数字**（规范 6.12、D12）：换语料 / 换切块 / 换融合参数 / 换向量配置后
   读旧阈值必须报错，而不是照用。
3. **闸门只认 `Hit.score`**（4.6）：标定不因开不开重排而变。

本文件用替身索引（不联网、不建真索引，5.17）；真实语料上的标定结果进 `docs/评测报告.md`。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.retrieval.backend import Hit, IndexStats
from app.retrieval.calibrate import (
    DevItem,
    ThresholdStaleError,
    calibrated_threshold,
    load_devset,
    max_gate_score,
    sweep_thresholds,
    write_threshold,
)


class FakeSignature:
    def __init__(self, digest: str = "sig-1") -> None:
        self.digest = digest

    def as_dict(self) -> dict:
        return {"digest": self.digest, "model": "fake", "text_types": ["document", "query"]}


class FakeIndex:
    """按题面哈希给一个稳定的相似度分数；`None` 表示该题没有任何带相似度的候选。"""

    def __init__(self, scores: dict[str, float | None], *, fingerprint: str = "fp-1",
                 rrf: int = 60, sig: str = "sig-1") -> None:
        self._scores = scores
        self._fingerprint = fingerprint
        self._sig = FakeSignature(sig)
        self.block_mode = "single"
        self.doc_count = 10
        self.cfg = type(
            "Cfg", (), {"retrieval_dense_top_k": 30, "retrieval_sparse_top_k": 30,
                        "retrieval_rrf_constant": rrf}
        )()
        self.search_calls = 0

    def search(self, query: str, k: int, *, rerank: bool = True) -> list[Hit]:
        self.search_calls += 1
        score = self._scores.get(query)
        if score is None:
            return []
        return [
            Hit(
                claim_id=1,
                card_id=1,
                score=score,
                dense_score=score,
                sparse_score=None,
                rerank_score=None,
            )
        ]

    def corpus_fingerprint(self) -> str:
        return self._fingerprint

    def vector_signature(self) -> FakeSignature:
        return self._sig

    def documents(self) -> list[dict]:
        return [{"claim_id": 1, "text": "正文"}]

    def index_stats(self) -> IndexStats:
        return IndexStats(dense_hits=1, sparse_hits=1, total_docs=10, index_built=True)


def devset_of(answerable: dict[str, float], unanswerable: dict[str, float]) -> list[DevItem]:
    items = [
        DevItem(qid=f"A{i}", question=q, answerable=True, expected_claim_ids=(1,), expected_key_fact="正文")
        for i, q in enumerate(answerable, 1)
    ]
    items += [DevItem(qid=f"U{i}", question=q, answerable=False) for i, q in enumerate(unanswerable, 1)]
    return items


def test_threshold_separates_answerable_and_not(tmp_path):
    """plan 步骤 5 的原文形态：可分的数据上 `min(可答) > tau > max(不可答)`。"""
    answerable = {f"可答{i}": 0.70 + i * 0.01 for i in range(10)}
    unanswerable = {f"不可答{i}": 0.30 + i * 0.01 for i in range(10)}
    index = FakeIndex({**answerable, **unanswerable})
    calibration = sweep_thresholds(index, devset_of(answerable, unanswerable))
    tau = calibration.tau
    ans = [max_gate_score(index, q) for q in answerable]
    un = [max_gate_score(index, q) for q in unanswerable]
    assert min(ans) > tau > max(un), f"阈值 {tau} 未把两类分开（可答最低 {min(ans)} / 不可答最高 {max(un)}）"
    assert calibration.separability()["可分性"] == "可分"


def test_threshold_never_rejects_answerable_when_separable(tmp_path):
    """选点规则：可答误拒必须为 0（宁可少拒也不误拒——误拒会把能答的问题拒掉）。"""
    answerable = {f"可答{i}": 0.62 + i * 0.01 for i in range(5)}
    unanswerable = {f"不可答{i}": 0.20 + i * 0.02 for i in range(5)}
    calibration = sweep_thresholds(FakeIndex({**answerable, **unanswerable}), devset_of(answerable, unanswerable))
    chosen = next(row for row in calibration.sweep if row.tau == calibration.tau)
    assert chosen.answerable_rejected == 0
    assert chosen.unanswerable_reject_rate == 1.0, "可分数据上应能拒掉全部不可答题"


def test_overlapping_distribution_is_reported_not_hidden():
    """分布重叠时不许假装达标：`可分性` 必须如实报「重叠」（规范 5.19、8.12）。"""
    answerable = {f"可答{i}": 0.40 + i * 0.01 for i in range(5)}
    unanswerable = {f"不可答{i}": 0.45 + i * 0.01 for i in range(5)}
    calibration = sweep_thresholds(FakeIndex({**answerable, **unanswerable}), devset_of(answerable, unanswerable))
    assert calibration.separability()["可分性"] == "重叠"


def test_calibration_requires_both_classes():
    """只有一类题的开发集不能标定（任何阈值都能「全拒」或「全放」）。"""
    with pytest.raises(ValueError, match="两类题必须都有"):
        sweep_thresholds(FakeIndex({}), [DevItem(qid="A1", question="q", answerable=True)])


def test_question_without_similarity_counts_as_rejected():
    """没有相似度的题按「低于任何阈值」处理：没有可比证据就不得放行（4.7 同源）。"""
    answerable = {"可答0": 0.80}
    unanswerable = {"不可答0": None}
    calibration = sweep_thresholds(FakeIndex({"可答0": 0.80, "不可答0": None}),
                                   devset_of(answerable, unanswerable))
    assert calibration.separability()["不可答题无相似度"] == 1
    assert calibration.separability()["可分性"] == "可分"


def test_threshold_file_carries_conditions(tmp_path):
    """阈值文件必须自带标定条件（模型、维度、text_type、融合参数、两个指纹），否则数字无效。"""
    answerable = {"可答0": 0.8}
    unanswerable = {"不可答0": 0.2}
    index = FakeIndex({"可答0": 0.8, "不可答0": 0.2})
    calibration = sweep_thresholds(index, devset_of(answerable, unanswerable))
    path = write_threshold(index, calibration, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "threshold.json"
    assert payload["tau"] == pytest.approx(calibration.tau)
    conditions = payload["conditions"]
    for key in (
        "corpus_fingerprint",
        "vector_signature",
        "retrieval_dense_top_k",
        "retrieval_sparse_top_k",
        "retrieval_rrf_constant",
        "block_mode",
        "top_k",
    ):
        assert key in conditions, f"阈值文件缺少标定条件 {key}：无条件的阈值数字视为无效（6.12）"
    assert payload["curve"], "曲线必须随阈值一起落盘，否则无法复盘选点依据"


def test_calibrated_threshold_rejects_changed_corpus(tmp_path):
    """语料指纹变了 → 旧阈值报错，而不是照用（4.9）。"""
    answerable = {"可答0": 0.8}
    unanswerable = {"不可答0": 0.2}
    index = FakeIndex({"可答0": 0.8, "不可答0": 0.2})
    calibration = sweep_thresholds(index, devset_of(answerable, unanswerable))
    write_threshold(index, calibration, tmp_path)
    changed = FakeIndex({"可答0": 0.8, "不可答0": 0.2}, fingerprint="fp-2")
    with pytest.raises(ThresholdStaleError, match="条件与当前索引不符"):
        calibrated_threshold(tmp_path, index=changed)


def test_calibrated_threshold_rejects_changed_vector_signature(tmp_path):
    """向量配置签名变了（换模型/改 text_type）→ 旧阈值报错（007 第四节）。"""
    answerable = {"可答0": 0.8}
    unanswerable = {"不可答0": 0.2}
    index = FakeIndex({"可答0": 0.8, "不可答0": 0.2})
    calibration = sweep_thresholds(index, devset_of(answerable, unanswerable))
    write_threshold(index, calibration, tmp_path)
    changed = FakeIndex({"可答0": 0.8, "不可答0": 0.2}, sig="sig-2")
    with pytest.raises(ThresholdStaleError, match="向量配置签名"):
        calibrated_threshold(tmp_path, index=changed)


def test_calibrated_threshold_requires_file(tmp_path):
    """没有阈值文件时明确报错并给出标定命令，不返回默认值（8.15）。"""
    with pytest.raises(ThresholdStaleError, match="阈值文件不存在"):
        calibrated_threshold(tmp_path)


def test_calibration_is_independent_of_rerank_flag():
    """标定只走 `search(..., rerank=False)`：闸门尺子不受重排影响（4.6）。"""
    index = FakeIndex({"可答0": 0.8, "不可答0": 0.2})
    sweep_thresholds(index, devset_of({"可答0": 0.8}, {"不可答0": 0.2}))
    assert index.search_calls == 2, "标定应当只对每题取一次分（可答 + 不可答各一次）"


def test_devset_loads_100_items_with_both_classes():
    """仓库里的开发集本身要合格：100 题、两类各半、可答题带期望条目（plan 6 的口径）。"""
    path = Path(__file__).resolve().parents[1] / "data" / "开发集-100题.csv"
    items = load_devset(path)
    answerable = [item for item in items if item.answerable]
    assert len(items) == 100 and len(answerable) == 50
    assert all(item.expected_claim_ids for item in answerable), "可答题必须绑定期望事实条目"
    assert all(not item.expected_claim_ids for item in items if not item.answerable)
