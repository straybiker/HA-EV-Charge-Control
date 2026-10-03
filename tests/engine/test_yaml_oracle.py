"""Parity oracle: render the original YAML variable chain and compare.

This test needs the sibling checkout of straybiker/HA-load-balancer at
../EV_Loadbalancer. It is skipped when that folder is absent (CI), and is
the parity gate when run locally.

It reproduces how Home Assistant evaluates a `variables:` action: each
template is rendered in order, the result is parsed back to a native type
with literal_eval, and it becomes available to the next template.
"""

from __future__ import annotations

import ast
import itertools
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargeMode,
    ChargerSpec,
    ConnectionState,
    Measurements,
    Phase,
    Settings,
    TimerState,
    decide,
)

from .conftest import NOW

jinja2 = pytest.importorskip("jinja2")
yaml = pytest.importorskip("yaml")

YAML_PATH = (
    Path(__file__).resolve().parents[3]
    / "EV_Loadbalancer"
    / "packages"
    / "ev_loadbalancer.yaml"
)
pytestmark = pytest.mark.skipif(
    not YAML_PATH.is_file(), reason="EV_Loadbalancer checkout not present"
)

PHASE_1 = "1 Phase"
PHASE_3 = "3 Phases"
CURRENT_OUTPUT = "number.charger_current"
PHASES_OUTPUT = "select.charger_phases"
TIMER = "timer.ev_load_balancer_phase_switching_timer"
INVALID = ["unavailable", "unknown", None, "none", "None", ""]


# --- Home Assistant template semantics ------------------------------------------


def _parse_result(rendered: str):
    """Parse a rendered template like Home Assistant does."""
    text = rendered.strip()
    try:
        value = ast.literal_eval(text)
    except ValueError, SyntaxError, MemoryError, TypeError:
        return text
    if isinstance(value, str):
        return text
    return value


def _bool_filter(value, default=False):
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


def _has_value(entity_id, db):
    return db.get(entity_id) not in INVALID


class _Oracle:
    """The YAML variable chain, compiled once, rendered against a swappable db."""

    def __init__(self, variables: dict) -> None:
        self.db: dict = {}
        env = jinja2.Environment()
        env.globals["states"] = self._states
        env.globals["state_attr"] = self._state_attr
        env.globals["has_value"] = lambda entity_id: _has_value(entity_id, self.db)
        env.globals["is_state"] = lambda entity_id, state: (
            self.db.get(entity_id) == state
        )
        env.filters["bool"] = _bool_filter
        env.filters["count"] = len
        self.templates = [(name, env.from_string(t)) for name, t in variables.items()]

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
            ctx[name] = _parse_result(template.render(**ctx))
        return ctx


def _load_variables():
    config = yaml.safe_load(YAML_PATH.read_text("utf-8"))
    automation = next(
        a for a in config["automation"] if a["alias"] == "EV Charging Load Balancer"
    )
    for action in automation["actions"]:
        if "variables" in action:
            return action["variables"]
    raise AssertionError("variables action not found")


@pytest.fixture(scope="module")
def oracle() -> _Oracle:
    return _Oracle(_load_variables())


# --- case grid ----------------------------------------------------------------------

MODES = list(ChargeMode)
HOUSEHOLD = [-6000, -1000, -500, -200, 0, 500, 2000, 7000, 9000]
EMS = [  # ems_control, ems_signal_w, ems_as_onoff
    (False, 0.0, False),
    (True, 0.0, False),
    (True, 3000.0, False),
    (True, 3000.0, True),
]
PV_PRIO = [(False, 0), (True, 0), (True, 1000)]  # pv_prioritized, threshold
CAR = [(False, 50), (True, 10), (True, 60), (True, 85)]  # car_aware, soc
PRICE = [0.20, 0.35]
CHARGING = [  # applied_current_a, charger_power_w, applied_phases
    (0.0, 0.0, PHASE_1),
    (10.0, 2070.0, PHASE_1),
    (10.0, 6210.0, PHASE_3),
]
HOLD = [  # commanded phase, timer active
    (PHASE_1, False),
    (PHASE_1, True),
    (PHASE_3, True),
]
SINGLE = [False, True]

# Full product over the mode logic; price, efficiency on 3 phases, a held
# 3-phase charger and single_phase_only are varied in a second, thinner grid.
GRID = list(
    itertools.product(
        MODES,
        HOUSEHOLD,
        EMS,
        PV_PRIO,
        CAR,
        PRICE[:1],
        CHARGING[:2],
        HOLD[:2],
        SINGLE[:1],
    )
) + list(
    itertools.product(
        MODES,
        HOUSEHOLD,
        EMS[:2],
        PV_PRIO,
        CAR,
        PRICE[1:],
        CHARGING[2:],
        HOLD[2:],
        SINGLE,
    )
)


def _build_db(mode, household, ems, pv, car, price, charging, hold, single):
    ems_control, ems_signal, ems_as_onoff = ems
    pv_prioritized, pv_threshold = pv
    car_aware, soc = car
    applied_current, charger_power, applied_phases = charging
    commanded_phase, timer_active = hold
    return {
        "sensor.ev_load_balancer_house": str(int(household)),
        "sensor.ev_load_balancer": {
            "power_limit": 10000,
            "car_aware": car_aware,
            "pv_prioritized": pv_prioritized,
            "pv_prio_threshold": float(pv_threshold),
            "single_phase_only": single,
            "ems_control": ems_control,
            "ems_signal": ems_signal,
            "ems_as_onoff": ems_as_onoff,
            "electricity_price": price,
            "max_cost_rate": 0.30,
            "emergency_soc": 20,
            "comfort_soc": 50,
            "target_soc": 80,
        },
        "sensor.ev_load_balancer.state": str(mode),
        "sensor.ev_load_balancer_charger": {
            "current_input": applied_current,
            "active_power": charger_power,
            "phases_input": applied_phases,
            "phases_output": PHASES_OUTPUT,
            "current_output": CURRENT_OUTPUT,
            "max_current": 16,
            "min_current": 6,
            "default_current": 7,
            "default_phases": 1,
            "nominal_voltage": 230,
            "phase_1_state": PHASE_1,
            "phase_3_state": PHASE_3,
        },
        "sensor.ev_load_balancer_car": {
            "max_current": 16,
            "min_current": 6,
            "battery_capacity_wh": 74000,
            "battery_percentage": soc,
        },
        PHASES_OUTPUT: commanded_phase,
        CURRENT_OUTPUT: "10.0",
        TIMER: "active" if timer_active else "idle",
    }


def _engine_inputs(mode, household, ems, pv, car, price, charging, hold, single):
    ems_control, ems_signal, ems_as_onoff = ems
    pv_prioritized, pv_threshold = pv
    car_aware, soc = car
    applied_current, charger_power, applied_phases = charging
    commanded_phase, timer_active = hold
    settings = Settings(
        mode=mode,
        power_limit_w=10000,
        car_aware=car_aware,
        pv_prioritized=pv_prioritized,
        pv_prio_threshold_w=pv_threshold,
        single_phase_only=single,
        ems_control=ems_control,
        ems_as_onoff=ems_as_onoff,
    )
    m = Measurements(
        household_power_w=household,
        charger_power_w=charger_power,
        applied_current_a=applied_current,
        applied_phases=Phase.THREE if applied_phases == PHASE_3 else Phase.ONE,
        connection=ConnectionState.CONNECTED,
        commanded_phase=Phase.THREE if commanded_phase == PHASE_3 else Phase.ONE,
        commanded_current_a=10.0,
        car_soc=soc,
        electricity_price=price,
        ems_signal_w=ems_signal,
    )
    timers = TimerState(
        phase_switch_until=NOW + timedelta(minutes=1) if timer_active else None
    )
    return settings, m, timers


SPEC = ChargerSpec(max_current_a=16)
CAR_SPEC = CarSpec(battery_capacity_wh=74000)


def _fixed_deviation(settings: Settings, d) -> str | None:
    """Name the fixed defect that explains a deviation from the YAML, if any.

    Each fixed defect in docs/known-defects.md must have an entry here that
    is as narrow as possible. Everything else must match the YAML exactly.
    """
    # D07: 3-Phases Minimum with single phase only is refused.
    if settings.mode == ChargeMode.MIN_3P and settings.single_phase_only:
        return "D07"
    # D05: a Minimum mode no longer adds solar surplus. Only cases with
    # surplus outside an emergency can differ.
    if (
        settings.mode in (ChargeMode.MIN_1P, ChargeMode.MIN_3P)
        and not d.is_emergency
        and d.solar_surplus_w > 0
    ):
        return "D05"
    # D02: the PV bridge is capped by the grid allowance. It only differs
    # from the YAML when that allowance is below the bridge threshold.
    if (
        settings.mode == ChargeMode.LIMITED
        and settings.pv_prioritized
        and d.effective_grid_w < settings.pv_prio_threshold_w
    ):
        return "D02"
    # D12 cannot occur on this grid: every efficiency in CHARGING is >= 0.85.
    return None


def test_engine_matches_yaml_on_grid(oracle):
    mismatches = []
    deviations: dict[str, int] = {}
    for case in GRID:
        ctx = oracle.render(_build_db(*case))
        settings, m, timers = _engine_inputs(*case)
        d = decide(SPEC, CAR_SPEC, settings, m, timers, NOW)
        expected = (
            int(ctx["adjusted_phase_selection"]),
            float(ctx["adjusted_current_limit"]),
        )
        actual = (int(d.phase), float(d.current_a))
        if expected[0] == actual[0] and abs(expected[1] - actual[1]) <= 1e-6:
            continue
        reason = _fixed_deviation(settings, d)
        if reason is None:
            mismatches.append((case, expected, actual))
        else:
            deviations[reason] = deviations.get(reason, 0) + 1
    assert not mismatches, (
        f"{len(mismatches)}/{len(GRID)} mismatches, first: {mismatches[:5]}"
    )
    # The fix must actually change something on the grid, or the filter is
    # hiding nothing and should be removed.
    for fix in ("D02", "D05", "D07"):
        assert deviations.get(fix, 0) > 0, deviations


def test_grid_is_large_enough():
    assert len(GRID) > 400


def test_oracle_reproduces_golden_values(oracle):
    """Sanity check of the oracle itself against two known template results."""
    fast = oracle.render(_build_db(*_case(ChargeMode.FAST, 500)))
    solar = oracle.render(_build_db(*_case(ChargeMode.SOLAR, -6000)))
    assert (fast["adjusted_phase_selection"], fast["adjusted_current_limit"]) == (
        3,
        13.8,
    )
    assert (solar["adjusted_phase_selection"], solar["adjusted_current_limit"]) == (
        3,
        8.7,
    )


def _case(mode, household):
    return (
        mode,
        household,
        EMS[0],
        PV_PRIO[0],
        CAR[0],
        0.20,
        CHARGING[0],
        HOLD[0],
        False,
    )


def test_settings_defaults_match_yaml_defaults():
    # Guard: Settings defaults equal the | int(20/50/80) fallbacks in the YAML.
    s = replace(Settings(mode=ChargeMode.OFF, power_limit_w=1))
    assert (s.emergency_soc, s.comfort_soc, s.target_soc, s.max_cost_rate) == (
        20,
        50,
        80,
        0.30,
    )
