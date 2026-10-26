"""SiliconFlow BGE Reranker 客户端。

接口：POST /v1/rerank
模型：BAAI/bge-reranker-v2-m3
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings


class RerankError(RuntimeError):
    pass


class SiliconFlowReranker:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        key = (
            settings.rerank_api_key
            or settings.embedding_api_key
        )
        if key is None or not key.get_secret_value().strip():
            raise RerankError("未配置 RERANK_API_KEY / EMBEDDING_API_KEY")
        self.api_key = key.get_secret_value()
        self.url = settings.rerank_base_url.rstrip("/") + "/rerank"
        self._client = client

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        top_n = top_n or min(self.settings.rerank_top_n, len(documents))
        payload: dict[str, Any] = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "return_documents": False,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._post(payload)
                data = response.json()
                results = data.get("results")
                if not isinstance(results, list):
                    raise RerankError(f"rerank 响应缺少 results: {str(data)[:200]}")
                ranked: list[tuple[int, float]] = []
                for item in results:
                    index = int(item["index"])
                    if 0 <= index < len(documents):
                        ranked.append((index, float(item.get("relevance_score", 0.0))))
                ranked.sort(key=lambda pair: pair[1], reverse=True)
                return ranked
            except RerankError:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RerankError(f"rerank 调用失败: {last_error}") from last_error

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self._client is not None:
            response = self._client.post(self.url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.settings.rerank_timeout) as client:
                response = client.post(self.url, headers=headers, json=payload)
        response.raise_for_status()
        return response
