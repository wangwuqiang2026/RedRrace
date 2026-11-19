"""阶段三 T3-6：端到端问答流水线（plan 步骤 1/3b/5/6）。

钉死最危险失败模式：默认路径必须真的走到检索（参考实现的 `default()` 不在可选项集、
用户 id 哨兵 -1 两条都落到「空文档列表 → 跳过检索」，模型凭预训练知识作答，
语气专业、格式完整，只有引用栏空）。本文件所有用例都不发真实 LLM 请求（5.17）。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient
from helpers import VALID_ROW

from app.db.migrate import migrate
from app.main import app
from app.qa.pipeline import answer_question
from app.qa.schemas import AskRequest
from app.retrieval.backend import Hit


class FakeModel:
    def __init__(self, draft="某校于一九二五年创设[1]。"):
        self.draft = draft
        self.calls = 0

    def generate(self, question, evidence):
        self.calls += 1
        return self.draft


class FakeIndex:
    """返回固定 Hit：用于验证流水线读的是检索结果，而不是模型记忆。"""

    def __init__(self, hits):
        self.hits = hits
        self.calls = 0

    def search(self, question, k, *, rerank=True):
        self.calls += 1
        return self.hits


@pytest.fixture
def seeded_db(tmp_path):
    db = tmp_path / "qa.db"
    migrate(db)
    with sqlite3.connect(db) as conn:
        row = {**VALID_ROW, "source_id": "S001", "title": "某校简史", "media_type": "文章",
               "url_or_path": "data/raw/articles/S001.html"}
        conn.execute(
            "INSERT INTO sources (source_id,title,publisher,publish_date,url_or_path,access_date,"
            "license_note,corpus_tier,media_type,verified) VALUES (?,?,?,?,?,?,?,?,?,1)",
            tuple(row[k] for k in ("source_id", "title", "publisher", "publish_date", "url_or_path",
                                   "access_date", "license_note", "corpus_tier", "media_type")),
        )
        conn.execute("INSERT INTO cards (card_id,source_id,type,name,summary) VALUES (1,'S001','event','某校','1925年创设')")
        conn.execute(
            "INSERT INTO claims (claim_id,card_id,source_id,subject,predicate,value,quote,locator,confidence) "
            "VALUES (1,1,'S001','某校','创设时间','一九二五年','该校于一九二五年创设',?,0.95)",
            ('{"heading_path":["沿革"]}',),
        )
    return db, tmp_path


def hit(claim_id=1, score=0.8):
    return Hit(claim_id=claim_id, card_id=1, score=score, dense_score=score,
               sparse_score=None, rerank_score=None)


def test_default_request_really_calls_retrieval_and_cites(seeded_db):
    """最默认请求（不带任何可选字段）：citations 非空、verified、`retrieved_count > 0`。"""
    db, root = seeded_db
    index = FakeIndex([hit()])
    model = FakeModel()
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db, index=index,
                          model=model, threshold=0.41, data_dir=root)
    assert index.calls == 1, "默认路径跳过了检索"
    assert out.retrieved_count == 1 and out.top_score == 0.8
    assert out.citations and all(c.verified for c in out.citations)
    assert not out.refusal


def test_answer_contains_verified_citation_with_title_and_locator(seeded_db):
    """步骤 1 的形态：出处有来源标题，且文章载体有 heading_path，引文非空。"""
    db, root = seeded_db
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                          index=FakeIndex([hit()]), model=FakeModel(),
                          threshold=0.41, data_dir=root)
    c = out.citations[0]
    assert c.source.title == "某校简史"
    assert c.locator.heading_path == ["沿革"] and c.locator.quote


def test_answer_survives_reindex(seeded_db):
    """重建索引后（换个临时 data_dir 与库），出处回链目标仍存在（步骤 4b）。"""
    db, root = seeded_db
    rebuilt = root / "rebuilt"
    (rebuilt / "parsed").mkdir(parents=True)
    (rebuilt / "parsed" / "S001.json").write_text("{}", encoding="utf-8")
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                          index=FakeIndex([hit()]), model=FakeModel(),
                          threshold=0.41, data_dir=rebuilt)
    assert out.citations
    assert (rebuilt / "parsed" / f"{out.citations[0].source.source_id}.json").exists()


def test_refusal_never_calls_llm(seeded_db):
    db, root = seeded_db
    model = FakeModel()
    out = answer_question(AskRequest(question="知识库里没有的人物是谁？"), db_path=db,
                          index=FakeIndex([]), model=model, threshold=0.41, data_dir=root)
    assert out.refusal is True and out.refusal_reason == "no_evidence"
    assert model.calls == 0, "拒答路径仍在调用模型"


def test_low_score_refusal_carries_audit_numbers(seeded_db):
    db, root = seeded_db
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                          index=FakeIndex([hit(score=0.2)]), model=FakeModel(),
                          threshold=0.41, data_dir=root)
    assert out.refusal is True and out.refusal_reason == "not_covered"
    assert out.retrieved_count == 1 and out.top_score == 0.2 and out.threshold == 0.41
    assert "0.20" in out.gate_note and "0.41" in out.gate_note


def test_all_claims_rejected_turns_into_refusal(seeded_db):
    db, root = seeded_db
    model = FakeModel(draft="完全捏造的事情[9]。")
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                          index=FakeIndex([hit()]), model=model, threshold=0.41, data_dir=root)
    assert out.refusal is True and out.refusal_reason == "all_claims_rejected"
    assert out.answer == ""


def test_v2_migration_adds_audit_columns(tmp_path):
    """阶段三闸门审计字段入 qa_logs：V2 迁移必须给旧库补齐四列（可重跑）。"""
    from app.db.migrate import current_version, migrate

    db = tmp_path / "old.db"
    migrate(db)
    assert current_version(db) == 2
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(qa_logs)").fetchall()}
    assert {"retrieved_count", "top_score", "threshold", "gate_note"} <= cols
    migrate(db)  # 幂等
    assert current_version(db) == 2


def test_qa_log_written_with_prompt_version(seeded_db):
    db, root = seeded_db
    answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                    index=FakeIndex([hit()]), model=FakeModel(), threshold=0.41, data_dir=root)
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT question, refused, prompt_version FROM qa_logs").fetchone()
    assert row is not None and row[1] == 0 and row[2]


def test_router_returns_real_answer_not_501(seeded_db, monkeypatch):
    """router 注入同一条流水线：默认请求出真答案（不再 501）。"""
    db, root = seeded_db
    from app.qa import router as qa_router

    def fake_answer(request, **kwargs):
        return answer_question(request, db_path=db, index=FakeIndex([hit()]),
                               model=FakeModel(), threshold=0.41, data_dir=root)

    monkeypatch.setattr(qa_router, "answer_question", fake_answer)
    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "某校何时创设？"})
    assert resp.status_code == 200
    assert resp.json()["citations"] and resp.json()["refusal"] is False
