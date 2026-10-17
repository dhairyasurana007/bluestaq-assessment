"""Pydantic request/response shapes (PLAN.md sections 5.1 and 5.2)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
NoteTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
NoteBody = Annotated[str, StringConstraints(max_length=100_000)]
AuthorName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TeamName


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TeamName


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class TeamList(BaseModel):
    items: list[TeamOut]
    next_cursor: str | None = None


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: NoteTitle
    body: NoteBody = ""
    author_name: AuthorName | None = None


class NoteUpdate(BaseModel):
    """PATCH body: at least one of title/body; explicit nulls are rejected."""

    model_config = ConfigDict(extra="forbid")

    title: NoteTitle | None = None
    body: NoteBody | None = None

    @model_validator(mode="after")
    def _check_provided(self) -> "NoteUpdate":
        provided = self.model_fields_set
        if not provided:
            raise ValueError("Provide at least one of: title, body.")
        for name in provided:
            if getattr(self, name) is None:
                raise ValueError(f"{name} must not be null.")
        return self


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)  # always [] until tags arrive in F1
    author_name: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class NoteList(BaseModel):
    items: list[NoteOut]
    next_cursor: str | None = None
