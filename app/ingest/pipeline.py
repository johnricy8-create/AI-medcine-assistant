"""P1 数据抓取编排。

设计：每个来源独立失败，不阻塞其他来源；文档与 manifest 均按 doc_id 幂等合并。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.config import PROJECT_ROOT
from app.ingest.clinical_trials import ClinicalTrialsClient
from app.ingest.europe_pmc import EuropePmcClient
from app.ingest.expression import fetch_expression
from app.ingest.manifest import read_jsonl, upsert_manifest, write_jsonl
from app.ingest.models import FetchedDocument, ManifestEntry
from app.ingest.open_targets import fetch_open_targets
from app.ingest.synthetic import seed_internal_demo


def upsert_documents(data_dir: Path, fetched: list[FetchedDocument]) -> int:
    path = data_dir / "processed" / "documents.jsonl"
    existing = {row["doc_id"]: row for row in read_jsonl(path)}
    for item in fetched:
        existing[item.document.doc_id] = item.document.model_dump(mode="json")
    write_jsonl(path, sorted(existing.values(), key=lambda row: row["doc_id"]))
    return len(existing)


def write_manifest(data_dir: Path, fetched: list[FetchedDocument]) -> int:
    entries = [
        ManifestEntry.from_document(
            item.document,
            source=item.source,
            raw_path=_portable_path(item.raw_path),
            parse_status=item.parse_status,
        )
        for item in fetched
    ]
    merged = upsert_manifest(data_dir / "manifest.jsonl", entries)
    return len(merged)


def _portable_path(raw_path: str | None) -> str | None:
    """manifest 中保存相对项目根目录的路径，避免提交机器绝对路径。"""
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(raw_path)


def run_public(
    data_dir: Path,
    *,
    papers: int = 100,
    fulltext: int = 40,
    trials: int = 10,
    expression_genes: dict[str, str] | None = None,
    include_open_targets: bool = True,
) -> tuple[list[FetchedDocument], list[str]]:
    fetched: list[FetchedDocument] = []
    errors: list[str] = []

    def _run(name: str, fn: Callable[[], list[FetchedDocument]]) -> None:
        try:
            items = fn()
            fetched.extend(items)
            print(f"[OK] {name}: {len(items)} 条")
        except Exception as exc:  # noqa: BLE001
            message = f"{name}: {type(exc).__name__}: {exc}"
            errors.append(message)
            print(f"[FAIL] {message}")

    client = EuropePmcClient()
    try:
        _run(
            "Europe PMC",
            lambda: client.fetch_corpus(
                data_dir,
                target_count=papers,
                fulltext_count=fulltext,
            ),
        )
    finally:
        client.close()

    trials_client = ClinicalTrialsClient()
    try:
        _run(
            "ClinicalTrials.gov",
            lambda: trials_client.fetch_corpus(data_dir, target_count=trials),
        )
    finally:
        trials_client.close()

    _run(
        "Human Protein Atlas",
        lambda: fetch_expression(data_dir, genes=expression_genes),
    )

    if include_open_targets:
        _run("Open Targets", lambda: fetch_open_targets(data_dir))

    if fetched:
        total_docs = upsert_documents(data_dir, fetched)
        total_manifest = write_manifest(data_dir, fetched)
        print(f"[OK] 文档总数: {total_docs}; manifest 总数: {total_manifest}")
    return fetched, errors


def run_synthetic(data_dir: Path) -> list[FetchedDocument]:
    fetched = seed_internal_demo(data_dir)
    total_docs = upsert_documents(data_dir, fetched)
    total_manifest = write_manifest(data_dir, fetched)
    print(
        f"[OK] 合成内部数据: {len(fetched)} 条; "
        f"文档总数: {total_docs}; manifest 总数: {total_manifest}"
    )
    return fetched
