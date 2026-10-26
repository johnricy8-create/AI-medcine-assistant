"""检索冒烟脚本：分别查看 Chroma 与 BM25 的 Top-K。

示例：
    uv run python scripts/query_index.py "IL23R 在 IBD 中是否有选择性表达？"
    uv run python scripts/query_index.py "公司是否做过 IL23R 体内验证？" --k 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils.console import configure_console  # noqa: E402

configure_console()

from app.config import get_settings  # noqa: E402
from app.ingest.chunker import Chunk  # noqa: E402
from app.ingest.manifest import read_jsonl  # noqa: E402
from app.retrieval.bm25 import BM25Index  # noqa: E402
from app.retrieval.vector_store import VectorStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="检索索引冒烟测试")
    parser.add_argument("query", help="查询文本")
    parser.add_argument("--k", type=int, default=5, help="Top-K")
    parser.add_argument(
        "--scopes",
        default="public,project:IBD-TX-07",
        help="逗号分隔的 ACL scope",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Chroma collection 名称；默认使用 .env 配置",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.collection:
        settings = settings.model_copy(update={"chroma_collection": args.collection})
    scopes = [item.strip() for item in args.scopes.split(",") if item.strip()]

    chunks_path = settings.data_dir / "processed" / "chunks.jsonl"
    if not chunks_path.exists():
        print(f"未找到 {chunks_path}；请先运行 scripts/rebuild_index.py")
        return 1
    chunks = [
        Chunk.model_validate(row)
        for row in read_jsonl(chunks_path)
    ]
    bm25 = BM25Index(chunks)
    store = VectorStore(settings)

    print(f"\nQUERY: {args.query}")
    print(f"scopes: {scopes}\n")
    print("--- Chroma (cosine distance, smaller is better) ---")
    for hit in store.search(args.query, k=args.k, allowed_scopes=scopes):
        print(
            f"{hit.score:.4f} | {hit.metadata.get('source_type')} | "
            f"{hit.metadata.get('doc_id')} | {hit.metadata.get('section_path')}"
        )
        print(f"       {hit.text[:160]}")

    print("\n--- BM25 (score, larger is better) ---")
    for hit in bm25.search(args.query, k=args.k, allowed_scopes=scopes):
        print(
            f"{hit.score:.4f} | {hit.metadata.get('source_type')} | "
            f"{hit.metadata.get('doc_id')} | {hit.metadata.get('section_path')}"
        )
        print(f"       {hit.text[:160]}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
