"""Shared e2e helpers. Import with `from tests.e2e.helpers import make_team`."""

import uuid

from playwright.sync_api import APIRequestContext


def unique_name(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def make_team(api: APIRequestContext) -> dict:
    """Create a team with a unique name (used from M3 onward)."""
    resp = api.post("/api/v1/teams", data={"name": unique_name()})
    assert resp.status == 201, resp.text()
    return resp.json()
