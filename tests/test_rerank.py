"""SiliconFlow rerank 客户端测试（MockTransport，不访问网络）。"""

from __future__ import annotations

import unittest

import httpx

from app.config import Settings
from app.retrieval.rerank import RerankError, SiliconFlowReranker


class TestReranker(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(
            _env_file=None,
            rerank_api_key="test-key",
            rerank_top_n=3,
        )

    def test_parse_and_sort(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/rerank")
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"index": 2, "relevance_score": 0.5},
                        {"index": 0, "relevance_score": 0.9},
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        reranker = SiliconFlowReranker(self._settings(), client=client)
        pairs = reranker.rerank("q", ["a", "b", "c"])
        self.assertEqual(pairs, [(0, 0.9), (2, 0.5)])

    def test_invalid_response_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": []})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        reranker = SiliconFlowReranker(self._settings(), client=client)
        with self.assertRaises(RerankError):
            reranker.rerank("q", ["a", "b"])

    def test_missing_key_raises(self) -> None:
        settings = Settings(_env_file=None, rerank_api_key=None, embedding_api_key=None)
        with self.assertRaises(RerankError):
            SiliconFlowReranker(settings)


if __name__ == "__main__":
    unittest.main()
