"""健康检查接口测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class TestHealthApi(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = Settings(
            _env_file=None,
            llm_api_key=None,
            embedding_api_key=None,
            data_dir=root / "data",
            raw_data_dir=root / "data" / "raw",
            chroma_dir=root / "storage" / "chroma",
            sqlite_path=root / "storage" / "app.db",
            snapshot_dir=root / "storage" / "snapshots",
            log_dir=root / "storage" / "logs",
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_health_returns_ok_and_initializes_db(self) -> None:
        with self.client as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["app"], "医药研发知识助手")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["database"], "ok")
        self.assertFalse(body["llm_configured"])
        self.assertFalse(body["embedding_configured"])
        self.assertFalse(body["index_available"])
        self.assertTrue(self.settings.sqlite_path.exists())

    def test_root_returns_workbench_page(self) -> None:
        with self.client as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("医药研发知识助手", response.text)
        self.assertIn("研究底稿", response.text)


if __name__ == "__main__":
    unittest.main()
