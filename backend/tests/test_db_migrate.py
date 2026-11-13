"""七张表的建表与迁移（阶段一步骤 9 前置）。

口径来自 plan 阶段一「接口约定」：来源表、卡片表、事实条目表、冲突表、问答日志表、审核日志表、
路线表。实现按简报要求用标准库 `sqlite3`，**不上 ORM**；库文件位置走 `Config.data_dir`，
不硬编码相对路径（阶段零 BACKEND_ROOT 那次教训）。
"""

import sqlite3

import pytest

from app.db.migrate import EXPECTED_TABLES, SCHEMA_VERSION, default_db_path, migrate


def table_names(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def row_count(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def columns(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migrate_creates_seven_plan_tables(tmp_path):
    db = tmp_path / "redtrace.db"
    migrate(db)
    names = table_names(db)
    assert {"sources", "cards", "claims", "conflicts", "qa_logs", "audit_logs", "routes"} <= names
    assert EXPECTED_TABLES == {"sources", "cards", "claims", "conflicts", "qa_logs", "audit_logs", "routes"}


def test_migrate_is_idempotent(tmp_path):
    """重复执行不报错、不重复建表，并且不能把已有数据洗掉。"""
    db = tmp_path / "redtrace.db"
    migrate(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO sources (source_id, title, publisher, publish_date, url_or_path,"
            " access_date, license_note, corpus_tier, media_type, verified) VALUES"
            " ('S001','书','人民出版社','1985','data/raw/a.pdf','2026-11-13','公开出版物','核心','电子书',1)"
        )
        conn.commit()
    before = row_count(db, "sources")
    migrate(db)
    migrate(db)
    assert row_count(db, "sources") == before, "幂等迁移不得丢数据"


def test_schema_version_is_recorded(tmp_path):
    db = tmp_path / "redtrace.db"
    migrate(db)
    with sqlite3.connect(db) as conn:
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_version ORDER BY version")]
    assert versions == [SCHEMA_VERSION]
    # 再跑一次不得重复登记版本
    migrate(db)
    with sqlite3.connect(db) as conn:
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_version")]
    assert len(versions) == 1


def test_source_table_carries_nine_columns_plus_whitelist_three(tmp_path):
    """出处九列 + domain/sections/verified 一并落到来源表（简报步骤 3）。"""
    db = tmp_path / "redtrace.db"
    migrate(db)
    cols = columns(db, "sources")
    assert {
        "source_id",
        "title",
        "publisher",
        "publish_date",
        "url_or_path",
        "access_date",
        "license_note",
        "corpus_tier",
        "media_type",
        "domain",
        "sections",
        "verified",
    } <= cols


def test_claims_table_stores_normalized_time_four_columns(tmp_path):
    """时间要存归一后的 start/end/granularity/raw 四列——冲突检测与时间轴都靠它，不能只存原文。"""
    db = tmp_path / "redtrace.db"
    migrate(db)
    cols = columns(db, "claims")
    assert {
        "claim_id",
        "card_id",
        "source_id",
        "subject",
        "predicate",
        "value",
        "quote",
        "locator",
        "confidence",
        "time_start",
        "time_end",
        "time_granularity",
        "time_raw",
    } <= cols


def test_cards_table_keeps_type_and_source_link(tmp_path):
    db = tmp_path / "redtrace.db"
    migrate(db)
    assert {"card_id", "source_id", "type", "name", "summary"} <= columns(db, "cards")


def test_foreignKey_and_index_present(tmp_path):
    """条目按 source_id / predicate 查是阶段四与阶段五的主路径，索引在建表时就位。"""
    db = tmp_path / "redtrace.db"
    migrate(db)
    with sqlite3.connect(db) as conn:
        indexes = {row[0] for row in conn.execute("PRAGMA index_list(claims)")}
    assert indexes, "事实条目表应当有支撑查询的索引"


def test_future_phase_tables_exist_but_stay_empty(tmp_path):
    """冲突/日志/路线表本轮只建不写：字段留给阶段四/六/七，不许提前塞业务语义。"""
    db = tmp_path / "redtrace.db"
    migrate(db)
    for table in ("conflicts", "qa_logs", "audit_logs", "routes"):
        assert row_count(db, table) == 0


def test_default_db_path_follows_data_dir(monkeypatch, tmp_path):
    """库位置必须跟着 DATA_DIR 走，否则数据目录迁移后闸门与库分家。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert default_db_path() == tmp_path / "redtrace.db"


def test_migrate_creates_parent_directory(tmp_path):
    db = tmp_path / "nested" / "deeper" / "redtrace.db"
    migrate(db)
    assert db.is_file()


def test_migrate_rejects_directory_as_db_path(tmp_path):
    d = tmp_path / "是个目录"
    d.mkdir()
    with pytest.raises(ValueError, match="不是文件"):
        migrate(d)
