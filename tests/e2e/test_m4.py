"""M4 e2e: note CRUD within team spaces, black-box over HTTP."""

import uuid
from datetime import datetime

import pytest
from playwright.sync_api import APIRequestContext

from tests.e2e.helpers import make_team, unique_name

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


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_problem(resp, status: int) -> dict:
    assert resp.status == status, resp.text()
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM
    body = resp.json()
    for key in ("type", "title", "status", "detail"):
        assert key in body, body
    assert body["status"] == status
    return body


def make_note(api: APIRequestContext, team_id: str, **fields) -> dict:
    payload = {"title": unique_name("note"), **fields}
    resp = api.post(f"/api/v1/teams/{team_id}/notes", data=payload)
    assert resp.status == 201, resp.text()
    return resp.json()


# --- create -----------------------------------------------------------------------------


def test_create_note_defaults(api: APIRequestContext):
    team = make_team(api)
    title = unique_name("note")
    resp = api.post(f"/api/v1/teams/{team['id']}/notes", data={"title": title})
    assert resp.status == 201
    assert resp.headers["content-type"].startswith("application/json")
    note = resp.json()
    assert set(note) == NOTE_KEYS
    uuid.UUID(note["id"])
    assert note["team_id"] == team["id"]
    assert note["title"] == title
    assert note["body"] == ""
    assert note["tags"] == []
    assert note["author_name"] is None
    assert note["version"] == 1
    assert _ts(note["created_at"]).tzinfo is not None
    assert note["created_at"] == note["updated_at"]
    assert resp.headers["location"] == f"/api/v1/notes/{note['id']}"
    assert resp.headers["etag"] == '"1"'


def test_create_note_with_all_fields_and_trimming(api: APIRequestContext):
    team = make_team(api)
    resp = api.post(
        f"/api/v1/teams/{team['id']}/notes",
        data={"title": "  Hello  ", "body": "  keep  my spaces ", "author_name": "  Ada  "},
    )
    assert resp.status == 201
    note = resp.json()
    assert note["title"] == "Hello"
    assert note["body"] == "  keep  my spaces "
    assert note["author_name"] == "Ada"
    assert note["tags"] == []


def test_create_note_explicit_null_author(api: APIRequestContext):
    team = make_team(api)
    resp = api.post(
        f"/api/v1/teams/{team['id']}/notes", data={"title": "t", "author_name": None, "body": ""}
    )
    assert resp.status == 201
    assert resp.json()["author_name"] is None


def test_create_note_length_bounds_accepted(api: APIRequestContext):
    team = make_team(api)
    resp = api.post(
        f"/api/v1/teams/{team['id']}/notes",
        data={"title": "t" * 200, "body": "b" * 100_000, "author_name": "a" * 100},
    )
    assert resp.status == 201, resp.text()
    note = resp.json()
    assert len(note["title"]) == 200
    assert len(note["body"]) == 100_000
    assert len(note["author_name"]) == 100
    fetched = api.get(f"/api/v1/notes/{note['id']}").json()
    assert fetched["body"] == "b" * 100_000


def test_create_note_in_unknown_team_is_404(api: APIRequestContext):
    resp = api.post(f"/api/v1/teams/{uuid.uuid4()}/notes", data={"title": "orphan"})
    body = assert_problem(resp, 404)
    assert body["title"] == "Not Found"


def test_create_note_non_uuid_team_is_422(api: APIRequestContext):
    body = assert_problem(api.post("/api/v1/teams/nope/notes", data={"title": "x"}), 422)
    assert any(err["loc"] == ["path", "team_id"] for err in body["errors"]), body["errors"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "   "}, "title"),
        ({"title": "t" * 201}, "title"),
        ({"title": None}, "title"),
        ({"title": 5}, "title"),
        ({}, "title"),
        ({"title": "ok", "body": "b" * 100_001}, "body"),
        ({"title": "ok", "body": None}, "body"),
        ({"title": "ok", "author_name": "a" * 101}, "author_name"),
        ({"title": "ok", "author_name": ""}, "author_name"),
        ({"title": "ok", "author_name": "   "}, "author_name"),
    ],
)
def test_create_note_invalid_field_is_422(api: APIRequestContext, payload: dict, field: str):
    team = make_team(api)
    body = assert_problem(api.post(f"/api/v1/teams/{team['id']}/notes", data=payload), 422)
    assert any(err["loc"][:2] == ["body", field] for err in body["errors"]), body["errors"]
    listing = api.get("/api/v1/notes", params={"team_id": team["id"]}).json()
    assert listing["items"] == []


@pytest.mark.parametrize("extra", [{"color": "red"}, {"tags": ["a"]}, {"version": 3}, {"id": "x"}])
def test_create_note_unknown_field_is_422(api: APIRequestContext, extra: dict):
    team = make_team(api)
    resp = api.post(f"/api/v1/teams/{team['id']}/notes", data={"title": "ok", **extra})
    body = assert_problem(resp, 422)
    key = next(iter(extra))
    assert any(err["loc"][:2] == ["body", key] for err in body["errors"]), body["errors"]


# --- get --------------------------------------------------------------------------------


def test_get_note(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], body="hello", author_name="Ada")
    resp = api.get(f"/api/v1/notes/{note['id']}")
    assert resp.status == 200
    assert resp.json() == note
    assert resp.headers["etag"] == '"1"'


def test_get_unknown_note_is_404(api: APIRequestContext):
    missing = str(uuid.uuid4())
    body = assert_problem(api.get(f"/api/v1/notes/{missing}"), 404)
    assert body["instance"] == f"/api/v1/notes/{missing}"


def test_get_note_non_uuid_is_422(api: APIRequestContext):
    body = assert_problem(api.get("/api/v1/notes/not-a-uuid"), 422)
    assert any(err["loc"] == ["path", "note_id"] for err in body["errors"]), body["errors"]


# --- list -------------------------------------------------------------------------------


def test_list_notes_by_team_newest_updated_first(api: APIRequestContext):
    team = make_team(api)
    first = make_note(api, team["id"])
    second = make_note(api, team["id"])
    third = make_note(api, team["id"])
    # Editing the oldest note moves it to the front.
    assert api.patch(f"/api/v1/notes/{first['id']}", data={"body": "edited"}).status == 200

    resp = api.get("/api/v1/notes", params={"team_id": team["id"]})
    assert resp.status == 200
    data = resp.json()
    assert set(data) == {"items", "next_cursor"}
    assert data["next_cursor"] is None
    assert [n["id"] for n in data["items"]] == [first["id"], third["id"], second["id"]]
    for item in data["items"]:
        assert set(item) == NOTE_KEYS
        assert item["team_id"] == team["id"]
    stamps = [_ts(n["updated_at"]) for n in data["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_list_notes_only_requested_team(api: APIRequestContext):
    team_a, team_b = make_team(api), make_team(api)
    note_a = make_note(api, team_a["id"])
    note_b = make_note(api, team_b["id"])

    only_a = api.get("/api/v1/notes", params={"team_id": team_a["id"]}).json()["items"]
    assert [n["id"] for n in only_a] == [note_a["id"]]
    only_b = api.get("/api/v1/notes", params={"team_id": team_b["id"]}).json()["items"]
    assert [n["id"] for n in only_b] == [note_b["id"]]


def test_list_notes_repeated_team_id(api: APIRequestContext):
    team_a, team_b, team_c = make_team(api), make_team(api), make_team(api)
    note_a = make_note(api, team_a["id"])
    note_b = make_note(api, team_b["id"])
    make_note(api, team_c["id"])

    resp = api.get(
        f"/api/v1/notes?team_id={team_a['id']}&team_id={team_b['id']}",
    )
    assert resp.status == 200
    items = resp.json()["items"]
    assert [n["id"] for n in items] == [note_b["id"], note_a["id"]]
    assert {n["team_id"] for n in items} == {team_a["id"], team_b["id"]}


@pytest.mark.parametrize("value", [None, "not-a-uuid"])
def test_list_notes_unknown_team_matches_nothing(api: APIRequestContext, value):
    team_id = str(uuid.uuid4()) if value is None else value
    resp = api.get("/api/v1/notes", params={"team_id": team_id})
    assert resp.status == 200
    assert resp.json() == {"items": [], "next_cursor": None}


def test_list_notes_without_team_id_spans_teams(api: APIRequestContext):
    note = make_note(api, make_team(api)["id"])
    resp = api.get("/api/v1/notes", params={"limit": 100})
    assert resp.status == 200
    data = resp.json()
    assert data["next_cursor"] is None
    assert 1 <= len(data["items"]) <= 100
    stamps = [_ts(n["updated_at"]) for n in data["items"]]
    assert stamps == sorted(stamps, reverse=True)
    # A shared DB may hold more than 100 newer notes; only check presence when it fits.
    ids = [n["id"] for n in data["items"]]
    if len(ids) < 100:
        assert note["id"] in ids


def test_list_notes_limit(api: APIRequestContext):
    team = make_team(api)
    notes = [make_note(api, team["id"]) for _ in range(3)]
    params = {"team_id": team["id"]}

    two = api.get("/api/v1/notes", params={**params, "limit": 2}).json()
    assert [n["id"] for n in two["items"]] == [notes[2]["id"], notes[1]["id"]]
    assert two["next_cursor"] is None
    one = api.get("/api/v1/notes", params={**params, "limit": 1}).json()
    assert [n["id"] for n in one["items"]] == [notes[2]["id"]]
    default = api.get("/api/v1/notes", params=params).json()
    assert len(default["items"]) == 3
    assert api.get("/api/v1/notes", params={**params, "limit": 100}).status == 200


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc"])
def test_list_notes_invalid_limit_is_422(api: APIRequestContext, limit: str):
    body = assert_problem(api.get("/api/v1/notes", params={"limit": limit}), 422)
    assert any(err["loc"] == ["query", "limit"] for err in body["errors"]), body["errors"]


# --- patch ------------------------------------------------------------------------------


def test_patch_title_only(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], body="original body", author_name="Ada")
    resp = api.patch(f"/api/v1/notes/{note['id']}", data={"title": "  New title "})
    assert resp.status == 200
    updated = resp.json()
    assert set(updated) == NOTE_KEYS
    assert updated["title"] == "New title"
    assert updated["body"] == "original body"
    assert updated["author_name"] == "Ada"
    assert updated["tags"] == []
    assert updated["id"] == note["id"]
    assert updated["team_id"] == team["id"]
    assert updated["version"] == 2
    assert updated["created_at"] == note["created_at"]
    assert _ts(updated["updated_at"]) > _ts(note["updated_at"])
    assert resp.headers["etag"] == '"2"'
    assert api.get(f"/api/v1/notes/{note['id']}").json() == updated


def test_patch_body_only_including_empty(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"], body="something")
    resp = api.patch(f"/api/v1/notes/{note['id']}", data={"body": ""})
    assert resp.status == 200
    updated = resp.json()
    assert updated["body"] == ""
    assert updated["title"] == note["title"]
    assert updated["version"] == 2


def test_patch_both_fields(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    resp = api.patch(f"/api/v1/notes/{note['id']}", data={"title": "T2", "body": "B2"})
    assert resp.status == 200
    updated = resp.json()
    assert (updated["title"], updated["body"], updated["version"]) == ("T2", "B2", 2)


def test_patch_bumps_version_by_one_each_time(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    previous = _ts(note["updated_at"])
    for expected in (2, 3, 4):
        resp = api.patch(f"/api/v1/notes/{note['id']}", data={"body": f"edit {expected}"})
        assert resp.status == 200
        updated = resp.json()
        assert updated["version"] == expected
        assert resp.headers["etag"] == f'"{expected}"'
        assert _ts(updated["updated_at"]) > previous
        assert updated["created_at"] == note["created_at"]
        previous = _ts(updated["updated_at"])
    assert api.get(f"/api/v1/notes/{note['id']}").headers["etag"] == '"4"'


def test_patch_unknown_note_is_404(api: APIRequestContext):
    assert_problem(api.patch(f"/api/v1/notes/{uuid.uuid4()}", data={"title": "x"}), 404)


def test_patch_non_uuid_is_422(api: APIRequestContext):
    assert_problem(api.patch("/api/v1/notes/nope", data={"title": "x"}), 422)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"color": "red"},
        {"author_name": "Mallory"},
        {"title": "ok", "author_name": "Mallory"},
        {"tags": ["a"]},
        {"title": "ok", "version": 9},
        {"title": ""},
        {"title": "   "},
        {"title": "t" * 201},
        {"title": None},
        {"body": None},
        {"body": "b" * 100_001},
    ],
)
def test_patch_invalid_body_is_422_and_changes_nothing(api: APIRequestContext, payload: dict):
    team = make_team(api)
    note = make_note(api, team["id"], body="stay", author_name="Ada")
    body = assert_problem(api.patch(f"/api/v1/notes/{note['id']}", data=payload), 422)
    assert body["errors"], body
    assert api.get(f"/api/v1/notes/{note['id']}").json() == note


def test_patch_length_bounds_accepted(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    resp = api.patch(
        f"/api/v1/notes/{note['id']}", data={"title": "t" * 200, "body": "b" * 100_000}
    )
    assert resp.status == 200, resp.text()


# --- delete (hard delete in M4) ---------------------------------------------------------


def test_delete_note(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    keep = make_note(api, team["id"])

    resp = api.delete(f"/api/v1/notes/{note['id']}")
    assert resp.status == 204
    assert resp.body() == b""

    assert_problem(api.get(f"/api/v1/notes/{note['id']}"), 404)
    assert_problem(api.patch(f"/api/v1/notes/{note['id']}", data={"title": "x"}), 404)
    assert_problem(api.delete(f"/api/v1/notes/{note['id']}"), 404)
    items = api.get("/api/v1/notes", params={"team_id": team["id"]}).json()["items"]
    assert [n["id"] for n in items] == [keep["id"]]


def test_delete_unknown_note_is_404(api: APIRequestContext):
    assert_problem(api.delete(f"/api/v1/notes/{uuid.uuid4()}"), 404)


def test_delete_note_non_uuid_is_422(api: APIRequestContext):
    assert_problem(api.delete("/api/v1/notes/nope"), 422)


# --- team cascade -----------------------------------------------------------------------


def test_deleting_team_deletes_its_notes(api: APIRequestContext):
    doomed, survivor = make_team(api), make_team(api)
    doomed_notes = [make_note(api, doomed["id"]) for _ in range(2)]
    kept = make_note(api, survivor["id"])

    assert api.delete(f"/api/v1/teams/{doomed['id']}").status == 204

    for note in doomed_notes:
        assert_problem(api.get(f"/api/v1/notes/{note['id']}"), 404)
    listing = api.get("/api/v1/notes", params={"team_id": doomed["id"]}).json()
    assert listing["items"] == []
    assert api.get(f"/api/v1/notes/{kept['id']}").status == 200
    assert_problem(api.post(f"/api/v1/teams/{doomed['id']}/notes", data={"title": "late"}), 404)


# --- routing ----------------------------------------------------------------------------


def test_notes_routing_405_is_problem_json(api: APIRequestContext):
    team = make_team(api)
    note = make_note(api, team["id"])
    assert_problem(api.put(f"/api/v1/notes/{note['id']}", data={"title": "x"}), 405)
    assert_problem(api.post(f"/api/v1/notes/{note['id']}", data={}), 405)
    assert_problem(api.post("/api/v1/notes", data={"title": "x"}), 405)
    assert_problem(api.get(f"/api/v1/teams/{team['id']}/notes"), 405)
