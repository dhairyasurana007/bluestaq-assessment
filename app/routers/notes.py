"""Note endpoints (PLAN.md section 5.3, endpoints 7-11)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import NotFoundError
from app.models import Note
from app.repositories import notes as repo
from app.repositories import teams as teams_repo
from app.schemas import NoteCreate, NoteList, NoteOut, NoteUpdate

router = APIRouter(prefix="/api/v1", tags=["notes"])

SessionDep = Annotated[Session, Depends(get_session)]


def _etag(note: Note) -> str:
    return f'"{note.version}"'


def _require_note(session: Session, note_id: UUID) -> Note:
    note = repo.get_note(session, str(note_id))
    if note is None:
        raise NotFoundError("Note not found.")
    return note


@router.post("/teams/{team_id}/notes", status_code=201, response_model=NoteOut)
def create_note(team_id: UUID, body: NoteCreate, response: Response, session: SessionDep) -> Note:
    if teams_repo.get_team(session, str(team_id)) is None:
        raise NotFoundError("Team not found.")
    note = repo.create_note(session, str(team_id), body.title, body.body, body.author_name)
    response.headers["Location"] = f"/api/v1/notes/{note.id}"
    response.headers["ETag"] = _etag(note)
    return note


@router.get("/notes", response_model=NoteList)
def list_notes(
    session: SessionDep,
    # team_id values are plain strings: an unknown (or non-UUID) value simply matches nothing.
    team_id: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NoteList:
    items = repo.list_notes(session, team_id, limit)
    return NoteList(items=[NoteOut.model_validate(n) for n in items])


@router.get("/notes/{note_id}", response_model=NoteOut)
def get_note(note_id: UUID, response: Response, session: SessionDep) -> Note:
    note = _require_note(session, note_id)
    response.headers["ETag"] = _etag(note)
    return note


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(note_id: UUID, body: NoteUpdate, response: Response, session: SessionDep) -> Note:
    note = _require_note(session, note_id)
    changes = body.model_dump(exclude_unset=True)
    note = repo.update_note(session, note, changes)
    response.headers["ETag"] = _etag(note)
    return note


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: UUID, session: SessionDep) -> Response:
    note = _require_note(session, note_id)
    repo.delete_note(session, note)
    return Response(status_code=204)
