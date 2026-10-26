"""科学实体本体文件测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from app.config import PROJECT_ROOT

ONTOLOGY = PROJECT_ROOT / "data" / "ontology" / "entities.yaml"


class TestOntology(unittest.TestCase):
    def setUp(self) -> None:
        self.data = yaml.safe_load(ONTOLOGY.read_text(encoding="utf-8"))
        self.entities = self.data["entities"]
        self.by_id = {entity["canonical_id"]: entity for entity in self.entities}

    def test_unique_ids_and_required_fields(self) -> None:
        ids = [entity["canonical_id"] for entity in self.entities]
        self.assertEqual(len(ids), len(set(ids)))
        for entity in self.entities:
            self.assertIn("canonical_id", entity)
            self.assertIn("entity_type", entity)
            self.assertIn("name", entity)
            self.assertTrue(entity.get("aliases"))

    def test_il23r_and_nod2_cross_ids(self) -> None:
        il23r = self.by_id["ENSG00000162594"]
        nod2 = self.by_id["ENSG00000167207"]
        self.assertEqual(il23r["cross_ids"]["uniprot"], "Q5VWK5")
        self.assertEqual(il23r["cross_ids"]["ncbi_gene"], "149233")
        self.assertEqual(nod2["cross_ids"]["uniprot"], "Q9HC29")
        self.assertEqual(nod2["cross_ids"]["ncbi_gene"], "64127")
        self.assertIn("IL-23R", il23r["aliases"])
        self.assertIn("CARD15", nod2["aliases"])

    def test_disease_and_cell_ids(self) -> None:
        self.assertIn("MONDO_0005265", self.by_id)
        self.assertIn("MONDO_0005011", self.by_id)
        self.assertIn("MONDO_0005101", self.by_id)
        self.assertIn("CL_0000897", self.by_id)
        self.assertIn("CL_0000815", self.by_id)


if __name__ == "__main__":
    unittest.main()
