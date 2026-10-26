"""离线检索评估：Chroma / BM25 / RRF 混合 / 可选 rerank。

示例：
    uv run python scripts/eval_retrieval.py
    uv run python scripts/eval_retrieval.py --hybrid
    uv run python scripts/eval_retrieval.py --hybrid --rerank
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils.console import configure_console  # noqa: E402

configure_console()

from app.config import get_settings  # noqa: E402
from app.ingest.chunker import Chunk  # noqa: E402
from app.ingest.manifest import read_jsonl, write_json  # noqa: E402
from app.retrieval.bm25 import BM25Index  # noqa: E402
from app.retrieval.hybrid import build_hybrid_retriever  # noqa: E402
from app.retrieval.vector_store import VectorStore  # noqa: E402

TOP_K = 5


def main() -> int:
    parser = argparse.ArgumentParser(description="离线检索评估")
    parser.add_argument("--hybrid", action="store_true", help="评估 RRF 混合检索")
    parser.add_argument("--rerank", action="store_true", help="混合检索后调用 rerank")
    parser.add_argument(
        "--questions",
        default="retrieval_smoke.json",
        help="评估集文件名（data/eval 下）或绝对路径",
    )
    parser.add_argument(
        "--output",
        default="retrieval_smoke_result.json",
        help="结果文件名（data/eval 下）或绝对路径",
    )
    args = parser.parse_args()

    settings = get_settings()
    questions_path = Path(args.questions)
    if not questions_path.is_absolute():
        questions_path = settings.data_dir / "eval" / questions_path
    questions = json.loads(questions_path.read_text(encoding="utf-8"))
    if args.rerank:
        args.hybrid = True

    retriever = None
    if args.hybrid:
        retriever = build_hybrid_retriever(settings, use_rerank=args.rerank)
        store = retriever.vector_store
        bm25 = retriever.bm25
    else:
        chunks = [
            Chunk.model_validate(row)
            for row in read_jsonl(
                settings.data_dir / "processed" / "chunks.jsonl"
            )
        ]
        bm25 = BM25Index(chunks)
        store = VectorStore(settings)

    records = []
    chroma_hits = bm25_hits = hybrid_hits = union_hits = 0
    answerable = 0
    leaks = 0

    for item in questions:
        scopes = item.get("scopes")
        source_types = item.get("source_types")
        vhits = store.search(
            item["question"], k=TOP_K, allowed_scopes=scopes,
            source_types=source_types,
        )
        bhits = bm25.search(
            item["question"], k=TOP_K, allowed_scopes=scopes,
            source_types=source_types,
        )
        hhits = []
        h_result = None
        if retriever is not None:
            h_result = retriever.retrieve(
                item["question"],
                k=TOP_K,
                allowed_scopes=scopes,
                source_types=source_types,
                use_rerank=args.rerank,
            )
            hhits = h_result.hits

        v_ids = [hit.doc_id for hit in vhits]
        b_ids = [hit.doc_id for hit in bhits]
        h_ids = [hit.doc_id for hit in hhits]
        expected = set(item.get("expected_doc_ids", []))
        forbidden = set(item.get("should_not_contain", []))
        v_hit = bool(expected & set(v_ids))
        b_hit = bool(expected & set(b_ids))
        h_hit = bool(expected & set(h_ids))
        union_hit = bool(expected & (set(v_ids) | set(b_ids) | set(h_ids)))
        leaked = bool(forbidden & (set(v_ids) | set(b_ids) | set(h_ids)))
        if item.get("answerable"):
            answerable += 1
            chroma_hits += int(v_hit)
            bm25_hits += int(b_hit)
            hybrid_hits += int(h_hit)
            union_hits += int(union_hit)
        leaks += int(leaked)

        records.append(
            {
                "id": item["id"],
                "question": item["question"],
                "answerable": item.get("answerable", False),
                "chroma_top_distance": vhits[0].score if vhits else None,
                "hybrid_top_distance": (
                    h_result.dense_top_distance if h_result else None
                ),
                "chroma_ids": v_ids,
                "bm25_ids": b_ids,
                "hybrid_ids": h_ids,
                "hybrid_terms": h_result.terms if h_result else [],
                "chroma_hit": v_hit,
                "bm25_hit": b_hit,
                "hybrid_hit": h_hit,
                "union_hit": union_hit,
                "acl_leak": leaked,
                "reranked": h_result.reranked if h_result else False,
            }
        )
        print(
            f"{item['id']:5} {item['question'][:42]:42} "
            f"V={v_hit!s:5} B={b_hit!s:5} H={h_hit!s:5} U={union_hit!s:5} "
            f"topD={vhits[0].score if vhits else float('nan'):.4f}"
        )

    summary: dict = {
        "questions": len(questions),
        "answerable": answerable,
        "chroma_recall_at_5": round(chroma_hits / answerable, 3) if answerable else 0,
        "bm25_recall_at_5": round(bm25_hits / answerable, 3) if answerable else 0,
        "union_recall_at_5": round(union_hits / answerable, 3) if answerable else 0,
        "acl_leaks": leaks,
        "no_answer_top_distances": [
            record["chroma_top_distance"]
            for record in records
            if record["id"].startswith("N")
            and record["chroma_top_distance"] is not None
        ],
    }
    if retriever is not None:
        summary["hybrid_recall_at_5"] = (
            round(hybrid_hits / answerable, 3) if answerable else 0
        )
        summary["reranked"] = args.rerank
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = settings.data_dir / "eval" / output_path
    write_json(
        output_path,
        {"summary": summary, "records": records},
    )
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
