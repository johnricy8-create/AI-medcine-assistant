"""测试用假 Embedding，不访问网络。"""

from __future__ import annotations

import hashlib


class FakeEmbeddings:
    def __init__(self, dim: int = 16) -> None:
        self.dim = dim
        self.calls = 0

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [
            (digest[index % len(digest)] / 127.5) - 1.0
            for index in range(self.dim)
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
