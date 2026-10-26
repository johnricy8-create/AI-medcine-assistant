"""任务持久化测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import PROJECT_ROOT
from app.graph.state import Event
from app.services.task_store import TaskStore
from app.storage.db import init_db


class TestTaskStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "app.db"
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        init_db(self.db_path)
        self.store = TaskStore(self.db_path, self.data_dir)
        self.store.ensure_projects_from_acl(
            PROJECT_ROOT / "data" / "internal_demo" / "acl"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_save_and_read(self) -> None:
        record = self.store.create_task(
            task_id="rt-test",
            user_id="scientist_031",
            project_id="IBD-TX-07",
            question="IL23R 是否有表达？",
            trace_id="rr-test",
        )
        self.assertEqual(record.status, "planned")
        self.assertIn("IBD-TX-07", [p["project_id"] for p in self.store.list_projects()])

        self.store.append_events(
            "rt-test",
            [
                Event(
                    node="intake",
                    event_type="info",
                    message="开始",
                    payload={"allowed_scopes": ["public"]},
                )
            ],
        )
        state = {
            "task_id": "rt-test",
            "trace_id": "rr-test",
            "status": "completed",
            "question": "IL23R 是否有表达？",
            "entities": [],
            "subquestions": [],
            "budget": {},
            "assessment": "有表达。",
            "gaps": [],
            "next_steps": [],
            "verify_notes": [],
            "llm_used": False,
            "report_md": "# 研究底稿",
            "events": [],
            "final_evidence": [
                {
                    "evidence_id": "ev-1",
                    "source_type": "eln",
                    "source_id": "eln:1",
                    "title": "ELN-1",
                    "chunk_id": "chunk-1",
                    "quote": "IL23R negative",
                    "locator": {"experiment_id": "ELN-1"},
                    "entity_ids": ["ENSG00000162594"],
                    "species": "Mus musculus",
                    "sample": "colon",
                    "method": "Western blot",
                    "stance": "unknown",
                    "level": "B",
                    "acl_scope": "project:IBD-TX-07",
                    "scores": {"rerank": 0.9},
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "阴性",
                    "stance": "contradict",
                    "level": "B",
                    "support_ids": [],
                    "contradict_ids": ["ev-1"],
                    "confidence": 0.8,
                    "caveats": [],
                    "verified": True,
                    "verify_notes": [],
                }
            ],
        }
        self.store.save_result("rt-test", state)

        record = self.store.get_task("rt-test")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "completed")
        self.assertGreater(record.event_count, 0)
        result = self.store.get_result("rt-test")
        self.assertEqual(result["assessment"], "有表达。")
        self.assertEqual(result["claims"][0]["stance"], "contradict")

        events = self.store.list_events("rt-test")
        self.assertEqual(events[0].node, "intake")

        evidence = self.store.get_evidence("ev-1")
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["locator_json"]["experiment_id"], "ELN-1")

        review = self.store.add_review(
            "rt-test",
            reviewer_id="reviewer_001",
            action="accept_with_revision",
            claim_id="claim-1",
            comment="补充蛋白验证",
        )
        self.assertTrue(review["review_id"].startswith("rev-"))
        self.assertEqual(len(self.store.list_reviews("rt-test")), 1)

        snapshot = self.store.save_snapshot("rt-test", state=state, version=2)
        self.assertTrue(snapshot["snapshot_id"].startswith("snap-"))
        loaded = self.store.get_snapshot("rt-test")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["version"], 2)

        updated = dict(result)
        updated["version"] = 2
        updated["claims"][0]["verified"] = True
        self.store.update_result_for_review(
            "rt-test",
            updated,
            status="completed",
            report_md="# 已评审",
            version=2,
        )
        self.assertEqual(self.store.get_task("rt-test").version, 2)
        self.assertEqual(self.store.get_result("rt-test")["report_md"], "# 已评审")

        self.store.log_audit(
            user_id="reviewer_001",
            project_id="IBD-TX-07",
            action="review",
            resource="rt-test",
            allowed=True,
        )
        self.assertTrue(self.store.list_audit())


if __name__ == "__main__":
    unittest.main()
