"""阶段三 T3-2：证据组装与出处回链（plan 步骤 4b）。

红线条目：回链一律由 `source_id` 现算两个持久路径（解析产物 `data/parsed/<Sxxx>.json`
与原文快照 `data/raw/articles/<Sxxx>.html`），索引/缓存/条目表禁止存绝对路径或临时路径。
重建索引（含写到临时目录）后回链目标必须仍存在，前端不得拿到点开 404 的链接。
"""

from __future__ import annotations

import sqlite3

import pytest
from helpers import VALID_ROW

from app.db.migrate import migrate
from app.qa.evidence import Evidence, assemble, citation_targets
from app.retrieval.backend import Hit


@pytest.fixture
def seeded_db(tmp_path):
    """一个按阶段一 schema 建好、写入两条来源/卡片/事实条目的临时库。"""
    db = tmp_path / "qa.db"
    migrate(db)
    with sqlite3.connect(db) as conn:
        rows = [
            {**VALID_ROW, "source_id": "S001", "media_type": "文章", "title": "某校简史",
             "url_or_path": "data/raw/articles/S001.html"},
            {**VALID_ROW, "source_id": "S002", "media_type": "电子书", "title": "校史读本",
             "url_or_path": "data/raw/ebooks/S002.pdf"},
        ]
        for r in rows:
            conn.execute(
                "INSERT INTO sources (source_id,title,publisher,publish_date,url_or_path,access_date,"
                "license_note,corpus_tier,media_type,verified) VALUES (?,?,?,?,?,?,?,?,?,1)",
                tuple(r[k] for k in ("source_id", "title", "publisher", "publish_date", "url_or_path",
                                     "access_date", "license_note", "corpus_tier", "media_type")),
            )
        conn.execute(
            "INSERT INTO cards (card_id,source_id,type,name,summary) VALUES (1,'S001','event','某校创设','1925 年创设')"
        )
        conn.execute(
            "INSERT INTO cards (card_id,source_id,type,name,summary) VALUES (2,'S002','event','某校沿革','沿革记载')"
        )
        conn.execute(
            "INSERT INTO claims (claim_id,card_id,source_id,subject,predicate,value,quote,locator,confidence) "
            "VALUES (1,1,'S001','某校','创设时间','一九二五年','该校于一九二五年创设',?,0.95)",
            ('{"heading_path":["第一章","沿革"],"paragraph":2}',),
        )
        conn.execute(
            "INSERT INTO claims (claim_id,card_id,source_id,subject,predicate,value,quote,locator,confidence) "
            "VALUES (2,2,'S002','某校','创设时间','一九二六年','本校创立于一九二六年',"
            "'{\"page\":12}',0.92)",
        )
    return db, tmp_path


def hit(claim_id: int, card_id: int, score: float = 0.8) -> Hit:
    return Hit(claim_id=claim_id, card_id=card_id, score=score, dense_score=score,
               sparse_score=None, rerank_score=None)


def test_assemble_reads_claim_source_and_locator_from_db(seeded_db):
    db, _ = seeded_db
    evidence = assemble(db, [hit(1, 1)])
    assert len(evidence) == 1
    e = evidence[0]
    assert isinstance(e, Evidence)
    assert e.claim_id == 1 and e.card_id == 1
    assert e.subject == "某校" and e.predicate == "创设时间" and e.value == "一九二五年"
    assert e.quote == "该校于一九二五年创设"
    assert e.source_id == "S001" and e.source.title == "某校简史"
    assert e.locator.heading_path == ["第一章", "沿革"] and e.locator.paragraph == 2
    assert e.locator.quote == e.quote, "Locator.quote 必须是原文逐字引文，与条目 quote 同源"


def test_assemble_skips_missing_claim_ids_instead_of_fabricating(seeded_db):
    """数据库里没有的 claim_id 不能造一条空证据（依 4.12：宁可少一条也不交半成品）。"""
    db, _ = seeded_db
    evidence = assemble(db, [hit(1, 1), hit(999, 999)])
    assert [e.claim_id for e in evidence] == [1]


def test_citation_targets_are_derived_from_source_id_and_persistent(seeded_db):
    """回链目标由 source_id 现算，指向持久副本；索引/库里不存绝对路径。"""
    db, tmp_path = seeded_db
    evidence = assemble(db, [hit(1, 1), hit(2, 2)])
    targets = citation_targets(evidence, tmp_path)
    assert set(targets) == {1, 2}, "回链映射的键是 claim_id"
    assert targets[1].endswith("S001.json") and targets[2].endswith("S002.json"), "按各自 source_id 现算"
    values = list(targets.values())
    assert all(v.endswith(".json") for v in values), "解析产物是持久副本，必须带扩展名"
    assert all(tmp_path.as_posix() in v.replace("\\", "/") for v in values), "回链锚在 data_dir 下，不随 cwd 漂移"


def test_citation_targets_survive_reindex(seeded_db, tmp_path):
    """重建索引（含写到临时 data_dir）后，回链目标文件仍存在（plan 步骤 4b 逐字形态）。"""
    db, _ = seeded_db
    evidence = assemble(db, [hit(1, 1)])
    # 模拟重建：在另一个临时 data_dir 下重新落盘解析产物
    new_root = tmp_path / "rebuilt"
    (new_root / "parsed").mkdir(parents=True)
    (new_root / "parsed" / "S001.json").write_text("{}", encoding="utf-8")
    targets = citation_targets(evidence, new_root)
    assert targets and all(__import__("pathlib").Path(t).exists() for t in targets.values()), (
        "回链指向了会被删除的工作副本"
    )


def test_ebook_carrier_uses_page_and_article_uses_heading(seeded_db):
    """电子书载体回链页码/章节，文章载体回链快照文件 + 标题路径锚点，两类不得混用。"""
    db, _tmp_path = seeded_db
    evidence = assemble(db, [hit(1, 1), hit(2, 2)])
    article = next(e for e in evidence if e.source_id == "S001")
    ebook = next(e for e in evidence if e.source_id == "S002")
    assert article.locator.page is None and article.locator.heading_path
    assert ebook.locator.page == 12 and ebook.locator.heading_path == []
