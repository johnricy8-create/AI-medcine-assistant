"""合成内部数据与 pipeline 幂等写入测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from app.ingest.pipeline import upsert_documents, write_manifest
from app.ingest.synthetic import seed_internal_demo


class TestSyntheticDemo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.data_dir.mkdir(parents=True)
        self.fetched = seed_internal_demo(self.data_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_counts_and_files(self) -> None:
        self.assertEqual(len(self.fetched), 38)
        self.assertTrue((self.data_dir / "internal_demo" / "eln.jsonl").exists())
        self.assertTrue((self.data_dir / "internal_demo" / "patents.json").exists())
        self.assertTrue((self.data_dir / "internal_demo" / "acl" / "users.yaml").exists())

        counts: dict[str, int] = {}
        for item in self.fetched:
            key = item.document.source_type.value
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(counts["eln"], 15)
        self.assertEqual(counts["patent"], 20)
        self.assertEqual(counts["report"], 3)

    def test_negative_and_acl_demo_data(self) -> None:
        eln_docs = [item.document for item in self.fetched if item.document.source_type.value == "eln"]
        negative = [doc for doc in eln_docs if doc.result_polarity == "negative"]
        self.assertGreaterEqual(len(negative), 4)
        self.assertTrue(any(doc.metadata.get("target") == "NOD2" for doc in negative))

        scopes = {doc.acl_scope for doc in eln_docs}
        self.assertEqual(scopes, {"project:IBD-TX-07", "project:ONCO-02"})
        onco = [doc for doc in eln_docs if doc.acl_scope == "project:ONCO-02"]
        self.assertEqual(len(onco), 1)
        self.assertEqual(onco[0].source_id, "ELN-ONCO-2024-777")

    def test_patent_without_embodiments(self) -> None:
        patents = [item.document for item in self.fetched if item.document.source_type.value == "patent"]
        without_embodiments = [
            doc for doc in patents if not doc.metadata.get("has_embodiments")
        ]
        self.assertEqual(len(without_embodiments), 1)
        self.assertEqual(without_embodiments[0].metadata["patent_no"], "DEMO-PAT-007")

    def test_acl_yaml(self) -> None:
        users = yaml.safe_load(
            (self.data_dir / "internal_demo" / "acl" / "users.yaml").read_text(
                encoding="utf-8"
            )
        )["users"]
        by_id = {user["user_id"]: user for user in users}
        self.assertEqual(by_id["scientist_031"]["allowed_scopes"], ["public", "project:IBD-TX-07"])
        self.assertNotIn("project:ONCO-02", by_id["scientist_031"]["allowed_scopes"])
        self.assertIn("project:ONCO-02", by_id["reviewer_001"]["allowed_scopes"])

    def test_pipeline_upsert_is_idempotent(self) -> None:
        total = upsert_documents(self.data_dir, self.fetched)
        self.assertEqual(total, 38)
        again = upsert_documents(self.data_dir, self.fetched)
        self.assertEqual(again, 38)

        manifest_count = write_manifest(self.data_dir, self.fetched)
        self.assertEqual(manifest_count, 38)
        again_count = write_manifest(self.data_dir, self.fetched)
        self.assertEqual(again_count, 38)

        rows = [
            json.loads(line)
            for line in (self.data_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(rows), 38)


if __name__ == "__main__":
    unittest.main()
