"""Static checks for the repository metadata. They do not import Home Assistant."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTEGRATION_DIR = ROOT / "custom_components" / "ev_charge_control"

SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
INTEGRATION_TYPES = {
    "device",
    "entity",
    "hardware",
    "helper",
    "hub",
    "service",
    "system",
    "virtual",
}
IOT_CLASSES = {
    "assumed_state",
    "cloud_polling",
    "cloud_push",
    "local_polling",
    "local_push",
    "calculated",
}
# Required by Home Assistant for custom integrations and by HACS.
REQUIRED_MANIFEST_KEYS = {
    "domain",
    "name",
    "codeowners",
    "dependencies",
    "documentation",
    "integration_type",
    "iot_class",
    "issue_tracker",
    "requirements",
    "version",
}


def _manifest() -> dict:
    return json.loads((INTEGRATION_DIR / "manifest.json").read_text("utf-8"))


def test_manifest_has_required_keys() -> None:
    assert REQUIRED_MANIFEST_KEYS <= _manifest().keys()


def test_domain_matches_directory_name() -> None:
    assert _manifest()["domain"] == INTEGRATION_DIR.name


def test_domain_constant_matches_manifest() -> None:
    const = (INTEGRATION_DIR / "const.py").read_text("utf-8")
    assert f'DOMAIN = "{_manifest()["domain"]}"' in const


def test_version_is_semver() -> None:
    assert SEMVER.match(_manifest()["version"])


def test_type_and_iot_class_are_valid() -> None:
    manifest = _manifest()
    assert manifest["integration_type"] in INTEGRATION_TYPES
    assert manifest["iot_class"] in IOT_CLASSES


def test_config_flow_file_exists_when_enabled() -> None:
    if _manifest().get("config_flow"):
        assert (INTEGRATION_DIR / "config_flow.py").is_file()


def test_hacs_json_is_valid() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text("utf-8"))
    assert hacs["name"]
    assert not hacs.get("content_in_root", False)


def test_brand_icon_exists() -> None:
    assert (INTEGRATION_DIR / "brand" / "icon.png").is_file()
