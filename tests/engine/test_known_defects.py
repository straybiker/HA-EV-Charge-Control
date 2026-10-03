"""Intended behaviour for the defects in docs/known-defects.md.

A defect kept for parity has a test that asserts the fix and is marked
xfail(strict=True). When a fix is approved and implemented, remove its
marker and update docs/known-defects.md. Fixed defects keep their tests
here as normal tests. Accepted defects (D01, D03, D04, D06, D08, D13) are the
designed behaviour and are covered in test_modes.py.

Not testable in the engine, because its typed inputs make them unreachable
or they live in the Home Assistant adapter: D09 (helper first-start
defaults), D10 (silent aborts on `| int`), D14 (string "true" from the
gate template), D17 (unknown mode), D18 (max_current source), D19
(`max_exceeded: silent`).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargeMode,
    Decision,
    Phase,
    Reason,
    filter_setpoint,
)
from custom_components.ev_charge_control.engine.balancer import EFFICIENCY_FLOOR

from .conftest import CAR, MEASUREMENTS, SETTINGS, SPEC

A = pytest.approx
parity = pytest.mark.xfail(strict=True, reason="kept for parity with the YAML")


# --- D02 fixed: the PV bridge is grid power and obeys the gates --------------

PV = {"pv_prioritized": True, "pv_prio_threshold_w": 1000}
PV_EMS = {**PV, "ems_control": True}


def test_d02_pv_bridge_respects_closed_price_gate(run_case):
    # 400 W export, bridge blocked: 400 W is below the 1380 W minimum.
    d = run_case(
        ChargeMode.LIMITED, -400, settings=PV, measurements={"electricity_price": 0.5}
    )
    assert d.solar_surplus_w == 400
    assert d.current_a == 0


def test_d02_closed_price_gate_still_charges_on_solar(run_case):
    d = run_case(
        ChargeMode.LIMITED, -2000, settings=PV, measurements={"electricity_price": 0.5}
    )
    assert d.current_a == A(8.7, abs=0.05)


def test_d02_pv_bridge_respects_ems_zero(run_case):
    d = run_case(
        ChargeMode.LIMITED, -400, settings=PV_EMS, measurements={"ems_signal_w": 0}
    )
    assert d.solar_surplus_w == 400
    assert d.current_a == 0


def test_d02_ems_zero_with_pv_priority_charges_on_solar(run_case):
    d = run_case(
        ChargeMode.LIMITED, -2000, settings=PV_EMS, measurements={"ems_signal_w": 0}
    )
    assert d.current_a == A(8.7, abs=0.05)


def test_d02_pv_bridge_is_capped_by_ems_budget(run_case):
    # 1000 W export + min(1000 W bridge, 500 W budget) = 1500 W.
    d = run_case(
        ChargeMode.LIMITED, -1000, settings=PV_EMS, measurements={"ems_signal_w": 500}
    )
    assert d.solar_surplus_w == 1500
    assert d.current_a == A(6.5, abs=0.05)


def test_d02_pv_bridge_unchanged_when_gates_open(run_case):
    d = run_case(ChargeMode.LIMITED, -400, settings=PV)
    assert d.solar_surplus_w == 1400


def test_d02_without_pv_priority_ems_zero_stops_even_with_sun(run_case):
    ems = {"ems_control": True, "pv_prioritized": False}
    d = run_case(
        ChargeMode.LIMITED, -6000, settings=ems, measurements={"ems_signal_w": 0}
    )
    assert d.current_a == 0


def test_d02_without_pv_priority_ems_budget_shapes_grid(run_case):
    # 1000 W export + 3000 W budget = 4000 W, 1 phase, capped at 16 A.
    ems = {"ems_control": True, "pv_prioritized": False}
    d = run_case(
        ChargeMode.LIMITED, -1000, settings=ems, measurements={"ems_signal_w": 3000}
    )
    assert d.effective_grid_w == 3000
    assert (d.phase, d.current_a) == (Phase.ONE, 16.0)


# --- D05 fixed: a Minimum mode takes the minimum only ---------------------------


@pytest.mark.parametrize(
    ("mode", "phase"),
    [(ChargeMode.MIN_1P, Phase.ONE), (ChargeMode.MIN_3P, Phase.THREE)],
)
def test_d05_minimum_modes_ignore_solar_surplus(run_case, mode, phase):
    d = run_case(mode, -6000)
    assert (d.phase, d.current_a) == (phase, 6.0)


def test_d05_minimum_runs_on_solar_when_grid_is_blocked(run_case):
    # Price too high: no grid, but 2000 W export covers the 1380 W minimum.
    d = run_case(ChargeMode.MIN_1P, -2000, measurements={"electricity_price": 0.5})
    assert d.raw_target_w == A(1380)
    assert d.current_a == 6.0


def test_d05_minimum_stops_when_solar_alone_is_too_small(run_case):
    d = run_case(ChargeMode.MIN_1P, -800, measurements={"electricity_price": 0.5})
    assert d.current_a == 0


def test_d05_minimum_tops_up_ems_budget_with_solar(run_case):
    # 500 W budget + 1000 W export = 1500 W available; the mode takes 1380 W.
    d = run_case(
        ChargeMode.MIN_1P,
        -1000,
        settings={"ems_control": True},
        measurements={"ems_signal_w": 500},
    )
    assert d.raw_target_w == A(1380)
    assert d.current_a == 6.0


def test_d05_emergency_still_overrides_minimum(run_case):
    d = run_case(
        ChargeMode.MIN_1P,
        -2000,
        settings={"car_aware": True},
        measurements={"car_soc": 10},
    )
    assert d.current_a == 16.0


# --- D07 fixed: 3-Phases Minimum with single phase only is refused --------------


def test_d07_3p_minimum_with_single_phase_only_is_refused(run_case):
    d = run_case(ChargeMode.MIN_3P, 500, settings={"single_phase_only": True})
    assert d.reason == Reason.REFUSED
    assert d.should_write
    assert (d.phase, d.current_a) == (Phase.ONE, 0.0)


def test_d07_refusal_ignores_solar_surplus(run_case):
    d = run_case(ChargeMode.MIN_3P, -6000, settings={"single_phase_only": True})
    assert (d.phase, d.current_a) == (Phase.ONE, 0.0)


# --- kept for parity (continued) --------------------------------------------------


@parity
def test_d11_failsafe_keeps_current_phase(run_case):
    d = run_case(ChargeMode.FAST, None, measurements={"commanded_phase": Phase.THREE})
    assert d.phase == Phase.THREE


# --- D12 fixed: efficiency has a floor ------------------------------------------


def test_d12_efficiency_has_a_floor(run_case):
    # 1001 W at 16 A on 3 phases: raw eff 0.09 would inflate the target 11x.
    m = {
        "applied_current_a": 16.0,
        "applied_phases": Phase.THREE,
        "charger_power_w": 1001,
    }
    d = run_case(ChargeMode.LIMITED, 5000, measurements=m)
    assert d.efficiency == EFFICIENCY_FLOOR
    assert d.current_a == A(8.5, abs=0.05)  # 5000 W headroom / 0.85 / 690 V


def test_d12_efficiency_above_floor_is_kept(run_case):
    m = {
        "applied_current_a": 10.0,
        "applied_phases": Phase.ONE,
        "charger_power_w": 2070,
    }
    d = run_case(ChargeMode.FAST, 500, measurements=m)
    assert d.efficiency == A(0.9)


# --- kept for parity ------------------------------------------------------------


@parity
def test_d15_setpoint_uses_validated_car_aware():
    # car_aware is on but the SOC is unknown, so decide() ignores the car.
    # The script still applies the car minimum and zeroes a valid 7 A.
    car = CarSpec(min_current_a=8, battery_capacity_wh=74000)
    settings = replace(SETTINGS, car_aware=True)
    m = replace(MEASUREMENTS, car_soc=None, commanded_current_a=10.0)
    d = Decision(reason=Reason.OK, should_write=True, phase=Phase.THREE, current_a=7.0)
    sp = filter_setpoint(d, SPEC, car, settings, m)
    assert sp.current_a == 7.0


@parity
def test_d16_rounding_never_exceeds_headroom(run_case):
    # 9500 W / 690 V = 13.77 A rounds to 13.8 A = 9522 W, above the limit.
    d = run_case(ChargeMode.LIMITED, 500)
    assert d.current_a * 690 <= 9500


def test_car_default_is_the_yaml_default():
    # Guard: the CarSpec used above matches the shared default.
    assert CAR.min_current_a == 6
