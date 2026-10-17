"""M7 regression tests: render.yaml deploy configuration."""

from pathlib import Path

import yaml

RENDER_YAML = Path(__file__).resolve().parents[2] / "render.yaml"
START_COMMAND = (
    "alembic upgrade head && python scripts/seed.py --if-empty "
    "&& uvicorn app.main:app --host 0.0.0.0 --port $PORT"
)


def load_service():
    data = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    assert len(data["services"]) == 1
    return data["services"][0]


def test_render_has_exactly_one_service():
    data = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    assert len(data["services"]) == 1


def test_render_start_command_migrates_seeds_then_serves():
    assert load_service()["startCommand"] == START_COMMAND


def test_render_env_vars_include_seed_flag_python_and_database_url():
    env = {e["key"]: e.get("value") for e in load_service()["envVars"]}
    assert env["SEED_DEMO_DATA"] == "true"
    assert "PYTHON_VERSION" in env
    assert "DATABASE_URL" in env


def test_render_auto_deploys_after_checks_pass():
    assert load_service()["autoDeployTrigger"] == "checksPass"
