"""M3 regression criteria: /health is unchanged (may pass on the pre-task baseline)."""


def test_health_ok_and_local_commit(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "commit": "local"}


def test_health_reads_commit_at_request_time(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    assert client.get("/health").json() == {"status": "ok", "commit": "abc123"}
    monkeypatch.setenv("RENDER_GIT_COMMIT", "def456")
    assert client.get("/health").json()["commit"] == "def456"


def test_health_is_not_under_api_prefix(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 404
