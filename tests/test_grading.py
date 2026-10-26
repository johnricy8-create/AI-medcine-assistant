"""证据分级测试。"""

from __future__ import annotations

import unittest

from app.evidence.grading import EvidenceGrader
from app.schemas import Evidence, EvidenceLevel, SourceType


def _evidence(
    *,
    source_type: SourceType = SourceType.LITERATURE,
    species: str = "Homo sapiens",
    method: str = "RNA-seq",
    quote: str = "IL23R was increased in inflamed biopsies (n=24).",
    metadata: dict | None = None,
) -> Evidence:
    return Evidence(
        evidence_id="ev-1",
        source_type=source_type,
        source_id="doc:1",
        title="IL23R evidence",
        chunk_id="chunk-1",
        quote=quote,
        species=species,
        method=method,
        metadata=metadata or {"pub_types": ["Journal Article"]},
    )


class TestEvidenceGrader(unittest.TestCase):
    def setUp(self) -> None:
        self.grader = EvidenceGrader()

    def test_human_rna_seq_n24_is_a(self) -> None:
        item = self.grader.grade(
            _evidence(quote="IL23R increased in 24 patients and 20 controls (n=24).")
        )
        self.assertEqual(item.level, EvidenceLevel.A)
        self.assertIn("grade", item.metadata)

    def test_human_qpcr_n18_is_b(self) -> None:
        item = self.grader.grade(
            _evidence(method="qPCR", quote="IL23R mRNA increased (n=18).")
        )
        self.assertEqual(item.level, EvidenceLevel.B)

    def test_mouse_in_vivo_is_b(self) -> None:
        item = self.grader.grade(
            _evidence(
                source_type=SourceType.ELN,
                species="Mus musculus",
                method="Western blot",
                quote="IL23R protein was not changed (n=8).",
                metadata={
                    "study_type": "体内验证 / in vivo mouse model",
                    "result_polarity": "negative",
                },
            )
        )
        self.assertEqual(item.level, EvidenceLevel.B)

    def test_organoid_is_c(self) -> None:
        item = self.grader.grade(
            _evidence(
                source_type=SourceType.ELN,
                species="Homo sapiens",
                method="qPCR",
                quote="IL23R mRNA was not changed (n=4).",
                metadata={"study_type": "体外实验 / in vitro"},
            )
        )
        self.assertEqual(item.level, EvidenceLevel.C)

    def test_patent_without_embodiment_is_d(self) -> None:
        item = self.grader.grade(
            _evidence(
                source_type=SourceType.PATENT,
                species="Homo sapiens",
                method="patent claims",
                quote="A method of treating IBD.",
                metadata={"has_embodiments": False},
            )
        )
        self.assertEqual(item.level, EvidenceLevel.D)

    def test_omics_is_c(self) -> None:
        item = self.grader.grade(
            _evidence(
                source_type=SourceType.OMICS,
                species="Homo sapiens",
                method="RNA expression profiling",
                quote="IL23R tissue nTPM 1.0.",
                metadata={},
            )
        )
        self.assertEqual(item.level, EvidenceLevel.C)


if __name__ == "__main__":
    unittest.main()
