"""M2 regression criteria: M0 render.yaml settings that must stay unchanged."""

from pathlib import Path

import pytest
import yaml

RENDER_YAML = Path(__file__).resolve().parents[2] / "render.yaml"


@pytest.fixture(scope="module")
def service():
    data = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    return data["services"][0]


def test_type_is_web(service):
    assert service["type"] == "web"


def test_runtime_is_python(service):
    assert service["runtime"] == "python"


def test_plan_is_free(service):
    assert service["plan"] == "free"


def test_health_check_path(service):
    assert service["healthCheckPath"] == "/health"


def test_build_command_installs_requirements(service):
    cmd = service["buildCommand"]
    assert "pip install" in cmd
    assert "-r requirements.txt" in cmd


def test_start_command_runs_uvicorn_app(service):
    assert "uvicorn app.main:app" in service["startCommand"]


def test_start_command_binds_all_interfaces(service):
    assert "--host 0.0.0.0" in service["startCommand"]


def test_start_command_uses_port_env(service):
    assert "--port $PORT" in service["startCommand"]


def test_branch_is_main(service):
    assert service["branch"] == "main"


def test_python_version_and_database_env_vars_present(service):
    envs = {e["key"]: e.get("value") for e in service["envVars"]}
    assert "PYTHON_VERSION" in envs
    assert "DATABASE_URL" in envs
