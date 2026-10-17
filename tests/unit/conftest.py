"""Unit-test harness (tester-owned). Alembic arrives in M3, so no migrations yet."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'unit.db').as_posix()}"


@pytest.fixture
def client(db_url):
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
