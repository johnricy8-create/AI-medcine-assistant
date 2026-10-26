"""科学切块测试。"""

from __future__ import annotations

import unittest

from app.config import Settings
from app.ingest.chunker import chunk_document
from app.ingest.models import DocumentSection, NormalizedDocument
from app.schemas import SourceType


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        chunk_size=120,
        chunk_overlap=20,
        table_chunk_size=200,
    )


def _document(
    *,
    doc_id: str = "paper:test",
    source_type: SourceType = SourceType.LITERATURE,
    sections: list[DocumentSection] | None = None,
    text: str = "",
    acl_scope: str = "public",
    result_polarity: str = "unknown",
) -> NormalizedDocument:
    return NormalizedDocument(
        doc_id=doc_id,
        source_type=source_type,
        source_id=doc_id,
        title="IL23R in inflammatory bowel disease",
        text=text or "IL23R is expressed in intestinal immune cells.",
        sections=sections or [],
        acl_scope=acl_scope,
        result_polarity=result_polarity,
        entity_ids=["ENSG00000162594"],
        species="Homo sapiens",
        method="qPCR",
    ).finalize()


class TestChunker(unittest.TestCase):
    def test_short_section_is_single_chunk(self) -> None:
        doc = _document(
            sections=[DocumentSection(heading="Results", text="IL23R was increased.")]
        )
        chunks = chunk_document(doc, _settings())
        self.assertEqual(len(chunks), 1)
        self.assertIn("IL23R was increased", chunks[0].text)
        self.assertEqual(chunks[0].section_path, "IL23R in inflammatory bowel disease > Results")
        self.assertIn("IL23R in inflammatory bowel disease", chunks[0].embed_text)
        self.assertEqual(chunks[0].acl_scope, "public")

    def test_long_section_splits_and_is_stable(self) -> None:
        paragraph = " ".join(
            f"IL23R signaling was measured in intestinal biopsy sample {index}."
            for index in range(30)
        )
        doc = _document(
            sections=[DocumentSection(heading="Results", text=paragraph)]
        )
        first = chunk_document(doc, _settings())
        second = chunk_document(doc, _settings())
        self.assertGreater(len(first), 1)
        self.assertEqual([c.chunk_id for c in first], [c.chunk_id for c in second])
        self.assertTrue(all(c.text for c in first))
        self.assertTrue(all(len(c.text) <= 120 for c in first))

    def test_eln_keeps_full_parent_and_negative_polarity(self) -> None:
        text = (
            "[DEMO] ELN-2019-881 IL23R protein in DSS colitis\n"
            "Results\nIL23R protein was not significantly changed.\n"
            "Conclusion\nNo increase was observed."
        )
        doc = _document(
            doc_id="eln:ELN-2019-881",
            source_type=SourceType.ELN,
            text=text,
            acl_scope="project:IBD-TX-07",
            result_polarity="negative",
        )
        chunks = chunk_document(doc, _settings())
        self.assertGreaterEqual(len(chunks), 1)
        self.assertTrue(all(c.parent_text == doc.text for c in chunks))
        self.assertTrue(all(c.result_polarity == "negative" for c in chunks))
        self.assertTrue(all(c.acl_scope == "project:IBD-TX-07" for c in chunks))
        # 不应因为每个 section 都切整篇而重复
        self.assertEqual(len({c.chunk_id for c in chunks}), len(chunks))

    def test_no_empty_chunks(self) -> None:
        doc = _document(text="   ")
        chunks = chunk_document(doc, _settings())
        self.assertEqual(chunks, [])

    def test_table_uses_table_chunk_size(self) -> None:
        table = "| Gene | Tissue | nTPM |\n" + "\n".join(
            f"| IL23R | tissue-{index} | {index}.0 |" for index in range(40)
        )
        doc = _document(
            sections=[DocumentSection(heading="Table 1", text=table, kind="table")]
        )
        chunks = chunk_document(doc, _settings())
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.table_ref == "Table 1" for c in chunks))
        self.assertTrue(all(len(c.text) <= 200 for c in chunks))


if __name__ == "__main__":
    unittest.main()
