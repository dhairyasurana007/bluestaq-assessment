"""M2 e2e: M2 only changes render.yaml (deploy gating), so the only HTTP-visible check is
a /health regression."""

from playwright.sync_api import APIRequestContext


def test_health_still_ok(api: APIRequestContext):
    resp = api.get("/health")
    assert resp.status == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["commit"], str) and body["commit"]
