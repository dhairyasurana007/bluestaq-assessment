"""M4 acceptance tests: note CRUD within team spaces (migration 0002_notes)."""

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
NOTES = "/api/v1/notes"
PROBLEM = "application/problem+json"
NOTE_KEYS = {
    "id",
    "team_id",
    "title",
    "body",
    "tags",
    "author_name",
    "version",
    "created_at",
    "updated_at",
}


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
    phrases = {HTTPStatus(status).phrase}
    if status == 422:
        phrases |= {"Unprocessable Entity", "Unprocessable Content"}
    assert body["title"] in phrases, body["title"]
    if instance is not None:
        assert body["instance"] == instance
    return body


def assert_422_loc(resp, loc):
    body = assert_problem(resp, 422)
    assert isinstance(body.get("errors"), list) and body["errors"], body
    for err in body["errors"]:
        assert "loc" in err and "msg" in err, err
    assert [e for e in body["errors"] if e["loc"] == loc], body["errors"]
    return body


def post_note(client, team_id, **payload):
    return client.post(f"{TEAMS}/{team_id}/notes", json=payload)


def list_notes(client, *team_ids, **params):
    query = [("team_id", t) for t in team_ids] + list(params.items())
    resp = client.get(NOTES, params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()


def db_path(url):
    return url.removeprefix("sqlite:///")


# ------------------------------------------------------------------ migration / table


def test_migration_0002_file_exists():
    # criterion: migration 0002_notes
    assert list((REPO_ROOT / "migrations" / "versions").glob("0002*.py"))


def test_notes_table_has_spec_columns_after_migrating_to_head(migrated_db_url):
    # criterion: notes table with the section 4 columns
    con = sqlite3.connect(db_path(migrated_db_url))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "notes" in tables, tables
        assert "teams" in tables
        cols = {r[1] for r in con.execute("PRAGMA table_info(notes)")}
        expected = {
            "id",
            "team_id",
            "title",
            "body",
            "author_name",
            "version",
            "created_at",
            "updated_at",
        }
        assert cols >= expected, cols
    finally:
        con.close()


def test_notes_table_has_team_updated_id_index(migrated_db_url):
    # criterion: index (team_id, updated_at, id)
    con = sqlite3.connect(db_path(migrated_db_url))
    try:
        found = []
        for row in con.execute("PRAGMA index_list(notes)"):
            name = row[1]
            cols = [r[2] for r in con.execute(f'PRAGMA index_info("{name}")')]
            found.append(cols)
        assert ["team_id", "updated_at", "id"] in found, found
    finally:
        con.close()


def test_notes_team_fk_cascades_on_delete(migrated_db_url):
    # criterion: team_id FK teams ON DELETE CASCADE
    con = sqlite3.connect(db_path(migrated_db_url))
    try:
        fks = [r for r in con.execute("PRAGMA foreign_key_list(notes)")]
        team_fks = [r for r in fks if r[2] == "teams" and r[3] == "team_id"]
        assert team_fks, fks
        assert team_fks[0][6].upper() == "CASCADE", team_fks
    finally:
        con.close()


def test_notes_persist_across_app_restarts(migrated_db_url, team_factory, note_factory):
    # criterion: data persists in the migrated database
    with TestClient(create_app(database_url=migrated_db_url)) as c1:
        team = team_factory(c1)
        note = note_factory(c1, team["id"], title="Persist me", body="hello", author_name="Ann")
    with TestClient(create_app(database_url=migrated_db_url)) as c2:
        resp = c2.get(f"{NOTES}/{note['id']}")
        assert resp.status_code == 200, resp.text
        got = resp.json()
        assert got["title"] == "Persist me"
        assert got["body"] == "hello"
        assert got["author_name"] == "Ann"
    con = sqlite3.connect(db_path(migrated_db_url))
    try:
        rows = con.execute("SELECT id, team_id, title FROM notes").fetchall()
    finally:
        con.close()
    assert rows == [(note["id"], team["id"], "Persist me")]


# ------------------------------------------------------------------ create


def test_create_note_returns_201_noteout_version_1(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="First", body="Hello", author_name="Ann")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert set(data) >= NOTE_KEYS, data
    uuid.UUID(data["id"])
    assert data["team_id"] == team["id"]
    assert data["title"] == "First"
    assert data["body"] == "Hello"
    assert data["author_name"] == "Ann"
    assert data["tags"] == []
    assert data["version"] == 1
    parse_ts(data["created_at"])
    parse_ts(data["updated_at"])


def test_create_note_location_and_etag_headers(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="Headers")
    assert resp.status_code == 201, resp.text
    assert resp.headers["location"] == f"/api/v1/notes/{resp.json()['id']}"
    assert resp.headers["etag"] == '"1"'


def test_create_note_author_name_defaults_to_null(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="Anon")
    assert resp.status_code == 201, resp.text
    assert resp.json()["author_name"] is None


def test_create_note_body_defaults_to_empty_string(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="No body")
    assert resp.status_code == 201, resp.text
    assert resp.json()["body"] == ""


def test_create_note_in_nonexistent_team_is_404_problem(client, team_factory):
    real = team_factory(client)
    assert post_note(client, real["id"], title="Works").status_code == 201
    missing = str(uuid.uuid4())
    resp = post_note(client, missing, title="Orphan")
    assert_problem(resp, 404, instance=f"{TEAMS}/{missing}/notes")


def test_create_note_with_non_uuid_team_id_is_422(client):
    resp = client.post(f"{TEAMS}/not-a-uuid/notes", json={"title": "x"})
    assert_problem(resp, 422)


def test_created_note_is_readable_via_get(client, team_factory):
    team = team_factory(client)
    posted = post_note(client, team["id"], title="Round trip", body="b")
    assert posted.status_code == 201, posted.text
    created = posted.json()
    got = client.get(f"{NOTES}/{created['id']}")
    assert got.status_code == 200, got.text
    assert got.json() == created


# ------------------------------------------------------------------ create validation


@pytest.mark.parametrize("title", ["", "   ", "\t\n "])
def test_create_empty_or_whitespace_title_is_422(client, team_factory, title):
    team = team_factory(client)
    assert_422_loc(post_note(client, team["id"], title=title), ["body", "title"])


def test_create_missing_title_is_422(client, team_factory):
    team = team_factory(client)
    assert_422_loc(post_note(client, team["id"], body="no title"), ["body", "title"])


def test_create_title_200_chars_ok_and_201_rejected(client, team_factory):
    team = team_factory(client)
    ok = post_note(client, team["id"], title="t" * 200)
    assert ok.status_code == 201, ok.text
    assert ok.json()["title"] == "t" * 200
    bad = post_note(client, team["id"], title="t" * 201)
    assert_422_loc(bad, ["body", "title"])


def test_create_title_is_trimmed(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="   Hello world \t")
    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "Hello world"


def test_create_title_length_is_measured_after_trimming(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="  " + "t" * 200 + "  ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "t" * 200


def test_create_body_100000_chars_ok_and_100001_rejected(client, team_factory):
    team = team_factory(client)
    ok = post_note(client, team["id"], title="Big", body="b" * 100_000)
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["body"]) == 100_000
    bad = post_note(client, team["id"], title="Too big", body="b" * 100_001)
    assert_422_loc(bad, ["body", "body"])


def test_create_author_name_100_chars_ok_and_101_rejected(client, team_factory):
    team = team_factory(client)
    ok = post_note(client, team["id"], title="A", author_name="a" * 100)
    assert ok.status_code == 201, ok.text
    assert ok.json()["author_name"] == "a" * 100
    bad = post_note(client, team["id"], title="B", author_name="a" * 101)
    assert_422_loc(bad, ["body", "author_name"])


def test_create_author_name_is_trimmed(client, team_factory):
    team = team_factory(client)
    resp = post_note(client, team["id"], title="Trim", author_name="  Ann Lee  ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["author_name"] == "Ann Lee"


@pytest.mark.parametrize("author", ["", "    "])
def test_create_empty_author_name_is_422(client, team_factory, author):
    team = team_factory(client)
    assert_422_loc(
        post_note(client, team["id"], title="X", author_name=author), ["body", "author_name"]
    )


def test_create_unknown_field_is_422(client, team_factory):
    team = team_factory(client)
    assert_422_loc(post_note(client, team["id"], title="X", bogus=1), ["body", "bogus"])


def test_create_rejected_notes_are_not_stored(client, team_factory):
    team = team_factory(client)
    assert post_note(client, team["id"], title="").status_code == 422
    assert post_note(client, team["id"], title="ok", bogus=1).status_code == 422
    assert list_notes(client, team["id"])["items"] == []


# ------------------------------------------------------------------ GET /notes/{id}


def test_get_note_200_with_etag(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Read me")
    resp = client.get(f"{NOTES}/{note['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == '"1"'
    data = resp.json()
    assert set(data) >= NOTE_KEYS
    assert data["id"] == note["id"]
    assert data["title"] == "Read me"


def test_get_unknown_note_is_404_problem(client, team_factory, note_factory):
    real = note_factory(client, team_factory(client)["id"])
    assert client.get(f"{NOTES}/{real['id']}").status_code == 200
    missing = str(uuid.uuid4())
    resp = client.get(f"{NOTES}/{missing}")
    assert_problem(resp, 404, instance=f"{NOTES}/{missing}")


def test_get_note_with_non_uuid_id_is_422(client):
    assert_problem(client.get(f"{NOTES}/not-a-uuid"), 422)


# ------------------------------------------------------------------ GET /notes


def test_list_notes_shape_and_next_cursor_null(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Only")
    data = list_notes(client, team["id"])
    assert set(data) >= {"items", "next_cursor"}
    assert data["next_cursor"] is None
    assert [n["id"] for n in data["items"]] == [note["id"]]
    assert set(data["items"][0]) >= NOTE_KEYS


def test_list_notes_filters_by_team(client, team_factory, note_factory):
    a = team_factory(client)
    b = team_factory(client)
    na = note_factory(client, a["id"], title="in a")
    nb = note_factory(client, b["id"], title="in b")
    assert [n["id"] for n in list_notes(client, a["id"])["items"]] == [na["id"]]
    assert [n["id"] for n in list_notes(client, b["id"])["items"]] == [nb["id"]]


def test_list_notes_newest_updated_first(client, team_factory, note_factory):
    team = team_factory(client)
    ids = []
    for i in range(3):
        ids.append(note_factory(client, team["id"], title=f"n{i}")["id"])
        tiny_sleep()
    assert [n["id"] for n in list_notes(client, team["id"])["items"]] == ids[::-1]


def test_list_notes_order_follows_updated_at_after_patch(client, team_factory, note_factory):
    team = team_factory(client)
    first = note_factory(client, team["id"], title="first")
    tiny_sleep()
    second = note_factory(client, team["id"], title="second")
    tiny_sleep()
    assert client.patch(f"{NOTES}/{first['id']}", json={"title": "first edited"}).status_code == 200
    ids = [n["id"] for n in list_notes(client, team["id"])["items"]]
    assert ids == [first["id"], second["id"]]


def test_list_notes_two_team_ids_return_both_teams(client, team_factory, note_factory):
    a = team_factory(client)
    b = team_factory(client)
    c = team_factory(client)
    na = note_factory(client, a["id"])
    tiny_sleep()
    nb = note_factory(client, b["id"])
    tiny_sleep()
    note_factory(client, c["id"])
    items = list_notes(client, a["id"], b["id"])["items"]
    assert [n["id"] for n in items] == [nb["id"], na["id"]]


def test_list_notes_unknown_team_id_matches_nothing(client, team_factory, note_factory):
    team = team_factory(client)
    note_factory(client, team["id"])
    assert list_notes(client, str(uuid.uuid4()))["items"] == []


def test_list_notes_without_team_filter_includes_all_teams(client, team_factory, note_factory):
    a = team_factory(client)
    b = team_factory(client)
    na = note_factory(client, a["id"])
    nb = note_factory(client, b["id"])
    ids = {n["id"] for n in list_notes(client)["items"]}
    assert {na["id"], nb["id"]} <= ids


def test_list_notes_limit_1_and_100_accepted(client, team_factory, note_factory):
    team = team_factory(client)
    ids = []
    for i in range(3):
        ids.append(note_factory(client, team["id"], title=f"n{i}")["id"])
        tiny_sleep()
    one = list_notes(client, team["id"], limit=1)
    assert [n["id"] for n in one["items"]] == [ids[-1]]
    assert one["next_cursor"] is None
    assert len(list_notes(client, team["id"], limit=100)["items"]) == 3


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc"])
def test_list_notes_invalid_limit_is_422(client, limit):
    assert_problem(client.get(NOTES, params={"limit": limit}), 422)


def test_list_notes_default_limit_is_20(client, team_factory, note_factory):
    team = team_factory(client)
    for i in range(22):
        note_factory(client, team["id"], title=f"n{i}")
    items = list_notes(client, team["id"])["items"]
    assert len(items) == 20


def test_list_notes_limit_100_returns_more_than_default(client, team_factory, note_factory):
    team = team_factory(client)
    for i in range(22):
        note_factory(client, team["id"], title=f"n{i}")
    assert len(list_notes(client, team["id"], limit=100)["items"]) == 22


# ------------------------------------------------------------------ PATCH


def test_patch_title_only_updates_only_title(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Old", body="keep body", author_name="Ann")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "New"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "New"
    assert data["body"] == "keep body"
    assert data["author_name"] == "Ann"
    assert data["team_id"] == team["id"]
    assert data["id"] == note["id"]


def test_patch_body_only_updates_only_body(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Keep title", body="old")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"body": "new"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Keep title"
    assert resp.json()["body"] == "new"


def test_patch_both_fields(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="t", body="b")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "T2", "body": "B2"})
    assert resp.status_code == 200, resp.text
    assert (resp.json()["title"], resp.json()["body"]) == ("T2", "B2")


def test_patch_body_to_empty_string_is_allowed(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="t", body="something")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"body": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json()["body"] == ""
    assert resp.json()["title"] == "t"


def test_patch_title_is_trimmed(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="t")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "  spaced  "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "spaced"


def test_patch_bumps_version_by_one_with_new_etag(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="v")
    assert note["version"] == 1
    for expected in (2, 3, 4):
        resp = client.patch(f"{NOTES}/{note['id']}", json={"title": f"v{expected}"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == expected
        assert resp.headers["etag"] == f'"{expected}"'
    got = client.get(f"{NOTES}/{note['id']}")
    assert got.json()["version"] == 4
    assert got.headers["etag"] == '"4"'


def test_patch_updates_updated_at_and_keeps_created_at(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="time")
    tiny_sleep()
    resp = client.patch(f"{NOTES}/{note['id']}", json={"body": "changed"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created_at"] == note["created_at"]
    assert parse_ts(data["updated_at"]) > parse_ts(note["updated_at"])


def test_patch_persists_changes(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="before", body="b0")
    client.patch(f"{NOTES}/{note['id']}", json={"title": "after"})
    got = client.get(f"{NOTES}/{note['id']}").json()
    assert got["title"] == "after"
    assert got["body"] == "b0"
    assert got["version"] == 2


def test_patch_empty_object_is_422_and_changes_nothing(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="same")
    resp = client.patch(f"{NOTES}/{note['id']}", json={})
    assert_problem(resp, 422)
    assert client.get(f"{NOTES}/{note['id']}").json()["version"] == 1


def test_patch_author_name_is_422_not_editable(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="same", author_name="Ann")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"author_name": "Bob"})
    assert_422_loc(resp, ["body", "author_name"])
    got = client.get(f"{NOTES}/{note['id']}").json()
    assert got["author_name"] == "Ann"
    assert got["version"] == 1


def test_patch_with_title_and_author_name_is_422_and_applies_nothing(
    client, team_factory, note_factory
):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="orig", author_name="Ann")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "new", "author_name": "Bob"})
    assert_422_loc(resp, ["body", "author_name"])
    got = client.get(f"{NOTES}/{note['id']}").json()
    assert got["title"] == "orig"
    assert got["version"] == 1


def test_patch_unknown_field_is_422(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    assert_422_loc(client.patch(f"{NOTES}/{note['id']}", json={"bogus": 1}), ["body", "bogus"])


@pytest.mark.parametrize("title", ["", "   "])
def test_patch_empty_title_is_422(client, team_factory, note_factory, title):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="keep")
    assert_422_loc(client.patch(f"{NOTES}/{note['id']}", json={"title": title}), ["body", "title"])
    assert client.get(f"{NOTES}/{note['id']}").json()["title"] == "keep"


def test_patch_title_201_chars_is_422(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "t" * 201})
    assert_422_loc(resp, ["body", "title"])


def test_patch_title_200_chars_ok(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "t" * 200})
    assert resp.status_code == 200, resp.text


def test_patch_body_100001_chars_is_422_and_100000_ok(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    assert_422_loc(
        client.patch(f"{NOTES}/{note['id']}", json={"body": "b" * 100_001}), ["body", "body"]
    )
    ok = client.patch(f"{NOTES}/{note['id']}", json={"body": "b" * 100_000})
    assert ok.status_code == 200, ok.text


def test_patch_unknown_note_is_404_problem(client, team_factory, note_factory):
    real = note_factory(client, team_factory(client)["id"])
    assert client.patch(f"{NOTES}/{real['id']}", json={"title": "ok"}).status_code == 200
    missing = str(uuid.uuid4())
    resp = client.patch(f"{NOTES}/{missing}", json={"title": "x"})
    assert_problem(resp, 404, instance=f"{NOTES}/{missing}")


def test_patch_non_uuid_id_is_422(client):
    assert_problem(client.patch(f"{NOTES}/nope", json={"title": "x"}), 422)


# ------------------------------------------------------------------ DELETE


def test_delete_note_204_then_get_404(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="bye")
    resp = client.delete(f"{NOTES}/{note['id']}")
    assert resp.status_code == 204, resp.text
    assert resp.content == b""
    assert_problem(client.get(f"{NOTES}/{note['id']}"), 404)


def test_delete_note_twice_is_404(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    assert client.delete(f"{NOTES}/{note['id']}").status_code == 204
    assert_problem(client.delete(f"{NOTES}/{note['id']}"), 404, instance=f"{NOTES}/{note['id']}")


def test_delete_unknown_note_is_404(client, team_factory, note_factory):
    real = note_factory(client, team_factory(client)["id"])
    assert client.delete(f"{NOTES}/{real['id']}").status_code == 204
    assert_problem(client.delete(f"{NOTES}/{uuid.uuid4()}"), 404)


def test_delete_non_uuid_id_is_422(client):
    assert_problem(client.delete(f"{NOTES}/nope"), 422)


def test_deleted_note_disappears_from_list_but_siblings_remain(client, team_factory, note_factory):
    team = team_factory(client)
    keep = note_factory(client, team["id"], title="keep")
    tiny_sleep()
    gone = note_factory(client, team["id"], title="gone")
    assert client.delete(f"{NOTES}/{gone['id']}").status_code == 204
    ids = [n["id"] for n in list_notes(client, team["id"])["items"]]
    assert ids == [keep["id"]]


def test_patch_deleted_note_is_404(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    client.delete(f"{NOTES}/{note['id']}")
    assert_problem(client.patch(f"{NOTES}/{note['id']}", json={"title": "x"}), 404)


# ------------------------------------------------------------------ team deletion cascade


def test_deleting_team_deletes_its_notes(client, team_factory, note_factory):
    team = team_factory(client)
    n1 = note_factory(client, team["id"], title="one")
    n2 = note_factory(client, team["id"], title="two")
    assert client.delete(f"{TEAMS}/{team['id']}").status_code == 204
    for n in (n1, n2):
        assert_problem(client.get(f"{NOTES}/{n['id']}"), 404)
    ids = {n["id"] for n in list_notes(client)["items"]}
    assert not ids & {n1["id"], n2["id"]}
    assert list_notes(client, team["id"])["items"] == []


def test_deleting_team_removes_note_rows_from_database(migrated_db_url, team_factory, note_factory):
    with TestClient(create_app(database_url=migrated_db_url)) as c:
        team = team_factory(c)
        note_factory(c, team["id"])
        note_factory(c, team["id"])
        assert c.delete(f"{TEAMS}/{team['id']}").status_code == 204
    con = sqlite3.connect(db_path(migrated_db_url))
    try:
        assert con.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    finally:
        con.close()


def test_deleting_team_leaves_other_teams_notes_intact(client, team_factory, note_factory):
    doomed = team_factory(client)
    safe = team_factory(client)
    note_factory(client, doomed["id"], title="doomed")
    survivor = note_factory(client, safe["id"], title="survivor", body="still here")
    assert client.delete(f"{TEAMS}/{doomed['id']}").status_code == 204
    got = client.get(f"{NOTES}/{survivor['id']}")
    assert got.status_code == 200, got.text
    assert got.json()["body"] == "still here"
    assert [n["id"] for n in list_notes(client, safe["id"])["items"]] == [survivor["id"]]


def test_note_cannot_be_created_in_deleted_team(client, team_factory):
    team = team_factory(client)
    assert post_note(client, team["id"], title="before").status_code == 201
    assert client.delete(f"{TEAMS}/{team['id']}").status_code == 204
    assert_problem(post_note(client, team["id"], title="late"), 404)
