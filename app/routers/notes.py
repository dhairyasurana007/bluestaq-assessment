"""Note endpoints (PLAN.md section 5.3, endpoints 7-13)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import (
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
)
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


def _parse_if_match(value: str, note: Note) -> int | None:
    """Parse an If-Match header: None means ``*``, otherwise the expected version.

    Trims, strips an optional ``W/`` prefix and the surrounding quotes. Anything that is not then
    a plain integer (including an empty value or a comma-separated list) is a 412.
    """
    candidate = value.strip()
    if candidate == "*":
        return None
    if candidate.startswith("W/"):
        candidate = candidate[2:]
    if len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"'):
        candidate = candidate[1:-1]
    # The length cap keeps absurd values from overflowing SQLite's 64-bit integers.
    if candidate.isascii() and candidate.isdigit() and len(candidate) <= 18:
        return int(candidate)
    raise PreconditionFailedError(
        f"Invalid If-Match header (current version {note.version}). "
        f'Send the ETag from a previous response, for example "{note.version}", or *.'
    )


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: UUID,
    body: NoteUpdate,
    response: Response,
    session: SessionDep,
    if_match: Annotated[str | None, Header()] = None,
) -> Note:
    note = _require_note(session, note_id)
    if if_match is None:
        raise PreconditionRequiredError(
            "If-Match header is required. Send the ETag from your last GET or PATCH."
        )
    expected_version = _parse_if_match(if_match, note)
    changes = body.model_dump(exclude_unset=True)
    updated = repo.update_note(session, note, changes, expected_version)
    if updated is None:
        current = repo.get_note(session, str(note_id))
        if current is None:
            raise NotFoundError("Note not found.")
        raise PreconditionFailedError(
            f"Note was modified by someone else (current version {current.version})."
        )
    response.headers["ETag"] = _etag(updated)
    return updated


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: UUID, session: SessionDep) -> Response:
    """Soft delete: the note moves to the trash (restorable via endpoint 13)."""
    if not repo.trash_note(session, str(note_id)):
        raise NotFoundError("Note not found.")
    return Response(status_code=204)


@router.get("/teams/{team_id}/trash", response_model=NoteList)
def list_trash(
    team_id: UUID,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NoteList:
    if teams_repo.get_team(session, str(team_id)) is None:
        raise NotFoundError("Team not found.")
    items = repo.list_trashed_notes(session, str(team_id), limit)
    return NoteList(items=[NoteOut.model_validate(n) for n in items])


@router.post("/notes/{note_id}/restore", response_model=NoteOut)
def restore_note(note_id: UUID, response: Response, session: SessionDep) -> Note:
    try:
        note = repo.restore_note(session, str(note_id))
    except repo.NotInTrashError:
        raise ConflictError("Note is not in the trash.") from None
    if note is None:
        raise NotFoundError("Note not found.")
    response.headers["ETag"] = _etag(note)
    return note
