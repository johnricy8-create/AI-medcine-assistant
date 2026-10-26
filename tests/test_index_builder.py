"""索引构建集成测试（Fake Embedding）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.ingest.manifest import write_jsonl
from app.ingest.models import DocumentSection, NormalizedDocument
from app.retrieval.index_builder import build_index
from app.retrieval.vector_store import VectorStore
from app.schemas import SourceType
from app.storage.db import db_session, init_db
from tests.fakes import FakeEmbeddings


def _doc(doc_id: str, text: str, acl_scope: str = "public") -> NormalizedDocument:
    return NormalizedDocument(
        doc_id=doc_id,
        source_type=SourceType.LITERATURE,
        source_id=doc_id,
        title="IL23R in IBD",
        text=text,
        sections=[DocumentSection(heading="Results", text=text)],
        acl_scope=acl_scope,
        entity_ids=["ENSG00000162594"],
        species="Homo sapiens",
        method="qPCR",
    ).finalize()


class TestIndexBuilder(unittest.TestCase):
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
            chroma_collection="test_index",
            chunk_size=120,
            chunk_overlap=20,
            enable_entity_linker=False,
            index_batch_size=2,
        )
        self.docs = [
            _doc("paper:1", "IL23R mRNA was increased in inflamed biopsies."),
            _doc(
                "eln:1",
                "IL23R protein was not changed in mouse colitis.",
                acl_scope="project:IBD-TX-07",
            ),
        ]
        processed = self.settings.data_dir / "processed"
        write_jsonl(
            processed / "documents.jsonl",
            [doc.model_dump(mode="json") for doc in self.docs],
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_chunks_only_build(self) -> None:
        result = build_index(self.settings, chunks_only=True)
        self.assertEqual(result.document_count, 2)
        self.assertGreater(result.chunk_count, 0)
        self.assertEqual(result.chroma_count, 0)
        self.assertEqual(result.bm25_count, result.chunk_count)
        self.assertTrue(Path(result.chunks_path).exists())
        self.assertTrue(Path(result.manifest_path).exists())

        init_db(self.settings.sqlite_path)
        with db_session(self.settings.sqlite_path) as conn:
            row = conn.execute(
                "SELECT document_count, chunk_count FROM index_manifest "
                "WHERE collection = ?",
                ("test_index",),
            ).fetchone()
        self.assertEqual(row["document_count"], 2)
        self.assertEqual(row["chunk_count"], result.chunk_count)

    def test_full_build_with_fake_embeddings(self) -> None:
        fake = FakeEmbeddings(dim=16)
        result = build_index(
            self.settings,
            embeddings=fake,
            expected_dim=16,
        )
        self.assertGreater(result.chunk_count, 0)
        self.assertEqual(result.chroma_count, result.chunk_count)
        self.assertGreater(fake.calls, 0)

        store = VectorStore(
            self.settings,
            embeddings=fake,
            expected_dim=16,
        )
        hits = store.search("IL23R", k=3, allowed_scopes=["public"])
        self.assertTrue(hits)
        self.assertTrue(all(hit.metadata["acl_scope"] == "public" for hit in hits))
        store.delete()


if __name__ == "__main__":
    unittest.main()
