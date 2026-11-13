"""幂等建库迁移（阶段一步骤 9 前置）。

用标准库 `sqlite3` + 版本表（不引入 ORM，也不引入 Alembic 这类迁移框架：七张表、
单机文件库，用不着）。`migrate()` 可以重复执行：已应用过的版本不再执行，
已写入的数据不受影响。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import get_config
from app.db.models import V1_STATEMENTS

SCHEMA_VERSION = 1

# plan 阶段一「接口约定」里那张七表清单的英文名，测试据此断言没有漏表
EXPECTED_TABLES = frozenset(
    {"sources", "cards", "claims", "conflicts", "qa_logs", "audit_logs", "routes"}
)

SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""

# 迁移脚本按版本号追加；改表只能新增版本，不要回改历史版本的内容
MIGRATIONS: dict[int, tuple[str, ...]] = {1: V1_STATEMENTS}


def default_db_path() -> Path:
    """数据库位置跟着 `Config.data_dir` 走（DATA_DIR 迁移即整体搬迁，阶段零的教训）。"""
    return get_config().data_dir / "redtrace.db"


def current_version(db_path: Path) -> int:
    path = Path(db_path)
    if not path.is_file():
        return 0
    with sqlite3.connect(path) as conn:
        conn.execute(SCHEMA_VERSION_DDL)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()
    return int(row[0])


def migrate(db_path: Path | None = None) -> int:
    """建库并应用所有未应用的迁移，返回最终版本号。可安全重复调用。"""
    path = default_db_path() if db_path is None else Path(db_path)
    if path.is_dir():
        raise ValueError(f"数据库路径不是文件，是个目录：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(SCHEMA_VERSION_DDL)
        applied = {
            row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()
        }
        for version in sorted(MIGRATIONS):
            if version in applied:
                continue
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                (version,),
            )
        conn.commit()
    return max(MIGRATIONS)
