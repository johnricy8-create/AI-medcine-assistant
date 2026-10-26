"""混合检索冒烟：RRF + 查询扩展 + 可选 rerank。

示例：
    uv run python scripts/query_hybrid.py "公司是否做过 IL23R 的体内验证？"
    uv run python scripts/query_hybrid.py "IL23R 在 IBD 中的表达" --rerank
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
from app.retrieval.hybrid import build_hybrid_retriever  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="混合检索冒烟")
    parser.add_argument("query", help="查询文本")
    parser.add_argument("--k", type=int, default=5, help="Top-K")
    parser.add_argument(
        "--scopes",
        default="public,project:IBD-TX-07",
        help="逗号分隔的 ACL scope",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="调用 SiliconFlow BGE reranker",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="强制关闭 rerank，只使用 RRF",
    )
    args = parser.parse_args()

    settings = get_settings()
    scopes = [item.strip() for item in args.scopes.split(",") if item.strip()]
    if args.no_rerank:
        rerank_setting: bool | None = False
    elif args.rerank:
        rerank_setting = True
    else:
        rerank_setting = None
    retriever = build_hybrid_retriever(settings, use_rerank=rerank_setting)
    try:
        result = retriever.retrieve(
            args.query,
            k=args.k,
            allowed_scopes=scopes,
            use_rerank=rerank_setting,
        )
    finally:
        retriever.vector_store.close()

    print(f"\nQUERY: {result.query}")
    print(f"entities: {result.entities}")
    print(f"terms:    {result.terms}")
    print(
        f"dense={result.dense_count} sparse={result.sparse_count} "
        f"reranked={result.reranked} topD={result.dense_top_distance}"
    )
    print("\n--- Hybrid top ---")
    for hit in result.hits:
        print(
            f"RRF={hit.rrf_score:.5f} dense={hit.dense_score} "
            f"sparse={hit.sparse_score} rerank={hit.rerank_score} "
            f"| {hit.metadata.get('source_type')} | {hit.doc_id}"
        )
        print(f"  {hit.metadata.get('section_path')}")
        print(f"  {hit.text[:180]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
