"""控制台输出辅助：Windows 下切到 UTF-8，避免中文/数学符号导致 GBK 编码异常。"""

from __future__ import annotations

import os
import sys


def configure_console() -> None:
    if sys.platform == "win32":
        os.system("chcp 65001 >nul")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
