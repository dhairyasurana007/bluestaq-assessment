"""M7 tests: scripts/seed.py demo data, gating, --if-empty and Render-style invocation.

The script is exercised as a black box via subprocess against temp SQLite files.
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED = "scripts/seed.py"
TEAMS = "/api/v1/teams"
NOTES = "/api/v1/notes"
AUTHORS = {"Alice", "Bob", "Carol"}


@pytest.fixture(autouse=True)
def _no_repo_root_notes_db():
    """Guard: a seed run must never fall back to ./notes.db in the repo root."""
    path = REPO_ROOT / "notes.db"
    existed = path.exists()
    yield
    if not existed:
        assert not path.exists(), "a test created ./notes.db in the repo root"


def seed_env(url=None, seed_demo_data=None, drop_pythonpath=False):
    env = os.environ.copy()
    env.pop("SEED_DEMO_DATA", None)
    env.pop("DATABASE_URL", None)
    if drop_pythonpath:
        env.pop("PYTHONPATH", None)
    if url is not None:
        env["DATABASE_URL"] = url
    if seed_demo_data is not None:
        env["SEED_DEMO_DATA"] = seed_demo_data
    return env


def run_seed(*args, url=None, seed_demo_data=None, drop_pythonpath=False):
    return subprocess.run(
        [sys.executable, SEED, *args],
        cwd=REPO_ROOT,
        env=seed_env(url, seed_demo_data, drop_pythonpath),
        capture_output=True,
        text=True,
        timeout=120,
    )


def db_path(url):
    return Path(url.removeprefix("sqlite:///"))


def query(url, sql):
    conn = sqlite3.connect(db_path(url))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def count(url, table):
    return query(url, f"SELECT COUNT(*) FROM {table}")[0][0]


def tables(url):
    return {r[0] for r in query(url, "SELECT name FROM sqlite_master WHERE type='table'")}


def assert_no_tables(url):
    assert not db_path(url).exists() or tables(url) == set()


def team_ids(client):
    items = client.get(TEAMS, params={"limit": 100}).json()["items"]
    return {t["name"]: t["id"] for t in items}


# ---------------------------------------------------------------- --force on empty DB


def test_force_seeds_two_teams_and_twelve_notes(migrated_db_url):
    proc = run_seed("--force", url=migrated_db_url)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()
    names = sorted(r[0] for r in query(migrated_db_url, "SELECT name FROM teams"))
    assert names == ["Platform", "Research"]
    assert count(migrated_db_url, "notes") == 12


def test_force_note_distribution_and_trash(migrated_db_url):
    assert run_seed("--force", url=migrated_db_url).returncode == 0
    rows = query(
        migrated_db_url,
        "SELECT t.name, COUNT(*), SUM(n.deleted_at IS NOT NULL) "
        "FROM notes n JOIN teams t ON t.id = n.team_id GROUP BY t.name",
    )
    by_team = {name: (total, trashed) for name, total, trashed in rows}
    assert by_team == {"Platform": (7, 1), "Research": (5, 0)}


def test_force_authors_titles_and_versions(migrated_db_url):
    assert run_seed("--force", url=migrated_db_url).returncode == 0
    rows = query(migrated_db_url, "SELECT author_name, title, version FROM notes")
    assert len(rows) == 12
    assert {r[0] for r in rows} == AUTHORS
    assert all(isinstance(r[1], str) and r[1].strip() for r in rows)
    assert all(r[2] == 1 for r in rows)


def test_force_data_visible_through_api(migrated_db_url):
    assert run_seed("--force", url=migrated_db_url).returncode == 0
    with TestClient(create_app(database_url=migrated_db_url)) as client:
        ids = team_ids(client)
        assert set(ids) == {"Platform", "Research"}

        platform = client.get(NOTES, params={"team_id": ids["Platform"], "limit": 100}).json()
        assert len(platform["items"]) == 6
        assert all(n["deleted_at"] is None for n in platform["items"])
        trash = client.get(f"{TEAMS}/{ids['Platform']}/trash").json()
        assert len(trash["items"]) == 1
        assert trash["items"][0]["deleted_at"] is not None

        research = client.get(NOTES, params={"team_id": ids["Research"], "limit": 100}).json()
        assert len(research["items"]) == 5
        assert client.get(f"{TEAMS}/{ids['Research']}/trash").json()["items"] == []


def test_trashed_demo_note_is_restorable(migrated_db_url):
    assert run_seed("--force", url=migrated_db_url).returncode == 0
    with TestClient(create_app(database_url=migrated_db_url)) as client:
        pid = team_ids(client)["Platform"]
        trashed = client.get(f"{TEAMS}/{pid}/trash").json()["items"][0]
        assert client.post(f"{NOTES}/{trashed['id']}/restore").status_code == 200
        active = client.get(NOTES, params={"team_id": pid, "limit": 100}).json()["items"]
        assert len(active) == 7


# ---------------------------------------------------------------- --if-empty


@pytest.mark.parametrize(
    ("args", "env_value"),
    [
        (["--if-empty"], "true"),
        (["--if-empty", "--force"], None),
        (["--if-empty", "--force"], "true"),
    ],
)
def test_if_empty_after_seeding_changes_nothing(migrated_db_url, args, env_value):
    assert run_seed("--force", url=migrated_db_url).returncode == 0
    before = query(migrated_db_url, "SELECT id, name FROM teams ORDER BY id")
    proc = run_seed(*args, url=migrated_db_url, seed_demo_data=env_value)
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 2
    assert count(migrated_db_url, "notes") == 12
    assert query(migrated_db_url, "SELECT id, name FROM teams ORDER BY id") == before


def test_if_empty_force_with_unrelated_existing_team_seeds_nothing(migrated_db_url):
    with TestClient(create_app(database_url=migrated_db_url)) as client:
        assert client.post(TEAMS, json={"name": "Unrelated"}).status_code == 201
    proc = run_seed("--if-empty", "--force", url=migrated_db_url)
    assert proc.returncode == 0, proc.stderr
    assert [r[0] for r in query(migrated_db_url, "SELECT name FROM teams")] == ["Unrelated"]
    assert count(migrated_db_url, "notes") == 0


def test_if_empty_env_with_unrelated_existing_team_seeds_nothing(migrated_db_url):
    with TestClient(create_app(database_url=migrated_db_url)) as client:
        assert client.post(TEAMS, json={"name": "Unrelated"}).status_code == 201
    proc = run_seed("--if-empty", url=migrated_db_url, seed_demo_data="true")
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 1
    assert count(migrated_db_url, "notes") == 0


# ---------------------------------------------------------------- gating


def test_if_empty_with_env_true_seeds_empty_db(migrated_db_url):
    proc = run_seed("--if-empty", url=migrated_db_url, seed_demo_data="true")
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 2
    assert count(migrated_db_url, "notes") == 12


@pytest.mark.parametrize("value", [None, "false", "", "0", "no"])
def test_seeding_disabled_creates_nothing(migrated_db_url, value):
    proc = run_seed("--if-empty", url=migrated_db_url, seed_demo_data=value)
    assert proc.returncode == 0, proc.stderr
    assert (proc.stdout + proc.stderr).strip()
    assert count(migrated_db_url, "teams") == 0
    assert count(migrated_db_url, "notes") == 0


def test_seeding_disabled_without_if_empty_creates_nothing(migrated_db_url):
    proc = run_seed(url=migrated_db_url)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()
    assert count(migrated_db_url, "teams") == 0


def test_force_overrides_seed_demo_data_false(migrated_db_url):
    proc = run_seed("--force", url=migrated_db_url, seed_demo_data="false")
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 2
    assert count(migrated_db_url, "notes") == 12


@pytest.mark.parametrize("value", [None, "false", ""])
def test_disabled_seeding_on_unmigrated_db_exits_zero_and_creates_no_tables(db_url, value):
    proc = run_seed("--if-empty", url=db_url, seed_demo_data=value)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()
    assert_no_tables(db_url)


# ---------------------------------------------------------------- database url


def test_database_url_flag_overrides_env(migrated_db_url, migrate, tmp_path):
    other_url = f"sqlite:///{(tmp_path / 'other.db').as_posix()}"
    migrate(other_url)
    proc = run_seed("--force", "--database-url", migrated_db_url, url=other_url)
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 2
    assert count(migrated_db_url, "notes") == 12
    assert count(other_url, "teams") == 0
    assert count(other_url, "notes") == 0


def test_default_database_url_comes_from_env(migrated_db_url):
    proc = run_seed("--force", url=migrated_db_url)
    assert proc.returncode == 0, proc.stderr
    assert count(migrated_db_url, "teams") == 2


# ---------------------------------------------------------------- unmigrated DB


@pytest.mark.parametrize("via", ["env", "force"])
def test_unmigrated_db_with_seeding_enabled_fails_clearly(db_url, via):
    if via == "env":
        proc = run_seed("--if-empty", url=db_url, seed_demo_data="true")
    else:
        proc = run_seed("--force", url=db_url)
    assert proc.returncode != 0
    message = proc.stdout + proc.stderr
    assert "alembic upgrade head" in message
    assert "Traceback" not in message
    assert_no_tables(db_url)


# ---------------------------------------------------------------- as Render runs it


def test_runs_as_render_does_without_pythonpath(migrated_db_url):
    first = run_seed("--if-empty", url=migrated_db_url, seed_demo_data="true", drop_pythonpath=True)
    assert first.returncode == 0, first.stderr
    assert count(migrated_db_url, "teams") == 2
    assert count(migrated_db_url, "notes") == 12
    again = run_seed("--if-empty", url=migrated_db_url, seed_demo_data="true", drop_pythonpath=True)
    assert again.returncode == 0, again.stderr
    assert count(migrated_db_url, "notes") == 12
