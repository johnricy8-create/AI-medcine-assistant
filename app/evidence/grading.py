"""确定性证据分级（A/B/C/D）。

LLM 只提供/归纳证据内容，不负责定级；等级由规则和元数据计算。
"""

from __future__ import annotations

import re
from typing import Iterable

from pydantic import BaseModel, Field

from app.schemas import Evidence, EvidenceLevel, SourceType

_N_PATTERN = re.compile(r"\bn\s*=\s*(\d+)", re.IGNORECASE)
_REPLICATION_TERMS = (
    "独立队列",
    "replicate",
    "replicated",
    "validation",
    "validated",
    "two cohorts",
    "multiple cohorts",
    "multi-cohort",
    "复现",
)


class GradeBreakdown(BaseModel):
    directness: int
    species_relevance: int
    method_strength: int
    replication: int
    sample_size: int
    consistency: int
    score: int
    level: EvidenceLevel
    rationale: str


class EvidenceGrader:
    def grade(self, evidence: Evidence) -> Evidence:
        breakdown = self.breakdown(evidence)
        evidence.level = breakdown.level
        evidence.metadata["grade"] = breakdown.model_dump(mode="json")
        return evidence

    def grade_all(self, evidence: Iterable[Evidence]) -> list[Evidence]:
        return [self.grade(item) for item in evidence]

    def breakdown(self, evidence: Evidence) -> GradeBreakdown:
        meta = evidence.metadata or {}
        text = " ".join(
            filter(
                None,
                [
                    evidence.title,
                    evidence.quote,
                    evidence.sample or "",
                    evidence.method or "",
                    str(meta.get("conditions", "")),
                    str(meta.get("result", "")),
                ],
            )
        ).casefold()
        pub_types = " ".join(
            str(item).casefold() for item in meta.get("pub_types", [])
        )
        study_type = str(meta.get("study_type") or "").casefold()
        species = (evidence.species or "").casefold()
        method = (evidence.method or "").casefold()
        source = evidence.source_type

        directness = self._directness(
            source, species, study_type, text, pub_types, meta
        )
        species_score = self._species_score(source, species, study_type)
        method_score = self._method_score(source, method, pub_types)
        replication = self._replication_score(source, text, pub_types)
        sample = self._sample_score(source, text, meta)
        consistency = 3 if source == SourceType.PATENT or "review" in pub_types else 5

        score = directness + species_score + method_score + replication + sample + consistency
        level = _level(score)
        rationale = (
            f"directness={directness}, species={species_score}, "
            f"method={method_score}, replication={replication}, "
            f"sample={sample}, consistency={consistency} → {level.value}"
        )
        return GradeBreakdown(
            directness=directness,
            species_relevance=species_score,
            method_strength=method_score,
            replication=replication,
            sample_size=sample,
            consistency=consistency,
            score=score,
            level=level,
            rationale=rationale,
        )

    def _directness(
        self,
        source: SourceType,
        species: str,
        study_type: str,
        text: str,
        pub_types: str,
        meta: dict,
    ) -> int:
        if source == SourceType.PATENT:
            return 12 if meta.get("has_embodiments") else 4
        if "review" in pub_types:
            return 12
        if source in {SourceType.OMICS, SourceType.DATABASE}:
            return 12
        if source == SourceType.TRIAL:
            return 26
        if source == SourceType.ELN:
            if "体外" in study_type or "in vitro" in study_type:
                return 15
            if "homo sapiens" in species or "人体" in study_type:
                return 30
            if "mus musculus" in species or "体内" in study_type:
                return 22
            return 18
        if "homo sapiens" in species or "human" in text:
            return 28
        if "mus musculus" in species or "mouse" in text:
            return 20
        return 12

    def _species_score(
        self,
        source: SourceType,
        species: str,
        study_type: str,
    ) -> int:
        if source == SourceType.PATENT:
            return 5
        if "homo sapiens" in species or "人体" in study_type:
            return 20
        if "mus musculus" in species or "体内" in study_type:
            return 12
        if "体外" in study_type or "in vitro" in study_type:
            return 8
        if source in {SourceType.OMICS, SourceType.DATABASE}:
            return 15
        return 5

    def _method_score(
        self,
        source: SourceType,
        method: str,
        pub_types: str,
    ) -> int:
        if source == SourceType.PATENT:
            return 5
        if "review" in pub_types:
            return 8
        if source == SourceType.OMICS:
            return 10
        if source == SourceType.TRIAL:
            return 14
        if any(term in method for term in ("western", "protein", "elisa")):
            return 15
        if any(term in method for term in ("ihc", "immunohist")):
            return 14
        if "flow" in method:
            return 13
        if any(term in method for term in ("qpcr", "pcr", "rna-seq", "sequencing")):
            return 12
        if "single-cell" in method or "single cell" in method:
            return 11
        return 10

    def _replication_score(
        self,
        source: SourceType,
        text: str,
        pub_types: str,
    ) -> int:
        if source == SourceType.PATENT or "review" in pub_types:
            return 2
        if any(term in text for term in _REPLICATION_TERMS):
            return 15
        if source == SourceType.ELN:
            return 5
        return 7

    def _sample_score(
        self,
        source: SourceType,
        text: str,
        meta: dict,
    ) -> int:
        if source == SourceType.PATENT:
            return 2
        values = [
            int(value)
            for value in _N_PATTERN.findall(text)
            if value.isdigit()
        ]
        enrollment = meta.get("enrollment")
        if isinstance(enrollment, int):
            values.append(enrollment)
        if not values:
            return 2
        largest = max(values)
        if largest >= 20:
            return 10
        if largest >= 8:
            return 7
        if largest >= 4:
            return 4
        return 2


def _level(score: int) -> EvidenceLevel:
    if score >= 80:
        return EvidenceLevel.A
    if score >= 65:
        return EvidenceLevel.B
    if score >= 45:
        return EvidenceLevel.C
    return EvidenceLevel.D
