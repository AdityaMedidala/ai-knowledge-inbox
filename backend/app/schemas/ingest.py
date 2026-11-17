"""POST /ingest contract: a union discriminated on `type`."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.items import ItemSummary

URL_MAX_CHARS = 2048
TITLE_MAX_CHARS = 200

# Length beyond min_length=1 is checked against NOTE_MAX_CHARS by the submission service.
NoteContent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NoteTitle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=TITLE_MAX_CHARS)]
UrlText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=URL_MAX_CHARS)
]


class NoteIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["note"]
    content: NoteContent
    title: NoteTitle | None = Field(
        default=None, description="Defaults to the note's first line (~60 characters)."
    )


class UrlIngest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["url"]
    url: UrlText = Field(description="http(s) only; fetched by the background worker.")


IngestRequest = Annotated[NoteIngest | UrlIngest, Field(discriminator="type")]


class IngestResponse(BaseModel):
    item: ItemSummary
