"""科学实体链接：本体别名 + 边界匹配 + 轻量模糊匹配。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml
from rapidfuzz import fuzz, process

from app.schemas import EntityRef

_ASCII_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-\s\+\.]*$")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{3,}")


class EntityLinker:
    def __init__(self, entities: Iterable[EntityRef]) -> None:
        self.entities = list(entities)
        self.alias_map: dict[str, EntityRef] = {}
        for entity in self.entities:
            for alias in [entity.name, *entity.aliases]:
                alias = alias.strip()
                if alias:
                    self.alias_map.setdefault(alias.casefold(), entity)

    @classmethod
    def from_yaml(cls, path: Path) -> "EntityLinker":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        entities = [
            EntityRef(
                canonical_id=item["canonical_id"],
                entity_type=item["entity_type"],
                name=item["name"],
                aliases=item.get("aliases", []),
                cross_ids=item.get("cross_ids", {}),
                species=item.get("species"),
                confidence=1.0,
            )
            for item in data.get("entities", [])
        ]
        return cls(entities)

    def link(self, text: str, *, fuzzy: bool = True) -> list[EntityRef]:
        """返回文本中命中的标准实体，按置信度降序去重。"""
        if not text.strip():
            return []
        lower = text.casefold()
        found: dict[str, EntityRef] = {}
        for alias, entity in sorted(
            self.alias_map.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if _alias_matches(alias, lower):
                found[entity.canonical_id] = entity.model_copy(
                    update={"confidence": 1.0}
                )

        if fuzzy:
            for token in set(_TOKEN.findall(text)):
                if len(token) < 4:
                    continue
                match = process.extractOne(
                    token.casefold(),
                    self.alias_map.keys(),
                    scorer=fuzz.WRatio,
                    score_cutoff=90,
                )
                if not match:
                    continue
                alias, score, _ = match
                entity = self.alias_map[alias]
                if entity.canonical_id not in found:
                    found[entity.canonical_id] = entity.model_copy(
                        update={"confidence": round(score / 100, 3)}
                    )

        return sorted(
            found.values(),
            key=lambda entity: (-entity.confidence, entity.canonical_id),
        )

    def canonical_ids(self, text: str) -> list[str]:
        return [entity.canonical_id for entity in self.link(text)]


def _alias_matches(alias: str, lower_text: str) -> bool:
    if not _ASCII_ALIAS.match(alias):
        return alias.casefold() in lower_text
    # 允许英文复数；同时用前后边界避免 "CD" 命中 "CD4"。
    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(alias)
        + r"(?:s|es)?(?![a-z0-9])"
    )
    return re.search(pattern, lower_text, flags=re.IGNORECASE) is not None
