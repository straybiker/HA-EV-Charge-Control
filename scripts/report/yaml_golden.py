"""What the EV Load Balancer YAML package decides for a golden case.

Renders the package's real automation variables (packages/ev_loadbalancer.yaml
in a sibling checkout of straybiker/HA-load-balancer) with Jinja, as Home
Assistant evaluates a `variables:` action. The package's own test file is not
used: its copy of the template has drifted (Comfort and emergency ignore
car_aware there).
"""

from __future__ import annotations

import ast
from pathlib import Path

import jinja2
import yaml

YAML_PATH = (
    Path(__file__).resolve().parents[3]
    / "EV_Loadbalancer"
    / "packages"
    / "ev_loadbalancer.yaml"
)
_INVALID = ["unavailable", "unknown", None, "none", "None", ""]
_PHASE_1, _PHASE_3 = "1 Phase", "3 Phases"
_CURRENT_OUTPUT, _PHASES_OUTPUT = "number.charger_current", "select.charger_phases"

# Engine mode value -> YAML mode label.
MODE_LABEL = {
    "off": "Off",
    "min_1p": "1-Phase Minimum",
    "min_3p": "3-Phases Minimum",
    "limited": "Limited",
    "fast": "Fast",
    "solar": "Solar",
    "comfort": "Comfort",
}


def available() -> bool:
    return YAML_PATH.is_file()


def _parse(rendered: str):
    """Parse a rendered template like Home Assistant does."""
    text = rendered.strip()
    try:
        value = ast.literal_eval(text)
    except ValueError, SyntaxError, MemoryError, TypeError:
        return text
    return text if isinstance(value, str) else value


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ("true", "on", "yes", "1"):
            return True
        if value.lower() in ("false", "off", "no", "0"):
            return False
    return bool(value)


class _Oracle:
    """The package's variable chain, compiled once."""

    def __init__(self) -> None:
        config = yaml.safe_load(YAML_PATH.read_text("utf-8"))
        automation = next(
            a for a in config["automation"] if a["alias"] == "EV Charging Load Balancer"
        )
        variables = next(
            a["variables"] for a in automation["actions"] if "variables" in a
        )
        self.db: dict = {}
        env = jinja2.Environment()
        env.globals["states"] = self._states
        env.globals["state_attr"] = self._state_attr
        env.globals["has_value"] = lambda e: self.db.get(e) not in _INVALID
        env.globals["is_state"] = lambda e, s: self.db.get(e) == s
        env.filters["bool"] = _bool
        env.filters["count"] = len
        self.templates = [(n, env.from_string(t)) for n, t in variables.items()]

    def _states(self, entity_id):
        value = self.db.get(entity_id)
        return (
            value if not isinstance(value, dict) else self.db.get(f"{entity_id}.state")
        )

    def _state_attr(self, entity_id, attr):
        attrs = self.db.get(entity_id)
        return attrs.get(attr) if isinstance(attrs, dict) else None

    def render(self, db: dict) -> dict:
        self.db = db
        ctx: dict = {}
        for name, template in self.templates:
            ctx[name] = _parse(template.render(**ctx))
        return ctx


_ORACLE: _Oracle | None = None


def yaml_result(
    mode: str,
    house_w: float,
    power_limit_w: float,
    *,
    car_aware: bool = False,
    soc: float = 50,
    ems_control: bool = False,
    ems_signal_w: float | None = None,
    solar_when_ems_blocks: bool = False,
    price: float = 0.20,
) -> tuple[int, float]:
    """(phases, amps) the YAML package would set.

    The engine's "solar when EMS blocks" is the YAML's pv_prioritized. The
    YAML has no bridge in Solar mode, so the engine's bridge has no input here.
    """
    global _ORACLE
    _ORACLE = _ORACLE or _Oracle()
    db = {
        "sensor.ev_load_balancer_house": str(int(house_w)),
        "sensor.ev_load_balancer": {
            "power_limit": power_limit_w,
            "car_aware": car_aware,
            "pv_prioritized": solar_when_ems_blocks,
            "pv_prio_threshold": 0.0,
            "single_phase_only": False,
            "ems_control": ems_control,
            "ems_signal": ems_signal_w or 0.0,
            "ems_as_onoff": False,
            "electricity_price": price,
            "max_cost_rate": 0.30,
            "emergency_soc": 20,
            "comfort_soc": 50,
            "target_soc": 80,
        },
        "sensor.ev_load_balancer.state": MODE_LABEL[mode],
        "sensor.ev_load_balancer_charger": {
            "current_input": 0.0,
            "active_power": 0.0,
            "phases_input": _PHASE_1,
            "phases_output": _PHASES_OUTPUT,
            "current_output": _CURRENT_OUTPUT,
            "max_current": 16,
            "min_current": 6,
            "default_current": 7,
            "default_phases": 1,
            "nominal_voltage": 230,
            "phase_1_state": _PHASE_1,
            "phase_3_state": _PHASE_3,
        },
        "sensor.ev_load_balancer_car": {
            "max_current": 16,
            "min_current": 6,
            "battery_capacity_wh": 74000,
            "battery_percentage": soc,
        },
        _PHASES_OUTPUT: _PHASE_1,
        _CURRENT_OUTPUT: "0.0",
        "timer.ev_load_balancer_phase_switching_timer": "idle",
    }
    ctx = _ORACLE.render(db)
    return int(ctx["adjusted_phase_selection"]), float(ctx["adjusted_current_limit"])
