"""手动验证智谱 LLM、硅基流动 Embedding 与 SQLite 是否可用。

用法（项目根目录）：
    uv run python scripts/check_services.py

不会打印 API Key；未配置 Key 时对应项标记为 SKIP。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.storage.db import check_db, init_db  # noqa: E402


def check_llm(settings) -> tuple[str, str]:
    if not settings.llm_configured():
        return "SKIP", "未配置 LLM_API_KEY"
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": "只回答：连接成功"}],
        "temperature": 0.1,
        "max_tokens": 16,
    }
    try:
        with httpx.Client(timeout=settings.llm_timeout) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}"
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return "OK", f"{settings.llm_model} -> {content.strip()[:40]}"
    except Exception as exc:  # noqa: BLE001 - 诊断脚本需要展示真实错误
        return "FAIL", f"{settings.llm_model}: {type(exc).__name__}: {exc}"


def check_embedding(settings) -> tuple[str, str]:
    if not settings.embedding_configured():
        return "SKIP", "未配置 EMBEDDING_API_KEY"
    url = settings.embedding_base_url.rstrip("/") + "/embeddings"
    payload = {
        "model": settings.embedding_model,
        "input": ["医药研发知识助手连接测试"],
        "encoding_format": "float",
    }
    try:
        with httpx.Client(timeout=settings.llm_timeout) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": (
                        f"Bearer {settings.embedding_api_key.get_secret_value()}"
                    )
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            vector = data["data"][0]["embedding"]
            if len(vector) != settings.embedding_dim:
                return (
                    "FAIL",
                    f"维度不匹配：期望 {settings.embedding_dim}，实际 {len(vector)}",
                )
            if not any(value != 0 for value in vector):
                return "FAIL", "返回了全零向量"
            return "OK", f"{settings.embedding_model} -> {len(vector)} 维"
    except Exception as exc:  # noqa: BLE001
        return "FAIL", f"{settings.embedding_model}: {type(exc).__name__}: {exc}"


def main() -> int:
    settings = get_settings()
    settings.ensure_directories()
    init_db(settings.sqlite_path)

    results: list[tuple[str, str, str]] = []

    db_ok = check_db(settings.sqlite_path)
    results.append(
        (
            "SQLite",
            "OK" if db_ok else "FAIL",
            str(settings.sqlite_path),
        )
    )
    results.append(("LLM", *check_llm(settings)))
    results.append(("Embedding", *check_embedding(settings)))

    print("\n=== 服务连通性检查 ===")
    for name, status, detail in results:
        print(f"[{status:4}] {name:10} {detail}")

    failures = [item for item in results if item[1] == "FAIL"]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
