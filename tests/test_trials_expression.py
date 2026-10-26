"""临床试验与表达数据标准化测试。"""

from __future__ import annotations

import unittest

from app.ingest.clinical_trials import build_document as build_trial_document
from app.ingest.expression import _build_dataset, _build_document as build_expression_document
from app.schemas import SourceType

TRIAL = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT000001",
            "briefTitle": "IL23R blockade in ulcerative colitis",
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2024-01-01"},
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE2"],
            "enrollmentInfo": {"count": 120},
        },
        "descriptionModule": {
            "briefSummary": "A study of IL23R blockade in patients with ulcerative colitis.",
        },
        "conditionsModule": {"conditions": ["Ulcerative Colitis"]},
        "armsInterventionsModule": {
            "interventions": [{"name": "Drug A", "type": "DRUG"}]
        },
        "outcomesModule": {
            "primaryOutcomes": [{"measure": "Clinical remission", "timeFrame": "Week 12"}]
        },
        "eligibilityModule": {"eligibilityCriteria": "Adults with active UC."},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Demo Sponsor"}},
    }
}

HPA = {
    "Gene": "IL23R",
    "Gene synonym": ["IL-23R"],
    "Ensembl": "ENSG00000162594",
    "Uniprot": ["Q5VWK5"],
    "Gene description": "Interleukin 23 receptor",
    "RNA tissue specific nTPM": {"intestine": 1.0, "testis": 1.1},
    "RNA single cell type specific nCPM": {"T-cells": 12.5},
    "RNA single cell type group specific nCPM": {"Immune cells": 8.0},
    "RNA blood cell specific nTPM": {"T-cell": 3.2},
}


class TestTrialDocument(unittest.TestCase):
    def test_build_trial_document(self) -> None:
        document = build_trial_document(TRIAL)
        self.assertEqual(document.doc_id, "trial:NCT000001")
        self.assertEqual(document.source_type, SourceType.TRIAL)
        self.assertEqual(document.species, "Homo sapiens")
        self.assertIn("MONDO_0005101", document.entity_ids)
        self.assertIn("Clinical remission", document.text)
        self.assertTrue(document.sections)


class TestExpressionDocument(unittest.TestCase):
    def test_build_expression_dataset_and_document(self) -> None:
        dataset = _build_dataset("IL23R", "ENSG00000162594", HPA)
        self.assertEqual(dataset.gene, "IL23R")
        self.assertAlmostEqual(dataset.tissue_specific_ntpm["intestine"], 1.0)
        self.assertAlmostEqual(dataset.single_cell_type_specific_ncpm["T-cells"], 12.5)

        document = build_expression_document(dataset)
        self.assertEqual(document.doc_id, "omics:hpa:IL23R")
        self.assertEqual(document.source_type, SourceType.OMICS)
        self.assertIn("ENSG00000162594", document.entity_ids)
        self.assertIn("T-cells: 12.5", document.text)


if __name__ == "__main__":
    unittest.main()
