"""规则规划器：把研究问题拆成受控子问题与数据源。

P4 先保证确定性、可测试；LLM 规划可在后续作为可选增强。
"""

from __future__ import annotations

from app.schemas import EntityRef, SourceType, SubQuestion

CLINICAL_KEYWORDS = ("临床", "试验", "患者", "入组", "终点", "trial", "patient")
PATENT_KEYWORDS = ("专利", "知识产权", "转化", "成药", "license", "patent")
INTERNAL_KEYWORDS = ("公司", "内部", "做过", "实验", "验证", "ELN", "阴性", "失败")


class RuleBasedPlanner:
    def plan(
        self,
        question: str,
        entities: list[EntityRef],
        *,
        allowed_sources: list[SourceType] | None = None,
        max_subquestions: int = 5,
        max_retrievals: int = 12,
    ) -> list[SubQuestion]:
        allowed = set(allowed_sources or list(SourceType))
        gene_entities = [
            entity
            for entity in entities
            if entity.entity_type in {"gene", "target", "protein"}
        ]
        lower = question.casefold()

        drafts: list[tuple[str, str, list[SourceType]]] = [
            (
                "文献与机制证据",
                "literature",
                [SourceType.LITERATURE],
            ),
            (
                "内部实验与项目报告",
                "internal",
                [SourceType.ELN, SourceType.REPORT],
            ),
            (
                "专利与转化线索",
                "patent",
                [SourceType.PATENT],
            ),
        ]
        if gene_entities:
            drafts[0][2].append(SourceType.OMICS)
        if any(keyword.casefold() in lower for keyword in CLINICAL_KEYWORDS):
            drafts.append(
                ("临床与转化证据", "clinical", [SourceType.TRIAL])
            )
        if not any(keyword.casefold() in lower for keyword in PATENT_KEYWORDS):
            # 仍保留专利线索，但放在最后，避免专利片段挤占内部证据。
            drafts.sort(key=lambda item: item[1] == "patent")

        subquestions: list[SubQuestion] = []
        used_retrievals = 0
        for index, (focus, intent, sources) in enumerate(drafts, start=1):
            if len(subquestions) >= max_subquestions:
                break
            selected: list[SourceType] = []
            for source in sources:
                if source not in allowed:
                    continue
                if used_retrievals >= max_retrievals:
                    break
                selected.append(source)
                used_retrievals += 1
            if not selected:
                continue
            subquestions.append(
                SubQuestion(
                    id=f"sq-{index}",
                    text=question,
                    intent=intent,
                    sources=selected,
                    queries=[question],
                    filters={"focus": focus},
                    status="pending",
                )
            )
        return subquestions

    @staticmethod
    def required_genes(entities: list[EntityRef]) -> list[str]:
        return [
            entity.name
            for entity in entities
            if entity.entity_type in {"gene", "target", "protein"}
        ]
