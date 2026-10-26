"""manifest 幂等写入测试。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ingest.manifest import load_manifest, sha256_text, upsert_manifest
from app.ingest.models import ManifestEntry


def _entry(doc_id: str, title: str) -> ManifestEntry:
    return ManifestEntry(
        doc_id=doc_id,
        source_type="literature",
        source_id=doc_id,
        title=title,
        source="test",
        retrieved_at=datetime.now(timezone.utc),
        content_hash=sha256_text(title),
        acl_scope="public",
    )


class TestManifest(unittest.TestCase):
    def test_sha256_is_stable(self) -> None:
        self.assertEqual(sha256_text("abc"), sha256_text("abc"))
        self.assertNotEqual(sha256_text("abc"), sha256_text("abd"))

    def test_upsert_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.jsonl"
            first = upsert_manifest(path, [_entry("b", "B"), _entry("a", "A")])
            self.assertEqual([item.doc_id for item in first], ["a", "b"])
            second = upsert_manifest(path, [_entry("a", "A updated")])
            self.assertEqual(len(second), 2)
            loaded = {item.doc_id: item for item in load_manifest(path)}
            self.assertEqual(loaded["a"].title, "A updated")
            self.assertEqual(loaded["b"].title, "B")


if __name__ == "__main__":
    unittest.main()
