"""Single source of configuration. Every value comes from the environment (or repo-root .env)."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

ProviderName = Literal["openai", "fake"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # `OPENAI_API_KEY=` in .env means "unset", not an empty key
        extra="ignore",
    )

    openai_api_key: SecretStr | None = None
    embedding_provider: ProviderName = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = Field(default=1536, gt=0)
    llm_provider: ProviderName = "openai"
    llm_model: str | None = None
    llm_temperature: float | None = Field(default=None, ge=0, le=2)  # sent only when set
    reranker: Literal["none", "cohere"] = "none"
    cohere_api_key: SecretStr | None = None
    rerank_model: str = "rerank-v3.5"

    openai_max_retries: int = Field(default=2, ge=0)  # SDK retries 429/5xx/timeouts w/ backoff
    embedding_timeout_s: float = Field(default=30, gt=0)
    llm_timeout_s: float = Field(default=60, gt=0)
    rerank_timeout_s: float = Field(default=10, gt=0)

    db_path: Path = Path("./data/inbox.db")
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    log_level: LogLevel = "INFO"
    log_json: bool = False

    worker_concurrency: int = Field(default=2, ge=1)
    chunk_tokens: int = Field(default=400, gt=0)
    chunk_overlap_tokens: int = Field(default=60, ge=0)
    retrieval_candidates: int = Field(default=20, gt=0)
    rrf_k: int = Field(default=60, gt=0)
    max_chunks_per_item: int = Field(default=3, gt=0)
    # Provisional values; calibrated against the eval set in M6.
    relevance_min_full: float = Field(default=0.45, ge=0, le=1)
    relevance_min_partial: float = Field(default=0.30, ge=0, le=1)

    fetch_timeout_s: float = Field(default=10, gt=0)
    fetch_max_bytes: int = Field(default=5_000_000, gt=0)
    fetch_max_redirects: int = Field(default=3, ge=0)
    note_max_chars: int = Field(default=50_000, gt=0)
    question_max_chars: int = Field(default=1_000, gt=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        uses_openai = "openai" in (self.embedding_provider, self.llm_provider)
        if uses_openai and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when a provider is 'openai'.")
        if self.llm_provider == "openai" and not self.llm_model:
            raise ValueError("LLM_MODEL is required when LLM_PROVIDER=openai.")
        if self.reranker == "cohere" and self.cohere_api_key is None:
            raise ValueError("COHERE_API_KEY is required when RERANKER=cohere.")
        if self.chunk_overlap_tokens >= self.chunk_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_TOKENS.")
        if self.relevance_min_partial > self.relevance_min_full:
            raise ValueError("RELEVANCE_MIN_PARTIAL must not exceed RELEVANCE_MIN_FULL.")
        return self
