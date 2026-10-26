"""Europe PMC JATS 解析与标准化测试。"""

from __future__ import annotations

import unittest

from app.ingest.europe_pmc import (
    build_document,
    extract_entity_ids,
    infer_species,
    parse_full_text_xml,
)
from app.ingest.models import normalize_text
from app.schemas import SourceType

JATS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <title-group><article-title>IL23R in inflammatory bowel disease</article-title></title-group>
      <abstract><p>IL23R is associated with IBD.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Results</title>
      <p>IL23R mRNA was increased in inflamed biopsies from patients.</p>
      <p>NOD2 was not significantly changed.</p>
    </sec>
    <fig>
      <label>Figure 1</label>
      <caption><p>IL23R expression in intestinal tissue.</p></caption>
    </fig>
  </body>
</article>
"""

RECORD = {
    "id": "123456",
    "source": "MED",
    "pmid": "123456",
    "pmcid": "PMC123456",
    "doi": "10.1000/demo",
    "title": "Fallback title",
    "authorString": "Alice A, Bob B",
    "journalTitle": "Demo Journal",
    "pubYear": "2024",
    "abstractText": "Fallback abstract",
    "isOpenAccess": "Y",
    "inPMC": "Y",
    "license": "cc by",
    "pubTypes": ["Journal Article"],
    "meshTerms": ["Inflammatory Bowel Diseases"],
    "citedByCount": 10,
    "firstPublicationDate": "2024-01-01",
}


class TestEuropePmc(unittest.TestCase):
    def test_parse_jats_sections_and_figures(self) -> None:
        parsed = parse_full_text_xml(JATS_XML)
        self.assertEqual(parsed["title"], "IL23R in inflammatory bowel disease")
        self.assertIn("IL23R is associated", parsed["abstract"])
        kinds = [section.kind for section in parsed["sections"]]
        self.assertIn("body", kinds)
        self.assertIn("figure", kinds)
        body = next(section for section in parsed["sections"] if section.kind == "body")
        self.assertEqual(body.heading, "Results")
        self.assertIn("inflamed biopsies", body.text)

    def test_build_document_metadata(self) -> None:
        parsed = parse_full_text_xml(JATS_XML)
        document = build_document(RECORD, parsed)
        self.assertEqual(document.doc_id, "paper:PMC123456")
        self.assertEqual(document.source_type, SourceType.LITERATURE)
        self.assertEqual(document.species, "Homo sapiens")
        self.assertIn("ENSG00000162594", document.entity_ids)
        self.assertIn("ENSG00000167207", document.entity_ids)
        self.assertIn("IL23R", document.text)
        self.assertEqual(document.license, "cc by")
        self.assertTrue(document.metadata["full_text_used"])

    def test_abstract_only_fallback(self) -> None:
        document = build_document(RECORD, None)
        self.assertEqual(document.doc_id, "paper:PMC123456")
        self.assertFalse(document.metadata["full_text_used"])
        self.assertIn("Fallback abstract", document.abstract)

    def test_normalize_text_strips_html(self) -> None:
        cleaned = normalize_text("<h4>Background &amp; aims</h4><p>IL23R &lt; 0.05</p>")
        self.assertEqual(cleaned, "Background & aims IL23R < 0.05")

    def test_inference_helpers(self) -> None:
        self.assertEqual(infer_species("Mice were treated with DSS"), "Mus musculus")
        self.assertEqual(infer_species("Human biopsies were analyzed"), "Homo sapiens")
        self.assertEqual(
            infer_species(
                "Human patients were studied; mice were used in a supporting experiment."
            ),
            "Homo sapiens",
        )
        self.assertEqual(
            extract_entity_ids("IL23R and NOD2 in Crohn disease"),
            ["ENSG00000162594", "ENSG00000167207", "MONDO_0005011"],
        )


if __name__ == "__main__":
    unittest.main()
