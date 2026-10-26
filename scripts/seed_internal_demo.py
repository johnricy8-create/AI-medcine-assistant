"""只生成合成内部演示数据（ELN / 项目报告 / 专利 / ACL）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.ingest.pipeline import run_synthetic  # noqa: E402


def main() -> int:
    settings = get_settings()
    settings.ensure_directories()
    run_synthetic(settings.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
