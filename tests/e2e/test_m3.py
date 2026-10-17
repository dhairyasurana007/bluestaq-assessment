"""M3 e2e: team spaces and the problem+json error contract, black-box over HTTP."""

import uuid
from datetime import datetime

import pytest
from playwright.sync_api import APIRequestContext

from tests.e2e.helpers import make_team, unique_name

PROBLEM = "application/problem+json"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_problem(resp, status: int) -> dict:
    assert resp.status == status, resp.text()
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM
    body = resp.json()
    for key in ("type", "title", "status", "detail"):
        assert key in body, body
    assert body["status"] == status
    assert isinstance(body["detail"], str) and body["detail"]
    return body


# --- create -----------------------------------------------------------------------------


def test_create_team(api: APIRequestContext):
    name = unique_name()
    resp = api.post("/api/v1/teams", data={"name": name})
    assert resp.status == 201
    assert resp.headers["content-type"].startswith("application/json")
    team = resp.json()
    assert set(team) == {"id", "name", "created_at", "updated_at"}
    assert team["name"] == name
    uuid.UUID(team["id"])
    assert resp.headers["location"] == f"/api/v1/teams/{team['id']}"
    assert _ts(team["created_at"]).tzinfo is not None
    assert _ts(team["created_at"]) <= _ts(team["updated_at"])


def test_create_team_trims_whitespace(api: APIRequestContext):
    name = unique_name()
    resp = api.post("/api/v1/teams", data={"name": f"   {name}\t "})
    assert resp.status == 201
    assert resp.json()["name"] == name


def test_create_team_name_length_bounds(api: APIRequestContext):
    ok = api.post("/api/v1/teams", data={"name": "n" * 100})
    assert ok.status == 201
    assert len(ok.json()["name"]) == 100
    api.delete(f"/api/v1/teams/{ok.json()['id']}")

    # 100 chars plus surrounding whitespace is fine: the limit applies after trimming.
    padded = api.post("/api/v1/teams", data={"name": "  " + "p" * 100 + "  "})
    assert padded.status == 201
    api.delete(f"/api/v1/teams/{padded.json()['id']}")


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {},
        {"name": 123},
        {"name": None},
    ],
)
def test_create_team_invalid_name_is_422(api: APIRequestContext, payload: dict):
    body = assert_problem(api.post("/api/v1/teams", data=payload), 422)
    assert body["errors"], body
    for err in body["errors"]:
        assert isinstance(err["loc"], list) and isinstance(err["msg"], str)
    assert any(err["loc"] == ["body", "name"] for err in body["errors"]), body["errors"]


def test_create_team_missing_name_loc(api: APIRequestContext):
    body = assert_problem(api.post("/api/v1/teams", data={}), 422)
    assert body["errors"][0]["loc"] == ["body", "name"]


def test_create_team_unknown_field_is_422(api: APIRequestContext):
    body = assert_problem(
        api.post("/api/v1/teams", data={"name": unique_name(), "color": "red"}), 422
    )
    assert any(err["loc"][:2] == ["body", "color"] for err in body["errors"]), body["errors"]


def test_create_team_malformed_json_is_422(api: APIRequestContext):
    resp = api.post(
        "/api/v1/teams",
        data="{not json",
        headers={"content-type": "application/json"},
    )
    assert_problem(resp, 422)


# --- list -------------------------------------------------------------------------------


def test_list_teams_shape_and_limit(api: APIRequestContext):
    made = [make_team(api) for _ in range(3)]
    resp = api.get("/api/v1/teams", params={"limit": 2})
    assert resp.status == 200
    data = resp.json()
    assert set(data) == {"items", "next_cursor"}
    assert data["next_cursor"] is None
    assert 1 <= len(data["items"]) <= 2
    for item in data["items"]:
        assert set(item) == {"id", "name", "created_at", "updated_at"}

    one = api.get("/api/v1/teams", params={"limit": 1}).json()
    assert len(one["items"]) == 1

    default = api.get("/api/v1/teams").json()
    assert 1 <= len(default["items"]) <= 20
    for team in made:
        api.delete(f"/api/v1/teams/{team['id']}")


def test_list_teams_newest_first(api: APIRequestContext):
    older = make_team(api)
    newer = make_team(api)
    items = api.get("/api/v1/teams", params={"limit": 100}).json()["items"]
    stamps = [_ts(t["created_at"]) for t in items]
    assert stamps == sorted(stamps, reverse=True)
    ids = [t["id"] for t in items]
    if older["id"] in ids and newer["id"] in ids:  # shared DBs may have >100 newer teams
        assert ids.index(newer["id"]) < ids.index(older["id"])
    for team in (older, newer):
        api.delete(f"/api/v1/teams/{team['id']}")


@pytest.mark.parametrize("limit", ["0", "101", "-1", "abc"])
def test_list_teams_invalid_limit_is_422(api: APIRequestContext, limit: str):
    body = assert_problem(api.get("/api/v1/teams", params={"limit": limit}), 422)
    assert any(err["loc"] == ["query", "limit"] for err in body["errors"]), body["errors"]


def test_list_teams_limit_bounds_accepted(api: APIRequestContext):
    assert api.get("/api/v1/teams", params={"limit": 1}).status == 200
    assert api.get("/api/v1/teams", params={"limit": 100}).status == 200


# --- get --------------------------------------------------------------------------------


def test_get_team(api: APIRequestContext):
    team = make_team(api)
    resp = api.get(f"/api/v1/teams/{team['id']}")
    assert resp.status == 200
    assert resp.json() == team
    api.delete(f"/api/v1/teams/{team['id']}")


def test_get_unknown_team_is_404_problem(api: APIRequestContext):
    missing = str(uuid.uuid4())
    body = assert_problem(api.get(f"/api/v1/teams/{missing}"), 404)
    assert body["title"] == "Not Found"
    assert body["instance"] == f"/api/v1/teams/{missing}"


def test_get_team_non_uuid_is_422(api: APIRequestContext):
    body = assert_problem(api.get("/api/v1/teams/not-a-uuid"), 422)
    assert any(err["loc"] == ["path", "team_id"] for err in body["errors"]), body["errors"]


# --- patch ------------------------------------------------------------------------------


def test_patch_team_renames_and_bumps_updated_at(api: APIRequestContext):
    team = make_team(api)
    new_name = unique_name("renamed")
    resp = api.patch(f"/api/v1/teams/{team['id']}", data={"name": f"  {new_name} "})
    assert resp.status == 200
    updated = resp.json()
    assert updated["id"] == team["id"]
    assert updated["name"] == new_name
    assert updated["created_at"] == team["created_at"]
    assert _ts(updated["updated_at"]) > _ts(team["updated_at"])

    again = api.get(f"/api/v1/teams/{team['id']}").json()
    assert again == updated
    api.delete(f"/api/v1/teams/{team['id']}")


def test_patch_unknown_team_is_404(api: APIRequestContext):
    resp = api.patch(f"/api/v1/teams/{uuid.uuid4()}", data={"name": "whatever"})
    assert_problem(resp, 404)


def test_patch_team_non_uuid_is_422(api: APIRequestContext):
    assert_problem(api.patch("/api/v1/teams/nope", data={"name": "x"}), 422)


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "  "}, {"name": "x" * 101}])
def test_patch_team_invalid_body_is_422(api: APIRequestContext, payload: dict):
    team = make_team(api)
    body = assert_problem(api.patch(f"/api/v1/teams/{team['id']}", data=payload), 422)
    assert any(err["loc"] == ["body", "name"] for err in body["errors"]), body["errors"]
    assert api.get(f"/api/v1/teams/{team['id']}").json()["name"] == team["name"]
    api.delete(f"/api/v1/teams/{team['id']}")


def test_patch_team_unknown_field_is_422(api: APIRequestContext):
    team = make_team(api)
    resp = api.patch(f"/api/v1/teams/{team['id']}", data={"name": "ok-name", "extra": 1})
    assert_problem(resp, 422)
    api.delete(f"/api/v1/teams/{team['id']}")


# --- delete -----------------------------------------------------------------------------


def test_delete_team(api: APIRequestContext):
    team = make_team(api)
    resp = api.delete(f"/api/v1/teams/{team['id']}")
    assert resp.status == 204
    assert resp.body() == b""

    assert_problem(api.get(f"/api/v1/teams/{team['id']}"), 404)
    assert_problem(api.delete(f"/api/v1/teams/{team['id']}"), 404)
    ids = [t["id"] for t in api.get("/api/v1/teams", params={"limit": 100}).json()["items"]]
    assert team["id"] not in ids


def test_delete_unknown_team_is_404(api: APIRequestContext):
    assert_problem(api.delete(f"/api/v1/teams/{uuid.uuid4()}"), 404)


def test_delete_team_non_uuid_is_422(api: APIRequestContext):
    assert_problem(api.delete("/api/v1/teams/nope"), 422)


# --- error contract on routing errors ---------------------------------------------------


def test_routing_404_is_problem_json(api: APIRequestContext):
    for path in ("/nope", "/api/v1/nope", "/api/v2/teams"):
        body = assert_problem(api.get(path), 404)
        assert body["title"] == "Not Found"
        assert body["instance"] == path


def test_routing_405_is_problem_json(api: APIRequestContext):
    resp = api.put("/api/v1/teams", data={"name": "x"})
    body = assert_problem(resp, 405)
    assert body["title"] == "Method Not Allowed"
    assert "POST" in resp.headers.get("allow", "")

    team = make_team(api)
    assert_problem(api.post(f"/api/v1/teams/{team['id']}", data={}), 405)
    assert_problem(api.put(f"/api/v1/teams/{team['id']}", data={"name": "x"}), 405)
    assert_problem(api.post("/health", data={}), 405)
    api.delete(f"/api/v1/teams/{team['id']}")


def test_health_unchanged(api: APIRequestContext):
    resp = api.get("/health")
    assert resp.status == 200
    assert resp.json()["status"] == "ok"
    assert set(resp.json()) == {"status", "commit"}
