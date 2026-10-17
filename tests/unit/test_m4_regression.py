"""M4 regression tests: teams endpoints and /health stay unchanged (may pass on the baseline)."""

import uuid

PROBLEM = "application/problem+json"


def test_health_unchanged(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "commit": "local"}


def test_team_create_get_list_patch_still_work(client, team_factory):
    team = team_factory(client, "Platform")
    assert client.get(f"/api/v1/teams/{team['id']}").json()["name"] == "Platform"
    resp = client.patch(f"/api/v1/teams/{team['id']}", json={"name": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    items = client.get("/api/v1/teams").json()["items"]
    assert team["id"] in {t["id"] for t in items}


def test_team_delete_still_works_without_notes(client, team_factory):
    team = team_factory(client)
    assert client.delete(f"/api/v1/teams/{team['id']}").status_code == 204
    resp = client.get(f"/api/v1/teams/{team['id']}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].split(";")[0] == PROBLEM


def test_unknown_route_is_still_problem_json_404(client):
    resp = client.get(f"/api/v1/{uuid.uuid4().hex}")
    assert resp.status_code == 404
    assert resp.headers["content-type"].split(";")[0] == PROBLEM
