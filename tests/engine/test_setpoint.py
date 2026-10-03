"""The write filter: minimum rule, Alfen 0.2 A workaround, hysteresis."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.ev_charge_control.engine import (
    CarSpec,
    Decision,
    Phase,
    Reason,
    filter_setpoint,
)

from .conftest import CAR, MEASUREMENTS, SETTINGS, SPEC


def decision(current_a: float, phase: Phase = Phase.THREE) -> Decision:
    return Decision(
        reason=Reason.OK, should_write=True, phase=phase, current_a=current_a
    )


def filt(d: Decision, commanded_current=10.0, commanded_phase=Phase.THREE, **kw):
    m = replace(
        MEASUREMENTS,
        commanded_current_a=commanded_current,
        commanded_phase=commanded_phase,
    )
    settings = replace(SETTINGS, **kw.pop("settings", {}))
    car = kw.pop("car", CAR)
    return filter_setpoint(d, SPEC, car, settings, m)


# --- hysteresis -------------------------------------------------------------


@pytest.mark.parametrize(
    ("phase", "target", "writes"),
    [
        (Phase.THREE, 10.3, False),  # 0.3 A < 230 W / 690 V = 0.333 A
        (Phase.THREE, 10.4, True),
        (Phase.ONE, 10.9, False),  # 0.9 A < 230 W / 230 V = 1.0 A
        (Phase.ONE, 11.0, True),
    ],
)
def test_increase_needs_power_threshold(phase, target, writes):
    sp = filt(decision(target, phase), commanded_current=10.0, commanded_phase=phase)
    assert sp.write_current is writes
    assert sp.current_a == target


def test_decrease_is_always_written():
    sp = filt(decision(9.5), commanded_current=10.0)
    assert sp.write_current
    assert sp.current_a == 9.5


def test_threshold_scales_with_power_update_threshold():
    sp = filt(decision(10.4), settings={"power_update_threshold_w": 460})
    assert not sp.write_current  # 0.4 A < 460 W / 690 V = 0.667 A


def test_no_write_when_commanded_current_unknown():
    sp = filt(decision(12.0), commanded_current=None)
    assert not sp.write_current


# --- Alfen 0.2 A workaround -------------------------------------------------


def test_small_decrease_is_widened_to_0_2_a():
    sp = filt(decision(9.9), commanded_current=10.0)
    assert sp.current_a == 9.8
    assert sp.write_current


def test_widening_stops_at_minimum_current():
    sp = filt(decision(6.0), commanded_current=6.1)
    assert sp.current_a == 6.0  # 6.1 - 0.2 would go below 6 A


def test_zero_target_is_not_widened():
    sp = filt(decision(0.0), commanded_current=10.0)
    assert sp.current_a == 0.0
    assert sp.write_current


def test_increase_is_not_widened():
    sp = filt(decision(10.1), commanded_current=10.0)
    assert sp.current_a == 10.1


# --- minimum current ---------------------------------------------------------


def test_below_minimum_becomes_zero():
    sp = filt(decision(5.0))
    assert sp.current_a == 0.0
    assert sp.min_current_a == 6


def test_minimum_uses_raw_car_aware_flag():
    car = CarSpec(min_current_a=8, max_current_a=16, battery_capacity_wh=74000)
    sp = filt(decision(7.0), car=car, settings={"car_aware": True})
    assert sp.min_current_a == 8
    assert sp.current_a == 0.0


# --- phase ---------------------------------------------------------------------


def test_phase_upgrade_zeroes_current_first():
    sp = filt(decision(10.0, Phase.THREE), commanded_phase=Phase.ONE)
    assert sp.write_phase
    assert sp.zero_before_phase_change


def test_phase_downgrade_does_not_zero_first():
    sp = filt(decision(10.0, Phase.ONE), commanded_phase=Phase.THREE)
    assert sp.write_phase
    assert not sp.zero_before_phase_change


def test_same_phase_is_not_written():
    sp = filt(decision(10.0, Phase.THREE), commanded_phase=Phase.THREE)
    assert not sp.write_phase
    assert not sp.zero_before_phase_change


def test_unknown_commanded_phase_is_not_written():
    sp = filt(decision(10.0, Phase.THREE), commanded_phase=None)
    assert not sp.write_phase


def test_skipped_decision_is_rejected():
    skipped = Decision(reason=Reason.NOT_CONNECTED, should_write=False)
    with pytest.raises(ValueError):
        filt(skipped)
