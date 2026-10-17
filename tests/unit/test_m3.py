"""M3 acceptance tests: team spaces, DB foundation (Alembic), problem+json error contract."""

import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
TEAMS = "/api/v1/teams"
TEAM_KEYS = {"id", "name", "created_at", "updated_at"}
PROBLEM = "application/problem+json"


def tiny_sleep():
    time.sleep(0.02)


def parse_ts(value):
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        assert parsed.utcoffset() == timedelta(0), f"timestamp not UTC: {value}"
    return parsed.replace(tzinfo=None)


def assert_problem(resp, status, instance=None):
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM, resp.headers
    body = resp.json()
    for key in ("type", "title", "status", "detail", "instance"):
        assert key in body, f"missing {key!r} in {body}"
    assert body["status"] == status
    assert body["type"] == "about:blank"
    phrases = {HTTPStatus(status).phrase}
    if status == 422:
        phrases |= {"Unprocessable Entity", "Unprocessable Content"}
    assert body["title"] in phrases, body["title"]
    assert isinstance(body["detail"], str) and body["detail"]
    if instance is not None:
        assert body["instance"] == instance
    return body


def assert_422_loc(resp, loc, instance=None):
    body = assert_problem(resp, 422, instance)
    assert isinstance(body.get("errors"), list) and body["errors"], body
    for err in body["errors"]:
        assert "loc" in err and "msg" in err, err
    assert [e["loc"] for e in body["errors"] if e["loc"] == loc], body["errors"]
    return body


def create(client, name="Platform"):
    resp = client.post(TEAMS, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- migrations / DB foundation


def test_alembic_ini_exists_and_migrates_to_head(db_url, migrate):
    migrate(db_url)
    migrated_db_url = db_url
    # criterion: alembic.ini + migrations/env.py + 0001_teams work via command.upgrade(cfg, "head")
    path = migrated_db_url.removeprefix("sqlite:///")
    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "teams" in tables, tables
        assert "alembic_version" in tables, tables
        cols = {r[1] for r in con.execute("PRAGMA table_info(teams)")}
        assert cols >= TEAM_KEYS, cols
    finally:
        con.close()


def test_migration_is_idempotent_at_head(db_url, migrate):
    migrate(db_url)
    migrated_db_url = db_url
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", migrated_db_url)
    monkey_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        command.upgrade(cfg, "head")  # second run must be a no-op, not an error
    finally:
        os.chdir(monkey_cwd)
    con = sqlite3.connect(migrated_db_url.removeprefix("sqlite:///"))
    try:
        assert con.execute("SELECT COUNT(*) FROM alembic_version").fetchone()[0] == 1
    finally:
        con.close()


def test_app_uses_migrated_database_end_to_end(db_url, migrate):
    migrate(db_url)
    migrated_db_url = db_url
    # criterion: migrations/env.py honours sqlalchemy.url; app on that URL serves teams
    with TestClient(create_app(database_url=migrated_db_url)) as c:
        created = create(c, "Persisted")
    path = migrated_db_url.removeprefix("sqlite:///")
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT id, name FROM teams").fetchall()
    finally:
        con.close()
    assert rows == [(created["id"], "Persisted")]


def test_data_persists_across_app_instances(db_url, migrate):
    migrate(db_url)
    migrated_db_url = db_url
    with TestClient(create_app(database_url=migrated_db_url)) as c1:
        created = create(c1, "Durable")
    with TestClient(create_app(database_url=migrated_db_url)) as c2:
        got = c2.get(f"{TEAMS}/{created['id']}")
        assert got.status_code == 200
        assert got.json() == created


def test_database_uses_wal_journal_mode(client, db_url):
    # criterion (Build): journal_mode=WAL is set on connect (persists in the db file)
    create(client)
    con = sqlite3.connect(db_url.removeprefix("sqlite:///"))
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        con.close()


# ---------------------------------------------------------------- POST /teams


def test_create_team_returns_201_and_team_out(client):
    resp = client.post(TEAMS, json={"name": "Platform"})
    assert resp.status_code == 201, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert set(body) == TEAM_KEYS
    assert body["name"] == "Platform"
    assert str(uuid.UUID(body["id"])) == body["id"]
    parse_ts(body["created_at"])
    parse_ts(body["updated_at"])


def test_create_team_location_header(client):
    resp = client.post(TEAMS, json={"name": "Platform"})
    assert resp.status_code == 201, resp.text
    assert resp.headers["location"] == f"/api/v1/teams/{resp.json()['id']}"


def test_create_team_then_get_returns_same_representation(client):
    created = create(client)
    got = client.get(f"{TEAMS}/{created['id']}")
    assert got.status_code == 200
    assert got.json() == created


def test_create_team_trims_whitespace(client):
    resp = client.post(TEAMS, json={"name": "   Platform \t\n"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Platform"
    assert client.get(f"{TEAMS}/{resp.json()['id']}").json()["name"] == "Platform"


def test_create_team_preserves_inner_whitespace(client):
    resp = client.post(TEAMS, json={"name": "  Core  Platform "})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Core  Platform"


def test_create_team_ids_are_unique(client):
    assert create(client, "A")["id"] != create(client, "B")["id"]


@pytest.mark.parametrize("length", [1, 99, 100])
def test_create_team_accepts_name_lengths_up_to_100(client, length):
    name = "a" * length
    resp = client.post(TEAMS, json={"name": name})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == name


def test_create_team_accepts_100_chars_after_trimming(client):
    resp = client.post(TEAMS, json={"name": "  " + "b" * 100 + "  "})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "b" * 100


def test_create_team_accepts_100_multibyte_chars(client):
    name = "é" * 100
    resp = client.post(TEAMS, json={"name": name})
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == name


def test_create_team_rejects_101_char_name(client):
    resp = client.post(TEAMS, json={"name": "a" * 101})
    assert_422_loc(resp, ["body", "name"], TEAMS)


def test_create_team_rejects_101_chars_after_trimming(client):
    resp = client.post(TEAMS, json={"name": " " + "a" * 101 + " "})
    assert_422_loc(resp, ["body", "name"], TEAMS)


@pytest.mark.parametrize("name", ["", " ", "   ", "\t\n "])
def test_create_team_rejects_empty_or_whitespace_name(client, name):
    resp = client.post(TEAMS, json={"name": name})
    assert_422_loc(resp, ["body", "name"], TEAMS)


def test_create_team_rejects_missing_name(client):
    resp = client.post(TEAMS, json={})
    assert_422_loc(resp, ["body", "name"], TEAMS)


@pytest.mark.parametrize("value", [None, 123, ["x"], {"a": 1}, True])
def test_create_team_rejects_non_string_name(client, value):
    resp = client.post(TEAMS, json={"name": value})
    assert_422_loc(resp, ["body", "name"], TEAMS)


def test_create_team_rejects_unknown_field(client):
    resp = client.post(TEAMS, json={"name": "Platform", "color": "red"})
    body = assert_problem(resp, 422, TEAMS)
    assert body["errors"], body


def test_create_team_unknown_field_creates_nothing(client):
    client.post(TEAMS, json={"name": "Platform", "color": "red"})
    assert client.get(TEAMS).json()["items"] == []


def test_create_team_rejects_client_supplied_id(client):
    resp = client.post(TEAMS, json={"name": "Platform", "id": str(uuid.uuid4())})
    assert_problem(resp, 422, TEAMS)


def test_create_team_rejects_empty_body(client):
    resp = client.post(TEAMS)
    assert_problem(resp, 422, TEAMS)


def test_create_team_rejects_malformed_json(client):
    resp = client.post(TEAMS, content=b"{not json", headers={"content-type": "application/json"})
    assert_problem(resp, 422, TEAMS)


def test_create_team_rejects_json_array_body(client):
    resp = client.post(TEAMS, json=["Platform"])
    assert_problem(resp, 422, TEAMS)


def test_failed_create_leaves_no_team_behind(client):
    client.post(TEAMS, json={"name": ""})
    assert client.get(TEAMS).json() == {"items": [], "next_cursor": None}


# ---------------------------------------------------------------- GET /teams


def test_list_teams_empty(client):
    resp = client.get(TEAMS)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "next_cursor": None}


def test_list_teams_shape(client):
    created = create(client)
    body = client.get(TEAMS).json()
    assert set(body) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert body["items"] == [created]


def test_list_teams_newest_first(client):
    names = []
    for i in range(4):
        names.append(create(client, f"team-{i}")["name"])
        tiny_sleep()
    items = client.get(TEAMS).json()["items"]
    assert [t["name"] for t in items] == list(reversed(names))
    created = [parse_ts(t["created_at"]) for t in items]
    assert created == sorted(created, reverse=True)


def test_list_teams_default_limit_is_20(client):
    for i in range(21):
        create(client, f"t{i}")
    body = client.get(TEAMS).json()
    assert len(body["items"]) == 20
    assert body["next_cursor"] is None


def test_list_teams_limit_is_respected_and_returns_newest(client):
    for i in range(3):
        create(client, f"t{i}")
        tiny_sleep()
    items = client.get(TEAMS, params={"limit": 2}).json()["items"]
    assert [t["name"] for t in items] == ["t2", "t1"]
    one = client.get(TEAMS, params={"limit": 1}).json()
    assert [t["name"] for t in one["items"]] == ["t2"]
    assert one["next_cursor"] is None


def test_list_teams_limit_100_accepted(client):
    create(client)
    resp = client.get(TEAMS, params={"limit": 100})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1


def test_list_teams_limit_larger_than_count_returns_all(client):
    for i in range(3):
        create(client, f"t{i}")
    assert len(client.get(TEAMS, params={"limit": 50}).json()["items"]) == 3


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc", "1.5", ""])
def test_list_teams_rejects_invalid_limit(client, limit):
    resp = client.get(TEAMS, params={"limit": limit})
    body = assert_problem(resp, 422, TEAMS)
    assert [e for e in body["errors"] if e["loc"] == ["query", "limit"]], body["errors"]


# ---------------------------------------------------------------- GET /teams/{id}


def test_get_team_returns_200(client):
    created = create(client)
    resp = client.get(f"{TEAMS}/{created['id']}")
    assert resp.status_code == 200
    assert set(resp.json()) == TEAM_KEYS
    assert resp.json() == created


def test_get_team_random_uuid_is_404_problem(client):
    missing = str(uuid.uuid4())
    body = assert_problem(client.get(f"{TEAMS}/{missing}"), 404, f"{TEAMS}/{missing}")
    assert body["title"] == "Not Found"


def test_get_team_only_returns_requested_team(client):
    a = create(client, "A")
    b = create(client, "B")
    assert client.get(f"{TEAMS}/{a['id']}").json()["name"] == "A"
    assert client.get(f"{TEAMS}/{b['id']}").json()["name"] == "B"


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "123", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"])
def test_get_team_non_uuid_is_422(client, bad_id):
    resp = client.get(f"{TEAMS}/{bad_id}")
    assert_422_loc(resp, ["path", "team_id"], f"{TEAMS}/{bad_id}")


# ---------------------------------------------------------------- PATCH /teams/{id}


def test_patch_team_renames_and_bumps_updated_at(client):
    created = create(client, "Old")
    tiny_sleep()
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "New"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == TEAM_KEYS
    assert body["name"] == "New"
    assert body["id"] == created["id"]
    assert parse_ts(body["updated_at"]) > parse_ts(created["updated_at"])


def test_patch_team_leaves_created_at_unchanged(client):
    created = create(client, "Old")
    tiny_sleep()
    body = client.patch(f"{TEAMS}/{created['id']}", json={"name": "New"}).json()
    assert body["created_at"] == created["created_at"]


def test_patch_team_is_persisted(client):
    created = create(client, "Old")
    tiny_sleep()
    patched = client.patch(f"{TEAMS}/{created['id']}", json={"name": "New"}).json()
    assert client.get(f"{TEAMS}/{created['id']}").json() == patched


def test_patch_team_trims_name(client):
    created = create(client)
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "  Trimmed  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Trimmed"


def test_patch_team_name_boundaries(client):
    created = create(client)
    assert client.patch(f"{TEAMS}/{created['id']}", json={"name": "x"}).status_code == 200
    assert client.patch(f"{TEAMS}/{created['id']}", json={"name": "y" * 100}).status_code == 200
    assert_422_loc(
        client.patch(f"{TEAMS}/{created['id']}", json={"name": "y" * 101}),
        ["body", "name"],
        f"{TEAMS}/{created['id']}",
    )


def test_patch_team_only_changes_target(client):
    a = create(client, "A")
    b = create(client, "B")
    client.patch(f"{TEAMS}/{a['id']}", json={"name": "A2"})
    assert client.get(f"{TEAMS}/{b['id']}").json() == b


def test_patch_team_unknown_id_is_404_problem(client):
    missing = str(uuid.uuid4())
    resp = client.patch(f"{TEAMS}/{missing}", json={"name": "New"})
    assert_problem(resp, 404, f"{TEAMS}/{missing}")


def test_patch_team_non_uuid_is_422(client):
    resp = client.patch(f"{TEAMS}/nope", json={"name": "New"})
    assert_422_loc(resp, ["path", "team_id"], f"{TEAMS}/nope")


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_patch_team_rejects_empty_or_whitespace_name(client, name):
    created = create(client, "Keep")
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": name})
    assert_422_loc(resp, ["body", "name"], f"{TEAMS}/{created['id']}")
    assert client.get(f"{TEAMS}/{created['id']}").json()["name"] == "Keep"


def test_patch_team_requires_name(client):
    created = create(client)
    assert_422_loc(
        client.patch(f"{TEAMS}/{created['id']}", json={}),
        ["body", "name"],
        f"{TEAMS}/{created['id']}",
    )


def test_patch_team_rejects_unknown_field(client):
    created = create(client)
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "New", "extra": 1})
    assert_problem(resp, 422, f"{TEAMS}/{created['id']}")


def test_patch_team_cannot_change_id_or_created_at(client):
    created = create(client)
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "N", "id": str(uuid.uuid4())})
    assert_problem(resp, 422)
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "N", "created_at": "2020-01-01"})
    assert_problem(resp, 422)


# ---------------------------------------------------------------- DELETE /teams/{id}


def test_delete_team_returns_204_with_empty_body(client):
    created = create(client)
    resp = client.delete(f"{TEAMS}/{created['id']}")
    assert resp.status_code == 204, resp.text
    assert resp.content == b""


def test_delete_team_then_get_is_404(client):
    created = create(client)
    client.delete(f"{TEAMS}/{created['id']}")
    assert_problem(client.get(f"{TEAMS}/{created['id']}"), 404, f"{TEAMS}/{created['id']}")


def test_delete_team_twice_second_is_404(client):
    created = create(client)
    assert client.delete(f"{TEAMS}/{created['id']}").status_code == 204
    assert_problem(client.delete(f"{TEAMS}/{created['id']}"), 404, f"{TEAMS}/{created['id']}")


def test_delete_team_unknown_id_is_404(client):
    missing = str(uuid.uuid4())
    assert_problem(client.delete(f"{TEAMS}/{missing}"), 404, f"{TEAMS}/{missing}")


def test_delete_team_non_uuid_is_422(client):
    assert_422_loc(client.delete(f"{TEAMS}/nope"), ["path", "team_id"], f"{TEAMS}/nope")


def test_delete_team_removes_it_from_list_only(client):
    a = create(client, "A")
    b = create(client, "B")
    client.delete(f"{TEAMS}/{a['id']}")
    assert client.get(TEAMS).json()["items"] == [b]


def test_deleted_team_cannot_be_patched(client):
    created = create(client)
    client.delete(f"{TEAMS}/{created['id']}")
    resp = client.patch(f"{TEAMS}/{created['id']}", json={"name": "Ghost"})
    assert_problem(resp, 404, f"{TEAMS}/{created['id']}")


# ---------------------------------------------------------------- error contract (all 4xx)


def test_routing_404_is_problem_json(client):
    body = assert_problem(client.get("/api/v1/does-not-exist"), 404, "/api/v1/does-not-exist")
    assert body["title"] == "Not Found"


def test_routing_404_for_unknown_root_path(client):
    assert_problem(client.get("/nope"), 404, "/nope")


def test_routing_404_for_unknown_nested_team_path(client):
    assert_problem(client.get(f"{TEAMS}/{uuid.uuid4()}/bogus"), 404)


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_collection_unsupported_methods_are_405_problem_json(client, method):
    resp = client.request(method, TEAMS)
    body = assert_problem(resp, 405, TEAMS)
    assert body["title"] == "Method Not Allowed"


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_item_unsupported_methods_are_405_problem_json(client, method):
    created = create(client)
    resp = client.request(method, f"{TEAMS}/{created['id']}", json={"name": "x"})
    body = assert_problem(resp, 405, f"{TEAMS}/{created['id']}")
    assert body["title"] == "Method Not Allowed"


def test_405_keeps_allow_header(client):
    resp = client.put(TEAMS)
    assert resp.status_code == 405
    allow = {m.strip() for m in resp.headers.get("allow", "").split(",") if m.strip()}
    assert allow and allow <= {"GET", "POST", "HEAD", "OPTIONS"}, resp.headers


def test_health_wrong_method_is_405_problem_json(client):
    assert_problem(client.post("/health"), 405, "/health")


def test_422_errors_entries_have_loc_and_msg(client):
    body = assert_problem(client.post(TEAMS, json={"name": ""}), 422, TEAMS)
    assert isinstance(body["errors"], list) and body["errors"]
    for err in body["errors"]:
        assert isinstance(err["loc"], list)
        assert isinstance(err["msg"], str) and err["msg"]


def test_404_body_has_no_errors_key(client):
    body = assert_problem(client.get(f"{TEAMS}/{uuid.uuid4()}"), 404)
    assert "errors" not in body


def test_error_responses_never_use_plain_json_content_type(client):
    missing = uuid.uuid4()
    responses = [
        client.get(f"{TEAMS}/{missing}"),
        client.get(f"{TEAMS}/bad"),
        client.post(TEAMS, json={}),
        client.get("/nope"),
        client.put(TEAMS),
        client.get(TEAMS, params={"limit": 0}),
    ]
    for resp in responses:
        assert 400 <= resp.status_code < 500
        assert resp.headers["content-type"].startswith(PROBLEM), (
            resp.status_code,
            resp.headers["content-type"],
        )
