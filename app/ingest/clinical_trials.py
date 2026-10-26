"""ClinicalTrials.gov API v2 抓取与标准化。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.ingest.europe_pmc import extract_entity_ids
from app.ingest.manifest import write_json
from app.ingest.models import DocumentSection, FetchedDocument, NormalizedDocument
from app.schemas import SourceType

API_URL = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_CONDITIONS = [
    "ulcerative colitis",
    "Crohn disease",
    "inflammatory bowel disease",
]


class ClinicalTrialsClient:
    def __init__(self, timeout: int = 60, delay: float = 0.2) -> None:
        self.timeout = timeout
        self.delay = delay
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "pharma-research-agent/0.1 (teaching demo)"},
        )

    def close(self) -> None:
        self._client.close()

    def search_condition(self, condition: str, page_size: int = 10) -> list[dict[str, Any]]:
        response = self._client.get(
            API_URL,
            params={
                "query.cond": condition,
                "pageSize": page_size,
                "format": "json",
            },
        )
        response.raise_for_status()
        return response.json().get("studies", [])

    def fetch_corpus(
        self,
        data_dir: Path,
        *,
        target_count: int = 10,
        conditions: list[str] | None = None,
    ) -> list[FetchedDocument]:
        raw_dir = data_dir / "raw" / "clinical_trials"
        raw_dir.mkdir(parents=True, exist_ok=True)
        conditions = conditions or DEFAULT_CONDITIONS

        studies: dict[str, dict[str, Any]] = {}
        for condition in conditions:
            for study in self.search_condition(condition, page_size=10):
                nct_id = (
                    study.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("nctId")
                )
                if nct_id and nct_id not in studies:
                    studies[nct_id] = study
            time.sleep(self.delay)

        selected = list(studies.values())[:target_count]
        write_json(raw_dir / "studies.json", selected)

        fetched: list[FetchedDocument] = []
        for study in selected:
            document = build_document(study)
            fetched.append(
                FetchedDocument(
                    document=document,
                    source="ClinicalTrials.gov",
                    raw_path=str(raw_dir / "studies.json"),
                    parse_status="ok",
                )
            )
        return fetched


def build_document(study: dict[str, Any]) -> NormalizedDocument:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    description = protocol.get("descriptionModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    arms = protocol.get("armsInterventionsModule", {})
    outcomes = protocol.get("outcomesModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})

    nct_id = identification.get("nctId", "UNKNOWN")
    title = identification.get("briefTitle") or identification.get("officialTitle") or nct_id
    brief_summary = description.get("briefSummary") or ""
    detailed = description.get("detailedDescription") or ""

    conditions = conditions_module.get("conditions", [])
    interventions = [
        " / ".join(
            part
            for part in (
                item.get("name"),
                item.get("type"),
                item.get("description"),
            )
            if part
        )
        for item in arms.get("interventions", [])
    ]
    primary_outcomes = [
        " / ".join(
            part
            for part in (item.get("measure"), item.get("timeFrame"))
            if part
        )
        for item in outcomes.get("primaryOutcomes", [])
    ]

    phases = design.get("phases", [])
    enrollment = design.get("enrollmentInfo", {}).get("count")
    sections = [
        DocumentSection(heading="Brief summary", text=brief_summary, kind="summary"),
        DocumentSection(
            heading="Detailed description", text=detailed, kind="description"
        ),
        DocumentSection(
            heading="Conditions",
            text="; ".join(conditions),
            kind="conditions",
        ),
        DocumentSection(
            heading="Interventions",
            text="; ".join(interventions),
            kind="interventions",
        ),
        DocumentSection(
            heading="Study design",
            text=(
                f"Study type: {design.get('studyType', 'unknown')}; "
                f"Phases: {', '.join(phases) if phases else 'NA'}; "
                f"Enrollment: {enrollment if enrollment is not None else 'unknown'}"
            ),
            kind="design",
        ),
        DocumentSection(
            heading="Primary outcomes",
            text="; ".join(primary_outcomes),
            kind="outcomes",
        ),
        DocumentSection(
            heading="Eligibility",
            text=eligibility.get("eligibilityCriteria", ""),
            kind="eligibility",
        ),
    ]
    sections = [section for section in sections if section.text.strip()]

    text = "\n\n".join(
        f"{section.heading}\n{section.text}" for section in sections
    )
    metadata = {
        "nct_id": nct_id,
        "overall_status": status.get("overallStatus"),
        "phases": phases,
        "study_type": design.get("studyType"),
        "enrollment": enrollment,
        "conditions": conditions,
        "interventions": interventions,
        "sponsor": sponsor.get("name"),
        "start_date": status.get("startDateStruct", {}).get("date"),
        "completion_date": status.get("completionDateStruct", {}).get("date"),
        "org_study_id": identification.get("orgStudyIdInfo", {}).get("id"),
    }

    document = NormalizedDocument(
        doc_id=f"trial:{nct_id}",
        source_type=SourceType.TRIAL,
        source_id=nct_id,
        title=title,
        text=f"{title}\n\n{text}",
        sections=sections,
        abstract=brief_summary,
        year=_year(status.get("startDateStruct", {}).get("date")),
        url=f"https://clinicaltrials.gov/study/{nct_id}",
        license="ClinicalTrials.gov public data",
        acl_scope="public",
        species="Homo sapiens",
        sample="clinical trial",
        method="clinical trial",
        entity_ids=extract_entity_ids(f"{title}\n{text}"),
        metadata=metadata,
    )
    return document.finalize()


def _year(value: str | None) -> int | None:
    if value and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None
