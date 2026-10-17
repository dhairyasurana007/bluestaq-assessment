"""Data access for notes."""

from datetime import timedelta

from sqlalchemy import select, update
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
    # populate_existing: always reflect the database, never a stale identity-map copy.
    return session.get(Note, note_id, populate_existing=True)


def list_notes(session: Session, team_ids: list[str] | None, limit: int) -> list[Note]:
    stmt = select(Note)
    if team_ids:
        stmt = stmt.where(Note.team_id.in_(team_ids))
    stmt = stmt.order_by(Note.updated_at.desc(), Note.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def update_note(
    session: Session, note: Note, changes: dict[str, str], expected_version: int | None
) -> Note | None:
    """Atomically apply ``changes`` and bump the version (PLAN.md section 5.7).

    Runs ``UPDATE notes SET ..., version = version + 1 WHERE id = :id AND version = :expected``.
    ``expected_version=None`` means ``If-Match: *``: the version condition is omitted. Returns the
    refreshed note, or None when no row matched (version mismatch, or the note is gone; for ``*``
    only the latter); the caller then looks the note up to tell 412 from 404.
    """
    while True:
        now = utcnow()
        if now <= note.updated_at:  # guarantee a strictly later timestamp
            now = note.updated_at + timedelta(microseconds=1)
        conditions = [Note.id == note.id]
        if expected_version is not None:
            conditions.append(Note.version == expected_version)
        else:
            # No version condition, but never let a concurrent write be overtaken by an older
            # timestamp: if the row moved since we read it, re-read and retry. Every retry means
            # another writer committed, so the loop makes progress and ends when we win or the
            # note is really gone (a `*` request never fails with 412 on an existing note).
            conditions.append(Note.updated_at == note.updated_at)
        stmt = (
            update(Note)
            .where(*conditions)
            .values(**changes, version=Note.version + 1, updated_at=now)
            .returning(Note)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        # RETURNING hands back the row this very UPDATE wrote, so the response can never show
        # another writer's later state (a separate read after the commit could).
        updated = session.scalars(stmt).one_or_none()
        session.commit()
        if updated is not None:
            return updated
        if expected_version is not None:
            return None
        reread = get_note(session, note.id)
        if reread is None:
            return None
        note = reread


def delete_note(session: Session, note: Note) -> None:
    session.delete(note)
    session.commit()
