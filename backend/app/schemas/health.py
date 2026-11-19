from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    sqlite_vec_version: str | None
    embedding_provider: str
    llm_provider: str
    demo_mode: bool = Field(description="Public demo: rate limits and an item cap apply.")
