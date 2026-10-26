"""Claims 综合：LLM JSON + 规则抽取兜底。

LLM 只负责归纳与引用 evidence_id；等级由 EvidenceGrader 计算，
引用必须经过 CitationVerifier。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.evidence.selection import question_focus, select_evidence_for_synthesis
from app.schemas import (
    Claim,
    Conflict,
    Evidence,
    EvidenceLevel,
    SourceType,
    Stance,
)

logger = logging.getLogger(__name__)

NEGATIVE_TERMS = (
    "not changed",
    "no significant",
    "no effect",
    "failed",
    "negative",
    "inconclusive",
    "未观察到",
    "无显著",
    "未重复",
    "未升高",
    "不升高",
    "未见",
    "阴性",
    "没有直接",
    "没有影响",
    "没有显著",
    "没有明显",
    "无直接",
    "无明显",
    "不支持",
)
POSITIVE_TERMS = (
    "increased",
    "upregulated",
    "elevated",
    "positive",
    "升高",
    "上调",
    "富集",
    "阳性",
    "支持",
)
LEVEL_ORDER = {
    EvidenceLevel.A: 4,
    EvidenceLevel.B: 3,
    EvidenceLevel.C: 2,
    EvidenceLevel.D: 1,
    EvidenceLevel.UNKNOWN: 0,
}


class ClaimDraft(BaseModel):
    text: str
    stance: Stance = Stance.NEUTRAL
    level: EvidenceLevel = EvidenceLevel.UNKNOWN
    support_ids: list[str] = Field(default_factory=list)
    contradict_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    caveats: list[str] = Field(default_factory=list)


class ConflictDraft(BaseModel):
    topic: str = ""
    support_ids: list[str] = Field(default_factory=list)
    contradict_ids: list[str] = Field(default_factory=list)
    explanation: str = ""


class SynthesisBundle(BaseModel):
    assessment: str = ""
    claims: list[ClaimDraft] = Field(default_factory=list)
    conflicts: list[ConflictDraft] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class SynthesisResult(BaseModel):
    assessment: str
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    llm_used: bool = False
    model: str | None = None


SYSTEM_PROMPT = """你是医药研发证据综合助手。你的任务是把给定证据整理成可复核的研究底稿。

硬性规则：
1. 只能使用“证据列表”中出现的 evidence_id；不得编造 id、文献、专利、实验或数字。
2. 每条 claim 必须至少引用一个 support_id 或 contradict_ids；没有证据就写“证据不足”。
3. 区分事实、相关性、推断和建议实验；不要把相关性写成因果。
4. 主动并列支持证据与反例/阴性结果，不得只保留正面结论。
5. stance 是相对于“研究问题所检验的正向假设”：support=支持正向/升高/有效；contradict=阴性、无变化、相反、失败；neutral=描述性/不确定。
6. 证据等级由系统计算，你不要自行夸大；level 可填 unknown。
7. 输出严格 JSON，不要 markdown，不要解释。

JSON schema：
{
  "assessment": "一句话判断，明确证据强度与不确定性",
  "claims": [
    {
      "text": "结论句",
      "stance": "support|contradict|neutral",
      "level": "A|B|C|D|unknown",
      "support_ids": ["ev-..."],
      "contradict_ids": ["ev-..."],
      "confidence": 0.0,
      "caveats": ["限制"]
    }
  ],
  "conflicts": [
    {"topic": "冲突主题", "support_ids": ["ev-..."], "contradict_ids": ["ev-..."], "explanation": "为什么冲突"}
  ],
  "gaps": ["数据缺口"],
  "next_steps": ["建议的下一步实验"]
}
"""


class ClaimSynthesizer:
    def synthesize(
        self,
        question: str,
        evidence: list[Evidence],
        *,
        llm: Any | None = None,
        max_evidence: int = 20,
    ) -> SynthesisResult:
        if not evidence:
            return SynthesisResult(
                assessment="没有可用证据，无法形成研究结论。",
                gaps=["缺少可用证据"],
            )
        selected = select_evidence_for_synthesis(
            question,
            evidence,
            max_evidence=max_evidence,
        )
        if llm is not None:
            try:
                result = self._llm_synthesize(
                    question,
                    selected,
                    llm=llm,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM claims 失败，回退抽取式: %s", exc)
                result = self._fallback(question, selected)
        else:
            result = self._fallback(question, selected)
        result.claims = _ensure_internal_evidence_coverage(
            question,
            result.claims,
            selected,
        )
        if not result.conflicts:
            result.conflicts = _infer_conflicts(question, result.claims)
        return result

    def _llm_synthesize(
        self,
        question: str,
        selected: list[Evidence],
        *,
        llm: Any,
    ) -> SynthesisResult:
        evidence_map = {item.evidence_id: item for item in selected}
        lines = []
        for item in selected:
            lines.append(
                f"- evidence_id: {item.evidence_id}\n"
                f"  source_type: {item.source_type.value}\n"
                f"  title: {item.title}\n"
                f"  section: {item.locator.section or ''}\n"
                f"  species: {item.species or 'unknown'}\n"
                f"  sample: {item.sample or ''}\n"
                f"  method: {item.method or ''}\n"
                f"  level: {item.level.value}\n"
                f"  result_polarity: {item.metadata.get('result_polarity', 'unknown')}\n"
                f"  quote: {item.quote[:600]}"
            )
        user_prompt = (
            f"研究问题：{question}\n"
            f"问题意图：{question_focus(question)}\n\n"
            f"证据列表（共 {len(selected)} 条）：\n"
            + "\n".join(lines)
            + "\n\n必须直接回答研究问题；若问题问体内验证，优先使用 ELN 体内结果，"
            "不得只用转录水平或体外证据替代。请输出 JSON。"
        )
        bundle, model = llm.generate_json(
            SYSTEM_PROMPT,
            user_prompt,
            SynthesisBundle,
            max_tokens=2500,
        )
        claims = self._sanitize_claims(bundle.claims, evidence_map)
        if not claims:
            raise ValueError("LLM 未产出可验证 claims")
        conflicts = self._sanitize_conflicts(
            bundle.conflicts, evidence_map, question
        )
        if not conflicts:
            conflicts = _infer_conflicts(question, claims)
        assessment = (bundle.assessment or "").strip() or _default_assessment(claims)
        return SynthesisResult(
            assessment=assessment,
            claims=claims,
            conflicts=conflicts,
            gaps=_clean_list(bundle.gaps, limit=6),
            next_steps=_clean_list(bundle.next_steps, limit=5),
            llm_used=True,
            model=model,
        )

    def _sanitize_claims(
        self,
        drafts: list[ClaimDraft],
        evidence_map: dict[str, Evidence],
    ) -> list[Claim]:
        claims: list[Claim] = []
        seen: set[str] = set()
        for draft in drafts:
            support = [item for item in draft.support_ids if item in evidence_map]
            contradict = [item for item in draft.contradict_ids if item in evidence_map]
            if not support and not contradict:
                continue
            if draft.stance == Stance.SUPPORT and not support:
                continue
            if draft.stance == Stance.CONTRADICT and not contradict:
                continue
            text = " ".join(draft.text.split())[:500]
            if not text or text.casefold() in seen:
                continue
            seen.add(text.casefold())
            cited = support + contradict
            stance = _normalize_stance(text, draft.stance)
            support, contradict = _align_ids(stance, support, contradict)
            if not support and not contradict:
                continue
            level = _best_level([evidence_map[item].level for item in cited])
            claims.append(
                Claim(
                    claim_id=f"claim-{len(claims) + 1}",
                    text=text,
                    stance=stance,
                    level=level,
                    support_ids=support,
                    contradict_ids=contradict,
                    confidence=max(0.0, min(1.0, draft.confidence)),
                    caveats=_clean_list(draft.caveats, limit=4),
                )
            )
            if len(claims) >= 8:
                break
        return claims

    def _sanitize_conflicts(
        self,
        drafts: list[ConflictDraft],
        evidence_map: dict[str, Evidence],
        question: str,
    ) -> list[Conflict]:
        conflicts: list[Conflict] = []
        for draft in drafts:
            support = [item for item in draft.support_ids if item in evidence_map]
            contradict = [item for item in draft.contradict_ids if item in evidence_map]
            if not support or not contradict:
                continue
            conflicts.append(
                Conflict(
                    topic=(draft.topic or question)[:200],
                    support_ids=support,
                    contradict_ids=contradict,
                    explanation=draft.explanation[:500],
                )
            )
        return conflicts

    def _fallback(self, question: str, evidence: list[Evidence]) -> SynthesisResult:
        selected = evidence[:8]
        claims: list[Claim] = []
        seen: set[str] = set()
        for item in selected:
            stance = _heuristic_stance(item)
            text = f"{item.title}: {item.quote[:180]}"
            key = text[:100].casefold()
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                Claim(
                    claim_id=f"claim-{len(claims) + 1}",
                    text=text,
                    stance=stance,
                    level=item.level,
                    support_ids=[item.evidence_id] if stance == Stance.SUPPORT else [],
                    contradict_ids=[item.evidence_id] if stance == Stance.CONTRADICT else [],
                    confidence=0.4,
                    caveats=["规则抽取式结论，需人工复核"],
                )
            )
        support_ids = [
            item.evidence_id
            for item in selected
            if _heuristic_stance(item) == Stance.SUPPORT
        ]
        contradict_ids = [
            item.evidence_id
            for item in selected
            if _heuristic_stance(item) == Stance.CONTRADICT
        ]
        conflicts = (
            [
                Conflict(
                    topic=question,
                    support_ids=support_ids,
                    contradict_ids=contradict_ids,
                    explanation="证据方向不一致，需核对物种、方法和实验条件。",
                )
            ]
            if support_ids and contradict_ids
            else []
        )
        gaps = rule_gaps(question, selected, conflicts)
        next_steps = rule_next_steps(conflicts, selected)
        assessment = _default_assessment(claims)
        return SynthesisResult(
            assessment=assessment,
            claims=claims,
            conflicts=conflicts,
            gaps=gaps,
            next_steps=next_steps,
            llm_used=False,
        )


def _ensure_internal_evidence_coverage(
    question: str,
    claims: list[Claim],
    evidence: list[Evidence],
) -> list[Claim]:
    eln = [item for item in evidence if item.source_type == SourceType.ELN]
    if not eln:
        return claims
    in_vivo = question_focus(question) == "体内/动物验证"
    targets = [
        item
        for item in eln
        if not in_vivo
        or "体内" in str(item.metadata.get("study_type", ""))
        or "in vivo" in str(item.metadata.get("study_type", "")).casefold()
        or (item.species or "").casefold() == "mus musculus"
    ]
    if not targets:
        targets = eln
    cited = {
        item
        for claim in claims
        for item in claim.support_ids + claim.contradict_ids
    }

    # 1) 至少覆盖一条与意图匹配的内部实验
    if not any(item.evidence_id in cited for item in targets):
        _append_internal_claim(claims, targets[0])
        cited.add(targets[0].evidence_id)

    # 2) 反例/阴性结果必须由 contradict claim 显式覆盖，不能被“支持/事实”claim 吞掉
    negative = [
        item
        for item in targets
        if str(item.metadata.get("result_polarity", "")).casefold() == "negative"
    ]
    negative_ids = {item.evidence_id for item in negative}
    negative_covered = any(
        claim.stance == Stance.CONTRADICT
        and bool(set(claim.contradict_ids) & negative_ids)
        for claim in claims
    )
    if not negative_covered:
        terms = [
            term
            for term in ("NOD2", "IL23R", "Treg", "CD4", "体内")
            if term.casefold() in question.casefold()
        ]
        negative.sort(
            key=lambda item: sum(
                term.casefold() in f"{item.title} {item.quote}".casefold()
                for term in terms
            ),
            reverse=True,
        )
        if negative:
            _append_internal_claim(claims, negative[0])
    return claims[:10]


def _append_internal_claim(claims: list[Claim], target: Evidence) -> None:
    polarity = str(target.metadata.get("result_polarity", "")).casefold()
    if polarity == "negative":
        stance = Stance.CONTRADICT
    elif polarity == "positive":
        stance = Stance.SUPPORT
    else:
        stance = Stance.NEUTRAL
    experiment_id = target.metadata.get("experiment_id") or target.source_id
    text = f"{experiment_id}：{target.title} — {target.quote[:180]}"
    claims.append(
        Claim(
            claim_id=f"claim-{len(claims) + 1}",
            text=text,
            stance=stance,
            level=target.level,
            support_ids=[target.evidence_id] if stance != Stance.CONTRADICT else [],
            contradict_ids=[target.evidence_id] if stance == Stance.CONTRADICT else [],
            confidence=0.6,
            caveats=[
                "内部 ELN 为 DEMO/SYNTHETIC",
                "规则补充以确保内部证据覆盖",
            ],
        )
    )


def _normalize_stance(text: str, fallback: Stance) -> Stance:
    lower = text.casefold()
    if any(term in lower for term in NEGATIVE_TERMS):
        return Stance.CONTRADICT
    if any(term in lower for term in POSITIVE_TERMS):
        return Stance.SUPPORT
    return fallback


def _align_ids(
    stance: Stance,
    support: list[str],
    contradict: list[str],
) -> tuple[list[str], list[str]]:
    if stance == Stance.SUPPORT:
        return (support, contradict) if support else ([], contradict)
    if stance == Stance.CONTRADICT:
        return (support, contradict) if contradict else ([], support)
    return support, contradict


def _heuristic_stance(item: Evidence) -> Stance:
    polarity = str(item.metadata.get("result_polarity") or "").casefold()
    text = f"{item.title} {item.quote}".casefold()
    if polarity == "negative" or any(term in text for term in NEGATIVE_TERMS):
        return Stance.CONTRADICT
    if polarity == "positive" or any(term in text for term in POSITIVE_TERMS):
        return Stance.SUPPORT
    return Stance.NEUTRAL


def _best_level(levels: list[EvidenceLevel]) -> EvidenceLevel:
    if not levels:
        return EvidenceLevel.UNKNOWN
    return max(levels, key=lambda level: LEVEL_ORDER.get(level, 0))


def _infer_conflicts(question: str, claims: list[Claim]) -> list[Conflict]:
    support = [
        item
        for claim in claims
        for item in claim.support_ids
    ]
    contradict = [
        item
        for claim in claims
        for item in claim.contradict_ids
    ]
    if not support or not contradict:
        return []
    return [
        Conflict(
            topic=question,
            support_ids=list(dict.fromkeys(support)),
            contradict_ids=list(dict.fromkeys(contradict)),
            explanation="证据方向不一致，需核对物种、方法和实验条件。",
        )
    ]


def _default_assessment(claims: list[Claim]) -> str:
    support = sum(1 for item in claims if item.stance == Stance.SUPPORT)
    contradict = sum(1 for item in claims if item.stance == Stance.CONTRADICT)
    neutral = len(claims) - support - contradict
    if support and contradict:
        return (
            f"检索到 {support} 条支持证据、{contradict} 条反例/阴性证据、"
            f"{neutral} 条中性证据；证据方向不一致，需人工复核。"
        )
    if support:
        return (
            f"检索到 {support} 条支持证据、{neutral} 条中性证据；"
            "结论强度受证据等级和实验条件限制。"
        )
    if contradict:
        return (
            f"检索到 {contradict} 条反例/阴性证据、{neutral} 条中性证据；"
            "现有证据不支持正向结论。"
        )
    return "证据以描述性/中性信息为主，尚不足以形成明确结论。"


def rule_gaps(
    question: str,
    evidence: list[Evidence],
    conflicts: list[Conflict],
) -> list[str]:
    gaps: list[str] = []
    if conflicts:
        gaps.append("存在冲突证据，需要统一物种、样本、方法和实验条件后复现。")
    levels = {item.level for item in evidence}
    if not levels.intersection({EvidenceLevel.A, EvidenceLevel.B}):
        gaps.append("缺少 A/B 级直接证据。")
    if not any(item.source_type == SourceType.ELN for item in evidence):
        gaps.append("缺少内部 ELN 实验验证。")
    if any(
        item.source_type == SourceType.PATENT and item.level == EvidenceLevel.D
        for item in evidence
    ):
        gaps.append("专利声称缺少实施例或可验证数据支持。")
    return gaps


def rule_next_steps(
    conflicts: list[Conflict],
    evidence: list[Evidence],
) -> list[str]:
    steps: list[str] = []
    if conflicts:
        steps.append("在标准化分选和实验条件下复现关键阳性/阴性结果。")
    if any(
        (item.method or "").casefold() in {"qpcr", "rna-seq"}
        for item in evidence
    ):
        steps.append("补充蛋白水平验证（Western blot / IHC / flow）。")
    if not any(item.source_type == SourceType.ELN for item in evidence):
        steps.append("在内部项目空间补充 ELN 验证并记录阴性结果。")
    return steps[:4]


def _clean_list(items: list[str], limit: int) -> list[str]:
    result: list[str] = []
    for item in items:
        text = " ".join(str(item).split())
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result
