"""M5 regression tests: behavior that M5 must leave unchanged (may pass on the baseline)."""

import threading
import uuid
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

NOTES = "/api/v1/notes"
TEAMS = "/api/v1/teams"
PROBLEM = "application/problem+json"


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


def patch_note(client, note_id, if_match=None, **payload):
    headers = {} if if_match is None else {"If-Match": if_match}
    return client.patch(f"{NOTES}/{note_id}", headers=headers, json=payload)


def new_note(client, team_factory, note_factory, **fields):
    return note_factory(client, team_factory(client)["id"], **fields)


# ------------------------------------------------------------------ 422 with a valid If-Match


@pytest.mark.parametrize(
    ("payload", "loc"),
    [
        ({}, None),
        ({"author_name": "Bob"}, ["body", "author_name"]),
        ({"bogus": 1}, ["body", "bogus"]),
        ({"title": ""}, ["body", "title"]),
        ({"title": "t" * 201}, ["body", "title"]),
        ({"body": "b" * 100_001}, ["body", "body"]),
        ({"title": "ok", "author_name": "Bob"}, ["body", "author_name"]),
    ],
    ids=["empty", "author_name", "unknown", "empty-title", "long-title", "long-body", "mixed"],
)
@pytest.mark.parametrize("header", ['"1"', "*"])
def test_invalid_body_with_valid_if_match_is_still_422_and_changes_nothing(
    client, team_factory, note_factory, payload, loc, header
):
    note = new_note(client, team_factory, note_factory, title="orig", author_name="Ann")
    resp = patch_note(client, note["id"], header, **payload)
    body = assert_problem(resp, 422)
    if loc is not None:
        assert [e for e in body["errors"] if e["loc"] == loc], body["errors"]
    after = client.get(f"{NOTES}/{note['id']}").json()
    assert (after["version"], after["title"], after["author_name"]) == (1, "orig", "Ann")


# ------------------------------------------------------------------ 404 / 422 on the id


def test_unknown_note_with_valid_if_match_is_404_problem(client, team_factory, note_factory):
    new_note(client, team_factory, note_factory)
    missing = str(uuid.uuid4())
    for header in ('"1"', "*", 'W/"1"'):
        resp = patch_note(client, missing, header, title="x")
        assert_problem(resp, 404, instance=f"{NOTES}/{missing}")


def test_non_uuid_note_id_with_if_match_is_422(client):
    assert_problem(patch_note(client, "nope", '"1"', title="x"), 422)


def test_patch_deleted_note_with_if_match_is_404(client, team_factory, note_factory):
    note = new_note(client, team_factory, note_factory)
    assert client.delete(f"{NOTES}/{note['id']}").status_code == 204
    assert_problem(patch_note(client, note["id"], '"1"', title="x"), 404)


# ------------------------------------------------------------------ ETag and the other endpoints


def test_post_create_still_returns_etag_1_and_location(client, team_factory):
    team = team_factory(client)
    resp = client.post(f"{TEAMS}/{team['id']}/notes", json={"title": "n"})
    assert resp.status_code == 201, resp.text
    assert resp.headers["etag"] == '"1"'
    assert resp.headers["location"] == f"{NOTES}/{resp.json()['id']}"
    assert resp.json()["version"] == 1


def test_post_create_ignores_if_match_header(client, team_factory):
    team = team_factory(client)
    for header in ('"99"', "abc", "*"):
        resp = client.post(
            f"{TEAMS}/{team['id']}/notes", headers={"If-Match": header}, json={"title": "n"}
        )
        assert resp.status_code == 201, resp.text
        assert resp.headers["etag"] == '"1"'


def test_get_one_still_returns_etag_matching_version(client, team_factory, note_factory):
    note = new_note(client, team_factory, note_factory, title="t")
    resp = client.get(f"{NOTES}/{note['id']}")
    assert resp.status_code == 200
    assert resp.headers["etag"] == f'"{resp.json()["version"]}"' == '"1"'
    assert patch_note(client, note["id"], '"1"', title="t2").status_code == 200
    again = client.get(f"{NOTES}/{note['id']}")
    assert again.headers["etag"] == '"2"'
    assert again.json()["version"] == 2


def test_get_one_and_list_ignore_if_match_header(client, team_factory, note_factory):
    team = team_factory(client)
    note = note_factory(client, team["id"], title="t")
    for header in ('"99"', "abc", "*"):
        one = client.get(f"{NOTES}/{note['id']}", headers={"If-Match": header})
        assert one.status_code == 200, one.text
        lst = client.get(NOTES, params=[("team_id", team["id"])], headers={"If-Match": header})
        assert lst.status_code == 200, lst.text
        assert [n["id"] for n in lst.json()["items"]] == [note["id"]]


def test_delete_note_does_not_require_if_match(client, team_factory, note_factory):
    note = new_note(client, team_factory, note_factory)
    resp = client.delete(f"{NOTES}/{note['id']}")
    assert resp.status_code == 204
    assert client.get(f"{NOTES}/{note['id']}").status_code == 404


def test_team_patch_does_not_require_if_match(client, team_factory):
    team = team_factory(client, "Before")
    resp = client.patch(f"{TEAMS}/{team['id']}", json={"name": "After"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "After"


def test_note_out_shape_unchanged_after_conditional_patch(client, team_factory, note_factory):
    note = new_note(client, team_factory, note_factory, title="t", body="b", author_name="Ann")
    resp = patch_note(client, note["id"], '"1"', title="t2")
    assert resp.status_code == 200, resp.text
    assert set(note) <= set(resp.json())
    assert resp.json()["tags"] == []


def test_concurrent_star_patches_all_succeed_and_each_bumps_version(
    client, team_factory, note_factory
):
    # '*' always matches, so racing writers never get 412 and each bump is counted exactly once
    team = team_factory(client)
    note = note_factory(client, team["id"], title="orig")
    workers = 4
    barrier = threading.Barrier(workers)
    codes = [None] * workers

    def worker(idx):
        local = TestClient(client.app)
        barrier.wait(timeout=10)
        resp = local.patch(
            f"{NOTES}/{note['id']}", headers={"If-Match": "*"}, json={"title": f"s{idx}"}
        )
        codes[idx] = resp.status_code

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert codes == [200] * workers, codes
    assert client.get(f"{NOTES}/{note['id']}").json()["version"] == 1 + workers


def test_star_never_gets_412_even_under_heavy_contention(client, team_factory, note_factory):
    # "If-Match: *" always matches (PLAN 5.7): 16 racing writers must all get 200, and every
    # success must bump the version exactly once (no lost or doubled bump).
    team = team_factory(client)
    workers = 16
    for _ in range(3):
        note = note_factory(client, team["id"], title="orig")
        barrier = threading.Barrier(workers)
        codes = [None] * workers

        def worker(idx, note_id=note["id"], barrier=barrier, codes=codes):
            local = TestClient(client.app)
            barrier.wait(timeout=10)
            resp = local.patch(
                f"{NOTES}/{note_id}", headers={"If-Match": "*"}, json={"title": f"s{idx}"}
            )
            codes[idx] = resp.status_code

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert codes == [200] * workers, codes
        assert client.get(f"{NOTES}/{note['id']}").json()["version"] == 1 + workers


def test_star_responses_describe_their_own_write_under_contention(
    client, team_factory, note_factory
):
    # each 200 must carry the version, title and ETag produced by *that* request: versions are
    # unique across writers (2..N+1) and a writer never sees another writer's title.
    team = team_factory(client)
    workers = 16
    note = note_factory(client, team["id"], title="orig")
    barrier = threading.Barrier(workers)
    results = [None] * workers

    def worker(idx):
        local = TestClient(client.app)
        barrier.wait(timeout=10)
        resp = local.patch(
            f"{NOTES}/{note['id']}", headers={"If-Match": "*"}, json={"title": f"s{idx}"}
        )
        results[idx] = (resp.status_code, resp.json(), resp.headers.get("etag"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(r is not None and r[0] == 200 for r in results), results
    for idx, (_, body, etag) in enumerate(results):
        assert body["title"] == f"s{idx}", f"writer {idx} got another writer's state: {body}"
        assert etag == f'"{body["version"]}"'
    assert sorted(r[1]["version"] for r in results) == list(range(2, 2 + workers))
    stamps = [r[1]["updated_at"] for r in sorted(results, key=lambda r: r[1]["version"])]
    assert all(a < b for a, b in zip(stamps, stamps[1:], strict=False)), stamps
