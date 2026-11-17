from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    sqlite_vec_version: str | None
    embedding_provider: str
    llm_provider: str
