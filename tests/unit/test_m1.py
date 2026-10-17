"""M1 acceptance tests: Settings and create_app wiring (must fail on M0 code)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No DATABASE_URL, run from an empty cwd so no .env / notes.db interferes."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_settings_importable_and_default_database_url(clean_env):
    from app.config import Settings

    assert Settings().database_url == "sqlite:///./notes.db"


def test_settings_reads_database_url_from_env(clean_env, monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    assert Settings().database_url == "sqlite:///x.db"


def test_settings_env_is_read_at_instantiation_not_import(clean_env, monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:///first.db")
    assert Settings().database_url == "sqlite:///first.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///second.db")
    assert Settings().database_url == "sqlite:///second.db"
    monkeypatch.delenv("DATABASE_URL")
    assert Settings().database_url == "sqlite:///./notes.db"


def test_settings_accepts_non_sqlite_url_verbatim(clean_env, monkeypatch):
    from app.config import Settings

    url = "postgresql+psycopg://user:pw@host:5432/db"
    monkeypatch.setenv("DATABASE_URL", url)
    assert Settings().database_url == url


def test_settings_ignores_unrelated_env_vars(clean_env, monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc")
    assert Settings().database_url == "sqlite:///./notes.db"


def test_create_app_stores_explicit_url_on_state(tmp_path):
    url = f"sqlite:///{(tmp_path / 'x.db').as_posix()}"
    app = create_app(url)
    assert app.state.database_url == url


def test_create_app_accepts_database_url_keyword(tmp_path):
    url = f"sqlite:///{(tmp_path / 'kw.db').as_posix()}"
    app = create_app(database_url=url)
    assert app.state.database_url == url


def test_create_app_explicit_url_wins_over_env(clean_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env.db")
    app = create_app("sqlite:///explicit.db")
    assert app.state.database_url == "sqlite:///explicit.db"


def test_create_app_without_url_uses_default_settings(clean_env):
    app = create_app()
    assert app.state.database_url == "sqlite:///./notes.db"


def test_create_app_none_uses_env_settings(clean_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from-env.db")
    app = create_app(None)
    assert app.state.database_url == "sqlite:///from-env.db"


def test_create_app_does_not_create_default_database_file(clean_env):
    app = create_app()
    assert app.state.database_url == "sqlite:///./notes.db"
    assert not (clean_env / "notes.db").exists()
    assert not (clean_env / "notes.db-wal").exists()


def test_create_app_with_explicit_url_does_not_create_default_database_file(clean_env):
    app = create_app("sqlite:///explicit.db")
    assert app.state.database_url == "sqlite:///explicit.db"
    assert not (clean_env / "notes.db").exists()


def test_each_app_instance_has_its_own_database_url(tmp_path):
    url_a = f"sqlite:///{(tmp_path / 'a.db').as_posix()}"
    url_b = f"sqlite:///{(tmp_path / 'b.db').as_posix()}"
    app_a = create_app(url_a)
    app_b = create_app(url_b)
    assert app_a is not app_b
    assert app_a.state.database_url == url_a
    assert app_b.state.database_url == url_b


def test_module_level_app_has_resolved_database_url():
    from app.main import app

    assert isinstance(app.state.database_url, str)
    assert "://" in app.state.database_url


def test_client_fixture_app_exposes_database_url(client, db_url):
    assert client.app.state.database_url == db_url


def test_health_still_works_on_app_built_with_database_url(db_url, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    app = create_app(db_url)
    assert app.state.database_url == db_url
    with TestClient(app) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "commit": "local"}
