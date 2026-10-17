"""Data access for notes."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Note


def create_note(
    session: Session, team_id: str, title: str, body: str, author_name: str | None
) -> Note:
    now = utcnow()  # one timestamp so created_at == updated_at on a fresh note
    note = Note(
        team_id=team_id,
        title=title,
        body=body,
        author_name=author_name,
        created_at=now,
        updated_at=now,
    )
    session.add(note)
    session.commit()
    return note


def get_note(session: Session, note_id: str) -> Note | None:
    return session.get(Note, note_id)


def list_notes(session: Session, team_ids: list[str] | None, limit: int) -> list[Note]:
    stmt = select(Note)
    if team_ids:
        stmt = stmt.where(Note.team_id.in_(team_ids))
    stmt = stmt.order_by(Note.updated_at.desc(), Note.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def update_note(session: Session, note: Note, changes: dict[str, str]) -> Note:
    now = utcnow()
    if now <= note.updated_at:  # guarantee a strictly later timestamp
        now = note.updated_at + timedelta(microseconds=1)
    for field, value in changes.items():
        setattr(note, field, value)
    note.version += 1
    note.updated_at = now
    session.commit()
    return note


def delete_note(session: Session, note: Note) -> None:
    session.delete(note)
    session.commit()
