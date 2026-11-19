"""阶段三 T3-6：问答流水线装配（plan 步骤 1/3b/5/6）。

顺序（不可调换）：
  检索 → 证据组装 → 拒答判定（空证据/低分直接返回，**不调模型**）→ 受约束生成
  → 三层引用校验 → 全剔除转拒答 → 冲突透传 → AnswerOut + 问答日志。

依赖通过参数注入（`db_path` / `index` / `model` / `threshold` / `data_dir`），装配层
（`router.py`）从 Config 与真实 LocalBackend 构造；测试注入替身，不发真实网络请求（5.17）。
默认路径的硬不变量：`AskRequest` 的空来源范围 = 不限制（`constants.is_unrestricted`），
且 `retrieved_count > 0` 才可继续调用模型（步骤 3b）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.core.config import get_config
from app.qa.citation import verify_answer
from app.qa.constants import PROMPT_VERSION, is_unrestricted
from app.qa.evidence import Evidence, assemble
from app.qa.refusal import GateInput, decide_refusal, gate_explanation
from app.qa.schemas import AnswerOut, AskRequest, Citation, ConflictItem
from app.retrieval.local import LocalBackend, default_index_dir


def _load_source_texts(evidence: list[Evidence], data_dir: Path) -> dict[int, str] | None:
    """第二层「引文逐字定位」用的原文：从持久 parsed/<source_id>.json 读正文。

    文件不存在或没有可抽取正文时返回 None（引文来自条目表，以其自证）；显式 dict 才按查表核。
    """
    texts: dict[int, str] = {}
    for e in evidence:
        path = data_dir / "parsed" / f"{e.source_id}.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        blocks = payload.get("blocks") if isinstance(payload, dict) else None
        if not blocks:
            continue
        text = "\n".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict))
        if text:
            texts[e.claim_id] = text
    return texts or None


def _write_logs(
    db_path: Path,
    request: AskRequest,
    answer: AnswerOut,
    verdicts: list[Any],
) -> None:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO qa_logs (question, refused, refusal_reason, answer, citations, elapsed_ms, "
            "prompt_version, retrieved_count, top_score, threshold, gate_note) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                request.question, int(answer.refusal), answer.refusal_reason, answer.answer,
                json.dumps([c.model_dump(mode="json") for c in answer.citations], ensure_ascii=False),
                answer.elapsed_ms, PROMPT_VERSION, answer.retrieved_count, answer.top_score,
                answer.threshold, answer.gate_note,
            ),
        )
        log_id = cur.lastrowid
        for i, v in enumerate(verdicts, start=1):
            # audit_logs.verdict 的 CHECK 只允许 kept/dropped（阶段一 DDL）；细粒度原因码写进 reason。
            verdict_value = "kept" if v.verdict.value == "kept" else "dropped"
            conn.execute(
                "INSERT INTO audit_logs (log_id, sentence_index, sentence, citation_indexes, verdict, reason) "
                "VALUES (?,?,?,?,?,?)",
                (log_id, i, v.sentence, json.dumps(v.citation_indexes), verdict_value,
                 f"{v.verdict.value}: {v.reason}"),
            )


def _conflicts_for(db_path: Path, evidence: list[Evidence]) -> list[ConflictItem]:
    """阶段三接口占位：返回空冲突组；检测与并列装配属阶段四（预扫描 P3-6）。

    不在本阶段「看见 conflicts 表里有记录就返回一个 ConflictItem」——那会造出未经校验的
    出处并列（两条来源、引文、定位都没按契约装好），比明确留空更危险。阶段四替换本函数即可，
    流水线与 AnswerOut 契约不变。
    """
    return []


def answer_question(
    request: AskRequest,
    *,
    db_path: Path | None = None,
    index: Any | None = None,
    model: Any | None = None,
    threshold: float | None = None,
    data_dir: Path | None = None,
    aliases_path: Path | None = None,
    confirm: bool = False,
) -> AnswerOut:
    """跑一条问答，返回带出处/审计字段的 AnswerOut。"""
    started = time.monotonic()
    cfg = get_config()
    db = Path(db_path) if db_path is not None else cfg.data_dir / "redtrace.db"
    root = Path(data_dir) if data_dir is not None else cfg.data_dir
    backend = index if index is not None else LocalBackend(config=cfg, db_path=db,
                                                            index_dir=default_index_dir(cfg))
    tau = threshold if threshold is not None else 0.41
    qa_model = model if model is not None else _default_model(cfg)

    # 步骤 3b-1：空来源范围 = 不限制；先调用判定函数（测试与流水线共用同一口径），
    # 若将来实现过滤，必须据它决定是否收窄，不得把空集合当成「搜 0 个来源」。
    is_unrestricted(request.source_ids, request.media_types)
    hits = backend.search(request.question, request.top_k, rerank=False)
    evidence = assemble(db, hits)
    decision = decide_refusal(GateInput(
        question=request.question,
        retrieved_count=len(hits),
        top_score=max((h.score for h in hits if h.score is not None), default=None),
        threshold=tau,
        evidence=evidence,
    ), model=qa_model)
    if decision.refuse:
        answer = AnswerOut(
            refusal=True, refusal_reason=decision.reason, answer="", citations=[],
            conflicts=[], suggestions=[], elapsed_ms=0,
            retrieved_count=decision.retrieved_count, top_score=decision.top_score,
            threshold=decision.threshold,
            gate_note=(decision.note + "；" if decision.note else "") + gate_explanation(decision),
        )
        answer.elapsed_ms = int((time.monotonic() - started) * 1000)
        _write_logs(db, request, answer, [])
        return answer

    draft = qa_model.generate(request.question, evidence)
    verified = verify_answer(
        draft, evidence, source_texts=_load_source_texts(evidence, root),
        alias_path=str(aliases_path) if aliases_path else None,
    )
    if verified.all_rejected:
        answer = AnswerOut(
            refusal=True, refusal_reason="all_claims_rejected", answer="", citations=[],
            conflicts=[], suggestions=[], elapsed_ms=0,
            retrieved_count=len(hits), top_score=decision.top_score, threshold=tau,
            gate_note="证据存在但逐句引用校验后无保留句",
        )
        answer.elapsed_ms = int((time.monotonic() - started) * 1000)
        _write_logs(db, request, answer, verified.dropped)
        return answer

    citations: list[Citation] = []
    for item in verified.kept:
        if item.citation is not None:
            citations.append(item.citation)
    answer = AnswerOut(
        refusal=False, refusal_reason=None, answer=verified.answer_text,
        citations=citations, conflicts=_conflicts_for(db, evidence),
        suggestions=[], elapsed_ms=0,
        retrieved_count=len(hits), top_score=decision.top_score, threshold=tau,
        gate_note=decision.note,
    )
    answer.elapsed_ms = int((time.monotonic() - started) * 1000)
    _write_logs(db, request, answer, verified.kept + verified.dropped)
    return answer


def _default_model(cfg: Any) -> Any:
    from app.qa.llm import build_qa_model
    return build_qa_model(cfg)
