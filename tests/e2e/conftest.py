"""E2E harness: black-box HTTP tests via Playwright's APIRequestContext (no browser).

If E2E_BASE_URL is set, tests run against that remote target. Otherwise a real uvicorn
process is started on a free port with a throwaway SQLite database.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import APIRequestContext, sync_playwright

from tests.e2e.helpers import make_team  # noqa: F401  (re-exported for convenience)

ROOT = Path(__file__).resolve().parents[2]
SERVER_LOG = Path(__file__).resolve().parent / ".server.log"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(url: str, proc: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn exited early with code {proc.returncode}; see {SERVER_LOG}"
            )
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become healthy within {timeout}s; see {SERVER_LOG}")


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    remote = os.environ.get("E2E_BASE_URL")
    if remote:
        yield remote.rstrip("/")
        return

    with tempfile.TemporaryDirectory(prefix="notes-e2e-") as tmp:
        env = os.environ.copy()
        env.pop("RENDER_GIT_COMMIT", None)
        env["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'e2e.db').as_posix()}"

        if (ROOT / "alembic.ini").exists():
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT,
                env=env,
                check=True,
            )

        port = _free_port()
        url = f"http://127.0.0.1:{port}"
        with SERVER_LOG.open("wb") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_for_health(url, proc)
                yield url
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


@pytest.fixture(scope="session")
def api(base_url: str) -> Iterator[APIRequestContext]:
    with sync_playwright() as p:
        ctx = p.request.new_context(base_url=base_url)
        yield ctx
        ctx.dispose()
