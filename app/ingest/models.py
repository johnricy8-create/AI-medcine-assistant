"""P1 数据模型：标准化文档、章节、manifest。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.schemas import SourceType

_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentSection(BaseModel):
    heading: str = ""
    text: str
    kind: str = "body"
    page: int | None = None


class NormalizedDocument(BaseModel):
    """跨数据源统一的文档表示。

    text 用于最终切块；sections 保留章节结构，供科学切块优先使用。
    """

    doc_id: str
    source_type: SourceType
    source_id: str
    title: str
    text: str
    sections: list[DocumentSection] = Field(default_factory=list)
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    license: str | None = None
    acl_scope: str = "public"
    project_id: str | None = None
    species: str | None = None
    sample: str | None = None
    method: str | None = None
    result_polarity: str = "unknown"
    entity_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=utcnow)
    content_hash: str = ""

    def finalize(self) -> "NormalizedDocument":
        if not self.text.strip():
            self.text = self.abstract.strip()
        self.text = normalize_text(self.text)
        for section in self.sections:
            section.text = normalize_text(section.text)
        self.sections = [s for s in self.sections if s.text]
        if not self.content_hash:
            from app.ingest.manifest import sha256_text

            self.content_hash = sha256_text(self.title + "\n" + self.text)
        return self


class ManifestEntry(BaseModel):
    doc_id: str
    source_type: str
    source_id: str
    title: str
    source: str
    source_url: str | None = None
    license: str | None = None
    retrieved_at: datetime
    content_hash: str
    acl_scope: str = "public"
    project_id: str | None = None
    raw_path: str | None = None
    parse_status: str = "ok"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_document(
        cls,
        document: NormalizedDocument,
        *,
        source: str,
        raw_path: str | None = None,
        parse_status: str = "ok",
    ) -> "ManifestEntry":
        return cls(
            doc_id=document.doc_id,
            source_type=document.source_type.value,
            source_id=document.source_id,
            title=document.title,
            source=source,
            source_url=document.url,
            license=document.license,
            retrieved_at=document.retrieved_at,
            content_hash=document.content_hash,
            acl_scope=document.acl_scope,
            project_id=document.project_id,
            raw_path=raw_path,
            parse_status=parse_status,
            metadata=document.metadata,
        )


@dataclass
class FetchedDocument:
    """抓取结果：标准化文档 + 来源信息，供 pipeline 统一写 manifest。"""

    document: NormalizedDocument
    source: str
    raw_path: str | None = None
    parse_status: str = "ok"


def normalize_text(text: str) -> str:
    """清理 HTML 标签、实体和空白，但保留段落边界。"""
    text = html.unescape(text)
    text = _HTML_TAG.sub(" ", text)
    lines = [" ".join(line.split()) for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()
