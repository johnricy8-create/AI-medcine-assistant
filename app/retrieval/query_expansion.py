"""规则化查询扩展：实体别名 + 领域同义词 + 反例查询。

P3 先用确定性规则，不依赖 LLM；后续可在 plan 节点增加 LLM 改写，
但规则扩展保留为兜底。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ingest.entity_linker import EntityLinker
from app.schemas import EntityRef

DOMAIN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "体内": ("in vivo", "animal model", "mouse", "mice"),
    "动物": ("animal model", "mouse", "mice", "rat"),
    "体外": ("in vitro", "organoid", "cell line"),
    "类器官": ("organoid", "in vitro"),
    "蛋白": ("protein", "Western blot", "IHC", "immunohistochemistry"),
    "表达": ("expression", "mRNA", "RNA-seq", "qPCR"),
    "rna": ("RNA", "mRNA", "RNA-seq", "qPCR"),
    "mrna": ("mRNA", "RNA-seq", "qPCR"),
    "阴性": ("negative", "no significant change", "not changed", "failed"),
    "反例": ("contradict", "negative", "no effect", "failed to replicate"),
    "验证": ("validation", "validate", "experiment"),
    "公司": ("internal", "in-house", "internal experiment"),
    "内部": ("internal", "in-house"),
    "临床": ("clinical trial", "patients", "cohort"),
    "活检": ("biopsy", "biopsies", "tissue"),
    "组织": ("tissue", "biopsy"),
    "细胞": ("cell", "cell type"),
    "专利": ("patent", "claims"),
    "安全性": ("safety", "toxicity", "adverse"),
}

NEGATION_TERMS = (
    "negative",
    "no significant change",
    "not changed",
    "no effect",
    "failed to replicate",
    "未观察到",
    "无显著变化",
    "阴性",
    "未重复",
    "相反",
)


class ExpandedQuery(BaseModel):
    original: str
    dense_query: str
    sparse_query: str
    entities: list[EntityRef] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)

    @property
    def canonical_ids(self) -> list[str]:
        return [entity.canonical_id for entity in self.entities]


class QueryExpander:
    def __init__(self, linker: EntityLinker, max_terms: int = 12) -> None:
        self.linker = linker
        self.max_terms = max_terms

    def expand(self, query: str) -> ExpandedQuery:
        entities = self.linker.link(query)
        terms: list[str] = []
        lower = query.casefold()

        for entity in entities:
            for term in (entity.name, *entity.aliases):
                term = term.strip()
                if term and term.casefold() not in lower:
                    _add_unique(terms, term)

        for keyword, synonyms in DOMAIN_SYNONYMS.items():
            if keyword in lower:
                for synonym in synonyms:
                    if synonym.casefold() not in lower:
                        _add_unique(terms, synonym)

        terms = terms[: self.max_terms]
        suffix = " ".join(terms)
        dense_query = f"{query} {suffix}".strip()
        sparse_query = dense_query
        return ExpandedQuery(
            original=query,
            dense_query=dense_query,
            sparse_query=sparse_query,
            entities=entities,
            terms=terms,
        )

    def counter_evidence_queries(self, query: str) -> list[str]:
        return [
            f"{query} 阴性 OR 未观察到 OR 无显著变化 OR 未重复",
            f"{query} negative OR no significant change OR not changed OR failed to replicate",
            f"{query} contradict OR no effect OR opposite",
        ]


def _add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)
