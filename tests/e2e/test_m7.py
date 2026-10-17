"""M7 e2e: demo seed script (scripts/seed.py).

Fully self-contained: it never uses the shared `base_url` target (so it also passes when
E2E_BASE_URL points at a remote server and never touches that server). Each module run creates
its own temp SQLite DB, migrates it, seeds it exactly as Render would (`python scripts/seed.py`
with cwd = repo root, not `python -m`), starts its own uvicorn and checks the result over HTTP.
"""

import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import APIRequestContext

ROOT = Path(__file__).resolve().parents[2]
SEED = "scripts/seed.py"
AUTHORS = {"Alice", "Bob", "Carol"}


@dataclass
class SeededServer:
    url: str
    env: dict[str, str]
    db_path: Path


def _env_for(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("RENDER_GIT_COMMIT", None)
    env.pop("SEED_DEMO_DATA", None)
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    return env


def _alembic_cmd() -> list[str]:
    """The plain `alembic` console script (as on Render); `-m alembic` only as a fallback."""
    bin_dir = Path(sys.executable).parent
    found = shutil.which("alembic", path=str(bin_dir))
    return (
        [found, "upgrade", "head"]
        if found
        else [sys.executable, "-m", "alembic", "upgrade", "head"]
    )


def _migrate(env: dict[str, str]) -> None:
    subprocess.run(_alembic_cmd(), cwd=ROOT, env=env, check=True, capture_output=True)


def _run_seed(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    # Exactly the Render invocation: plain `python scripts/seed.py`, cwd = repo root.
    return subprocess.run(
        [sys.executable, SEED, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _db_counts(db_path: Path) -> tuple[int, int]:
    con = sqlite3.connect(db_path)
    try:
        teams = con.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        con.close()
    return teams, notes


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(url: str, proc: subprocess.Popen, log: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn exited early ({proc.returncode}); see {log}")
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become healthy within {timeout}s; see {log}")


@pytest.fixture(scope="module")
def seeded() -> Iterator[SeededServer]:
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp, "seed.db")
        env = _env_for(db_path)
        _migrate(env)

        result = _run_seed(env, "--force")
        assert result.returncode == 0, result.stdout + result.stderr

        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        log_path = Path(tmp, "server.log")
        with log_path.open("wb") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_health(url, proc, log_path)
                yield SeededServer(url=url, env=env, db_path=db_path)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def _get(api: APIRequestContext, srv: SeededServer, path: str, **params) -> dict:
    # Absolute URL: independent of the shared `api` fixture's base_url (possibly remote).
    resp = api.get(f"{srv.url}{path}", params=params or None)
    assert resp.status == 200, resp.text()
    return resp.json()


def _teams_by_name(api: APIRequestContext, srv: SeededServer) -> dict[str, dict]:
    items = _get(api, srv, "/api/v1/teams", limit=100)["items"]
    return {t["name"]: t for t in items}


def _team_notes(api: APIRequestContext, srv: SeededServer, team_id: str) -> list[dict]:
    return _get(api, srv, "/api/v1/notes", team_id=team_id, limit=100)["items"]


# --- seeded content over HTTP ------------------------------------------------------------


def test_seed_creates_platform_and_research_teams(api: APIRequestContext, seeded: SeededServer):
    teams = _teams_by_name(api, seeded)
    assert set(teams) == {"Platform", "Research"}
    assert _db_counts(seeded.db_path) == (2, 12)


def test_platform_has_exactly_one_trashed_note(api: APIRequestContext, seeded: SeededServer):
    platform = _teams_by_name(api, seeded)["Platform"]
    trash = _get(api, seeded, f"/api/v1/teams/{platform['id']}/trash", limit=100)
    assert len(trash["items"]) == 1
    assert trash["items"][0]["deleted_at"] is not None
    assert trash["next_cursor"] is None


def test_active_note_counts_per_team(api: APIRequestContext, seeded: SeededServer):
    teams = _teams_by_name(api, seeded)
    platform_notes = _team_notes(api, seeded, teams["Platform"]["id"])
    research_notes = _team_notes(api, seeded, teams["Research"]["id"])
    assert len(platform_notes) == 6  # 7 notes, 1 of them in the trash
    assert len(research_notes) == 5
    assert all(n["deleted_at"] is None for n in platform_notes + research_notes)


def test_research_has_no_trashed_notes(api: APIRequestContext, seeded: SeededServer):
    research = _teams_by_name(api, seeded)["Research"]
    trash = _get(api, seeded, f"/api/v1/teams/{research['id']}/trash")
    assert trash["items"] == []


def test_author_names_drawn_from_alice_bob_carol(api: APIRequestContext, seeded: SeededServer):
    teams = _teams_by_name(api, seeded)
    notes = _team_notes(api, seeded, teams["Platform"]["id"]) + _team_notes(
        api, seeded, teams["Research"]["id"]
    )
    trash = _get(api, seeded, f"/api/v1/teams/{teams['Platform']['id']}/trash")["items"]
    authors = {n["author_name"] for n in notes + trash}
    assert authors <= AUTHORS
    assert authors == AUTHORS


def test_seeded_notes_are_well_formed(api: APIRequestContext, seeded: SeededServer):
    teams = _teams_by_name(api, seeded)
    notes = _team_notes(api, seeded, teams["Platform"]["id"])
    trash = _get(api, seeded, f"/api/v1/teams/{teams['Platform']['id']}/trash")["items"]
    for n in notes + trash:
        assert n["version"] == 1
        assert n["title"].strip()
        assert n["body"].strip()
        assert n["created_at"] == n["updated_at"]
        datetime.fromisoformat(n["created_at"].replace("Z", "+00:00"))
    resp = api.get(f"{seeded.url}/api/v1/notes/{notes[0]['id']}")
    assert resp.status == 200
    assert resp.headers["etag"] == '"1"'


# --- re-runs and gating (CLI behaviour) --------------------------------------------------


def test_second_if_empty_run_changes_nothing(api: APIRequestContext, seeded: SeededServer):
    before = _db_counts(seeded.db_path)
    env = {**seeded.env, "SEED_DEMO_DATA": "true"}
    result = _run_seed(env, "--if-empty")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _db_counts(seeded.db_path) == before == (2, 12)
    # --force --if-empty also respects --if-empty
    result = _run_seed(seeded.env, "--force", "--if-empty")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _db_counts(seeded.db_path) == (2, 12)
    # and the API still shows exactly the same two teams
    assert set(_teams_by_name(api, seeded)) == {"Platform", "Research"}


def test_seed_if_empty_via_env_seeds_empty_db_once():
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp, "env.db")
        env = {**_env_for(db_path), "SEED_DEMO_DATA": "true"}
        _migrate(env)
        first = _run_seed(env, "--if-empty")
        assert first.returncode == 0, first.stdout + first.stderr
        assert _db_counts(db_path) == (2, 12)
        second = _run_seed(env, "--if-empty")
        assert second.returncode == 0, second.stdout + second.stderr
        assert _db_counts(db_path) == (2, 12)


@pytest.mark.parametrize("extra_env", [{}, {"SEED_DEMO_DATA": "false"}, {"SEED_DEMO_DATA": ""}])
@pytest.mark.parametrize("args", [(), ("--if-empty",)])
def test_nothing_seeded_without_env_or_force(extra_env: dict[str, str], args: tuple[str, ...]):
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp, "off.db")
        env = {**_env_for(db_path), **extra_env}
        _migrate(env)
        result = _run_seed(env, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip()  # prints a message
        assert _db_counts(db_path) == (0, 0)


def test_skip_does_not_touch_the_database():
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp, "never-created.db")
        result = _run_seed(_env_for(db_path))
        assert result.returncode == 0, result.stdout + result.stderr
        assert not db_path.exists()


def test_database_url_flag_overrides_env():
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        env_db = Path(tmp, "env.db")
        flag_db = Path(tmp, "flag.db")
        env = _env_for(env_db)
        _migrate(env)
        _migrate(_env_for(flag_db))
        result = _run_seed(env, "--force", "--database-url", f"sqlite:///{flag_db.as_posix()}")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _db_counts(flag_db) == (2, 12)
        assert _db_counts(env_db) == (0, 0)


def test_missing_schema_fails_with_clear_error():
    with tempfile.TemporaryDirectory(prefix="notes-m7-", ignore_cleanup_errors=True) as tmp:
        env = _env_for(Path(tmp, "unmigrated.db"))
        result = _run_seed(env, "--force")
        assert result.returncode != 0
        assert "alembic upgrade head" in result.stderr
        assert "Traceback" not in result.stderr
