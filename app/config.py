"""应用配置。

所有路径都基于项目根目录解析，避免依赖启动时的当前工作目录。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """项目配置，优先读取环境变量，其次读取项目根目录 .env。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "医药研发知识助手"
    app_version: str = "0.1.0"
    app_env: str = "development"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    # ---------- 生成模型：智谱 GLM ----------
    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    llm_api_key: SecretStr | None = None
    llm_model: str = "glm-4.7-flash"
    llm_fallback_model: str = "glm-4.5-flash"
    # 智谱文档说明 temperature=0 不适用，必须落在 (0, 1]
    llm_temperature: float = Field(default=0.1, gt=0, le=1)
    llm_json_mode: bool = True
    llm_thinking: Literal["enabled", "disabled"] = "disabled"
    llm_timeout: int = Field(default=120, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_max_concurrency: int = Field(default=2, ge=1)
    llm_max_tokens: int = Field(default=4096, gt=0)

    # ---------- Embedding：硅基流动 BGE-M3 ----------
    embedding_provider: str = "openai_compatible"
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_api_key: SecretStr | None = None
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = Field(default=1024, gt=0)
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    embedding_max_retries: int = Field(default=3, ge=0)

    # ---------- Rerank：可选 ----------
    rerank_enabled: bool = False
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_api_key: SecretStr | None = None
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # ---------- 路径 ----------
    data_dir: Path = PROJECT_ROOT / "data"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    chroma_dir: Path = PROJECT_ROOT / "storage" / "chroma"
    sqlite_path: Path = PROJECT_ROOT / "storage" / "app.db"
    snapshot_dir: Path = PROJECT_ROOT / "storage" / "snapshots"
    log_dir: Path = PROJECT_ROOT / "storage" / "logs"

    # ---------- 切块与检索 ----------
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=80, ge=0)
    table_chunk_size: int = Field(default=1200, gt=0)
    chunker_version: str = "scientific-v1"
    enable_entity_linker: bool = True
    retrieval_k: int = Field(default=20, gt=0)
    max_context_chunks: int = Field(default=8, gt=0)
    # 初始阈值基于 P2 冒烟集校准；P8 评估集上必须重新校准。
    max_distance: float = Field(default=0.45, gt=0)
    chroma_collection: str = "pharma_research"
    index_batch_size: int = Field(default=64, ge=1, le=512)
    embedding_timeout: int = Field(default=120, gt=0)
    hnsw_batch_size: int = Field(default=1000, ge=1)
    hnsw_sync_threshold: int = Field(default=100000, ge=1)

    # ---------- LangGraph 预算与停止条件 ----------
    max_plan_rounds: int = Field(default=2, ge=1)
    max_subquestions: int = Field(default=5, ge=1)
    max_retrievals: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=4, ge=0)
    max_llm_calls: int = Field(default=12, ge=0)
    max_task_seconds: int = Field(default=180, gt=0)
    max_evidence: int = Field(default=40, gt=0)

    # ---------- 演示身份 ----------
    demo_user_header: str = "X-User-Id"
    default_demo_user: str = "scientist_031"

    @field_validator(
        "data_dir",
        "raw_data_dir",
        "chroma_dir",
        "sqlite_path",
        "snapshot_dir",
        "log_dir",
        mode="before",
    )
    @classmethod
    def _resolve_path(cls, value: object) -> Path:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @model_validator(mode="after")
    def _check_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        if self.max_context_chunks > self.retrieval_k:
            raise ValueError("max_context_chunks 不能大于 retrieval_k")
        return self

    def ensure_directories(self) -> None:
        """创建运行所需目录，不创建任何索引或数据库内容。"""
        for path in (
            self.data_dir,
            self.raw_data_dir,
            self.chroma_dir,
            self.snapshot_dir,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def llm_configured(self) -> bool:
        return bool(
            self.llm_api_key
            and self.llm_api_key.get_secret_value().strip()
        )

    def embedding_configured(self) -> bool:
        return bool(
            self.embedding_api_key
            and self.embedding_api_key.get_secret_value().strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级缓存配置。测试中可通过 Settings(_env_file=None, ...) 覆盖。"""
    return Settings()
