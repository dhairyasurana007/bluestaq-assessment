"""M6 e2e: trash and restore (soft delete, GET /teams/{id}/trash, POST /notes/{id}/restore)."""

import uuid
from datetime import datetime

import pytest
from playwright.sync_api import APIRequestContext

from tests.e2e.helpers import make_team
from tests.e2e.test_m4 import NOTE_KEYS, _ts, assert_problem, make_note, patch_note


def trash_list(api: APIRequestContext, team_id: str, **params):
    return api.get(f"/api/v1/teams/{team_id}/trash", params=params or None)


def trash_ids(api: APIRequestContext, team_id: str, **params) -> list[str]:
    resp = trash_list(api, team_id, **params)
    assert resp.status == 200, resp.text()
    return [n["id"] for n in resp.json()["items"]]


def active_ids(api: APIRequestContext, team_id: str) -> list[str]:
    resp = api.get("/api/v1/notes", params={"team_id": team_id})
    assert resp.status == 200, resp.text()
    return [n["id"] for n in resp.json()["items"]]


def trash(api: APIRequestContext, note: dict) -> None:
    resp = api.delete(f"/api/v1/notes/{note['id']}")
    assert resp.status == 204, resp.text()


def restore(api: APIRequestContext, note_id: str):
    return api.post(f"/api/v1/notes/{note_id}/restore")


# --- soft delete ------------------------------------------------------------------------


def test_delete_hides_note_everywhere_except_trash(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], body="keep me")
    keep = make_note(api, team["id"])
    # An active note sits at the top of the all-teams listing (newest updated_at first).
    everything = api.get("/api/v1/notes", params={"limit": 100}).json()["items"]
    assert note["id"] in [n["id"] for n in everything]

    resp = api.delete(f"/api/v1/notes/{note['id']}")
    assert resp.status == 204
    assert resp.body() == b""

    assert_problem(api.get(f"/api/v1/notes/{note['id']}"), 404)
    assert_problem(patch_note(api, note, {"title": "x"}), 404)
    assert_problem(
        api.patch(f"/api/v1/notes/{note['id']}", data={"title": "x"}, headers={"If-Match": "*"}),
        404,
    )
    assert_problem(api.delete(f"/api/v1/notes/{note['id']}"), 404)
    assert active_ids(api, team["id"]) == [keep["id"]]
    everything = api.get("/api/v1/notes", params={"limit": 100}).json()["items"]
    assert note["id"] not in [n["id"] for n in everything]


def test_delete_unknown_note_is_404(api: APIRequestContext):
    assert_problem(api.delete(f"/api/v1/notes/{uuid.uuid4()}"), 404)


def test_delete_non_uuid_is_422(api: APIRequestContext):
    assert_problem(api.delete("/api/v1/notes/nope"), 422)


def test_delete_does_not_require_if_match(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    resp = api.delete(f"/api/v1/notes/{note['id']}")  # no If-Match header at all
    assert resp.status == 204


# --- trash list -------------------------------------------------------------------------


def test_trash_lists_deleted_note_with_deleted_at(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], body="body text", author_name="Ada")
    active = make_note(api, team["id"])
    assert trash_ids(api, team["id"]) == []

    before = datetime.now().astimezone()
    trash(api, note)

    resp = trash_list(api, team["id"])
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert set(data) == {"items", "next_cursor"}
    assert data["next_cursor"] is None
    assert [n["id"] for n in data["items"]] == [note["id"]]
    item = data["items"][0]
    assert set(item) == NOTE_KEYS
    assert item["deleted_at"] is not None
    stamp = _ts(item["deleted_at"])
    assert stamp.tzinfo is not None
    assert abs((stamp - before).total_seconds()) < 300
    # Everything but deleted_at is the note as it was; soft delete changes nothing else.
    assert {k: v for k, v in item.items() if k != "deleted_at"} == {
        k: v for k, v in note.items() if k != "deleted_at"
    }
    assert active["id"] not in trash_ids(api, team["id"])


def test_trash_most_recently_deleted_first(api: APIRequestContext):
    team = make_team(api)
    notes = [make_note(api, team["id"]) for _ in range(4)]
    order = [notes[2], notes[0], notes[3], notes[1]]  # deletion order, not creation order
    for note in order:
        trash(api, note)

    items = trash_list(api, team["id"]).json()["items"]
    assert [n["id"] for n in items] == [n["id"] for n in reversed(order)]
    stamps = [_ts(n["deleted_at"]) for n in items]
    assert stamps == sorted(stamps, reverse=True)
    assert all(n["deleted_at"] is not None for n in items)


def test_trash_is_scoped_to_its_team(api: APIRequestContext):
    team_a, team_b = make_team(api), make_team(api)
    in_a = make_note(api, team_a["id"])
    in_b = make_note(api, team_b["id"])
    trash(api, in_a)
    trash(api, in_b)
    assert trash_ids(api, team_a["id"]) == [in_a["id"]]
    assert trash_ids(api, team_b["id"]) == [in_b["id"]]


def test_trash_limit(api: APIRequestContext):
    team = make_team(api)
    notes = [make_note(api, team["id"]) for _ in range(3)]
    for note in notes:
        trash(api, note)
    newest_first = [n["id"] for n in reversed(notes)]

    assert trash_ids(api, team["id"], limit=2) == newest_first[:2]
    assert trash_ids(api, team["id"], limit=1) == newest_first[:1]
    assert trash_ids(api, team["id"], limit=100) == newest_first
    assert trash_ids(api, team["id"]) == newest_first  # default 20 covers all three
    assert trash_list(api, team["id"], limit=2).json()["next_cursor"] is None


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc", ""])
def test_trash_invalid_limit_is_422(api: APIRequestContext, limit: str):
    team = make_team(api)
    body = assert_problem(trash_list(api, team["id"], limit=limit), 422)
    assert body["errors"]


def test_trash_unknown_team_is_404(api: APIRequestContext):
    body = assert_problem(trash_list(api, str(uuid.uuid4())), 404)
    assert body["title"] == "Not Found"


def test_trash_non_uuid_team_is_422(api: APIRequestContext):
    assert_problem(api.get("/api/v1/teams/nope/trash"), 422)


# --- restore ----------------------------------------------------------------------------


def test_restore_returns_note_with_bumped_version_and_etag(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], title="Title ok", body="body ok", author_name="Grace")
    other = make_note(api, team["id"])
    trash(api, note)

    resp = restore(api, note["id"])
    assert resp.status == 200, resp.text()
    assert resp.headers["content-type"].startswith("application/json")
    restored = resp.json()
    assert set(restored) == NOTE_KEYS
    assert restored["deleted_at"] is None
    assert restored["version"] == note["version"] + 1 == 2
    assert resp.headers["etag"] == '"2"'
    for key in ("id", "team_id", "title", "body", "author_name", "created_at", "tags"):
        assert restored[key] == note[key], key
    assert _ts(restored["updated_at"]) > _ts(note["updated_at"])

    # Back in the normal reads; out of the trash.
    got = api.get(f"/api/v1/notes/{note['id']}")
    assert got.status == 200
    assert got.json() == restored
    assert got.headers["etag"] == '"2"'
    assert active_ids(api, team["id"]) == [note["id"], other["id"]]  # restore bumped updated_at
    assert trash_ids(api, team["id"]) == []


def test_restored_note_can_be_edited_and_trashed_again(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    trash(api, note)
    restored = restore(api, note["id"]).json()

    resp = patch_note(api, restored, {"body": "after restore"})
    assert resp.status == 200, resp.text()
    assert resp.json()["version"] == 3

    trash(api, resp.json())
    again = restore(api, note["id"])
    assert again.status == 200
    assert again.json()["version"] == 4
    assert again.json()["body"] == "after restore"


def test_restore_active_note_is_409_and_changes_nothing(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    body = assert_problem(restore(api, note["id"]), 409)
    assert body["title"] == "Conflict"
    assert body["instance"] == f"/api/v1/notes/{note['id']}/restore"
    got = api.get(f"/api/v1/notes/{note['id']}")
    assert got.json() == note
    assert got.headers["etag"] == '"1"'


def test_restore_twice_second_is_409(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    trash(api, note)
    assert restore(api, note["id"]).status == 200
    assert_problem(restore(api, note["id"]), 409)
    # The failed second restore did not bump the version again.
    assert api.get(f"/api/v1/notes/{note['id']}").json()["version"] == 2


def test_restore_unknown_note_is_404(api: APIRequestContext):
    assert_problem(restore(api, str(uuid.uuid4())), 404)


def test_restore_non_uuid_is_422(api: APIRequestContext):
    assert_problem(restore(api, "nope"), 422)


def test_restore_needs_no_body_or_if_match(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    trash(api, note)
    resp = api.post(f"/api/v1/notes/{note['id']}/restore")  # no body, no headers
    assert resp.status == 200, resp.text()


def test_restore_wrong_method_is_405_problem_json(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    assert_problem(api.get(f"/api/v1/notes/{note['id']}/restore"), 405)


# --- concurrency token across a delete/restore cycle ------------------------------------


def test_if_match_captured_before_delete_is_stale_after_restore(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    old_etag = api.get(f"/api/v1/notes/{note['id']}").headers["etag"]
    assert old_etag == '"1"'
    trash(api, note)
    assert restore(api, note["id"]).headers["etag"] == '"2"'

    resp = api.patch(
        f"/api/v1/notes/{note['id']}", data={"title": "stale"}, headers={"If-Match": old_etag}
    )
    body = assert_problem(resp, 412)
    assert "version 2" in body["detail"]
    assert api.get(f"/api/v1/notes/{note['id']}").json()["title"] == note["title"]

    fresh = api.patch(
        f"/api/v1/notes/{note['id']}", data={"title": "fresh"}, headers={"If-Match": '"2"'}
    )
    assert fresh.status == 200, fresh.text()
    assert fresh.json()["version"] == 3


# --- team deletion ----------------------------------------------------------------------


def test_deleting_team_permanently_removes_trashed_notes(api: APIRequestContext):
    team = make_team(api)
    trashed = make_note(api, team["id"])
    active = make_note(api, team["id"])
    trash(api, trashed)
    assert trash_ids(api, team["id"]) == [trashed["id"]]

    assert api.delete(f"/api/v1/teams/{team['id']}").status == 204

    assert_problem(restore(api, trashed["id"]), 404)
    assert_problem(restore(api, active["id"]), 404)
    assert_problem(trash_list(api, team["id"]), 404)
    assert_problem(api.get(f"/api/v1/notes/{trashed['id']}"), 404)
