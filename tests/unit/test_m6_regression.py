"""M6 regression tests: create, read, update and concurrency behavior from M4-M5 is unchanged.

These may pass on the pre-M6 baseline.
"""

import uuid

NOTES = "/api/v1/notes"
TEAMS = "/api/v1/teams"
PROBLEM = "application/problem+json"


def problem(resp, status):
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].split(";")[0].strip() == PROBLEM
    return resp.json()


def test_create_note_still_returns_201_version_1_and_etag(client, team_factory):
    team = team_factory(client)
    resp = client.post(
        f"{TEAMS}/{team['id']}/notes", json={"title": "T", "body": "B", "author_name": "Ann"}
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert (data["version"], data["tags"], data["author_name"]) == (1, [], "Ann")
    assert resp.headers["etag"] == '"1"'
    assert resp.headers["location"] == f"{NOTES}/{data['id']}"


def test_get_note_still_returns_etag(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="Read me")
    resp = client.get(f"{NOTES}/{note['id']}")
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"1"'
    assert resp.json()["title"] == "Read me"
    problem(client.get(f"{NOTES}/{uuid.uuid4()}"), 404)


def test_patch_still_requires_if_match(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    problem(client.patch(f"{NOTES}/{note['id']}", json={"title": "x"}), 428)


def test_patch_with_matching_if_match_bumps_version(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="a", body="b")
    resp = client.patch(f"{NOTES}/{note['id']}", json={"title": "z"}, headers={"If-Match": '"1"'})
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == '"2"'
    data = resp.json()
    assert (data["version"], data["title"], data["body"]) == (2, "z", "b")
    assert data["created_at"] == note["created_at"]


def test_stale_if_match_still_412_and_change_not_applied(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="orig")
    h = {"If-Match": '"1"'}
    assert client.patch(f"{NOTES}/{note['id']}", json={"title": "A"}, headers=h).status_code == 200
    body = problem(client.patch(f"{NOTES}/{note['id']}", json={"title": "B"}, headers=h), 412)
    assert "2" in body["detail"]
    assert client.get(f"{NOTES}/{note['id']}").json()["title"] == "A"


def test_if_match_weak_wildcard_and_garbage_still_handled(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    url = f"{NOTES}/{note['id']}"
    assert client.patch(url, json={"body": "1"}, headers={"If-Match": '"1"'}).status_code == 200
    assert client.patch(url, json={"body": "2"}, headers={"If-Match": 'W/"2"'}).status_code == 200
    assert client.patch(url, json={"body": "3"}, headers={"If-Match": "*"}).status_code == 200
    problem(client.patch(url, json={"body": "4"}, headers={"If-Match": '"abc"'}), 412)


def test_list_notes_still_newest_updated_first(client, team_factory, note_factory):
    team = team_factory(client)
    a = note_factory(client, team["id"], title="a")
    b = note_factory(client, team["id"], title="b")
    client.patch(f"{NOTES}/{a['id']}", json={"body": "bump"}, headers={"If-Match": '"1"'})
    data = client.get(NOTES, params={"team_id": team["id"]}).json()
    assert [n["id"] for n in data["items"]] == [a["id"], b["id"]]
    assert data["next_cursor"] is None
    assert len(client.get(NOTES, params={"team_id": team["id"], "limit": 1}).json()["items"]) == 1


def test_delete_note_still_204_then_get_patch_delete_404(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    url = f"{NOTES}/{note['id']}"
    assert client.delete(url).status_code == 204
    problem(client.get(url), 404)
    problem(client.patch(url, json={"title": "x"}, headers={"If-Match": '"1"'}), 404)
    problem(client.delete(url), 404)
    assert note["id"] not in [n["id"] for n in client.get(NOTES).json()["items"]]


def test_team_delete_still_removes_active_notes(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    assert client.delete(f"{TEAMS}/{team['id']}").status_code == 204
    problem(client.get(f"{NOTES}/{note['id']}"), 404)
    problem(client.get(f"{TEAMS}/{team['id']}"), 404)


def test_note_validation_unchanged(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    problem(client.post(f"{TEAMS}/{team['id']}/notes", json={"title": "  "}), 422)
    problem(
        client.post(f"{TEAMS}/{team['id']}/notes", json={"title": "x", "deleted_at": None}), 422
    )
    problem(client.patch(f"{NOTES}/{note['id']}", json={}, headers={"If-Match": '"1"'}), 422)
    problem(client.get(NOTES, params={"limit": 0}), 422)


def test_delete_unknown_note_404_and_non_uuid_422(client):
    problem(client.delete(f"{NOTES}/{uuid.uuid4()}"), 404)
    problem(client.delete(f"{NOTES}/not-a-uuid"), 422)


def test_delete_note_needs_no_if_match(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"])
    assert client.delete(f"{NOTES}/{note['id']}").status_code == 204


def test_delete_note_leaves_siblings_in_list(client, team_factory, note_factory):
    team = team_factory(client)
    gone = note_factory(client, team["id"])
    stay = note_factory(client, team["id"])
    assert client.delete(f"{NOTES}/{gone['id']}").status_code == 204
    ids = [n["id"] for n in client.get(NOTES, params={"team_id": team["id"]}).json()["items"]]
    assert ids == [stay["id"]]
