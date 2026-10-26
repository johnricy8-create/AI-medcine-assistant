"""Europe PMC 文献抓取与 JATS XML 解析。

只抓公开可访问的元数据/摘要；全文仅对 PMC/Europe PMC 开放获取记录抓取，
并在 manifest 中记录 license（缺失时明确标注 unknown）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from lxml import etree

from app.ingest.manifest import write_json
from app.ingest.models import (
    DocumentSection,
    FetchedDocument,
    NormalizedDocument,
    normalize_text,
)
from app.schemas import SourceType

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

DEFAULT_QUERIES = [
    'TITLE_ABS:"IL23R" AND TITLE_ABS:("inflammatory bowel disease" OR "Crohn" OR "ulcerative colitis")',
    'TITLE_ABS:"NOD2" AND TITLE_ABS:("inflammatory bowel disease" OR "Crohn" OR "ulcerative colitis")',
    'TITLE_ABS:("IL-23" OR "IL23") AND TITLE_ABS:("inflammatory bowel disease" OR "ulcerative colitis")',
    'TITLE_ABS:"IL23R" AND TITLE_ABS:("CD4" OR "T cell" OR "Th17" OR "Treg" OR "innate lymphoid")',
    'TITLE_ABS:"NOD2" AND TITLE_ABS:("autophagy" OR "innate immunity" OR "Paneth" OR "pattern recognition")',
    'TITLE_ABS:("inflammatory bowel disease" OR "Crohn" OR "ulcerative colitis") AND TITLE_ABS:("single-cell" OR "RNA-seq" OR "biopsy")',
]

IBD_TERMS = ("inflammatory bowel", "crohn", "ulcerative colitis", "ibd")
TARGET_TERMS = ("il23r", "il-23r", "il23", "il-23", "nod2", "card15")

MAX_DOC_CHARS = 80_000
MAX_SECTION_CHARS = 8_000
MAX_ABSTRACT_CHARS = 5_000

ENTITY_IDS = {
    "IL23R": "ENSG00000162594",
    "IL-23R": "ENSG00000162594",
    "NOD2": "ENSG00000167207",
    "CARD15": "ENSG00000167207",
    "IL23A": "ENSG00000110944",
    "IL-23": "ENSG00000110944",
    "inflammatory bowel disease": "MONDO_0005265",
    "Crohn": "MONDO_0005011",
    "ulcerative colitis": "MONDO_0005101",
}


class EuropePmcClient:
    def __init__(self, timeout: int = 60, delay: float = 0.25) -> None:
        self.timeout = timeout
        self.delay = delay
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "pharma-research-agent/0.1 (teaching demo; contact: local)",
                "Accept": "application/json, application/xml;q=0.9, */*;q=0.8",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.get(url, params=params)
                response.raise_for_status()
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Europe PMC 请求失败: {url}: {last_error}") from last_error

    def search(
        self,
        query: str,
        *,
        max_records: int = 50,
        page_size: int = 50,
        sort: str = "CITED desc",
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor = "*"
        while len(results) < max_records:
            response = self._get(
                SEARCH_URL,
                {
                    "query": query,
                    "format": "json",
                    "resultType": "core",
                    "pageSize": min(page_size, max_records - len(results)),
                    "cursorMark": cursor,
                    "sort": sort,
                },
            )
            data = response.json()
            batch = data.get("resultList", {}).get("result", [])
            if not batch:
                break
            results.extend(_compact_record(record) for record in batch)
            next_cursor = data.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(self.delay)
        return results[:max_records]

    def fetch_full_text(self, pmcid: str, raw_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
        url = FULLTEXT_URL.format(pmcid=pmcid)
        try:
            response = self._get(url)
        except Exception:  # noqa: BLE001
            return None, None
        content = response.content
        if not content.lstrip().startswith(b"<"):
            return None, None
        target = raw_dir / f"{pmcid}.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        try:
            parsed = parse_full_text_xml(content)
        except Exception:  # noqa: BLE001
            return None, str(target)
        return parsed, str(target)

    def fetch_corpus(
        self,
        data_dir: Path,
        *,
        target_count: int = 100,
        fulltext_count: int = 40,
        queries: list[str] | None = None,
    ) -> list[FetchedDocument]:
        raw_dir = data_dir / "raw" / "europe_pmc"
        fulltext_raw_dir = raw_dir / "fulltext"
        raw_dir.mkdir(parents=True, exist_ok=True)

        queries = queries or DEFAULT_QUERIES
        candidates: dict[str, dict[str, Any]] = {}
        for query in queries:
            if len(candidates) >= target_count * 3:
                break
            for record in self.search(query, max_records=60):
                key = _record_key(record)
                if key and key not in candidates:
                    candidates[key] = record
            time.sleep(self.delay)

        relevant = [
            record
            for record in candidates.values()
            if record.get("title")
            and (record.get("abstractText") or record.get("pmcid"))
            and _relevance_score(record) >= 0
        ]
        ordered = sorted(
            relevant,
            key=lambda item: (_relevance_score(item), int(item.get("citedByCount") or 0)),
            reverse=True,
        )
        write_json(raw_dir / "search.json", ordered)

        fulltext_candidates = [
            record
            for record in ordered
            if record.get("pmcid")
            and record.get("isOpenAccess") in {"Y", "y"}
            and record.get("inPMC") in {"Y", "y"}
        ][: min(fulltext_count + 10, target_count)]
        fulltext_keys = {_record_key(record) for record in fulltext_candidates}

        selected: list[dict[str, Any]] = list(fulltext_candidates)
        for record in ordered:
            if len(selected) >= target_count:
                break
            if _record_key(record) not in fulltext_keys:
                selected.append(record)

        fetched: list[FetchedDocument] = []
        for record in selected:
            parsed: dict[str, Any] | None = None
            raw_path: str | None = None
            parse_status = "ok_abstract"
            if record.get("pmcid") and _record_key(record) in fulltext_keys:
                parsed, raw_path = self.fetch_full_text(record["pmcid"], fulltext_raw_dir)
                parse_status = "ok_fulltext" if parsed else "ok_abstract_fulltext_failed"
                time.sleep(self.delay)
            document = build_document(record, parsed)
            fetched.append(
                FetchedDocument(
                    document=document,
                    source="Europe PMC",
                    raw_path=raw_path or str(raw_dir / "search.json"),
                    parse_status=parse_status,
                )
            )
        return fetched


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    full_text_ids = record.get("fullTextIdList", {}).get("fullTextId", [])
    pub_types = record.get("pubTypeList", {}).get("pubType", [])
    mesh = [
        item.get("descriptorName", "")
        for item in record.get("meshHeadingList", {}).get("meshHeading", [])
        if item.get("descriptorName")
    ]
    return {
        "id": record.get("id"),
        "source": record.get("source"),
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid") or (full_text_ids[0] if full_text_ids else None),
        "doi": record.get("doi"),
        "title": record.get("title") or "",
        "authorString": record.get("authorString") or "",
        "journalTitle": record.get("journalTitle") or "",
        "pubYear": record.get("pubYear"),
        "abstractText": record.get("abstractText") or "",
        "isOpenAccess": record.get("isOpenAccess"),
        "inEPMC": record.get("inEPMC"),
        "inPMC": record.get("inPMC"),
        "license": record.get("license") or "",
        "pubTypes": pub_types,
        "meshTerms": mesh,
        "citedByCount": record.get("citedByCount") or 0,
        "firstPublicationDate": record.get("firstPublicationDate"),
    }


def _record_key(record: dict[str, Any]) -> str | None:
    return (
        record.get("pmcid")
        or record.get("pmid")
        or record.get("doi")
        or record.get("id")
    )


def parse_full_text_xml(xml_bytes: bytes) -> dict[str, Any]:
    """解析 Europe PMC JATS XML，返回标题、摘要和章节/图表。"""
    tree = etree.fromstring(xml_bytes)
    title = _first_text(tree, ".//*[local-name()='article-title']")
    abstract_parts = [
        _text(element)
        for element in tree.xpath("//*[local-name()='abstract']")
    ]
    abstract = "\n".join(_dedupe_nonempty(abstract_parts))

    sections: list[DocumentSection] = []
    seen: set[str] = set()
    for sec in tree.xpath("//*[local-name()='body']//*[local-name()='sec']"):
        heading = _first_text(sec, "./*[local-name()='title']")
        paragraphs: list[str] = []
        for child in sec:
            tag = _local_name(child)
            if tag in {"p", "list", "disp-quote", "boxed-text"}:
                paragraph = _text(child)
                if paragraph:
                    paragraphs.append(paragraph)
        body = "\n".join(paragraphs)
        if not body:
            continue
        key = body[:160]
        if key in seen:
            continue
        seen.add(key)
        sections.append(DocumentSection(heading=heading, text=body, kind="body"))

    if not sections:
        body = " ".join(
            _text(paragraph)
            for paragraph in tree.xpath("//*[local-name()='body']//*[local-name()='p']")
        )
        if body:
            sections.append(DocumentSection(heading="Body", text=body, kind="body"))

    for figure in tree.xpath("//*[local-name()='fig']"):
        label = _first_text(figure, "./*[local-name()='label']")
        caption = _first_text(figure, "./*[local-name()='caption']")
        text = " ".join(part for part in (label, caption) if part)
        if text:
            sections.append(
                DocumentSection(heading=label or "Figure", text=text, kind="figure")
            )

    for table in tree.xpath("//*[local-name()='table-wrap']"):
        label = _first_text(table, "./*[local-name()='label']")
        caption = _first_text(table, "./*[local-name()='caption']")
        text = " ".join(part for part in (label, caption, _text(table)) if part)
        if text:
            sections.append(
                DocumentSection(
                    heading=label or "Table",
                    text=text[:3000],
                    kind="table",
                )
            )

    return {
        "title": title,
        "abstract": abstract,
        "sections": sections,
    }


def build_document(
    record: dict[str, Any],
    full_text: dict[str, Any] | None,
) -> NormalizedDocument:
    source_id = (
        record.get("pmcid")
        or record.get("pmid")
        or record.get("doi")
        or str(record.get("id"))
    )
    title = normalize_text(
        (full_text or {}).get("title") or record.get("title") or source_id
    )
    abstract = normalize_text(
        (full_text or {}).get("abstract") or record.get("abstractText") or ""
    )[:MAX_ABSTRACT_CHARS]
    sections: list[DocumentSection] = (full_text or {}).get("sections") or []
    if not sections and abstract:
        sections = [DocumentSection(heading="Abstract", text=abstract, kind="abstract")]
    sections, truncated = _truncate_sections(sections)

    body_text = "\n\n".join(
        f"{section.heading}\n{section.text}" if section.heading else section.text
        for section in sections
    )
    text = "\n\n".join(part for part in (title, abstract, body_text) if part)
    if len(text) > MAX_DOC_CHARS + MAX_ABSTRACT_CHARS:
        text = text[: MAX_DOC_CHARS + MAX_ABSTRACT_CHARS].rstrip() + "\n\n[TRUNCATED]"
        truncated = True

    license_value = record.get("license") or "unknown"
    if full_text and license_value == "unknown":
        license_value = "Europe PMC full text (license metadata missing)"

    year_value = record.get("pubYear")
    year = int(year_value) if str(year_value).isdigit() else None

    authors = [
        author.strip()
        for author in (record.get("authorString") or "").split(",")
        if author.strip()
    ][:20]

    metadata = {
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid"),
        "doi": record.get("doi"),
        "journal": record.get("journalTitle"),
        "pub_types": record.get("pubTypes", []),
        "mesh_terms": record.get("meshTerms", []),
        "cited_by_count": record.get("citedByCount", 0),
        "is_open_access": record.get("isOpenAccess"),
        "in_pmc": record.get("inPMC"),
        "full_text_used": bool(full_text),
        "first_publication_date": record.get("firstPublicationDate"),
        "truncated": truncated,
        "text_chars": len(text),
    }

    document = NormalizedDocument(
        doc_id=f"paper:{source_id}",
        source_type=SourceType.LITERATURE,
        source_id=source_id,
        title=title,
        text=text,
        sections=sections,
        abstract=abstract,
        authors=authors,
        journal=record.get("journalTitle") or None,
        year=year,
        doi=record.get("doi") or None,
        url=f"https://europepmc.org/article/{record.get('source') or 'MED'}/{record.get('id')}",
        license=license_value,
        acl_scope="public",
        species=infer_species(text),
        sample=infer_sample(text),
        method=infer_method(text),
        entity_ids=extract_entity_ids(text),
        metadata=metadata,
    )
    return document.finalize()


def _relevance_score(record: dict[str, Any]) -> int:
    """标题/摘要必须与 IBD 相关；靶点匹配越多，排序越靠前。"""
    text = f"{record.get('title', '')} {record.get('abstractText', '')}".lower()
    if not any(term in text for term in IBD_TERMS):
        return -1
    return sum(1 for term in TARGET_TERMS if term in text)


def _truncate_sections(
    sections: list[DocumentSection],
) -> tuple[list[DocumentSection], bool]:
    result: list[DocumentSection] = []
    total = 0
    truncated = False
    for section in sections:
        text = section.text
        if len(text) > MAX_SECTION_CHARS:
            text = text[:MAX_SECTION_CHARS].rstrip() + " …"
            truncated = True
        remaining = MAX_DOC_CHARS - total
        if remaining <= 200:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining].rstrip() + " …"
            truncated = True
        if text:
            result.append(section.model_copy(update={"text": text}))
            total += len(text)
    return result, truncated


def infer_species(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ("mouse", "mice", "murine")):
        return "Mus musculus"
    if any(word in lower for word in ("rat ", "rats", "rat.")):
        return "Rattus norvegicus"
    if any(word in lower for word in ("human", "patient", "patients", "biopsy", "biopsies")):
        return "Homo sapiens"
    return "unknown"


def infer_sample(text: str) -> str | None:
    lower = text.lower()
    for keyword, label in (
        ("single-cell", "single-cell suspension"),
        ("single cell", "single-cell suspension"),
        ("organoid", "organoid"),
        ("pbmc", "PBMC"),
        ("biopsy", "intestinal biopsy"),
        ("biopsies", "intestinal biopsy"),
        ("cell line", "cell line"),
        ("whole blood", "whole blood"),
    ):
        if keyword in lower:
            return label
    return None


def infer_method(text: str) -> str | None:
    lower = text.lower()
    for keyword, label in (
        ("single-cell rna", "single-cell RNA-seq"),
        ("scrna", "single-cell RNA-seq"),
        ("rna-seq", "RNA-seq"),
        ("rna sequencing", "RNA-seq"),
        ("western blot", "Western blot"),
        ("immunohistochem", "IHC"),
        ("flow cytometry", "flow cytometry"),
        ("qpcr", "qPCR"),
        ("quantitative pcr", "qPCR"),
        ("genome-wide association", "GWAS"),
        ("gwas", "GWAS"),
    ):
        if keyword in lower:
            return label
    return None


def extract_entity_ids(text: str) -> list[str]:
    lower = text.lower()
    ids: list[str] = []
    for term, entity_id in ENTITY_IDS.items():
        if term.lower() in lower and entity_id not in ids:
            ids.append(entity_id)
    return ids


def _first_text(element: etree._Element, xpath: str) -> str:
    matches = element.xpath(xpath)
    return _text(matches[0]) if matches else ""


def _text(element: etree._Element) -> str:
    return normalize_text(" ".join("".join(element.itertext()).split()))


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _dedupe_nonempty(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        part = normalize_text(part)
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return result
