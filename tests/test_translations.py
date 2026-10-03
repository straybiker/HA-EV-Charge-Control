"""Translation files match the code. Runs without Home Assistant's harness."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from custom_components.ev_charge_control.engine import ChargeMode, Reason

ROOT = Path(__file__).parent.parent / "custom_components" / "ev_charge_control"
STRINGS = json.loads((ROOT / "strings.json").read_text("utf-8"))
LANGUAGES = {
    p.stem: json.loads(p.read_text("utf-8"))
    for p in sorted((ROOT / "translations").glob("*.json"))
}


def _keys(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _keys(v, f"{prefix}.{k}" if prefix else k)
    else:
        yield prefix


def test_english_equals_strings():
    assert LANGUAGES["en"] == STRINGS


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_every_language_has_every_key(language):
    assert set(_keys(LANGUAGES[language])) == set(_keys(STRINGS))


def test_decision_states_match_reasons():
    states = STRINGS["entity"]["sensor"]["decision"]["state"]
    assert set(states) == {r.value for r in Reason}


def test_mode_states_match_charge_modes():
    states = STRINGS["entity"]["select"]["charge_mode"]["state"]
    assert set(states) == {m.value for m in ChargeMode}


def test_every_flow_error_has_text():
    source = (ROOT / "config_flow.py").read_text("utf-8")
    raised = set(re.findall(r'SchemaFlowError\("(\w+)"\)', source))
    assert raised <= set(STRINGS["config"]["error"])
    assert raised <= set(STRINGS["options"]["error"])


def test_every_exception_has_text():
    source = "".join(p.read_text("utf-8") for p in ROOT.glob("*.py"))
    raised = set(
        re.findall(
            r'ServiceValidationError\(\s*translation_domain=DOMAIN,\s*translation_key="(\w+)"',
            source,
        )
    )
    assert raised  # the pattern still finds the raises
    assert raised <= set(STRINGS["exceptions"])
