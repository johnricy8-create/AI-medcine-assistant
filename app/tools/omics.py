"""组学工具：读取 HPA 表达数据，只读、参数化、可复现。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ingest.expression import ExpressionDataset
from app.ingest.manifest import sha256_bytes, sha256_text
from app.tools.models import ToolResult


class OmicsTool:
    def __init__(self, expression_path: Path) -> None:
        self.expression_path = expression_path
        self._raw = expression_path.read_bytes() if expression_path.exists() else b"[]"
        self._dataset_version = sha256_bytes(self._raw)[:16]
        rows = json.loads(self._raw.decode("utf-8")) if self._raw else []
        self.datasets: list[ExpressionDataset] = [
            ExpressionDataset.model_validate(row) for row in rows
        ]
        self._by_gene: dict[str, ExpressionDataset] = {}
        for dataset in self.datasets:
            for name in [dataset.gene, *dataset.synonyms]:
                self._by_gene.setdefault(name.casefold(), dataset)

    def genes(self) -> list[str]:
        return [dataset.gene for dataset in self.datasets]

    def expression(
        self,
        gene: str,
        *,
        tissue: str | None = None,
        cell_type: str | None = None,
        top_n: int = 8,
    ) -> ToolResult:
        arguments = {
            "gene": gene,
            "tissue": tissue,
            "cell_type": cell_type,
            "top_n": top_n,
        }
        dataset = self._by_gene.get(gene.casefold())
        if dataset is None:
            return ToolResult(
                tool_name="omics.expression",
                arguments=arguments,
                source="Human Protein Atlas",
                dataset_version=self._dataset_version,
                ok=False,
                error=f"未找到基因 {gene}；可用基因: {', '.join(self.genes())}",
            )

        data: dict[str, Any] = {
            "gene": dataset.gene,
            "ensembl": dataset.ensembl,
            "uniprot": dataset.uniprot,
            "description": dataset.description,
            "tissue_specific_ntpm": _filter_values(
                dataset.tissue_specific_ntpm, tissue, top_n
            ),
            "single_cell_type_specific_ncpm": _filter_values(
                dataset.single_cell_type_specific_ncpm, cell_type, top_n
            ),
            "single_cell_group_specific_ncpm": _filter_values(
                dataset.single_cell_group_specific_ncpm, cell_type, top_n
            ),
            "blood_cell_specific_ntpm": _filter_values(
                dataset.blood_cell_specific_ntpm, cell_type, top_n
            ),
            "source_url": dataset.source_url,
            "license": dataset.license,
        }
        return ToolResult(
            tool_name="omics.expression",
            arguments=arguments,
            data=data,
            source="Human Protein Atlas",
            license=dataset.license,
            dataset_version=self._dataset_version,
            result_hash=sha256_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True)
            ),
            ok=True,
        )


def _filter_values(
    values: dict[str, float],
    keyword: str | None,
    top_n: int,
) -> dict[str, float]:
    items = list(values.items())
    if keyword:
        needle = keyword.casefold()
        items = [
            (key, value)
            for key, value in items
            if needle in key.casefold()
        ]
    items.sort(key=lambda item: item[1], reverse=True)
    return dict(items[:top_n])
