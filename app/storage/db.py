"""SQLite 连接与初始化。

P0 只提供最小、可测试的数据库边界；具体 repository 在后续阶段实现。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _resolve_path(db_path: Path | str | None = None) -> Path:
    if db_path is None:
        return get_settings().sqlite_path
    path = Path(db_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """创建一个启用外键与 WAL 的 SQLite 连接。"""
    path = _resolve_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """事务边界：正常提交，异常回滚，最后关闭连接。"""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> None:
    """幂等初始化数据库结构，并做轻量列迁移。"""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with db_session(db_path) as conn:
        conn.executescript(schema)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(research_tasks)").fetchall()
        }
        if "result_json" not in columns:
            conn.execute(
                "ALTER TABLE research_tasks "
                "ADD COLUMN result_json TEXT NOT NULL DEFAULT '{}'"
            )
        snapshot_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()
        }
        if "version" not in snapshot_columns:
            conn.execute(
                "ALTER TABLE snapshots ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
            )


def check_db(db_path: Path | str | None = None) -> bool:
    """轻量数据库健康检查。"""
    try:
        with db_session(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def list_tables(db_path: Path | str | None = None) -> list[str]:
    """测试/诊断辅助：返回用户表名。"""
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    return [row["name"] for row in rows]
