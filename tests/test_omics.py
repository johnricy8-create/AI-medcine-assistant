"""组学工具测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.ingest.expression import ExpressionDataset
from app.tools.omics import OmicsTool


def _dataset(gene: str, ensembl: str, synonyms: list[str]) -> ExpressionDataset:
    return ExpressionDataset(
        gene=gene,
        ensembl=ensembl,
        uniprot=["Q5VWK5"] if gene == "IL23R" else ["Q9HC29"],
        synonyms=synonyms,
        description=f"{gene} demo",
        tissue_specific_ntpm={"intestine": 1.0, "testis": 1.1, "liver": 0.2},
        single_cell_type_specific_ncpm={"T-cell": 12.5, "B-cell": 1.0},
        single_cell_group_specific_ncpm={"Immune cells": 8.0},
        blood_cell_specific_ntpm={"T-cell": 3.2},
        source_url=f"https://example.org/{gene}",
    )


class TestOmicsTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "hpa_expression.json"
        rows = [
            _dataset("IL23R", "ENSG00000162594", ["IL-23R"]).model_dump(mode="json"),
            _dataset("NOD2", "ENSG00000167207", ["CARD15"]).model_dump(mode="json"),
        ]
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        self.tool = OmicsTool(path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_expression_by_gene(self) -> None:
        result = self.tool.expression("IL23R", tissue="intestine")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["gene"], "IL23R")
        self.assertEqual(result.data["tissue_specific_ntpm"], {"intestine": 1.0})
        self.assertTrue(result.result_hash)
        self.assertEqual(len(result.dataset_version), 16)

    def test_alias_and_cell_type_filter(self) -> None:
        result = self.tool.expression("IL-23R", cell_type="T-cell")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["single_cell_type_specific_ncpm"], {"T-cell": 12.5})

    def test_unknown_gene(self) -> None:
        result = self.tool.expression("UNKNOWN")
        self.assertFalse(result.ok)
        self.assertIn("IL23R", result.error or "")

    def test_genes(self) -> None:
        self.assertEqual(self.tool.genes(), ["IL23R", "NOD2"])


if __name__ == "__main__":
    unittest.main()
