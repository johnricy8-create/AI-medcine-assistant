"""科学切块：父块提供上下文，子块用于检索。

设计：
- 论文按章节，ELN 按实验记录，专利按权利要求，项目报告按章节；
- 父块保留完整章节/实验上下文；
- 子块 500 字左右，带重叠，避免截断英文词、DOI、错误码；
- chunk_id 由 doc_id + section + page + 顺序 + 文本哈希生成，重复运行稳定；
- 表格整表优先保留表头，超长时才切分。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from pydantic import BaseModel, Field

from app.config import Settings
from app.ingest.models import DocumentSection, NormalizedDocument
from app.schemas import SourceType

SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\.])\s*")
WORD_BOUNDARY = re.compile(r"\s+")


class Chunk(BaseModel):
    chunk_id: str
    parent_id: str
    doc_id: str
    source_type: SourceType
    title: str
    text: str
    embed_text: str
    parent_text: str
    section_path: str = ""
    page_number: int | None = None
    figure: str | None = None
    table_ref: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    species: str | None = None
    sample: str | None = None
    method: str | None = None
    stance_hint: str = "unknown"
    result_polarity: str = "unknown"
    acl_scope: str = "public"
    project_id: str | None = None
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_chroma_metadata(self) -> dict[str, str | int | float | bool]:
        """Chroma 元数据只接受标量；列表/字典序列化为 JSON 字符串。"""
        return {
            "chunk_id": self.chunk_id,
            "parent_id": self.parent_id,
            "doc_id": self.doc_id,
            "source_type": self.source_type.value,
            "title": self.title,
            "text": self.text,
            "section_path": self.section_path,
            "page_number": self.page_number if self.page_number is not None else -1,
            "figure": self.figure or "",
            "table_ref": self.table_ref or "",
            "entity_ids_json": ",".join(self.entity_ids),
            "species": self.species or "unknown",
            "sample": self.sample or "",
            "method": self.method or "",
            "stance_hint": self.stance_hint,
            "result_polarity": self.result_polarity,
            "acl_scope": self.acl_scope,
            "project_id": self.project_id or "",
            "token_count": self.token_count,
        }


def chunk_documents(
    documents: Iterable[NormalizedDocument],
    settings: Settings,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, settings))
    return chunks


def chunk_document(document: NormalizedDocument, settings: Settings) -> list[Chunk]:
    chunks: list[Chunk] = []
    parents = _parent_blocks(document, settings)
    for parent_index, parent in enumerate(parents):
        parent_id = _stable_id(
            "par",
            document.doc_id,
            parent_index,
            parent.section_path,
            parent.page_number,
            parent.text,
        )
        max_size = (
            settings.table_chunk_size
            if parent.kind == "table"
            else settings.chunk_size
        )
        overlap = 0 if parent.kind == "table" else settings.chunk_overlap
        children = _split_text(parent.text, max_size, overlap)
        for child_index, child_text in enumerate(children):
            text = child_text.strip()
            if not text:
                continue
            embed_text = _compose_embed_text(
                document.title,
                parent.heading,
                text,
            )
            chunk_id = _stable_id(
                "chk",
                document.doc_id,
                parent.section_path,
                parent.page_number,
                child_index,
                text,
            )
            metadata = {
                "source_id": document.source_id,
                "doi": document.doi,
                "year": document.year,
                "journal": document.journal,
                "section_kind": parent.kind,
                "synthetic": bool(document.metadata.get("synthetic")),
                "demo_notice": document.metadata.get("demo_notice"),
                "truncated": bool(document.metadata.get("truncated")),
            }
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    parent_id=parent_id,
                    doc_id=document.doc_id,
                    source_type=document.source_type,
                    title=document.title,
                    text=text,
                    embed_text=embed_text,
                    parent_text=parent.text,
                    section_path=parent.section_path,
                    page_number=parent.page_number,
                    figure=parent.heading if parent.kind == "figure" else None,
                    table_ref=parent.heading if parent.kind == "table" else None,
                    entity_ids=sorted(set(document.entity_ids)),
                    species=document.species,
                    sample=document.sample,
                    method=document.method,
                    stance_hint="unknown",
                    result_polarity=document.result_polarity,
                    acl_scope=document.acl_scope,
                    project_id=document.project_id,
                    token_count=_approx_tokens(text),
                    metadata=metadata,
                )
            )
    return chunks


class _ParentBlock(BaseModel):
    text: str
    heading: str = ""
    section_path: str = ""
    page_number: int | None = None
    kind: str = "body"


def _parent_blocks(
    document: NormalizedDocument,
    settings: Settings,
) -> list[_ParentBlock]:
    if document.source_type == SourceType.ELN:
        text = document.text.strip()
        if not text:
            return []
        return [
            _ParentBlock(
                text=text,
                heading="Experiment record",
                section_path=document.title,
                kind="body",
            )
        ]

    if document.sections:
        blocks: list[_ParentBlock] = []
        for index, section in enumerate(document.sections):
            text = section.text.strip()
            if not text:
                continue
            heading = section.heading.strip() or f"Section {index + 1}"
            section_path = f"{document.title} > {heading}"
            blocks.append(
                _ParentBlock(
                    text=text,
                    heading=heading,
                    section_path=section_path,
                    page_number=section.page,
                    kind=section.kind,
                )
            )
        if blocks:
            return blocks

    text = document.text.strip()
    if not text:
        return []
    return _split_parent_text(text, settings)


def _split_parent_text(text: str, settings: Settings) -> list[_ParentBlock]:
    """无章节结构的文档：按段落聚合为父块。"""
    target = max(settings.chunk_size * 3, 1200)
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    blocks: list[_ParentBlock] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs or [text]:
        if current and current_len + len(paragraph) > target:
            block_text = "\n\n".join(current)
            blocks.append(
                _ParentBlock(
                    text=block_text,
                    heading=f"Block {len(blocks) + 1}",
                    section_path="",
                    kind="body",
                )
            )
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        block_text = "\n\n".join(current)
        blocks.append(
            _ParentBlock(
                text=block_text,
                heading=f"Block {len(blocks) + 1}",
                section_path="",
                kind="body",
            )
        )
    return blocks


def _split_text(text: str, max_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_size:
        return [text]

    units = _units(text)
    chunks: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        if len(unit) > max_size:
            if current:
                chunks.append(current.strip())
                current = ""
            pieces = _hard_split(unit, max_size)
            chunks.extend(piece for piece in pieces[:-1] if piece.strip())
            current = pieces[-1] if pieces else ""
            continue
        if len(current) + len(unit) <= max_size:
            current += unit
        else:
            if current:
                chunks.append(current.strip())
                current = _tail(current, overlap) + unit
            else:
                current = unit
            if len(current) > max_size:
                pieces = _hard_split(current, max_size)
                chunks.extend(piece for piece in pieces[:-1] if piece.strip())
                current = pieces[-1] if pieces else ""
    if current.strip():
        chunks.append(current.strip())

    # 只去重完全相同的 chunk；不能用前缀去重，否则重复句式会被误删。
    seen: set[str] = set()
    result: list[str] = []
    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            result.append(chunk)
    return result


def _units(text: str) -> list[str]:
    units: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        sentences = [part.strip() for part in SENTENCE_BOUNDARY.split(paragraph) if part.strip()]
        for sentence in sentences:
            units.append(sentence if sentence.endswith((" ", "\n")) else sentence + " ")
    return units


def _hard_split(text: str, max_size: int) -> list[str]:
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_size:
        window = remaining[:max_size]
        split_at = max(window.rfind(" "), window.rfind("，"), window.rfind(","), window.rfind("。"))
        if split_at < max_size // 2:
            split_at = max_size
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail = text[-overlap:]
    boundary = max(tail.rfind(" "), tail.rfind("。"), tail.rfind("，"))
    if boundary > 0:
        tail = tail[boundary + 1 :]
    return tail.strip() + (" " if tail.strip() else "")


def _compose_embed_text(title: str, heading: str, text: str) -> str:
    parts = [part for part in (title, heading, text) if part]
    return "\n".join(parts)


def _approx_tokens(text: str) -> int:
    # BGE-M3 对中文约 1 token/1.5 字，英文约 1 token/4 字符；这里取保守近似。
    return max(1, int(len(text) / 2))


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"
