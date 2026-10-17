"""Data access for notes."""

from datetime import timedelta

from sqlalchemy import ColumnElement, Select, select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Note


class NotInTrashError(Exception):
    """Raised by ``restore_note`` when the note exists but is not in the trash."""


def is_active() -> ColumnElement[bool]:
    """The one definition of "active": the clause ``deleted_at IS NULL``.

    Use it in UPDATE/DELETE statements; SELECTs should start from ``active_notes()``.
    """
    return Note.deleted_at.is_(None)


def active_notes() -> Select[tuple[Note]]:
    """Base SELECT for every query over live notes; trashed notes are excluded.

    Every read of active notes (lookup, listings, and later tags, pagination and search) must
    start from this helper so the trash filter cannot be forgotten.
    """
    return select(Note).where(is_active())


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
    """Return the active note with this id; a trashed or unknown note gives None."""
    # populate_existing: always reflect the database, never a stale identity-map copy.
    stmt = active_notes().where(Note.id == note_id).execution_options(populate_existing=True)
    return session.scalars(stmt).one_or_none()


def list_notes(session: Session, team_ids: list[str] | None, limit: int) -> list[Note]:
    stmt = active_notes()
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
        conditions = [Note.id == note.id, is_active()]
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


def trash_note(session: Session, note_id: str) -> bool:
    """Move an active note to the trash. Returns False when there is no such active note.

    One conditional UPDATE, so two concurrent deletes cannot both succeed. ``version`` and
    ``updated_at`` are left alone: only ``deleted_at`` changes.
    """
    stmt = (
        update(Note)
        .where(Note.id == note_id, is_active())
        .values(deleted_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    moved = session.execute(stmt).rowcount
    session.commit()
    return moved == 1


def list_trashed_notes(session: Session, team_id: str, limit: int) -> list[Note]:
    """A team's trashed notes, most recently deleted first (ties broken by id)."""
    stmt = (
        select(Note)
        .where(Note.team_id == team_id, Note.deleted_at.is_not(None))
        .order_by(Note.deleted_at.desc(), Note.id.desc())
        .limit(limit)
        .execution_options(populate_existing=True)
    )
    return list(session.scalars(stmt))


def restore_note(session: Session, note_id: str) -> Note | None:
    """Atomically take a note out of the trash.

    Runs ``UPDATE notes SET deleted_at = NULL, version = version + 1, updated_at = ... WHERE
    id = :id AND deleted_at IS NOT NULL RETURNING ...`` and returns that row, so the response
    is exactly what this call wrote. ``updated_at`` becomes strictly later than before.
    Returns None for an unknown note and raises ``NotInTrashError`` for an active one.
    """
    while True:
        current = session.scalars(
            select(Note).where(Note.id == note_id).execution_options(populate_existing=True)
        ).one_or_none()
        if current is None:
            return None
        if current.deleted_at is None:
            raise NotInTrashError
        now = utcnow()
        if now <= current.updated_at:  # guarantee a strictly later timestamp
            now = current.updated_at + timedelta(microseconds=1)
        stmt = (
            update(Note)
            .where(
                Note.id == note_id,
                Note.deleted_at.is_not(None),
                # Guards the timestamp computed above: if the row changed since the read,
                # nothing matches and we re-read instead of writing an out-of-date value.
                Note.updated_at == current.updated_at,
            )
            .values(deleted_at=None, version=Note.version + 1, updated_at=now)
            .returning(Note)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        restored = session.scalars(stmt).one_or_none()
        session.commit()
        if restored is not None:
            return restored
        # Lost a race (another restore, a team delete...): re-read to decide 404 / 409 / retry.
