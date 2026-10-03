"""Behaviour the original Jinja tests did not cover.

Expected values follow the YAML as it runs. Where that differs from the
README, the case is marked with the defect ID from docs/known-defects.md.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargeMode,
    ConnectionState,
    Phase,
    Reason,
    TimerState,
)

from .conftest import NOW

CAR_AWARE = {"car_aware": True}
A = pytest.approx


def amps(d):
    return d.phase, A(d.current_a, abs=0.05)


# --- emergency -----------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [ChargeMode.LIMITED, ChargeMode.FAST, ChargeMode.SOLAR, ChargeMode.COMFORT],
)
def test_emergency_requests_power_limit_in_every_mode(run_case, mode):
    # D06 accepted: the emergency floor uses the grid, also in Solar mode.
    d = run_case(mode, 500, settings=CAR_AWARE, measurements={"car_soc": 10})
    assert d.is_emergency
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))  # 9500 W headroom


def test_emergency_overrides_price_and_ems(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        500,
        settings={**CAR_AWARE, "ems_control": True},
        measurements={"car_soc": 10, "electricity_price": 0.50, "ems_signal_w": 0},
    )
    assert d.grid_gate_open
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))


def test_emergency_in_1p_minimum_is_capped_by_max_current(run_case):
    d = run_case(
        ChargeMode.MIN_1P, 500, settings=CAR_AWARE, measurements={"car_soc": 10}
    )
    assert amps(d) == (Phase.ONE, A(16.0))


def test_emergency_does_not_apply_to_off(run_case):
    d = run_case(ChargeMode.OFF, 500, settings=CAR_AWARE, measurements={"car_soc": 10})
    assert d.current_a == 0
    assert d.reason == Reason.OFF


def test_emergency_needs_car_aware(run_case):
    # D08 accepted: with car_aware off the SOC rules do nothing.
    d = run_case(ChargeMode.LIMITED, 500, measurements={"car_soc": 10})
    assert not d.is_emergency


# --- target SOC ------------------------------------------------------------------


def test_target_reached_stops_charging(run_case):
    d = run_case(ChargeMode.FAST, 500, settings=CAR_AWARE, measurements={"car_soc": 85})
    assert d.target_reached
    assert d.current_a == 0


def test_target_reached_ignores_solar_surplus(run_case):
    d = run_case(
        ChargeMode.SOLAR, -6000, settings=CAR_AWARE, measurements={"car_soc": 85}
    )
    assert d.current_a == 0


def test_unknown_soc_disables_car_awareness(run_case):
    d = run_case(
        ChargeMode.FAST, 500, settings=CAR_AWARE, measurements={"car_soc": None}
    )
    assert not d.target_reached
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))


def test_unknown_capacity_disables_car_awareness(run_case):
    car = CarSpec(battery_capacity_wh=None)
    d = run_case(
        ChargeMode.FAST, 500, car=car, settings=CAR_AWARE, measurements={"car_soc": 85}
    )
    assert not d.target_reached


# --- comfort ---------------------------------------------------------------------


def test_comfort_below_threshold_behaves_like_limited(run_case):
    d = run_case(
        ChargeMode.COMFORT, 500, settings=CAR_AWARE, measurements={"car_soc": 40}
    )
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))


def test_comfort_above_threshold_behaves_like_solar(run_case):
    no_sun = run_case(
        ChargeMode.COMFORT, 500, settings=CAR_AWARE, measurements={"car_soc": 60}
    )
    sun = run_case(
        ChargeMode.COMFORT, -6000, settings=CAR_AWARE, measurements={"car_soc": 60}
    )
    assert no_sun.current_a == 0
    assert amps(sun) == (Phase.THREE, A(8.7, abs=0.05))


def test_comfort_without_car_aware_is_always_limited(run_case):
    d = run_case(ChargeMode.COMFORT, 500, measurements={"car_soc": 60})
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))


# --- price gate -----------------------------------------------------------------


def test_price_above_max_cost_blocks_grid_but_not_solar(run_case):
    blocked = run_case(
        ChargeMode.LIMITED, 500, measurements={"electricity_price": 0.35}
    )
    solar = run_case(
        ChargeMode.LIMITED, -6000, measurements={"electricity_price": 0.35}
    )
    assert not blocked.grid_gate_open
    assert blocked.current_a == 0
    assert amps(solar) == (Phase.THREE, A(8.7, abs=0.05))


def test_price_at_max_cost_is_allowed(run_case):
    d = run_case(ChargeMode.LIMITED, 500, measurements={"electricity_price": 0.30})
    assert d.grid_gate_open


def test_unavailable_price_skips_the_price_check(run_case):
    # D01 accepted: no price behaves as if there were no price feature.
    d = run_case(ChargeMode.LIMITED, 500, measurements={"electricity_price": None})
    assert d.grid_gate_open
    assert amps(d) == (Phase.THREE, A(13.8, abs=0.05))


def test_unavailable_price_does_not_override_ems(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        500,
        settings={"ems_control": True},
        measurements={"electricity_price": None, "ems_signal_w": 0},
    )
    assert not d.grid_gate_open
    assert d.current_a == 0


# --- efficiency ------------------------------------------------------------------

CHARGING_1P = {"applied_current_a": 10.0, "applied_phases": Phase.ONE}


def test_efficiency_scales_target_and_headroom(run_case):
    # 2070 W at 10 A on 1 phase: eff 0.9. Headroom 9500 / 0.9 = 10556 W.
    d = run_case(
        ChargeMode.FAST, 500, measurements={**CHARGING_1P, "charger_power_w": 2070}
    )
    assert d.efficiency == A(0.9)
    assert amps(d) == (Phase.THREE, A(15.3, abs=0.05))


def test_efficiency_is_capped_at_one(run_case):
    d = run_case(
        ChargeMode.FAST, 500, measurements={**CHARGING_1P, "charger_power_w": 3000}
    )
    assert d.efficiency == 1.0


def test_efficiency_ignored_below_1_kw(run_case):
    d = run_case(
        ChargeMode.FAST, 500, measurements={**CHARGING_1P, "charger_power_w": 900}
    )
    assert d.efficiency == 1.0


def test_efficiency_uses_applied_phase_count(run_case):
    three = {
        "applied_current_a": 10.0,
        "applied_phases": Phase.THREE,
        "charger_power_w": 6210,
    }
    d = run_case(ChargeMode.FAST, 500, measurements=three)
    assert d.efficiency == A(0.9)


# --- PV priority -------------------------------------------------------------------

PV_PRIO = {"pv_prioritized": True, "pv_prio_threshold_w": 1000}


def test_pv_priority_follows_surplus_when_sun_is_enough(run_case):
    d = run_case(ChargeMode.LIMITED, -2000, settings=PV_PRIO)
    assert d.solar_surplus_w == 2000
    assert amps(d) == (Phase.ONE, A(8.7, abs=0.05))


def test_pv_priority_bridge_adds_grid_below_minimum(run_case):
    # 400 W export + 1000 W bridge = 1400 W > 1380 W minimum.
    d = run_case(ChargeMode.LIMITED, -400, settings=PV_PRIO)
    assert d.solar_surplus_w == 1400
    assert amps(d) == (Phase.ONE, A(6.1, abs=0.05))


def test_pv_priority_dead_band_stops_charging(run_case):
    # 0 W export + 1000 W bridge = 1000 W < 1380 W: below minimum, so 0 A.
    d = run_case(ChargeMode.LIMITED, 0, settings=PV_PRIO)
    assert d.current_a == 0


def test_pv_priority_falls_back_to_grid_above_bridge(run_case):
    # 2000 W import exceeds the bridge: surplus 0, normal Limited behaviour.
    d = run_case(ChargeMode.LIMITED, 2000, settings=PV_PRIO)
    assert d.solar_surplus_w == 0
    assert amps(d) == (Phase.THREE, A(11.6, abs=0.05))  # 8000 W headroom


def test_pv_priority_bridge_stops_at_closed_price_gate(run_case):
    # D02 fixed: see test_known_defects.py for the full set.
    d = run_case(
        ChargeMode.LIMITED,
        -400,
        settings=PV_PRIO,
        measurements={"electricity_price": 0.5},
    )
    assert not d.grid_gate_open
    assert d.current_a == 0


def test_pv_priority_only_applies_to_limited(run_case):
    d = run_case(ChargeMode.FAST, -400, settings=PV_PRIO)
    assert d.solar_surplus_w == 400


# --- EMS ----------------------------------------------------------------------------

EMS_BUDGET = {"ems_control": True, "ems_as_onoff": False}
EMS_ONOFF = {"ems_control": True, "ems_as_onoff": True}


def test_ems_onoff_mode_ignores_budget(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        -1000,
        settings=EMS_ONOFF,
        measurements={"ems_signal_w": 3000},
    )
    assert d.effective_grid_w == 10000
    assert amps(d) == (Phase.THREE, A(15.9, abs=0.05))  # 11000 W


def test_ems_onoff_mode_zero_stops(run_case):
    d = run_case(
        ChargeMode.LIMITED, -1000, settings=EMS_ONOFF, measurements={"ems_signal_w": 0}
    )
    assert d.current_a == 0


def test_ems_budget_shaves_fast(run_case):
    # D03 accepted: EMS is always in control when enabled.
    d = run_case(
        ChargeMode.FAST, 500, settings=EMS_BUDGET, measurements={"ems_signal_w": 3000}
    )
    assert d.effective_grid_w == 3000
    assert amps(d) == (Phase.ONE, A(13.0, abs=0.05))


@pytest.mark.parametrize("mode", [ChargeMode.MIN_1P, ChargeMode.MIN_3P])
def test_ems_zero_stops_minimum_modes(run_case, mode):
    # D04 accepted: EMS is always in control when enabled.
    d = run_case(mode, 500, settings=EMS_BUDGET, measurements={"ems_signal_w": 0})
    assert d.current_a == 0


def test_ems_budget_below_minimum_stops_3p_minimum(run_case):
    # 3000 W budget < 4140 W minimum on 3 phases: 4.3 A is below 6 A.
    d = run_case(
        ChargeMode.MIN_3P, 500, settings=EMS_BUDGET, measurements={"ems_signal_w": 3000}
    )
    assert d.effective_grid_w == 3000
    assert (d.phase, d.current_a) == (Phase.THREE, 0.0)


def test_ems_onoff_lets_minimum_mode_run(run_case):
    d = run_case(
        ChargeMode.MIN_3P, 500, settings=EMS_ONOFF, measurements={"ems_signal_w": 3000}
    )
    assert amps(d) == (Phase.THREE, A(6.0))


def test_unavailable_ems_signal_fails_closed(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        500,
        settings=EMS_BUDGET,
        measurements={"ems_signal_w": None},
    )
    assert not d.grid_gate_open
    assert d.current_a == 0


# --- minimum modes -------------------------------------------------------------------


def test_minimum_mode_stays_at_minimum_while_exporting(run_case):
    # D05 fixed: see test_known_defects.py for the full set.
    d = run_case(ChargeMode.MIN_1P, -2000)
    assert amps(d) == (Phase.ONE, A(6.0))


def test_3p_minimum_with_single_phase_only_is_refused(run_case):
    # D07 fixed: see test_known_defects.py.
    d = run_case(ChargeMode.MIN_3P, 500, settings={"single_phase_only": True})
    assert d.reason == Reason.REFUSED
    assert d.current_a == 0


def test_single_phase_only_forces_one_phase(run_case):
    d = run_case(ChargeMode.FAST, 500, settings={"single_phase_only": True})
    assert amps(d) == (Phase.ONE, A(16.0))


# --- car limits -----------------------------------------------------------------------


def test_car_max_current_caps_fast(run_case):
    car = CarSpec(max_current_a=10, battery_capacity_wh=74000)
    d = run_case(ChargeMode.FAST, 500, car=car, settings=CAR_AWARE)
    assert d.max_current_a == 10
    assert amps(d) == (Phase.THREE, A(10.0))


def test_car_min_current_raises_minimum(run_case):
    car = CarSpec(min_current_a=8, battery_capacity_wh=74000)
    d = run_case(ChargeMode.MIN_1P, 500, car=car, settings=CAR_AWARE)
    assert d.min_current_a == 8
    assert amps(d) == (Phase.ONE, A(8.0))


def test_car_limits_ignored_without_car_aware(run_case):
    car = CarSpec(max_current_a=10, battery_capacity_wh=74000)
    d = run_case(ChargeMode.FAST, 500, car=car)
    assert d.max_current_a == 16


# --- phase hold -----------------------------------------------------------------------

TIMER_ACTIVE = TimerState(phase_switch_until=NOW + timedelta(minutes=1))
TIMER_EXPIRED = TimerState(phase_switch_until=NOW - timedelta(seconds=1))


def test_phase_timer_holds_upgrade_in_dynamic_modes(run_case):
    d = run_case(ChargeMode.LIMITED, 500, timers=TIMER_ACTIVE)
    assert amps(d) == (Phase.ONE, A(16.0))


def test_expired_timer_allows_upgrade(run_case):
    d = run_case(ChargeMode.LIMITED, 500, timers=TIMER_EXPIRED)
    assert d.phase == Phase.THREE


def test_phase_timer_does_not_hold_fast(run_case):
    # D13 accepted: Fast is a fixed mode and needs no flap protection.
    d = run_case(ChargeMode.FAST, 500, timers=TIMER_ACTIVE)
    assert d.phase == Phase.THREE


def test_phase_timer_does_not_hold_downgrade(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        7000,
        timers=TIMER_ACTIVE,
        measurements={"commanded_phase": Phase.THREE},
    )
    assert amps(d) == (Phase.ONE, A(13.0))


def test_phase_timer_keeps_three_phases(run_case):
    d = run_case(
        ChargeMode.LIMITED,
        500,
        timers=TIMER_ACTIVE,
        measurements={"commanded_phase": Phase.THREE},
    )
    assert d.phase == Phase.THREE


# --- run conditions -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"measurements": {"connection": ConnectionState.DISCONNECTED}},
            Reason.NOT_CONNECTED,
        ),
        ({"measurements": {"connection": ConnectionState.ERROR}}, Reason.NOT_CONNECTED),
        ({"measurements": {"commanded_phase": None}}, Reason.OUTPUTS_UNAVAILABLE),
        ({"measurements": {"commanded_current_a": None}}, Reason.OUTPUTS_UNAVAILABLE),
        ({"settings": {"power_limit_w": 0}}, Reason.POWER_LIMIT_ZERO),
        (
            {"timers": TimerState(grace_until=NOW + timedelta(seconds=10))},
            Reason.GRACE_PERIOD,
        ),
    ],
)
def test_run_is_skipped(run_case, overrides, reason):
    d = run_case(ChargeMode.FAST, 500, **overrides)
    assert not d.should_write
    assert d.reason == reason
    assert d.phase is None and d.current_a is None


def test_disconnected_wins_over_other_skips(run_case):
    d = run_case(
        ChargeMode.FAST,
        500,
        settings={"power_limit_w": 0},
        measurements={"connection": ConnectionState.DISCONNECTED},
    )
    assert d.reason == Reason.NOT_CONNECTED


# --- fail-safe ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["household_power_w", "applied_current_a", "charger_power_w", "applied_phases"],
)
def test_failsafe_on_missing_base_sensor(run_case, missing):
    overrides = {missing: None, "commanded_current_a": 10.0}
    household = overrides.pop("household_power_w", 500)
    d = run_case(ChargeMode.FAST, household, measurements=overrides)
    assert d.reason == Reason.FAILSAFE
    assert d.should_write
    assert d.phase == Phase.ONE
    assert d.current_a == 7.0  # min(commanded 10, default 7)


def test_failsafe_never_raises_current(run_case):
    d = run_case(ChargeMode.FAST, None, measurements={"commanded_current_a": 0.0})
    assert d.current_a == 0.0


def test_failsafe_forces_default_phase(run_case):
    # D11: a fail-safe during 3-phase charging switches to 1 phase.
    d = run_case(ChargeMode.FAST, None, measurements={"commanded_phase": Phase.THREE})
    assert d.phase == Phase.ONE


def test_failsafe_does_not_check_price_or_soc(run_case):
    d = run_case(
        ChargeMode.FAST, 500, measurements={"electricity_price": None, "car_soc": None}
    )
    assert d.reason == Reason.OK


# --- off ------------------------------------------------------------------------------


def test_off_writes_zero(run_case):
    d = run_case(ChargeMode.OFF, -6000)
    assert d.reason == Reason.OFF
    assert d.should_write
    assert d.current_a == 0
    assert d.phase == Phase.ONE
