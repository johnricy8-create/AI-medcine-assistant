"""Chroma 向量库测试（使用 Fake Embedding，不访问网络）。"""

from __future__ import annotations

import gc
import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.ingest.chunker import Chunk
from app.retrieval.vector_store import VectorStore
from app.schemas import SourceType
from tests.fakes import FakeEmbeddings


def _chunk(
    chunk_id: str,
    text: str,
    *,
    acl_scope: str = "public",
    doc_id: str = "doc:1",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        parent_id=f"parent:{chunk_id}",
        doc_id=doc_id,
        source_type=SourceType.LITERATURE,
        title="Test document",
        text=text,
        embed_text=text,
        parent_text=text,
        acl_scope=acl_scope,
    )


class TestVectorStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self.settings = Settings(
            _env_file=None,
            data_dir=root / "data",
            chroma_dir=root / "chroma",
            sqlite_path=root / "app.db",
            snapshot_dir=root / "snapshots",
            log_dir=root / "logs",
            chroma_collection="test_collection",
            index_batch_size=2,
        )
        self.embeddings = FakeEmbeddings(dim=16)
        self.store = VectorStore(
            self.settings,
            embeddings=self.embeddings,
            expected_dim=16,
        )
        self.chunks = [
            _chunk("c1", "IL23R mRNA increased in inflamed biopsies."),
            _chunk("c2", "NOD2 knockdown did not change IL23R in organoids."),
            _chunk(
                "c3",
                "IL23R expression in tumor infiltrating lymphocytes.",
                acl_scope="project:ONCO-02",
                doc_id="doc:onco",
            ),
            _chunk(
                "c4",
                "IL23R protein was not changed in mouse colitis.",
                acl_scope="project:IBD-TX-07",
                doc_id="doc:ibd",
            ),
        ]

    def tearDown(self) -> None:
        try:
            self.store.delete()
        except Exception:
            pass
        del self.store
        gc.collect()
        self.tmp.cleanup()

    def test_add_and_count(self) -> None:
        self.store.reset()
        added = self.store.add_chunks(self.chunks)
        self.assertEqual(added, 4)
        self.assertEqual(self.store.count(), 4)
        self.assertTrue(self.store.exists())

    def test_search_with_acl(self) -> None:
        self.store.reset()
        self.store.add_chunks(self.chunks)
        public_hits = self.store.search(
            "IL23R", k=4, allowed_scopes=["public"]
        )
        self.assertTrue(public_hits)
        self.assertTrue(all(hit.metadata["acl_scope"] == "public" for hit in public_hits))
        self.assertNotIn("c3", {hit.chunk_id for hit in public_hits})
        self.assertNotIn("c4", {hit.chunk_id for hit in public_hits})

        ibd_hits = self.store.search(
            "IL23R protein mouse", k=4, allowed_scopes=["project:IBD-TX-07"]
        )
        self.assertTrue(ibd_hits)
        self.assertTrue(all(hit.metadata["acl_scope"] == "project:IBD-TX-07" for hit in ibd_hits))

    def test_reset_removes_old_vectors(self) -> None:
        self.store.reset()
        self.store.add_chunks(self.chunks[:2])
        self.assertEqual(self.store.count(), 2)
        self.store.reset()
        self.assertEqual(self.store.count(), 0)


if __name__ == "__main__":
    unittest.main()
