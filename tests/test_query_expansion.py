"""查询扩展测试。"""

from __future__ import annotations

import unittest

from app.config import PROJECT_ROOT
from app.ingest.entity_linker import EntityLinker
from app.retrieval.query_expansion import QueryExpander


class TestQueryExpansion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expander = QueryExpander(
            EntityLinker.from_yaml(
                PROJECT_ROOT / "data" / "ontology" / "entities.yaml"
            )
        )

    def test_entity_and_in_vivo_expansion(self) -> None:
        expanded = self.expander.expand("IL23R 体内验证")
        self.assertIn("ENSG00000162594", expanded.canonical_ids)
        self.assertIn("IL-23R", expanded.terms)
        self.assertIn("in vivo", expanded.terms)
        self.assertIn("mouse", expanded.terms)
        self.assertIn("IL23R", expanded.dense_query)

    def test_nod2_alias_expansion(self) -> None:
        expanded = self.expander.expand("NOD2 敲低")
        self.assertIn("ENSG00000167207", expanded.canonical_ids)
        self.assertIn("CARD15", expanded.terms)

    def test_unknown_query_has_no_entities(self) -> None:
        expanded = self.expander.expand("完全无关的行政问题")
        self.assertEqual(expanded.entities, [])
        self.assertEqual(expanded.terms, [])

    def test_counter_evidence_queries(self) -> None:
        queries = self.expander.counter_evidence_queries("IL23R 表达")
        joined = " ".join(queries)
        self.assertIn("阴性", joined)
        self.assertIn("no significant change", joined)
        self.assertIn("failed to replicate", joined)


if __name__ == "__main__":
    unittest.main()
