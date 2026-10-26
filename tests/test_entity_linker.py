"""实体链接测试。"""

from __future__ import annotations

import unittest

from app.config import PROJECT_ROOT
from app.ingest.entity_linker import EntityLinker


class TestEntityLinker(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.linker = EntityLinker.from_yaml(
            PROJECT_ROOT / "data" / "ontology" / "entities.yaml"
        )

    def test_il23r_nod2_and_ibd(self) -> None:
        ids = self.linker.canonical_ids("IL23R and NOD2 in IBD")
        self.assertIn("ENSG00000162594", ids)
        self.assertIn("ENSG00000167207", ids)
        self.assertIn("MONDO_0005265", ids)

    def test_alias_card15(self) -> None:
        ids = self.linker.canonical_ids("CARD15 variant")
        self.assertIn("ENSG00000167207", ids)

    def test_crohn_alias_does_not_match_cd4(self) -> None:
        ids = self.linker.canonical_ids("CD4+ T cells were analyzed")
        self.assertNotIn("MONDO_0005011", ids)

    def test_crohn_disease_matches(self) -> None:
        ids = self.linker.canonical_ids("Crohn's disease biopsies")
        self.assertIn("MONDO_0005011", ids)

    def test_cell_type_alias(self) -> None:
        ids = self.linker.canonical_ids("CD4+ memory T cells")
        self.assertIn("CL_0000897", ids)

    def test_unknown_returns_empty(self) -> None:
        self.assertEqual(self.linker.link("completely unrelated text"), [])


if __name__ == "__main__":
    unittest.main()
