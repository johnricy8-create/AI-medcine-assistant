"""引用校验：evidence_id 存在、ACL 可访问、quote 是 chunk 子串。"""

from __future__ import annotations

from app.ingest.chunker import Chunk
from app.ingest.models import normalize_text
from app.schemas import Claim, Evidence, Stance


class CitationVerifier:
    def __init__(self, chunks: dict[str, Chunk]) -> None:
        self.chunks = chunks

    def verify(
        self,
        claims: list[Claim],
        evidence: list[Evidence],
        allowed_scopes: list[str],
    ) -> tuple[list[Claim], list[str]]:
        evidence_map = {item.evidence_id: item for item in evidence}
        allowed = set(allowed_scopes)
        verified_claims: list[Claim] = []
        notes: list[str] = []

        for claim in claims:
            claim_notes: list[str] = []
            support = [
                item
                for item in claim.support_ids
                if self._valid(item, evidence_map, allowed, claim_notes)
            ]
            contradict = [
                item
                for item in claim.contradict_ids
                if self._valid(item, evidence_map, allowed, claim_notes)
            ]
            if claim.stance == Stance.SUPPORT and not support:
                notes.extend(f"{claim.claim_id}: {note}" for note in claim_notes)
                notes.append(f"{claim.claim_id}: 支持证据校验失败，已丢弃")
                continue
            if claim.stance == Stance.CONTRADICT and not contradict:
                notes.extend(f"{claim.claim_id}: {note}" for note in claim_notes)
                notes.append(f"{claim.claim_id}: 反例证据校验失败，已丢弃")
                continue
            if claim.stance == Stance.NEUTRAL and not support and not contradict:
                notes.extend(f"{claim.claim_id}: {note}" for note in claim_notes)
                notes.append(f"{claim.claim_id}: 无有效引用，已丢弃")
                continue
            claim.support_ids = list(dict.fromkeys(support))
            claim.contradict_ids = list(dict.fromkeys(contradict))
            claim.verified = not claim_notes
            claim.verify_notes = claim_notes
            if claim_notes:
                notes.extend(f"{claim.claim_id}: {note}" for note in claim_notes)
            verified_claims.append(claim)

        return verified_claims, notes

    def _valid(
        self,
        evidence_id: str,
        evidence_map: dict[str, Evidence],
        allowed: set[str],
        notes: list[str],
    ) -> bool:
        item = evidence_map.get(evidence_id)
        if item is None:
            notes.append(f"{evidence_id} 不存在")
            return False
        if allowed and item.acl_scope not in allowed:
            notes.append(f"{evidence_id} ACL 不可访问")
            return False
        if not item.quote.strip():
            notes.append(f"{evidence_id} 缺少原文片段")
            return False
        chunk = self.chunks.get(item.chunk_id)
        if chunk is None:
            # 工具证据没有文本 chunk；保留但标记未做 quote 校验。
            if not item.chunk_id.startswith("tool:"):
                notes.append(f"{evidence_id} 缺少 chunk 原文")
            return True
        quote = normalize_text(item.quote)
        chunk_text = normalize_text(chunk.text)
        if quote and quote not in chunk_text:
            notes.append(f"{evidence_id} quote 不是 chunk 子串")
            return False
        return True
