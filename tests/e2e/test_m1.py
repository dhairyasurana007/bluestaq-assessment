"""M1 e2e: scaffold behavior visible over HTTP (health, docs, OpenAPI, unknown paths)."""

import os

from playwright.sync_api import APIRequestContext


def test_health_ok(api: APIRequestContext):
    resp = api.get("/health")
    assert resp.status == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["commit"], str) and body["commit"]
    assert set(body) == {"status", "commit"}


def test_health_commit_is_local_for_local_server(api: APIRequestContext):
    if os.environ.get("E2E_BASE_URL"):
        return  # remote targets report their deployed commit
    assert api.get("/health").json()["commit"] == "local"


def test_docs_page(api: APIRequestContext):
    resp = api.get("/docs")
    assert resp.status == 200
    assert "text/html" in resp.headers["content-type"]


def test_openapi_title_and_health_route(api: APIRequestContext):
    resp = api.get("/openapi.json")
    assert resp.status == 200
    spec = resp.json()
    assert spec["info"]["title"] == "Team Notes API"
    assert "/health" in spec["paths"]


def test_unknown_path_is_404(api: APIRequestContext):
    assert api.get("/definitely-not-a-route").status == 404
    assert api.get("/api/v1/definitely-not-a-route").status == 404
