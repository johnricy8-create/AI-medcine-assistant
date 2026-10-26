"""Embedding 客户端构造与向量校验。"""

from __future__ import annotations

import math

from langchain_openai import OpenAIEmbeddings

from app.config import Settings


class EmbeddingConfigurationError(RuntimeError):
    pass


class EmbeddingValidationError(RuntimeError):
    pass


def build_embeddings(settings: Settings) -> OpenAIEmbeddings:
    if not settings.embedding_configured():
        raise EmbeddingConfigurationError(
            "未配置 EMBEDDING_API_KEY；请在 .env 填入硅基流动 Key"
        )
    key = settings.embedding_api_key.get_secret_value()
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        api_key=key,
        check_embedding_ctx_length=False,
        chunk_size=settings.embedding_batch_size,
        max_retries=settings.embedding_max_retries,
        request_timeout=settings.embedding_timeout,
    )


def validate_vectors(
    vectors: list[list[float]],
    expected_dim: int,
    *,
    label: str = "embedding",
) -> None:
    if not vectors:
        raise EmbeddingValidationError(f"{label}: 返回空向量列表")
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dim:
            raise EmbeddingValidationError(
                f"{label}[{index}]: 维度 {len(vector)} != {expected_dim}"
            )
        if not any(value != 0 for value in vector):
            raise EmbeddingValidationError(f"{label}[{index}]: 全零向量")
        if any(math.isnan(value) or math.isinf(value) for value in vector):
            raise EmbeddingValidationError(f"{label}[{index}]: 包含 NaN/Inf")
        if max(abs(value) for value in vector) > 100:
            raise EmbeddingValidationError(f"{label}[{index}]: 数值范围异常")
