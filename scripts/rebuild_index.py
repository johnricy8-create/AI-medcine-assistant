"""重建本地索引。

示例（项目根目录）：
    uv run python scripts/rebuild_index.py
    uv run python scripts/rebuild_index.py --chunks-only
    uv run python scripts/rebuild_index.py --limit 20 --collection pharma_research_smoke
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
from app.retrieval.index_builder import build_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重建医药研发知识助手索引")
    parser.add_argument("--limit", type=int, default=None, help="只索引前 N 篇文档")
    parser.add_argument(
        "--collection",
        default=None,
        help="Chroma collection 名称；limit 模式建议单独指定",
    )
    parser.add_argument(
        "--chunks-only",
        action="store_true",
        help="只生成 chunks 和 BM25，不调用 Embedding / Chroma",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.collection:
        settings = settings.model_copy(update={"chroma_collection": args.collection})
    elif args.limit and settings.chroma_collection == "pharma_research":
        settings = settings.model_copy(
            update={"chroma_collection": "pharma_research_smoke"}
        )

    def progress(done: int, total: int) -> None:
        percent = done / total * 100 if total else 100
        print(f"\rEmbedding {done}/{total} ({percent:.1f}%)", end="", flush=True)
        if done >= total:
            print()

    result = build_index(
        settings,
        limit=args.limit,
        chunks_only=args.chunks_only,
        progress=progress,
    )

    print("\n=== 索引构建完成 ===")
    print(f"文档数:     {result.document_count}")
    print(f"chunk 数:   {result.chunk_count}")
    print(f"collection: {result.collection}")
    print(f"BM25:       {result.bm25_count}")
    print(f"Chroma:     {result.chroma_count}")
    print(f"Embedding:  {result.embedding_model} ({result.embedding_dim} 维)")
    print(f"chunks:     {result.chunks_path}")
    print(f"manifest:   {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
