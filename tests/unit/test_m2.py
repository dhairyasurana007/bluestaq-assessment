"""M2 acceptance: render.yaml gates Render auto-deploys on passing CI checks."""

from pathlib import Path

import pytest
import yaml

RENDER_YAML = Path(__file__).resolve().parents[2] / "render.yaml"


@pytest.fixture(scope="module")
def doc():
    data = yaml.safe_load(RENDER_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "render.yaml must be a YAML mapping"
    return data


@pytest.fixture
def service(doc):
    services = doc.get("services")
    assert isinstance(services, list), "render.yaml needs a services list"
    assert len(services) == 1, f"expected exactly one service, got {len(services)}"
    svc = services[0]
    assert isinstance(svc, dict)
    return svc


def test_service_declares_auto_deploy_trigger(service):
    assert "autoDeployTrigger" in service, "autoDeployTrigger missing from service"


def test_auto_deploy_trigger_is_checks_pass(service):
    assert service.get("autoDeployTrigger") == "checksPass", (
        "autoDeployTrigger missing or not 'checksPass'"
    )


def test_auto_deploy_trigger_is_exact_string(service):
    value = service.get("autoDeployTrigger")
    assert isinstance(value, str), "autoDeployTrigger missing or not a string"
    assert value == "checksPass"
    assert value == value.strip()


def test_auto_deploy_trigger_not_a_weaker_mode(service):
    value = service.get("autoDeployTrigger")
    assert value is not None, "autoDeployTrigger missing"
    assert value not in ("commit", "off", "Commit", "Off", "checkspass", "ChecksPass")
    assert value is not True
    assert value is not False


def test_exactly_one_service_with_trigger_set(doc):
    services = doc.get("services")
    assert isinstance(services, list)
    assert len(services) == 1
    assert services[0].get("autoDeployTrigger") == "checksPass", (
        "autoDeployTrigger missing from the only service"
    )


def test_trigger_sits_at_service_level_not_top_level(doc):
    assert "autoDeployTrigger" not in doc, "trigger must not be a top-level key"
    services = doc["services"]
    assert len(services) == 1
    assert "autoDeployTrigger" in services[0], "autoDeployTrigger missing from service"


def test_trigger_not_smuggled_into_env_vars(service):
    assert "autoDeployTrigger" in service, "autoDeployTrigger missing from service"
    keys = [e.get("key") for e in service.get("envVars", [])]
    assert "autoDeployTrigger" not in keys


def test_trigger_present_in_raw_file_text(doc):
    text = RENDER_YAML.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines()]
    assert "autoDeployTrigger: checksPass" in lines, "autoDeployTrigger: checksPass line missing"


def test_trigger_defined_exactly_once(service):
    text = RENDER_YAML.read_text(encoding="utf-8")
    assert text.count("autoDeployTrigger") == 1, "autoDeployTrigger missing or duplicated"
    assert service.get("autoDeployTrigger") == "checksPass"


def test_branch_main_kept_with_trigger(service):
    assert service.get("branch") == "main"
    assert service.get("autoDeployTrigger") == "checksPass", (
        "autoDeployTrigger missing alongside branch: main"
    )


def test_legacy_auto_deploy_flag_not_enabled_alongside_trigger(service):
    assert service.get("autoDeployTrigger") == "checksPass", "autoDeployTrigger missing"
    assert service.get("autoDeploy") is not True
