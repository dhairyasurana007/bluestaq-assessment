"""M5 e2e: optimistic concurrency with ETag and If-Match on PATCH /notes/{id}."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from playwright.sync_api import APIRequestContext

from tests.e2e.helpers import make_team
from tests.e2e.test_m4 import _ts, assert_problem, make_note


def patch(api: APIRequestContext, note_id: str, data: dict, if_match: str | None = None):
    headers = {} if if_match is None else {"If-Match": if_match}
    return api.patch(f"/api/v1/notes/{note_id}", data=data, headers=headers)


def get_note(api: APIRequestContext, note_id: str):
    resp = api.get(f"/api/v1/notes/{note_id}")
    assert resp.status == 200, resp.text()
    return resp


def new_note(api: APIRequestContext, **fields) -> dict:
    return make_note(api, make_team(api)["id"], **fields)


def test_patch_without_if_match_is_428_and_changes_nothing(api: APIRequestContext):
    note = new_note(api, body="original")
    body = assert_problem(patch(api, note["id"], {"body": "sneaky"}), 428)
    assert body["title"] == "Precondition Required"
    assert body["instance"] == f"/api/v1/notes/{note['id']}"
    assert "If-Match" in body["detail"]
    assert get_note(api, note["id"]).json() == note


def test_etag_on_create_and_get_matches_version(api: APIRequestContext):
    team = make_team(api)
    resp = api.post(f"/api/v1/teams/{team['id']}/notes", data={"title": "etag"})
    assert resp.status == 201
    assert resp.headers["etag"] == '"1"'
    note = resp.json()
    assert get_note(api, note["id"]).headers["etag"] == '"1"'


def test_patch_with_matching_if_match_bumps_version_and_etag(api: APIRequestContext):
    note = new_note(api, body="before")
    assert note["version"] == 1
    resp = patch(api, note["id"], {"body": "after"}, '"1"')
    assert resp.status == 200, resp.text()
    updated = resp.json()
    assert updated["version"] == 2
    assert updated["body"] == "after"
    assert updated["title"] == note["title"]
    assert resp.headers["etag"] == '"2"'
    fetched = get_note(api, note["id"])
    assert fetched.headers["etag"] == '"2"'
    assert fetched.json() == updated


def test_chained_patches_use_each_responses_etag(api: APIRequestContext):
    note = new_note(api)
    etag = get_note(api, note["id"]).headers["etag"]
    for expected in (2, 3, 4):
        resp = patch(api, note["id"], {"body": f"edit {expected}"}, etag)
        assert resp.status == 200, resp.text()
        assert resp.json()["version"] == expected
        etag = resp.headers["etag"]
        assert etag == f'"{expected}"'


def test_stale_update_is_412_and_not_applied(api: APIRequestContext):
    note = new_note(api, body="start")
    # A and B both read version 1.
    etag_a = get_note(api, note["id"]).headers["etag"]
    etag_b = get_note(api, note["id"]).headers["etag"]
    assert etag_a == etag_b == '"1"'

    resp_a = patch(api, note["id"], {"title": "A title", "body": "A body"}, etag_a)
    assert resp_a.status == 200, resp_a.text()
    assert resp_a.json()["version"] == 2

    resp_b = patch(api, note["id"], {"title": "B title", "body": "B body"}, etag_b)
    body = assert_problem(resp_b, 412)
    assert body["title"] == "Precondition Failed"
    assert body["instance"] == f"/api/v1/notes/{note['id']}"
    assert "current version 2" in body["detail"]
    assert "modified by someone else" in body["detail"]

    final = get_note(api, note["id"])
    assert final.json() == resp_a.json()
    assert final.json()["title"] == "A title"
    assert final.json()["body"] == "A body"
    assert final.headers["etag"] == '"2"'


def test_stale_update_can_retry_with_refetched_etag(api: APIRequestContext):
    note = new_note(api)
    assert patch(api, note["id"], {"body": "A"}, '"1"').status == 200
    assert patch(api, note["id"], {"body": "B"}, '"1"').status == 412
    fresh = get_note(api, note["id"])
    resp = patch(api, note["id"], {"body": "B"}, fresh.headers["etag"])
    assert resp.status == 200
    assert resp.json()["version"] == 3
    assert resp.json()["body"] == "B"


def test_future_version_if_match_is_412(api: APIRequestContext):
    note = new_note(api)
    body = assert_problem(patch(api, note["id"], {"body": "x"}, '"2"'), 412)
    assert "current version 1" in body["detail"]
    assert get_note(api, note["id"]).json() == note


@pytest.mark.parametrize("header", ['W/"2"', "W/2", '  W/"2"  '])
def test_weak_etag_and_whitespace_accepted_as_version_2(api: APIRequestContext, header: str):
    note = new_note(api)
    assert patch(api, note["id"], {"body": "v2"}, '"1"').status == 200
    resp = patch(api, note["id"], {"body": "v3"}, header)
    assert resp.status == 200, resp.text()
    assert resp.json()["version"] == 3
    assert resp.headers["etag"] == '"3"'


@pytest.mark.parametrize("header", ["1", " 1 ", '"1"', 'W/"1"'])
def test_unquoted_and_quoted_integer_forms_parse(api: APIRequestContext, header: str):
    note = new_note(api)
    resp = patch(api, note["id"], {"body": "ok"}, header)
    assert resp.status == 200, resp.text()
    assert resp.json()["version"] == 2


def test_star_always_matches_and_still_bumps_version(api: APIRequestContext):
    note = new_note(api)
    first = patch(api, note["id"], {"body": "one"}, "*")
    assert first.status == 200, first.text()
    assert first.json()["version"] == 2
    assert first.headers["etag"] == '"2"'
    second = patch(api, note["id"], {"body": "two"}, " * ")
    assert second.status == 200, second.text()
    assert second.json()["version"] == 3
    assert second.headers["etag"] == '"3"'
    assert get_note(api, note["id"]).json()["body"] == "two"


@pytest.mark.parametrize(
    "header",
    ['"abc"', "abc", "", "   ", '""', "W/", '"1", "2"', "1,2", "-1", "1.5", '"1', "W/*", "99" * 20],
)
def test_malformed_if_match_is_412_and_changes_nothing(api: APIRequestContext, header: str):
    note = new_note(api, body="stay")
    body = assert_problem(patch(api, note["id"], {"body": "nope"}, header), 412)
    assert body["title"] == "Precondition Failed"
    assert get_note(api, note["id"]).json() == note


def test_if_match_zero_is_412(api: APIRequestContext):
    note = new_note(api)
    assert_problem(patch(api, note["id"], {"body": "x"}, '"0"'), 412)


def test_unknown_note_with_if_match_is_404(api: APIRequestContext):
    assert_problem(patch(api, str(uuid.uuid4()), {"body": "x"}, '"1"'), 404)
    assert_problem(patch(api, str(uuid.uuid4()), {"body": "x"}, "*"), 404)


@pytest.mark.parametrize(
    "payload",
    [{}, {"author_name": "Mallory"}, {"color": "red"}, {"title": ""}, {"body": None}],
)
def test_invalid_body_is_still_422_with_valid_if_match(api: APIRequestContext, payload: dict):
    note = new_note(api, author_name="Ada")
    assert_problem(patch(api, note["id"], payload, '"1"'), 422)
    assert get_note(api, note["id"]).json() == note


def test_only_the_patched_note_changes(api: APIRequestContext):
    team = make_team(api)
    target = make_note(api, team["id"], body="t")
    other = make_note(api, team["id"], body="o")
    assert patch(api, target["id"], {"body": "t2"}, '"1"').status == 200
    assert get_note(api, other["id"]).json() == other
    # The other note's version is independent: its own "1" still works.
    assert patch(api, other["id"], {"body": "o2"}, '"1"').status == 200


def test_star_never_gets_412_under_contention(api: APIRequestContext, base_url: str):
    note = new_note(api)
    writers = 16
    start = threading.Barrier(writers)

    def one(i: int) -> int:
        # Playwright's sync API is not thread-safe, so the racing writers use plain httpx.
        start.wait()
        resp = httpx.patch(
            f"{base_url}/api/v1/notes/{note['id']}",
            json={"body": f"writer {i}"},
            headers={"If-Match": "*"},
            timeout=30,
        )
        return resp.status_code

    with ThreadPoolExecutor(max_workers=writers) as pool:
        statuses = list(pool.map(one, range(writers)))
    assert statuses == [200] * writers
    final = get_note(api, note["id"]).json()
    assert final["version"] == 1 + writers
    assert final["body"].startswith("writer ")


def test_star_responses_describe_their_own_write_under_contention(
    api: APIRequestContext, base_url: str
):
    note = new_note(api)
    writers = 16
    start = threading.Barrier(writers)

    def one(i: int) -> tuple[int, dict, str | None]:
        start.wait()
        resp = httpx.patch(
            f"{base_url}/api/v1/notes/{note['id']}",
            json={"title": f"writer-{i}"},
            headers={"If-Match": "*"},
            timeout=30,
        )
        return resp.status_code, resp.json(), resp.headers.get("etag")

    with ThreadPoolExecutor(max_workers=writers) as pool:
        results = list(pool.map(one, range(writers)))

    assert [status for status, _, _ in results] == [200] * writers
    for i, (_, body, etag) in enumerate(results):
        # Each response describes the caller's own write, never another writer's.
        assert body["title"] == f"writer-{i}"
        assert etag == f'"{body["version"]}"'
    versions = [body["version"] for _, body, _ in results]
    assert sorted(versions) == list(range(2, writers + 2))
    ordered = sorted((body for _, body, _ in results), key=lambda b: b["version"])
    stamps = [_ts(b["updated_at"]) for b in ordered]
    assert stamps == sorted(set(stamps)), "updated_at must strictly increase with version"
    final = get_note(api, note["id"]).json()
    assert final == ordered[-1]
