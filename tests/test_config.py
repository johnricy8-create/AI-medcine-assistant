"""配置测试。"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.config import PROJECT_ROOT, Settings


class TestSettings(unittest.TestCase):
    def test_project_root_is_project_directory(self) -> None:
        self.assertTrue((PROJECT_ROOT / "pyproject.toml").exists())
        self.assertEqual(PROJECT_ROOT.name, "医药研发助手")

    def test_default_models_and_provider(self) -> None:
        settings = Settings(_env_file=None)
        self.assertEqual(settings.llm_model, "glm-4.7-flash")
        self.assertEqual(settings.llm_base_url, "https://open.bigmodel.cn/api/paas/v4/")
        self.assertEqual(settings.embedding_model, "BAAI/bge-m3")
        self.assertEqual(settings.embedding_dim, 1024)
        self.assertEqual(settings.embedding_base_url, "https://api.siliconflow.cn/v1")
        self.assertGreater(settings.llm_temperature, 0)

    def test_paths_are_absolute_and_based_on_root(self) -> None:
        settings = Settings(_env_file=None)
        self.assertTrue(settings.data_dir.is_absolute())
        self.assertEqual(settings.data_dir, PROJECT_ROOT / "data")
        self.assertEqual(settings.sqlite_path, PROJECT_ROOT / "storage" / "app.db")

    def test_chunk_overlap_must_be_smaller_than_chunk_size(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, chunk_size=100, chunk_overlap=100)

    def test_context_chunks_cannot_exceed_retrieval_k(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, retrieval_k=5, max_context_chunks=8)

    def test_zhipu_temperature_zero_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, llm_temperature=0)

    def test_relative_paths_resolve_to_project_root(self) -> None:
        settings = Settings(_env_file=None, data_dir="data/custom")
        self.assertEqual(settings.data_dir, PROJECT_ROOT / "data" / "custom")

    def test_key_helpers(self) -> None:
        settings = Settings(
            _env_file=None,
            llm_api_key=None,
            embedding_api_key=None,
        )
        self.assertFalse(settings.llm_configured())
        self.assertFalse(settings.embedding_configured())


if __name__ == "__main__":
    unittest.main()
