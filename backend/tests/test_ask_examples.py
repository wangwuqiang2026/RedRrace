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


def test_source_texts_use_full_text_not_block_fragments(tmp_path):
    """parsed 产物有 full_text（完整原文）：逐字定位必须读它，不能只用 blocks 拼（smoke 实测缺口）。

    真实数据里引文「自1934年10月起…」在 full_text 里命中，但按 blocks[].text 拼接后丢失
    （块边界切断），导致第二层校验误判 quote_not_found、真模型答案被全部剔除→永远拒答。
    """
    import json

    from app.qa.pipeline import _load_source_texts

    parsed = tmp_path / "parsed"
    parsed.mkdir()
    (parsed / "S001.json").write_text(
        json.dumps({
            "source_id": "S001",
            "full_text": "开头。自1934年10月起，各路红军被迫相继开启战略大转移。结尾。",
            "blocks": [{"text": "开头。"}, {"text": "结尾。"}],  # 故意不含引文
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    texts = _load_source_texts([_evidence_for_source("S001")], tmp_path)
    assert texts is not None and 1 in texts
    assert "自1934年10月起，各路红军被迫相继开启战略大转移" in texts[1]


def _evidence_for_source(sid: str):
    from app.qa.evidence import Evidence
    from app.qa.schemas import Locator, SourceOut

    src = SourceOut(
        source_id=sid, title="校史", publisher="人民出版社", publish_date="1985",
        url_or_path="data/raw/articles/S001.html", access_date="2026-11-13",
        license_note="公开", corpus_tier="核心", media_type="文章",
    )
    return Evidence(
        claim_id=1, card_id=1, source_id=sid, subject="某校", predicate="创设时间",
        value="一九二五年", quote="自1934年10月起，各路红军被迫相继开启战略大转移", score=0.8,
        source=src, locator=Locator(quote="自1934年10月起，各路红军被迫相继开启战略大转移"),
    )


def test_pipeline_upgrades_legacy_v1_db_before_writing_logs(tmp_path):
    """真实试点库是 V1 建的：流水线写审计列前须自动跑 V2 迁移（幂等），否则 OperationalError。

    这是 smoke 实测暴露的部署缺口：本地测试库都经 migrate() 到 V2，但生产库停留在 V1。
    """
    import sqlite3 as sq

    from app.db.migrate import SCHEMA_VERSION, current_version, migrate

    db = tmp_path / "legacy.db"
    # 手工建一个只有 V1 的库，再删掉版本表里的 V2 记录（模拟旧库）
    migrate(db)
    with sq.connect(db) as conn:
        conn.execute("DELETE FROM schema_version WHERE version = 2")
        for col in ("retrieved_count", "top_score", "threshold", "gate_note"):
            conn.execute(f"ALTER TABLE qa_logs DROP COLUMN {col}")
    assert current_version(db) == 1
    out = answer_question(AskRequest(question="某校何时创设？"), db_path=db,
                          index=FakeIndex([hit()]), model=FakeModel(),
                          threshold=0.41, data_dir=tmp_path)
    # 空库走拒答路径也要能写日志（不再 OperationalError）
    assert out.refusal is True
    assert current_version(db) == SCHEMA_VERSION
    with sq.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM qa_logs").fetchone()[0]
    assert count == 1, "拒答也要落一条问答日志"


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
