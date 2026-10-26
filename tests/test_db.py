"""数据库初始化与事务测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.storage.db import db_session, init_db, list_tables


class TestDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_expected_tables_exist(self) -> None:
        tables = set(list_tables(self.db_path))
        expected = {
            "projects",
            "project_members",
            "documents",
            "chunks",
            "research_tasks",
            "task_events",
            "evidence",
            "claims",
            "reviews",
            "snapshots",
            "tool_calls",
            "audit_log",
            "index_manifest",
            "llm_cache",
        }
        self.assertTrue(expected.issubset(tables), expected - tables)

    def test_init_is_idempotent(self) -> None:
        init_db(self.db_path)
        self.assertIn("research_tasks", list_tables(self.db_path))

    def test_insert_project_task_and_evidence(self) -> None:
        with db_session(self.db_path) as conn:
            conn.execute(
                "INSERT INTO projects(project_id, name) VALUES (?, ?)",
                ("IBD-TX-07", "IBD 靶点验证"),
            )
            conn.execute(
                "INSERT INTO research_tasks"
                "(task_id, user_id, project_id, question, trace_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "rt-001",
                    "scientist_031",
                    "IBD-TX-07",
                    "IL23R 在 IBD 中是否有选择性表达？",
                    "trace-001",
                ),
            )
            conn.execute(
                "INSERT INTO evidence"
                "(evidence_id, task_id, source_type, source_id, title, quote) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "ev-001",
                    "rt-001",
                    "literature",
                    "PMC000001",
                    "IL23R expression in IBD",
                    "IL23R was increased in inflamed ileal biopsies.",
                ),
            )
            task = conn.execute(
                "SELECT * FROM research_tasks WHERE task_id = ?", ("rt-001",)
            ).fetchone()
            evidence = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", ("ev-001",)
            ).fetchone()

        self.assertEqual(task["status"], "planned")
        self.assertEqual(task["project_id"], "IBD-TX-07")
        self.assertEqual(evidence["source_type"], "literature")
        self.assertEqual(evidence["acl_scope"], "public")

    def test_task_requires_existing_project(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            with db_session(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO research_tasks"
                    "(task_id, user_id, project_id, question, trace_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("rt-bad", "u1", "MISSING", "q", "trace-bad"),
                )


if __name__ == "__main__":
    unittest.main()
