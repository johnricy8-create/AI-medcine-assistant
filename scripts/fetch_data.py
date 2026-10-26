"""抓取 P1 语料并生成 manifest。

示例（项目根目录）：
    uv run python scripts/fetch_data.py
    uv run python scripts/fetch_data.py --papers 100 --fulltext 40 --trials 10
    uv run python scripts/fetch_data.py --skip-public
    uv run python scripts/fetch_data.py --skip-synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.ingest.pipeline import run_public, run_synthetic  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取医药研发知识助手 P1 语料")
    parser.add_argument("--papers", type=int, default=100, help="论文目标数量")
    parser.add_argument("--fulltext", type=int, default=40, help="全文目标数量")
    parser.add_argument("--trials", type=int, default=10, help="临床试验目标数量")
    parser.add_argument("--skip-public", action="store_true", help="跳过公开数据抓取")
    parser.add_argument("--skip-synthetic", action="store_true", help="跳过合成内部数据")
    parser.add_argument(
        "--skip-open-targets",
        action="store_true",
        help="跳过 Open Targets 图谱数据",
    )
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_directories()
    data_dir = settings.data_dir

    all_errors: list[str] = []
    if not args.skip_public:
        _, errors = run_public(
            data_dir,
            papers=args.papers,
            fulltext=args.fulltext,
            trials=args.trials,
            include_open_targets=not args.skip_open_targets,
        )
        all_errors.extend(errors)

    if not args.skip_synthetic:
        run_synthetic(data_dir)

    docs_path = data_dir / "processed" / "documents.jsonl"
    manifest_path = data_dir / "manifest.jsonl"
    print("\n=== P1 数据汇总 ===")
    print(f"documents: {docs_path} (exists={docs_path.exists()})")
    print(f"manifest:  {manifest_path} (exists={manifest_path.exists()})")
    if all_errors:
        print("\n失败项：")
        for error in all_errors:
            print(f"- {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
