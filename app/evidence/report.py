"""研究底稿渲染。"""

from __future__ import annotations

from typing import Iterable

from app.schemas import (
    Claim,
    Conflict,
    EntityRef,
    Evidence,
    SourceType,
    Stance,
)


def render_research_brief(
    *,
    question: str,
    user_id: str,
    project_id: str,
    allowed_scopes: list[str],
    entities: list[EntityRef],
    assessment: str,
    claims: list[Claim],
    conflicts: list[Conflict],
    gaps: list[str],
    next_steps: list[str],
    evidence: list[Evidence],
    llm_used: bool = False,
    verify_notes: list[str] | None = None,
) -> str:
    evidence_map = {item.evidence_id: item for item in evidence}
    claims_map = {item.claim_id: item for item in claims}
    lines: list[str] = [
        "# 医药研发研究底稿",
        "",
        "> 本底稿用于研究辅助与证据整理，不构成临床诊疗建议、医学判断或知识产权结论。",
        "",
        f"**研究问题**：{question}",
        f"**用户/项目**：{user_id} / {project_id}",
        f"**可见范围**：{', '.join(allowed_scopes)}",
        f"**识别实体**：{', '.join(entity.name for entity in entities) or '未识别'}",
        "",
        "## 一句话判断",
        "",
        assessment or "证据不足，无法形成明确判断。",
        "",
        "## 支持证据",
        "",
    ]
    support_claims = [item for item in claims if item.stance == Stance.SUPPORT]
    if support_claims:
        for claim in support_claims:
            lines.append(
                f"- **{claim.text}**（等级 {claim.level.value}，"
                f"置信度 {claim.confidence:.2f}）"
            )
            lines.append(
                f"  - 引用：{_ids(claim.support_ids)}"
            )
            if claim.caveats:
                lines.append(f"  - 限制：{'；'.join(claim.caveats)}")
    else:
        lines.append("- 未形成可验证的支持性 claim。")

    lines.extend(["", "## 反例与冲突", ""])
    if conflicts:
        for conflict in conflicts:
            lines.append(f"- **{conflict.topic}**")
            lines.append(f"  - 支持：{_ids(conflict.support_ids)}")
            lines.append(f"  - 反例：{_ids(conflict.contradict_ids)}")
            lines.append(f"  - 解释：{conflict.explanation or '需人工核对'}")
    contradict_claims = [item for item in claims if item.stance == Stance.CONTRADICT]
    for claim in contradict_claims:
        lines.append(
            f"- 反例 claim：{claim.text}（等级 {claim.level.value}，"
            f"引用 {_ids(claim.contradict_ids)}）"
        )
    if not conflicts and not contradict_claims:
        lines.append("- 未发现明确反例；这不等同于没有反例，需继续检索。")

    lines.extend(["", "## 内部实验（ELN）", ""])
    internal = [
        item for item in evidence if item.source_type == SourceType.ELN
    ][:8]
    if internal:
        for item in internal:
            experiment_id = item.locator.experiment_id or item.source_id
            polarity = item.metadata.get("result_polarity", "unknown")
            lines.append(
                f"- **{experiment_id}**（{item.species or 'unknown'}，"
                f"极性 {polarity}，等级 {item.level.value}）"
            )
            lines.append(f"  - {item.title}")
            lines.append(f"  - {_short(item.quote, 220)}")
    else:
        lines.append("- 当前可见范围内没有内部 ELN 证据。")

    lines.extend(["", "## 证据等级", ""])
    lines.append("| Evidence ID | 来源 | 标题 | 等级 | 评分理由 |")
    lines.append("|---|---|---|---|---|")
    for item in evidence[:15]:
        grade = item.metadata.get("grade", {})
        rationale = grade.get("rationale", "")
        lines.append(
            f"| `{item.evidence_id}` | {item.source_type.value} | "
            f"{_short(item.title, 60)} | {item.level.value} | "
            f"{_short(rationale, 80)} |"
        )

    lines.extend(["", "## 数据缺口", ""])
    if gaps:
        lines.extend(f"- {gap}" for gap in gaps)
    else:
        lines.append("- 未自动识别到缺口，仍需专家复核。")

    lines.extend(["", "## 建议的下一步实验", ""])
    if next_steps:
        lines.extend(f"- {step}" for step in next_steps)
    else:
        lines.append("- 由项目科学家根据证据等级和资源决定验证顺序。")

    lines.extend(["", "## 引用与定位", ""])
    for index, item in enumerate(evidence[:20], start=1):
        locator = []
        if item.locator.doi:
            locator.append(f"DOI: {item.locator.doi}")
        if item.locator.patent_no:
            locator.append(f"专利: {item.locator.patent_no}")
        if item.locator.experiment_id:
            locator.append(f"ELN: {item.locator.experiment_id}")
        if item.locator.section:
            locator.append(item.locator.section)
        if item.locator.url:
            locator.append(item.locator.url)
        lines.extend(
            [
                f"{index}. `{item.evidence_id}` [{item.source_type.value}] {item.title}",
                f"   - 定位：{'；'.join(locator) or 'N/A'}",
                f"   - 原文：{_short(item.quote, 260)}",
            ]
        )

    verified = sum(1 for item in claims if item.verified)
    lines.extend(
        [
            "",
            "## 校验与边界",
            "",
            f"- Claims：{len(claims)} 条；通过引用/ACL 校验 {verified} 条。",
            f"- Claims 生成方式：{'LLM 结构化综合' if llm_used else '规则抽取式兜底'}。",
            (
                "- 校验备注："
                + "；".join((verify_notes or [])[:5])
                if verify_notes
                else "- 校验备注：无。"
            ),
            "- 内部 ELN/项目/专利为 `DEMO / SYNTHETIC`，不得作为真实科学结论。",
            "- 动物/体外结果不能直接外推到人体；所有结论需实验验证与专家评审。",
        ]
    )
    return "\n".join(lines)


def _ids(items: Iterable[str]) -> str:
    values = list(dict.fromkeys(item for item in items if item))
    return ", ".join(f"`{item}`" for item in values) or "无"


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"
