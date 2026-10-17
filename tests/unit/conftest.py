"""Unit-test harness (tester-owned).

Per test: a temp SQLite file, migrations to head once ``alembic.ini`` exists (M3+; the M1/M2
baselines have no Alembic yet), and ``TestClient(create_app(database_url=url))``.
"""

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def run_migrations(url: str) -> None:
    """Upgrade the database at ``url`` to head. Raises if alembic.ini does not exist."""
    from alembic import command
    from alembic.config import Config

    if not ALEMBIC_INI.is_file():
        raise FileNotFoundError(f"alembic.ini not found at {ALEMBIC_INI}")
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = Path.cwd()
    os.chdir(REPO_ROOT)  # relative script_location in alembic.ini resolves from the repo root
    try:
        command.upgrade(cfg, "head")
    finally:
        os.chdir(previous)


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'unit.db').as_posix()}"


@pytest.fixture
def migrate():
    """The migration helper; calling it raises FileNotFoundError without alembic.ini."""
    return run_migrations


@pytest.fixture
def migrated_db_url(db_url):
    """A fresh temp database migrated to head. Errors (FileNotFoundError) without alembic.ini."""
    run_migrations(db_url)
    return db_url


@pytest.fixture
def client(db_url):
    # Migrate only when the repo has Alembic, so M1/M2 baselines keep working.
    if ALEMBIC_INI.is_file():
        run_migrations(db_url)
    with TestClient(create_app(database_url=db_url)) as c:
        yield c


def make_team(client, name=None):
    name = name or f"team-{uuid.uuid4().hex[:8]}"
    resp = client.post("/api/v1/teams", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_note(client, team_id, **fields):
    payload = {"title": f"note-{uuid.uuid4().hex[:8]}"}
    payload.update(fields)
    resp = client.post(f"/api/v1/teams/{team_id}/notes", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def team_factory():
    return make_team


@pytest.fixture
def note_factory():
    return make_note
