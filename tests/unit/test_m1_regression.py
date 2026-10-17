"""M1 regression criteria: already true on the M0 baseline and must stay true."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def api(tmp_path):
    url = f"sqlite:///{(tmp_path / 'reg.db').as_posix()}"
    with TestClient(create_app(database_url=url)) as c:
        yield c


def test_health_local_commit_when_env_unset(api, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    resp = api.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "commit": "local"}


def test_health_reports_render_commit_from_env(api, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    resp = api.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "commit": "abc123"}


def test_health_reads_env_at_request_time(api, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "first")
    assert api.get("/health").json()["commit"] == "first"
    monkeypatch.setenv("RENDER_GIT_COMMIT", "second")
    assert api.get("/health").json()["commit"] == "second"
    monkeypatch.delenv("RENDER_GIT_COMMIT")
    assert api.get("/health").json()["commit"] == "local"


def test_docs_page_is_served(api):
    assert api.get("/docs").status_code == 200


def test_openapi_json_title(api):
    resp = api.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Team Notes API"


def test_openapi_documents_health_route(api):
    assert "/health" in api.get("/openapi.json").json()["paths"]


def test_unknown_path_is_404(api):
    assert api.get("/definitely/not/a/route").status_code == 404
