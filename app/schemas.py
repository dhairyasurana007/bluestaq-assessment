"""Pydantic request/response shapes (PLAN.md sections 5.1 and 5.2)."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


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
