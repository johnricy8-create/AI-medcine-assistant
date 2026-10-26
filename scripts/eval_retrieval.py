"""离线检索冒烟评估：Chroma / BM25 命中、ACL 泄露、无答案距离。

示例：
    uv run python scripts/eval_retrieval.py
"""

from __future__ import annotations

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
from app.retrieval.vector_store import VectorStore  # noqa: E402

TOP_K = 5


def main() -> int:
    settings = get_settings()
    questions = json.loads(
        (settings.data_dir / "eval" / "retrieval_smoke.json").read_text(
            encoding="utf-8"
        )
    )
    chunks = [
        Chunk.model_validate(row)
        for row in read_jsonl(settings.data_dir / "processed" / "chunks.jsonl")
    ]
    bm25 = BM25Index(chunks)
    store = VectorStore(settings)

    records = []
    chroma_hits = 0
    bm25_hits = 0
    union_hits = 0
    answerable = 0
    leaks = 0

    for item in questions:
        vhits = store.search(
            item["question"], k=TOP_K, allowed_scopes=item.get("scopes")
        )
        bhits = bm25.search(
            item["question"], k=TOP_K, allowed_scopes=item.get("scopes")
        )
        v_ids = [hit.doc_id for hit in vhits]
        b_ids = [hit.doc_id for hit in bhits]
        expected = set(item.get("expected_doc_ids", []))
        forbidden = set(item.get("should_not_contain", []))
        v_hit = bool(expected & set(v_ids))
        b_hit = bool(expected & set(b_ids))
        union_hit = bool(expected & (set(v_ids) | set(b_ids)))
        leaked = bool(forbidden & (set(v_ids) | set(b_ids)))
        if item.get("answerable"):
            answerable += 1
            chroma_hits += int(v_hit)
            bm25_hits += int(b_hit)
            union_hits += int(union_hit)
        leaks += int(leaked)

        records.append(
            {
                "id": item["id"],
                "question": item["question"],
                "answerable": item.get("answerable", False),
                "chroma_top_distance": vhits[0].score if vhits else None,
                "chroma_ids": v_ids,
                "bm25_ids": b_ids,
                "chroma_hit": v_hit,
                "bm25_hit": b_hit,
                "union_hit": union_hit,
                "acl_leak": leaked,
            }
        )
        print(
            f"{item['id']:5} {item['question'][:42]:42} "
            f"V={v_hit!s:5} B={b_hit!s:5} U={union_hit!s:5} "
            f"topD={vhits[0].score if vhits else float('nan'):.4f}"
        )

    summary = {
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
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    write_json(
        settings.data_dir / "eval" / "retrieval_smoke_result.json",
        {"summary": summary, "records": records},
    )
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
