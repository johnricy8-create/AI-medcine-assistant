"""为 claims 综合选择证据：按问题意图保留来源多样性，并优先内部/阴性证据。"""

from __future__ import annotations

from app.schemas import Evidence, SourceType

IN_VIVO_TERMS = ("体内", "in vivo", "动物", "mouse", "mice", "小鼠", "大鼠")
IN_VITRO_TERMS = ("体外", "in vitro", "类器官", "organoid", "细胞系", "cell line")
PATENT_TERMS = ("专利", "知识产权", "转化", "成药", "patent")
MECHANISM_TERMS = ("机制", "通路", "pathway", "如何", "作用", "为什么")


def question_focus(question: str) -> str:
    lower = question.casefold()
    if any(term in lower for term in IN_VIVO_TERMS):
        return "体内/动物验证"
    if any(term in lower for term in IN_VITRO_TERMS):
        return "体外/类器官验证"
    if any(term in lower for term in PATENT_TERMS):
        return "专利/转化"
    if any(term in lower for term in MECHANISM_TERMS):
        return "机制/通路"
    return "综合证据"


def select_evidence_for_synthesis(
    question: str,
    evidence: list[Evidence],
    *,
    max_evidence: int = 20,
) -> list[Evidence]:
    focus = question_focus(question)
    if focus == "体内/动物验证":
        order = [
            SourceType.ELN,
            SourceType.REPORT,
            SourceType.LITERATURE,
            SourceType.OMICS,
            SourceType.PATENT,
            SourceType.TRIAL,
            SourceType.DATABASE,
        ]
    elif focus == "体外/类器官验证":
        order = [
            SourceType.ELN,
            SourceType.LITERATURE,
            SourceType.REPORT,
            SourceType.OMICS,
            SourceType.PATENT,
            SourceType.TRIAL,
            SourceType.DATABASE,
        ]
    elif focus == "专利/转化":
        order = [
            SourceType.PATENT,
            SourceType.LITERATURE,
            SourceType.REPORT,
            SourceType.ELN,
            SourceType.TRIAL,
            SourceType.OMICS,
            SourceType.DATABASE,
        ]
    elif focus == "机制/通路":
        order = [
            SourceType.LITERATURE,
            SourceType.REPORT,
            SourceType.ELN,
            SourceType.OMICS,
            SourceType.PATENT,
            SourceType.TRIAL,
            SourceType.DATABASE,
        ]
    else:
        order = [
            SourceType.ELN,
            SourceType.LITERATURE,
            SourceType.REPORT,
            SourceType.PATENT,
            SourceType.OMICS,
            SourceType.TRIAL,
            SourceType.DATABASE,
        ]

    quotas = {
        SourceType.ELN: 6 if focus == "体内/动物验证" else 4,
        SourceType.LITERATURE: 8 if focus == "机制/通路" else 5,
        SourceType.REPORT: 3,
        SourceType.PATENT: 2,
        SourceType.OMICS: 1,
        SourceType.TRIAL: 2,
        SourceType.DATABASE: 1,
    }
    if focus == "体内/动物验证":
        quotas[SourceType.ELN] = 8
    if focus == "专利/转化":
        quotas[SourceType.PATENT] = 4

    selected: list[Evidence] = []
    seen: set[str] = set()
    for source_type in order:
        group = [
            item for item in evidence if item.source_type == source_type
        ]
        group.sort(key=_score, reverse=True)
        if focus == "体内/动物验证" and source_type == SourceType.ELN:
            group.sort(
                key=lambda item: (
                    "体内" in str(item.metadata.get("study_type", "")),
                    item.metadata.get("result_polarity") == "negative",
                    _score(item),
                ),
                reverse=True,
            )
        for item in group[: quotas.get(source_type, 1)]:
            if item.evidence_id in seen:
                continue
            seen.add(item.evidence_id)
            selected.append(item)
            if len(selected) >= max_evidence:
                return selected

    # 若还有余量，补充高分证据
    for item in sorted(evidence, key=_score, reverse=True):
        if len(selected) >= max_evidence:
            break
        if item.evidence_id not in seen:
            seen.add(item.evidence_id)
            selected.append(item)
    return selected


def _score(item: Evidence) -> float:
    if item.scores.rerank is not None:
        return float(item.scores.rerank)
    if item.scores.rrf is not None:
        return float(item.scores.rrf)
    if item.scores.dense is not None:
        return -float(item.scores.dense)
    return 0.0
