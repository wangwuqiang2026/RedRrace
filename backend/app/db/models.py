"""七张表的 DDL（阶段一「接口约定」：来源、卡片、事实条目、冲突、问答日志、审核日志、路线）。

字段口径的来源与边界：

- `sources`：出处九列（与 `registry.SourceRecord` / `qa.schemas.SourceOut` 同名）+ 白名单三列
  `domain/sections/verified`（口径来自 `Whitelist.entries`，装配时写入，不在这里重新解析 YAML），
  另加 `local_path` 记录原件实际落点（无原件时为空，阶段一步骤 9 的两栏统计要用）。
- `claims`：除事实条目本身的六个字段外，**必须存归一后的时间四列**
  （`time_start/time_end/time_granularity/time_raw`）——阶段四的冲突判定与阶段五的时间轴
  都按区间比对，只存原文就无法比较。
- `conflicts` / `qa_logs` / `audit_logs` / `routes`：本轮**只建表不写入**，列只放 plan 已给的，
  业务语义等阶段四/六/七再定，届时以新增迁移版本的方式扩列，不改这张表的既有含义。
"""

from __future__ import annotations

SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS sources (
    source_id     TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    publisher     TEXT NOT NULL,
    publish_date  TEXT NOT NULL,
    url_or_path   TEXT NOT NULL,
    access_date   TEXT NOT NULL,
    license_note  TEXT NOT NULL,
    corpus_tier   TEXT NOT NULL CHECK (corpus_tier IN ('核心', '补充')),
    media_type    TEXT NOT NULL CHECK (media_type IN ('电子书', '文章')),
    domain        TEXT,
    sections      TEXT NOT NULL DEFAULT '[]',
    verified      INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    local_path    TEXT,
    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CARDS_DDL = """
CREATE TABLE IF NOT EXISTS cards (
    card_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    type      TEXT NOT NULL CHECK (type IN ('person', 'event', 'place', 'time', 'relation')),
    name      TEXT NOT NULL,
    summary   TEXT NOT NULL,
    UNIQUE (source_id, type, name)
)
"""

CLAIMS_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id           INTEGER NOT NULL REFERENCES cards (card_id) ON DELETE CASCADE,
    source_id         TEXT NOT NULL REFERENCES sources (source_id) ON DELETE CASCADE,
    subject           TEXT NOT NULL,
    predicate         TEXT NOT NULL,
    value             TEXT NOT NULL,
    quote             TEXT NOT NULL,
    locator           TEXT NOT NULL,
    confidence        REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    time_start        TEXT,
    time_end          TEXT,
    time_granularity  TEXT CHECK (time_granularity IN ('year', 'month', 'day', 'range', 'unknown')
                                  OR time_granularity IS NULL),
    time_raw          TEXT,
    UNIQUE (card_id, subject, predicate, value)
)
"""

CONFLICTS_DDL = """
CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_key   TEXT NOT NULL UNIQUE,
    predicate   TEXT NOT NULL,
    claim_ids   TEXT NOT NULL,
    disputed    INTEGER NOT NULL DEFAULT 1 CHECK (disputed IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

QA_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS qa_logs (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    question       TEXT NOT NULL,
    refused        INTEGER NOT NULL CHECK (refused IN (0, 1)),
    refusal_reason TEXT,
    answer         TEXT NOT NULL,
    citations      TEXT NOT NULL DEFAULT '[]',
    elapsed_ms     INTEGER NOT NULL,
    prompt_version TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

AUDIT_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id           INTEGER REFERENCES qa_logs (log_id) ON DELETE CASCADE,
    sentence_index   INTEGER NOT NULL,
    sentence         TEXT NOT NULL,
    citation_indexes TEXT NOT NULL DEFAULT '[]',
    verdict          TEXT NOT NULL CHECK (verdict IN ('kept', 'dropped')),
    reason           TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

ROUTES_DDL = """
CREATE TABLE IF NOT EXISTS routes (
    route_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    theme      TEXT NOT NULL,
    days       INTEGER NOT NULL,
    pace       TEXT NOT NULL CHECK (pace IN ('紧凑', '轻松')),
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# 支撑阶段四（同主谓分组）、阶段五（时间区间与地点）与统计查询的索引
CLAIMS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_claims_source ON claims (source_id)",
    "CREATE INDEX IF NOT EXISTS idx_claims_predicate ON claims (predicate)",
    "CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims (subject)",
    "CREATE INDEX IF NOT EXISTS idx_claims_time ON claims (time_start, time_end)",
)

V1_STATEMENTS: tuple[str, ...] = (
    SOURCES_DDL,
    CARDS_DDL,
    CLAIMS_DDL,
    CONFLICTS_DDL,
    QA_LOGS_DDL,
    AUDIT_LOGS_DDL,
    ROUTES_DDL,
    *CLAIMS_INDEX_DDL,
)

# V2（阶段三步骤 5b-2）：拒答可审计的四列。只新增列，不改 V1 任何字段含义（D6 注释纪律）。
V2_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE qa_logs ADD COLUMN retrieved_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE qa_logs ADD COLUMN top_score REAL",
    "ALTER TABLE qa_logs ADD COLUMN threshold REAL",
    "ALTER TABLE qa_logs ADD COLUMN gate_note TEXT NOT NULL DEFAULT ''",
)
