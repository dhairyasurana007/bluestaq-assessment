"""M5 hidden unit tests: optimistic concurrency with ETag / If-Match on PATCH /notes/{id}.

Every test here must fail on the pre-M5 baseline (where PATCH ignores If-Match). Behavior that
is unchanged by M5 (404/422 paths, ETag on POST/GET, ...) lives in test_m5_regression.py.
"""

import threading
import time
from datetime import datetime, timedelta
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

NOTES = "/api/v1/notes"
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
    assert body["title"] == HTTPStatus(status).phrase, body["title"]
    assert isinstance(body["detail"], str) and body["detail"]
    if instance is not None:
        assert body["instance"] == instance
    return body


def patch_note(client, note_id, if_match=None, **payload):
    headers = {} if if_match is None else {"If-Match": if_match}
    return client.patch(f"{NOTES}/{note_id}", headers=headers, json=payload)


def get_note(client, note_id):
    resp = client.get(f"{NOTES}/{note_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def new_note(client, team_factory, note_factory, **fields):
    team = team_factory(client)
    return note_factory(client, team["id"], **fields)


def bump_to(client, note, version):
    """Advance ``note`` (currently v1) to ``version`` using correct If-Match values."""
    assert note["version"] == 1
    for current in range(1, version):
        resp = patch_note(client, note["id"], f'"{current}"', title=f"step-{current + 1}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == current + 1
    return get_note(client, note["id"])


def assert_untouched(client, before):
    after = get_note(client, before["id"])
    for key in ("version", "title", "body", "updated_at", "created_at", "author_name"):
        assert after[key] == before[key], f"{key} changed: {before[key]!r} -> {after[key]!r}"


# ------------------------------------------------------------------ 428: header missing


def test_patch_without_if_match_is_428_problem_json(client, team_factory, note_factory):
    # criterion: PATCH without If-Match -> 428 problem+json
    note = new_note(client, team_factory, note_factory, title="t", body="b")
    resp = patch_note(client, note["id"], title="new")
    body = assert_problem(resp, 428, instance=f"{NOTES}/{note['id']}")
    assert body["title"] == "Precondition Required"
    assert "type" in body


@pytest.mark.parametrize(
    "payload",
    [{"title": "x"}, {"body": "y"}, {"title": "x", "body": "y"}, {"body": ""}],
    ids=["title", "body", "both", "empty-body"],
)
def test_patch_without_if_match_is_428_for_every_valid_payload(
    client, team_factory, note_factory, payload
):
    # criterion: 428 whenever If-Match is missing, regardless of which fields are patched
    note = new_note(client, team_factory, note_factory, title="t", body="b")
    assert_problem(patch_note(client, note["id"], **payload), 428)


def test_428_leaves_note_untouched(client, team_factory, note_factory):
    # criterion: nothing is changed when If-Match is missing
    note = new_note(client, team_factory, note_factory, title="orig", body="orig body")
    tiny_sleep()
    resp = patch_note(client, note["id"], title="changed", body="changed body")
    assert_problem(resp, 428)
    assert_untouched(client, note)
    assert get_note(client, note["id"])["version"] == 1
    assert client.get(f"{NOTES}/{note['id']}").headers["etag"] == '"1"'


def test_428_does_not_reorder_listing(client, team_factory, note_factory):
    # criterion: a rejected PATCH must not touch updated_at (list order unchanged)
    team = team_factory(client)
    first = note_factory(client, team["id"], title="first")
    tiny_sleep()
    second = note_factory(client, team["id"], title="second")
    assert_problem(patch_note(client, first["id"], title="first edited"), 428)
    resp = client.get(NOTES, params=[("team_id", team["id"])])
    assert [n["id"] for n in resp.json()["items"]] == [second["id"], first["id"]]


# ------------------------------------------------------------------ success path


def test_patch_with_matching_if_match_returns_version_2_and_etag_2(
    client, team_factory, note_factory
):
    # criterion: If-Match "1" on a v1 note -> 200, version 2, ETag "2"
    note = new_note(client, team_factory, note_factory, title="t")
    assert note["version"] == 1
    resp = patch_note(client, note["id"], '"1"', title="t2")
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2
    assert resp.headers["etag"] == '"2"'
    # the old validator is now stale
    assert_problem(patch_note(client, note["id"], '"1"', title="t3"), 412)


def test_successful_patch_response_shape_and_timestamps(client, team_factory, note_factory):
    # criterion: 200 (no Location), ETag matches version, updated_at later, created_at unchanged
    note = new_note(client, team_factory, note_factory, title="t", body="b", author_name="Ann")
    assert_problem(patch_note(client, note["id"], title="no header"), 428)
    tiny_sleep()
    resp = patch_note(client, note["id"], '"1"', body="changed")
    assert resp.status_code == 200, resp.text
    assert "location" not in {k.lower() for k in resp.headers}
    data = resp.json()
    assert resp.headers["etag"] == f'"{data["version"]}"'
    assert data["version"] == 2
    assert data["created_at"] == note["created_at"]
    assert parse_ts(data["updated_at"]) > parse_ts(note["updated_at"])
    assert (data["title"], data["body"], data["author_name"]) == ("t", "changed", "Ann")
    assert data["id"] == note["id"] and data["team_id"] == note["team_id"]


def test_sequential_patches_with_correct_etags_keep_working(client, team_factory, note_factory):
    # criterion: 1 -> 2 -> 3 using the ETag returned by the previous response
    note = new_note(client, team_factory, note_factory, title="v1")
    etag = client.get(f"{NOTES}/{note['id']}").headers["etag"]
    assert etag == '"1"'
    for expected in (2, 3, 4):
        resp = patch_note(client, note["id"], etag, title=f"v{expected}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == expected
        etag = resp.headers["etag"]
        assert etag == f'"{expected}"'
    # replaying any earlier validator now fails
    for stale in ('"1"', '"2"', '"3"'):
        assert_problem(patch_note(client, note["id"], stale, title="late"), 412)
    final = get_note(client, note["id"])
    assert (final["title"], final["version"]) == ("v4", 4)


def test_patch_to_empty_body_with_if_match_bumps_version(client, team_factory, note_factory):
    # criterion: a legal edit with a matching If-Match is applied; replaying it is stale
    note = new_note(client, team_factory, note_factory, title="t", body="something")
    resp = patch_note(client, note["id"], '"1"', body="")
    assert resp.status_code == 200, resp.text
    assert resp.json()["body"] == ""
    assert_problem(patch_note(client, note["id"], '"1"', body="again"), 412)
    assert get_note(client, note["id"])["body"] == ""


# ------------------------------------------------------------------ 412: stale writes


def test_stale_update_second_writer_gets_412(client, team_factory, note_factory):
    # criterion: A and B read v1; A patches "1" -> 200; B patches "1" -> 412 and B is not applied
    note = new_note(client, team_factory, note_factory, title="orig", body="orig body")
    a_read = client.get(f"{NOTES}/{note['id']}")
    b_read = client.get(f"{NOTES}/{note['id']}")
    assert a_read.headers["etag"] == b_read.headers["etag"] == '"1"'

    a = patch_note(client, note["id"], a_read.headers["etag"], title="A title", body="A body")
    assert a.status_code == 200, a.text
    assert a.json()["version"] == 2

    b = patch_note(client, note["id"], b_read.headers["etag"], title="B title", body="B body")
    problem = assert_problem(b, 412, instance=f"{NOTES}/{note['id']}")
    assert problem["title"] == "Precondition Failed"

    current = get_note(client, note["id"])
    assert current["title"] == "A title"
    assert current["body"] == "A body"
    assert current["version"] == 2
    assert client.get(f"{NOTES}/{note['id']}").headers["etag"] == '"2"'


def test_412_detail_mentions_current_version(client, team_factory, note_factory):
    # criterion: detail mentions current version 2
    note = new_note(client, team_factory, note_factory, title="t")
    assert patch_note(client, note["id"], '"1"', title="A").status_code == 200
    body = assert_problem(patch_note(client, note["id"], '"1"', title="B"), 412)
    assert "2" in body["detail"]
    assert "version" in body["detail"].lower()


def test_412_detail_reports_latest_version_after_several_patches(
    client, team_factory, note_factory
):
    # criterion: stale If-Match after several patches; detail names the current version
    note = new_note(client, team_factory, note_factory, title="t")
    bump_to(client, note, 5)
    body = assert_problem(patch_note(client, note["id"], '"2"', title="late"), 412)
    assert "5" in body["detail"]
    assert get_note(client, note["id"])["version"] == 5


def test_stale_update_of_other_field_is_not_merged(client, team_factory, note_factory):
    # criterion: B's change is NOT applied, even if it touches a field A did not change
    note = new_note(client, team_factory, note_factory, title="orig", body="orig body")
    assert patch_note(client, note["id"], '"1"', title="A title").status_code == 200
    assert_problem(patch_note(client, note["id"], '"1"', body="B body"), 412)
    current = get_note(client, note["id"])
    assert current["title"] == "A title"
    assert current["body"] == "orig body"
    assert current["version"] == 2


def test_412_leaves_note_untouched(client, team_factory, note_factory):
    # criterion: 412 leaves version, title, body and updated_at unchanged
    note = new_note(client, team_factory, note_factory, title="orig", body="orig body")
    tiny_sleep()
    assert patch_note(client, note["id"], '"1"', title="A").status_code == 200
    before = get_note(client, note["id"])
    tiny_sleep()
    assert_problem(patch_note(client, note["id"], '"1"', title="B", body="B body"), 412)
    assert_untouched(client, before)


def test_412_does_not_reorder_listing(client, team_factory, note_factory):
    # criterion: a rejected stale PATCH must not touch updated_at (list order unchanged)
    team = team_factory(client)
    first = note_factory(client, team["id"], title="first")
    tiny_sleep()
    second = note_factory(client, team["id"], title="second")
    assert_problem(patch_note(client, first["id"], '"7"', title="stale"), 412)
    resp = client.get(NOTES, params=[("team_id", team["id"])])
    assert [n["id"] for n in resp.json()["items"]] == [second["id"], first["id"]]


def test_stale_after_many_patches_is_rejected_and_current_still_works(
    client, team_factory, note_factory
):
    # criterion: stale If-Match after several patches -> 412; the current one still works
    note = new_note(client, team_factory, note_factory, title="t")
    current = bump_to(client, note, 4)
    for stale in ('"1"', '"2"', '"3"'):
        assert_problem(patch_note(client, note["id"], stale, title="late"), 412)
    assert_untouched(client, current)
    ok = patch_note(client, note["id"], '"4"', title="fresh")
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == 5
    assert ok.headers["etag"] == '"5"'


# ------------------------------------------------------------------ If-Match variants


@pytest.mark.parametrize(
    "header",
    ['W/"2"', '"2"', "2", ' "2" ', '  W/"2"  ', "*", " * "],
    ids=["weak", "strong", "unquoted", "padded", "padded-weak", "star", "padded-star"],
)
def test_if_match_variants_that_are_accepted_for_version_2(
    client, team_factory, note_factory, header
):
    # criterion: W/"2" accepted as version 2; * matches any version; quotes optional; trimmed
    note = new_note(client, team_factory, note_factory, title="t")
    v2 = bump_to(client, note, 2)
    assert_problem(patch_note(client, note["id"], title="missing header"), 428)
    resp = patch_note(client, note["id"], header, title="via variant")
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 3
    assert resp.json()["title"] == "via variant"
    assert resp.headers["etag"] == '"3"'
    assert v2["version"] == 2


@pytest.mark.parametrize("header", ['W/"2"', '"2"', "2"])
def test_accepted_variant_is_consumed_like_any_other_validator(
    client, team_factory, note_factory, header
):
    # criterion: after a variant succeeds the same header is stale (412 naming version 3)
    note = new_note(client, team_factory, note_factory, title="t")
    bump_to(client, note, 2)
    assert patch_note(client, note["id"], header, title="first").status_code == 200
    body = assert_problem(patch_note(client, note["id"], header, title="second"), 412)
    assert "3" in body["detail"]
    assert get_note(client, note["id"])["title"] == "first"


def test_weak_if_match_for_wrong_version_is_412(client, team_factory, note_factory):
    # criterion: W/ prefix does not bypass the version check
    note = new_note(client, team_factory, note_factory, title="t")
    bump_to(client, note, 3)
    assert_problem(patch_note(client, note["id"], 'W/"2"', title="stale"), 412)
    assert get_note(client, note["id"])["version"] == 3


@pytest.mark.parametrize("upto", [1, 2, 6])
def test_if_match_star_matches_any_version_and_bumps_by_one(
    client, team_factory, note_factory, upto
):
    # criterion: * always matches, and the version still goes up by exactly one
    note = new_note(client, team_factory, note_factory, title="t")
    current = bump_to(client, note, upto)
    assert_problem(patch_note(client, note["id"], title="no header"), 428)
    resp = patch_note(client, note["id"], "*", title="star")
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == upto + 1
    assert resp.headers["etag"] == f'"{upto + 1}"'
    assert current["version"] == upto
    assert get_note(client, note["id"])["title"] == "star"


def test_if_match_star_makes_stale_validators_stale(client, team_factory, note_factory):
    # criterion: a '*' write bumps the version, so a previously captured ETag no longer matches
    note = new_note(client, team_factory, note_factory, title="t")
    assert patch_note(client, note["id"], "*", title="star").status_code == 200
    assert_problem(patch_note(client, note["id"], '"1"', title="stale"), 412)
    assert get_note(client, note["id"])["title"] == "star"


@pytest.mark.parametrize(
    "header",
    [
        "abc",
        '"abc"',
        'W/"abc"',
        "W/abc",
        "W/",
        "",
        "   ",
        '""',
        "1.5",
        "1.0",
        "-1",
        "0",
        '"0"',
        "99",
        '"99"',
        "2",
        'W/"99"',
    ],
)
def test_if_match_values_that_never_match_a_v1_note_are_412(
    client, team_factory, note_factory, header
):
    # criterion: malformed, non-integer, zero and future versions -> 412
    note = new_note(client, team_factory, note_factory, title="orig", body="orig body")
    tiny_sleep()
    resp = patch_note(client, note["id"], header, title="should not apply")
    problem = assert_problem(resp, 412, instance=f"{NOTES}/{note['id']}")
    assert problem["title"] == "Precondition Failed"
    assert_untouched(client, note)


@pytest.mark.parametrize("header", ["99", '"99"', "0", '"0"', "2"])
def test_numeric_mismatch_412_detail_names_current_version(
    client, team_factory, note_factory, header
):
    # criterion: future/zero versions are plain mismatches; detail names the current version (1)
    note = new_note(client, team_factory, note_factory, title="t")
    body = assert_problem(patch_note(client, note["id"], header, title="x"), 412)
    assert "1" in body["detail"]
    assert "version" in body["detail"].lower()


def test_if_match_abc_is_412_on_current_note_and_valid_header_still_works_after(
    client, team_factory, note_factory
):
    # criterion: "abc" -> 412 and does not poison the note: the right ETag works afterwards
    note = new_note(client, team_factory, note_factory, title="t")
    assert_problem(patch_note(client, note["id"], '"abc"', title="x"), 412)
    ok = patch_note(client, note["id"], '"1"', title="y")
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == 2


def test_if_match_for_a_different_notes_version_is_checked_per_note(
    client, team_factory, note_factory
):
    # criterion: the version compared is the target note's own version
    team = team_factory(client)
    busy = note_factory(client, team["id"], title="busy")
    quiet = note_factory(client, team["id"], title="quiet")
    bump_to(client, busy, 3)
    assert_problem(patch_note(client, quiet["id"], '"3"', title="wrong"), 412)
    assert patch_note(client, quiet["id"], '"1"', title="right").status_code == 200
    assert get_note(client, busy["id"])["version"] == 3


# ------------------------------------------------------------------ atomicity under concurrency


def _race(app, note_id, header, workers, titles):
    """Fire ``workers`` PATCHes at once through separate TestClients; return status codes."""
    barrier = threading.Barrier(workers)
    results = [None] * workers

    def worker(idx):
        local = TestClient(app)
        barrier.wait(timeout=10)
        resp = local.patch(
            f"{NOTES}/{note_id}", headers={"If-Match": header}, json={"title": titles[idx]}
        )
        results[idx] = resp.status_code

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(r is not None for r in results), results
    return results


def test_two_concurrent_patches_with_same_if_match_one_wins(client, team_factory, note_factory):
    # criterion: atomic conditional update; exactly one 200 and one 412
    team = team_factory(client)
    for round_no in range(5):
        note = note_factory(client, team["id"], title=f"race-{round_no}")
        codes = _race(client.app, note["id"], '"1"', 2, ["left", "right"])
        assert sorted(codes) == [200, 412], codes
        final = get_note(client, note["id"])
        assert final["version"] == 2
        assert final["title"] in {"left", "right"}


def test_many_concurrent_patches_with_same_if_match_exactly_one_wins(
    client, team_factory, note_factory
):
    # criterion: no lost update, no double bump, with 6 racing writers
    team = team_factory(client)
    note = note_factory(client, team["id"], title="orig")
    titles = [f"writer-{i}" for i in range(6)]
    codes = _race(client.app, note["id"], '"1"', 6, titles)
    assert sorted(codes) == [200] + [412] * 5, codes
    final = get_note(client, note["id"])
    assert final["version"] == 2
    assert final["title"] in titles
