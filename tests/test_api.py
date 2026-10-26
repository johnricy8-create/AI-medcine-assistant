"""P6 API 测试（Fake TaskService，不启动真实模型/索引）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.schemas import TaskStatusResponse
from app.config import Settings
from app.main import create_app
from app.services.task_store import StoredEvent, TaskRecord


class _FakeStore:
    def __init__(self) -> None:
        self.events = [
            StoredEvent(
                id=1,
                task_id="rt-1",
                node="intake",
                event_type="info",
                payload={"allowed_scopes": ["public"]},
                created_at="2026-01-01T00:00:00+00:00",
            )
        ]

    def list_projects(self):
        return [
            {
                "project_id": "IBD-TX-07",
                "name": "IBD 靶点验证",
                "description": "demo",
            }
        ]

    def list_events(self, task_id: str, after_id: int = 0):
        return [event for event in self.events if event.id > after_id]

    def get_evidence(self, evidence_id: str):
        if evidence_id != "ev-1":
            return None
        return {
            "evidence_id": "ev-1",
            "source_type": "eln",
            "source_id": "eln:1",
            "title": "demo",
            "quote": "IL23R negative",
            "acl_scope": "public",
        }

    def log_audit(self, **kwargs):
        return None

    def list_audit(self, limit=100):
        return []

    def list_reviews(self, task_id):
        return []

    def get_snapshot(self, task_id):
        return None


class _FakeTaskService:
    def __init__(self) -> None:
        self.store = _FakeStore()
        self.services = SimpleNamespace(
            acl=SimpleNamespace(
                users={
                    "scientist_031": SimpleNamespace(
                        allowed_scopes=["public", "project:IBD-TX-07"]
                    )
                }
            )
        )
        self._record = TaskRecord(
            task_id="rt-1",
            user_id="scientist_031",
            project_id="IBD-TX-07",
            question="IL23R 体内验证？",
            status="completed",
            trace_id="rr-1",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:05+00:00",
            event_count=1,
            result={},
        )

    def create_task(self, *, user_id, project_id, question, sources=None):
        return self._record.model_copy(
            update={
                "user_id": user_id,
                "project_id": project_id,
                "question": question,
                "status": "planned",
            }
        )

    def get_task(self, task_id: str):
        return self._record if task_id == "rt-1" else None

    def get_result(self, task_id: str):
        if task_id != "rt-1":
            return None
        return {
            "task_id": "rt-1",
            "status": "completed",
            "assessment": "体内验证结果为阴性。",
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "体内实验未观察到 IL23R 升高。",
                    "stance": "contradict",
                    "level": "B",
                    "support_ids": [],
                    "contradict_ids": ["ev-1"],
                    "verified": True,
                }
            ],
            "final_evidence": [
                {
                    "evidence_id": "ev-1",
                    "source_type": "eln",
                    "source_id": "eln:1",
                    "title": "demo",
                    "quote": "IL23R negative",
                    "level": "B",
                    "acl_scope": "public",
                }
            ],
            "gaps": ["需要复现"],
            "next_steps": ["补充蛋白验证"],
            "conflicts": [],
            "report_md": "# 研究底稿",
            "trace_id": "rr-1",
            "entities": [],
            "subquestions": [],
            "verify_notes": [],
            "llm_used": False,
        }


class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(
            _env_file=None,
            llm_api_key=None,
            embedding_api_key=None,
            data_dir=root / "data",
            chroma_dir=root / "chroma",
            sqlite_path=root / "app.db",
            snapshot_dir=root / "snapshots",
            log_dir=root / "logs",
        )
        self.fake = _FakeTaskService()
        self.app = create_app(self.settings, task_service=self.fake)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health_and_projects(self) -> None:
        with self.client as client:
            health = client.get("/api/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["services_ready"])
            projects = client.get("/api/projects")
            self.assertEqual(projects.status_code, 200)
            self.assertEqual(projects.json()[0]["project_id"], "IBD-TX-07")

    def test_create_status_result(self) -> None:
        with self.client as client:
            created = client.post(
                "/api/research/tasks",
                json={
                    "project_id": "IBD-TX-07",
                    "question": "IL23R 体内验证？",
                    "sources": ["literature", "eln"],
                },
                headers={"X-User-Id": "scientist_031"},
            )
            self.assertEqual(created.status_code, 200)
            task_id = created.json()["task_id"]
            self.assertEqual(task_id, "rt-1")

            status = client.get(f"/api/research/tasks/{task_id}")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["status"], "completed")

            result = client.get(f"/api/research/tasks/{task_id}/result")
            self.assertEqual(result.status_code, 200)
            body = result.json()
            self.assertEqual(body["assessment"], "体内验证结果为阴性。")
            self.assertEqual(body["claims"][0]["stance"], "contradict")
            self.assertEqual(body["internal_evidence"][0]["source_type"], "eln")

    def test_missing_task(self) -> None:
        with self.client as client:
            self.assertEqual(client.get("/api/research/tasks/missing").status_code, 404)

    def test_sse_events(self) -> None:
        with self.client as client:
            response = client.get("/api/research/tasks/rt-1/events")
            self.assertEqual(response.status_code, 200)
            self.assertIn('"node": "intake"', response.text)
            self.assertIn("event: done", response.text)

    def test_evidence_acl(self) -> None:
        with self.client as client:
            ok = client.get(
                "/api/evidence/ev-1",
                headers={"X-User-Id": "scientist_031"},
            )
            self.assertEqual(ok.status_code, 200)
            missing = client.get(
                "/api/evidence/ev-1",
                headers={"X-User-Id": "guest"},
            )
            self.assertEqual(missing.status_code, 200)

    def test_unknown_project_rejected(self) -> None:
        with self.client as client:
            response = client.post(
                "/api/research/tasks",
                json={"project_id": "NOPE", "question": "test"},
                headers={"X-User-Id": "scientist_031"},
            )
            self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
