"""M6 acceptance tests: trash and restore for deleted notes (migration 0003_note_trash)."""

import os
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
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
    "deleted_at",
}


def tiny_sleep():
    time.sleep(0.03)


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


def db_path(url):
    return url.removeprefix("sqlite:///")


def sql(url, query, args=()):
    con = sqlite3.connect(db_path(url))
    try:
        rows = con.execute(query, args).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def trash(client, team_id, **params):
    resp = client.get(f"{TEAMS}/{team_id}/trash", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def trash_ids(client, team_id, **params):
    return [n["id"] for n in trash(client, team_id, **params)["items"]]


def list_ids(client, *team_ids, **params):
    query = [("team_id", t) for t in team_ids] + list(params.items())
    resp = client.get(NOTES, params=query)
    assert resp.status_code == 200, resp.text
    return [n["id"] for n in resp.json()["items"]]


def delete_note(client, note_id):
    resp = client.delete(f"{NOTES}/{note_id}")
    assert resp.status_code == 204, resp.text
    return resp


def restore(client, note_id):
    return client.post(f"{NOTES}/{note_id}/restore")


def upgrade(url, revision):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        command.upgrade(cfg, revision)
    finally:
        os.chdir(previous)


# ------------------------------------------------------------------ migration 0003


def test_migration_0003_file_exists():
    # criterion: migration 0003_note_trash
    assert list((REPO_ROOT / "migrations" / "versions").glob("0003*.py"))


def test_notes_table_has_nullable_deleted_at_column(migrated_db_url):
    # criterion: notes.deleted_at nullable timestamp
    cols = {r[1]: r for r in sql(migrated_db_url, "PRAGMA table_info(notes)")}
    assert "deleted_at" in cols, list(cols)
    assert cols["deleted_at"][3] == 0, "deleted_at must be nullable"


def test_notes_table_has_team_deleted_at_index(migrated_db_url):
    # criterion: index (team_id, deleted_at)
    found = []
    for row in sql(migrated_db_url, "PRAGMA index_list(notes)"):
        found.append([r[2] for r in sql(migrated_db_url, f'PRAGMA index_info("{row[1]}")')])
    assert ["team_id", "deleted_at"] in found, found


def test_migration_keeps_existing_notes_active(db_url):
    # criterion: the migration leaves existing notes active (deleted_at NULL)
    upgrade(db_url, "0002")
    t = str(uuid.uuid4())
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    stamp = "2026-01-01 10:00:00.000000"
    sql(
        db_url,
        "INSERT INTO teams (id, name, created_at, updated_at) VALUES (?,?,?,?)",
        (t, "Legacy", stamp, stamp),
    )
    for nid, title in ((n1, "old one"), (n2, "old two")):
        sql(
            db_url,
            "INSERT INTO notes (id, team_id, title, body, author_name, version, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (nid, t, title, "legacy body", None, 1, stamp, stamp),
        )
    assert "deleted_at" not in {r[1] for r in sql(db_url, "PRAGMA table_info(notes)")}
    upgrade(db_url, "head")
    rows = sql(db_url, "SELECT id, deleted_at FROM notes ORDER BY id")
    assert sorted(r[0] for r in rows) == sorted([n1, n2])
    assert all(r[1] is None for r in rows), rows
    with TestClient(create_app(database_url=db_url)) as c:
        got = c.get(f"{NOTES}/{n1}")
        assert got.status_code == 200, got.text
        assert got.json()["deleted_at"] is None
        assert set(list_ids(c, t)) == {n1, n2}
        assert trash_ids(c, t) == []


# ------------------------------------------------------------------ DELETE /notes/{id}


def test_delete_note_returns_204_with_empty_body(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    resp = client.delete(f"{NOTES}/{note['id']}")
    assert resp.status_code == 204, resp.text
    assert resp.content == b""
    assert trash_ids(client, team["id"]) == [note["id"]]  # moved to the trash, not removed


def test_deleted_note_get_is_404_problem(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    assert_problem(client.get(f"{NOTES}/{note['id']}"), 404, instance=f"{NOTES}/{note['id']}")
    # and it really is in the trash (soft delete), not just gone
    assert trash_ids(client, team["id"]) == [note["id"]]


def test_deleted_note_patch_with_correct_if_match_is_404(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="keep")
    delete_note(client, note["id"])
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "x"}, headers={"If-Match": '"1"'})
    assert_problem(resp, 404)
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "x"}, headers={"If-Match": "*"})
    assert_problem(resp, 404)
    # the trashed note was not modified
    assert trash(client, team["id"])["items"][0]["title"] == "keep"


def test_deleted_note_delete_again_is_404_and_stays_in_trash(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    before = trash(client, team["id"])["items"][0]["deleted_at"]
    tiny_sleep()
    assert_problem(client.delete(f"{NOTES}/{note['id']}"), 404, instance=f"{NOTES}/{note['id']}")
    after = trash(client, team["id"])["items"]
    assert [n["id"] for n in after] == [note["id"]]
    assert after[0]["deleted_at"] == before, "a failed second delete must not touch deleted_at"


def test_deleted_note_absent_from_list_by_team_and_global(client, team_factory, note_factory):
    team = team_factory(client)
    other = team_factory(client)
    gone = note_factory(client, team["id"], title="gone")
    stay = note_factory(client, team["id"], title="stay")
    other_note = note_factory(client, other["id"], title="other")
    delete_note(client, gone["id"])
    assert trash_ids(client, team["id"]) == [gone["id"]]
    assert list_ids(client, team["id"]) == [stay["id"]]
    assert gone["id"] not in list_ids(client)
    assert set(list_ids(client, team["id"], other["id"])) == {stay["id"], other_note["id"]}
    assert set(list_ids(client)) >= {stay["id"], other_note["id"]}


def test_delete_leaves_other_notes_untouched(client, team_factory, note_factory):
    team = team_factory(client)
    gone = note_factory(client, team["id"], title="gone")
    keep = note_factory(client, team["id"], title="keep", body="intact", author_name="Zed")
    delete_note(client, gone["id"])
    got = client.get(f"{NOTES}/{keep['id']}")
    assert got.status_code == 200, got.text
    assert got.json() == {**keep, "deleted_at": None}
    assert (
        client.patch(
            f"{NOTES}/{keep['id']}", json={"body": "still editable"}, headers={"If-Match": '"1"'}
        ).status_code
        == 200
    )
    assert trash_ids(client, team["id"]) == [gone["id"]]


def test_delete_does_not_require_if_match_and_ignores_it(client, team_factory, note_factory):
    team = team_factory(client)
    a = note_factory(client, team["id"])
    b = note_factory(client, team["id"])
    assert client.delete(f"{NOTES}/{a['id']}").status_code == 204
    assert client.delete(f"{NOTES}/{b['id']}", headers={"If-Match": '"99"'}).status_code == 204
    assert set(trash_ids(client, team["id"])) == {a["id"], b["id"]}


def test_delete_does_not_bump_version_or_updated_at(client, team_factory, note_factory):
    # decision: soft delete leaves version and updated_at as they were
    team = team_factory(client)
    note = note_factory(client, team["id"])
    patched = client.patch(
        f"{NOTES}/{note['id']}", json={"title": "v2"}, headers={"If-Match": '"1"'}
    ).json()
    assert patched["version"] == 2
    tiny_sleep()
    delete_note(client, note["id"])
    item = trash(client, team["id"])["items"][0]
    assert item["version"] == 2
    assert item["updated_at"] == patched["updated_at"]


# ------------------------------------------------------------------ GET /teams/{id}/trash


def test_trash_lists_deleted_note_with_deleted_at(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="T", body="B", author_name="Ann")
    delete_note(client, note["id"])
    data = trash(client, team["id"])
    assert set(data) == {"items", "next_cursor"}
    assert data["next_cursor"] is None
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert set(item) >= NOTE_KEYS, item
    assert item["id"] == note["id"]
    assert item["team_id"] == team["id"]
    assert (item["title"], item["body"], item["author_name"]) == ("T", "B", "Ann")
    assert item["deleted_at"] is not None
    deleted = parse_ts(item["deleted_at"])
    assert deleted >= parse_ts(item["created_at"])
    assert abs(deleted - datetime.now(UTC).replace(tzinfo=None)) < timedelta(minutes=5)


def test_trash_response_is_json_200(client, team_factory):
    team = team_factory(client)
    resp = client.get(f"{TEAMS}/{team['id']}/trash")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")


def test_trash_empty_returns_empty_items_and_null_cursor(client, team_factory, note_factory):
    team = team_factory(client)
    note_factory(client, team["id"])  # active only
    assert trash(client, team["id"]) == {"items": [], "next_cursor": None}


def test_trash_most_recently_deleted_first(client, team_factory, note_factory):
    team = team_factory(client)
    notes = [note_factory(client, team["id"], title=f"n{i}") for i in range(4)]
    order = [notes[2], notes[0], notes[3], notes[1]]
    for n in order:
        delete_note(client, n["id"])
        tiny_sleep()
    assert trash_ids(client, team["id"]) == [n["id"] for n in reversed(order)]
    stamps = [parse_ts(n["deleted_at"]) for n in trash(client, team["id"])["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_trash_order_is_by_deleted_at_not_updated_at(client, team_factory, note_factory):
    team = team_factory(client)
    first = note_factory(client, team["id"], title="first")
    second = note_factory(client, team["id"], title="second")
    tiny_sleep()
    # make `first` the most recently *updated* note, but delete it first
    client.patch(f"{NOTES}/{first['id']}", json={"body": "edit"}, headers={"If-Match": '"1"'})
    delete_note(client, first["id"])
    tiny_sleep()
    delete_note(client, second["id"])
    assert trash_ids(client, team["id"]) == [second["id"], first["id"]]


def test_trash_tie_break_is_id_descending(migrated_db_url, team_factory, note_factory):
    with TestClient(create_app(database_url=migrated_db_url)) as c:
        team = team_factory(c)
        ids = [note_factory(c, team["id"])["id"] for _ in range(4)]
        for nid in ids:
            delete_note(c, nid)
        sql(
            migrated_db_url,
            "UPDATE notes SET deleted_at = ? WHERE team_id = ?",
            ("2026-02-02 12:00:00.000000", team["id"]),
        )
        assert trash_ids(c, team["id"]) == sorted(ids, reverse=True)


def test_trash_excludes_active_notes(client, team_factory, note_factory):
    team = team_factory(client)
    active = note_factory(client, team["id"], title="active")
    trashed = note_factory(client, team["id"], title="trashed")
    delete_note(client, trashed["id"])
    assert trash_ids(client, team["id"]) == [trashed["id"]]
    assert active["id"] not in trash_ids(client, team["id"])


def test_trash_is_per_team(client, team_factory, note_factory):
    a = team_factory(client)
    b = team_factory(client)
    na = note_factory(client, a["id"])
    nb = note_factory(client, b["id"])
    delete_note(client, na["id"])
    delete_note(client, nb["id"])
    assert trash_ids(client, a["id"]) == [na["id"]]
    assert trash_ids(client, b["id"]) == [nb["id"]]


def test_trash_unknown_team_is_404_problem(client, team_factory):
    assert trash(client, team_factory(client)["id"]) == {"items": [], "next_cursor": None}
    team_id = str(uuid.uuid4())
    assert_problem(client.get(f"{TEAMS}/{team_id}/trash"), 404, instance=f"{TEAMS}/{team_id}/trash")


def test_trash_non_uuid_team_is_422(client):
    body = assert_problem(client.get(f"{TEAMS}/nope/trash"), 422)
    assert any(e["loc"] == ["path", "team_id"] for e in body["errors"]), body["errors"]


def test_trash_of_deleted_team_is_404(client, team_factory):
    team = team_factory(client)
    assert trash(client, team["id"])["items"] == []
    assert client.delete(f"{TEAMS}/{team['id']}").status_code == 204
    assert_problem(client.get(f"{TEAMS}/{team['id']}/trash"), 404)


@pytest.mark.parametrize("limit", [0, 101, -1, "abc"])
def test_trash_limit_out_of_bounds_is_422(client, team_factory, limit):
    team = team_factory(client)
    body = assert_problem(client.get(f"{TEAMS}/{team['id']}/trash", params={"limit": limit}), 422)
    assert any(e["loc"] == ["query", "limit"] for e in body["errors"]), body["errors"]


def test_trash_limit_one_returns_newest_only(client, team_factory, note_factory):
    team = team_factory(client)
    old = note_factory(client, team["id"])
    new = note_factory(client, team["id"])
    delete_note(client, old["id"])
    tiny_sleep()
    delete_note(client, new["id"])
    data = trash(client, team["id"], limit=1)
    assert [n["id"] for n in data["items"]] == [new["id"]]
    assert data["next_cursor"] is None


def test_trash_default_limit_20_and_max_100(client, team_factory, note_factory):
    team = team_factory(client)
    ids = [note_factory(client, team["id"])["id"] for _ in range(21)]
    for nid in ids:
        delete_note(client, nid)
    assert len(trash_ids(client, team["id"])) == 20
    assert len(trash_ids(client, team["id"], limit=100)) == 21
    assert len(trash_ids(client, team["id"], limit=5)) == 5
    assert trash(client, team["id"])["next_cursor"] is None


# ------------------------------------------------------------------ POST /notes/{id}/restore


def test_restore_returns_200_noteout_with_deleted_at_null(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Back", body="again", author_name="Ann")
    delete_note(client, note["id"])
    resp = restore(client, note["id"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) >= NOTE_KEYS, data
    assert data["id"] == note["id"]
    assert data["deleted_at"] is None
    assert data["tags"] == []


def test_restore_bumps_version_by_exactly_one_and_sets_etag(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    resp = restore(client, note["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert resp.headers["etag"] == '"2"'


def test_restore_version_is_pre_delete_version_plus_one(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    for i, v in enumerate(("1", "2", "3")):
        resp = client.patch(
            f"{NOTES}/{note['id']}", json={"body": f"rev{i}"}, headers={"If-Match": f'"{v}"'}
        )
        assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 4
    delete_note(client, note["id"])
    resp = restore(client, note["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 5
    assert resp.headers["etag"] == '"5"'
    got = client.get(f"{NOTES}/{note['id']}")
    assert got.headers["etag"] == '"5"'
    assert got.json()["version"] == 5


def test_restore_updated_at_strictly_later_than_before(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    before = parse_ts(note["updated_at"])
    delete_note(client, note["id"])
    tiny_sleep()
    data = restore(client, note["id"]).json()
    assert parse_ts(data["updated_at"]) > before
    assert parse_ts(data["created_at"]) == parse_ts(note["created_at"])


def test_restore_keeps_content_and_created_at(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Keep me", body="line1\nline2", author_name="Bo")
    delete_note(client, note["id"])
    data = restore(client, note["id"]).json()
    for key in ("id", "team_id", "title", "body", "author_name", "created_at"):
        assert data[key] == note[key], key
    assert data["title"] == "Keep me"
    assert data["body"] == "line1\nline2"
    assert data["author_name"] == "Bo"


def test_restored_note_reappears_in_get_and_list(client, team_factory, note_factory):
    team = team_factory(client)
    other = note_factory(client, team["id"], title="other")
    note = note_factory(client, team["id"], title="restored", body="body!")
    delete_note(client, note["id"])
    assert note["id"] not in list_ids(client, team["id"])
    tiny_sleep()
    restore(client, note["id"])
    got = client.get(f"{NOTES}/{note['id']}")
    assert got.status_code == 200, got.text
    assert (got.json()["title"], got.json()["body"]) == ("restored", "body!")
    assert got.json()["deleted_at"] is None
    assert list_ids(client, team["id"]) == [note["id"], other["id"]]  # restore bumped updated_at
    assert note["id"] in list_ids(client)


def test_restored_note_leaves_the_trash(client, team_factory, note_factory):
    team = team_factory(client)
    a = note_factory(client, team["id"])
    b = note_factory(client, team["id"])
    delete_note(client, a["id"])
    delete_note(client, b["id"])
    restore(client, a["id"])
    assert trash_ids(client, team["id"]) == [b["id"]]
    restore(client, b["id"])
    assert trash(client, team["id"]) == {"items": [], "next_cursor": None}


def test_restore_needs_no_body_or_if_match(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    resp = client.post(f"{NOTES}/{note['id']}/restore")
    assert resp.status_code == 200, resp.text


def test_restore_active_note_is_409_problem(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    resp = restore(client, note["id"])
    assert_problem(resp, 409, instance=f"{NOTES}/{note['id']}/restore")
    # the active note is unchanged
    got = client.get(f"{NOTES}/{note['id']}")
    assert got.status_code == 200
    assert got.json()["version"] == 1


def test_restore_twice_second_is_409_and_version_bumped_once(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    assert restore(client, note["id"]).status_code == 200
    assert_problem(restore(client, note["id"]), 409)
    assert client.get(f"{NOTES}/{note['id']}").json()["version"] == 2


def test_restore_unknown_id_is_404(client, team_factory, note_factory):
    real = note_factory(client, team_factory(client)["id"])
    delete_note(client, real["id"])
    assert restore(client, real["id"]).status_code == 200  # the route exists and works
    missing = str(uuid.uuid4())
    assert_problem(restore(client, missing), 404, instance=f"{NOTES}/{missing}/restore")


def test_restore_non_uuid_is_422(client):
    body = assert_problem(restore(client, "nope"), 422)
    assert any(e["loc"] == ["path", "note_id"] for e in body["errors"]), body["errors"]


def test_restore_rejects_get_method(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    assert_problem(client.get(f"{NOTES}/{note['id']}/restore"), 405)


def test_old_etag_is_stale_after_restore_new_etag_works(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="orig")
    old_etag = client.get(f"{NOTES}/{note['id']}").headers["etag"]
    assert old_etag == '"1"'
    delete_note(client, note["id"])
    new_etag = restore(client, note["id"]).headers["etag"]
    assert new_etag == '"2"'
    stale = client.patch(
        f"{NOTES}/{note['id']}", json={"title": "stale"}, headers={"If-Match": old_etag}
    )
    body = assert_problem(stale, 412)
    assert "2" in body["detail"]
    assert client.get(f"{NOTES}/{note['id']}").json()["title"] == "orig"
    ok = client.patch(
        f"{NOTES}/{note['id']}", json={"title": "fresh"}, headers={"If-Match": new_etag}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == 3
    assert ok.json()["title"] == "fresh"
    assert ok.json()["deleted_at"] is None


def test_restored_note_can_be_deleted_and_restored_again(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    delete_note(client, note["id"])
    assert restore(client, note["id"]).json()["version"] == 2
    delete_note(client, note["id"])
    assert trash_ids(client, team["id"]) == [note["id"]]
    assert restore(client, note["id"]).json()["version"] == 3
    assert client.get(f"{NOTES}/{note['id']}").status_code == 200


# ------------------------------------------------------------------ team deletion


def test_deleting_team_removes_trashed_notes_permanently(
    migrated_db_url, team_factory, note_factory
):
    with TestClient(create_app(database_url=migrated_db_url)) as c:
        team = team_factory(c)
        trashed = note_factory(c, team["id"])
        active = note_factory(c, team["id"])
        delete_note(c, trashed["id"])
        assert trash_ids(c, team["id"]) == [trashed["id"]]
        assert c.delete(f"{TEAMS}/{team['id']}").status_code == 204
        assert_problem(restore(c, trashed["id"]), 404)
        assert_problem(c.get(f"{NOTES}/{active['id']}"), 404)
        assert_problem(c.get(f"{TEAMS}/{team['id']}/trash"), 404)
    count = sql(migrated_db_url, "SELECT COUNT(*) FROM notes WHERE team_id = ?", (team["id"],))
    assert count == [(0,)]
    assert sql(migrated_db_url, "SELECT COUNT(*) FROM notes") == [(0,)]


def test_deleting_team_leaves_other_teams_trash_intact(client, team_factory, note_factory):
    doomed = team_factory(client)
    safe = team_factory(client)
    n1 = note_factory(client, doomed["id"])
    n2 = note_factory(client, safe["id"])
    delete_note(client, n1["id"])
    delete_note(client, n2["id"])
    assert client.delete(f"{TEAMS}/{doomed['id']}").status_code == 204
    assert trash_ids(client, safe["id"]) == [n2["id"]]
    assert restore(client, n2["id"]).status_code == 200


# ------------------------------------------------------------------ NoteOut shape


def test_noteout_deleted_at_is_null_on_create(client, team_factory):
    team = team_factory(client)
    resp = client.post(f"{TEAMS}/{team['id']}/notes", json={"title": "x"})
    assert resp.status_code == 201, resp.text
    assert "deleted_at" in resp.json()
    assert resp.json()["deleted_at"] is None


def test_noteout_deleted_at_is_null_on_get_patch_and_list(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    got = client.get(f"{NOTES}/{note['id']}").json()
    assert "deleted_at" in got and got["deleted_at"] is None
    patched = client.patch(
        f"{NOTES}/{note['id']}", json={"title": "p"}, headers={"If-Match": '"1"'}
    ).json()
    assert "deleted_at" in patched and patched["deleted_at"] is None
    items = client.get(NOTES, params={"team_id": team["id"]}).json()["items"]
    assert items and all("deleted_at" in n and n["deleted_at"] is None for n in items)
    assert set(items[0]) >= NOTE_KEYS


def test_noteout_deleted_at_is_iso8601_in_trash(client, team_factory, note_factory):
    team = team_factory(client)
    delete_note(client, note_factory(client, team["id"])["id"])
    value = trash(client, team["id"])["items"][0]["deleted_at"]
    assert isinstance(value, str)
    parse_ts(value)


# ------------------------------------------------------------------ persistence


def test_soft_deleted_row_persists_in_database(migrated_db_url, team_factory, note_factory):
    with TestClient(create_app(database_url=migrated_db_url)) as c1:
        team = team_factory(c1)
        note = note_factory(c1, team["id"], title="Persist", body="soft")
        active = note_factory(c1, team["id"], title="Active")
        delete_note(c1, note["id"])
    rows = dict(sql(migrated_db_url, "SELECT id, deleted_at FROM notes"))
    assert set(rows) == {note["id"], active["id"]}, "soft delete must keep the row"
    assert rows[note["id"]] is not None
    assert rows[active["id"]] is None
    with TestClient(create_app(database_url=migrated_db_url)) as c2:
        assert_problem(c2.get(f"{NOTES}/{note['id']}"), 404)
        assert trash_ids(c2, team["id"]) == [note["id"]]
        resp = restore(c2, note["id"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "Persist"
    with TestClient(create_app(database_url=migrated_db_url)) as c3:
        assert c3.get(f"{NOTES}/{note['id']}").status_code == 200
        assert trash_ids(c3, team["id"]) == []
    assert sql(migrated_db_url, "SELECT deleted_at FROM notes WHERE id = ?", (note["id"],)) == [
        (None,)
    ]
