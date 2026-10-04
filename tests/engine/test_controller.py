"""Controller behaviour, one rule per test. See docs/behaviour.md."""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.ev_charge_control.engine import (
    GRACE_PERIOD,
    RESET_AFTER_DISCONNECT,
    CarSpec,
    ChargeMode,
    ChargerSpec,
    ConnectionState,
    Controller,
    Phase,
    Reason,
)

from .conftest import CAR, CHARGER, NOW, measurements, result, settings, step

M = ChargeMode
CAR_AWARE = {"car_aware": True}
EMS_BUDGET = {"ems_control": True}
EMS_ONOFF = {"ems_control": True, "ems_as_onoff": True}
SOLAR_ON_BLOCK = {"ems_control": True, "solar_when_ems_blocks": True}
BRIDGE = {"solar_bridge_w": 1000}


# --- the original 13 cases -----------------------------

GOLDEN = [
    ("fast plenty", M.FAST, 500, {}, {}, (3, 13.7)),
    ("fast low headroom", M.FAST, 7000, {}, {}, (1, 13.0)),
    ("3p min", M.MIN_3P, 500, {}, {}, (3, 6.0)),
    ("3p min low headroom", M.MIN_3P, 8000, {}, {}, (3, 0.0)),
    ("1p min", M.MIN_1P, 500, {}, {}, (1, 6.0)),
    ("solar no sun", M.SOLAR, 500, {}, {}, (1, 0.0)),
    ("solar 6 kW", M.SOLAR, -6000, {}, {}, (3, 8.7)),
    ("ems 0 limited", M.LIMITED, -6000, EMS_BUDGET, {"ems_signal_w": 0}, (1, 0.0)),
    (
        "ems 0 limited solar",
        M.LIMITED,
        -6000,
        SOLAR_ON_BLOCK,
        {"ems_signal_w": 0},
        (3, 8.7),
    ),
    ("ems 0 fast", M.FAST, -6000, EMS_BUDGET, {"ems_signal_w": 0}, (1, 0.0)),
    ("ems 0 fast solar", M.FAST, -6000, SOLAR_ON_BLOCK, {"ems_signal_w": 0}, (3, 8.7)),
    ("ems 0 solar", M.SOLAR, -6000, EMS_BUDGET, {"ems_signal_w": 0}, (3, 8.7)),
    (
        "ems 3 kW limited",
        M.LIMITED,
        -1000,
        EMS_BUDGET,
        {"ems_signal_w": 3000},
        (1, 16.0),
    ),
]


@pytest.mark.parametrize(
    ("mode", "house", "s", "m", "expected"),
    [g[1:] for g in GOLDEN],
    ids=[g[0] for g in GOLDEN],
)
def test_golden(mode, house, s, m, expected):
    assert result(step(mode, house, s=s, m=m)) == expected


# The same cases at a 6 kW limit, closer to a real household on the capacity
# tariff. Where the power limit binds, the engine rounds down and the YAML
# package rounds up past the limit (D16).
GOLDEN_6KW = {
    "fast plenty": (3, 7.9),  # 7.97 A; 8.0 A would exceed the 5.5 kW headroom
    "fast low headroom": (1, 0.0),  # 7 kW house load is above the limit
    "3p min": (3, 6.0),
    "3p min low headroom": (3, 0.0),
    "1p min": (1, 6.0),
    "solar no sun": (1, 0.0),
    "solar 6 kW": (3, 8.7),
    "ems 0 limited": (1, 0.0),
    "ems 0 limited solar": (3, 8.7),
    "ems 0 fast": (1, 0.0),
    "ems 0 fast solar": (3, 8.7),
    "ems 0 solar": (3, 8.7),
    "ems 3 kW limited": (1, 16.0),
}


@pytest.mark.parametrize(
    ("name", "mode", "house", "s", "m"),
    [g[:5] for g in GOLDEN],
    ids=[g[0] for g in GOLDEN],
)
def test_golden_at_6_kw(name, mode, house, s, m):
    out = step(mode, house, s={**s, "power_limit_w": 6000}, m=m)
    assert result(out) == GOLDEN_6KW[name]


# Comfort: Limited below the comfort SOC (50 %), Solar with the bridge from it.
# name, house W, settings, measurements, {power limit: expected}
COMFORT = [
    (
        "comfort below soc",
        500,
        CAR_AWARE,
        {"car_soc": 40},
        {10000: (3, 13.7), 6000: (3, 7.9)},
    ),
    (
        "comfort below soc, sun",
        -6000,
        CAR_AWARE,
        {"car_soc": 40},
        {10000: (3, 16.0), 6000: (3, 16.0)},
    ),
    (
        "comfort above soc, no sun",
        500,
        CAR_AWARE,
        {"car_soc": 60},
        {10000: (1, 0.0), 6000: (1, 0.0)},
    ),
    (
        "comfort above soc, sun",
        -6000,
        CAR_AWARE,
        {"car_soc": 60},
        {10000: (3, 8.7), 6000: (3, 8.7)},
    ),
    (
        "comfort above soc, bridge",
        -400,
        {**CAR_AWARE, **BRIDGE},
        {"car_soc": 60},
        {10000: (1, 6.0), 6000: (1, 6.0)},
    ),
    (
        "comfort emergency",
        500,
        CAR_AWARE,
        {"car_soc": 10},
        {10000: (3, 13.7), 6000: (3, 7.9)},
    ),
    (
        "comfort target reached",
        -6000,
        CAR_AWARE,
        {"car_soc": 85},
        {10000: (1, 0.0), 6000: (1, 0.0)},
    ),
    (
        "comfort without car aware",
        500,
        {},
        {"car_soc": 60},
        {10000: (3, 13.7), 6000: (3, 7.9)},
    ),
    (
        "comfort below soc, ems 3 kW",
        500,
        {**CAR_AWARE, **EMS_BUDGET},
        {"car_soc": 40, "ems_signal_w": 3000},
        {10000: (1, 13.0), 6000: (1, 13.0)},
    ),
    (
        "comfort above soc, ems 0",
        -2000,
        {**CAR_AWARE, **EMS_BUDGET},
        {"car_soc": 60, "ems_signal_w": 0},
        {10000: (1, 8.7), 6000: (1, 8.7)},
    ),
]


@pytest.mark.parametrize("limit", [10000, 6000])
@pytest.mark.parametrize(
    ("house", "s", "m", "expected"),
    [c[1:] for c in COMFORT],
    ids=[c[0] for c in COMFORT],
)
def test_comfort_golden(limit, house, s, m, expected):
    out = step(M.COMFORT, house, s={**s, "power_limit_w": limit}, m=m)
    assert result(out) == expected[limit]


# --- Solar mode: solar first, bridge to the minimum (B1) -----------------------


@pytest.mark.parametrize(
    ("house", "s", "m", "expected", "grid_w"),
    [
        (-2000, BRIDGE, {}, (1, 8.7), 0),  # enough sun: solar alone
        (-400, BRIDGE, {}, (1, 6.0), 980),  # gap 980 W <= bridge: exactly the minimum
        (-100, BRIDGE, {}, (1, 0.0), 0),  # gap 1280 W > bridge: stop
        (2000, BRIDGE, {}, (1, 0.0), 0),  # importing: never full grid
        (0, {"solar_bridge_w": 1500}, {}, (1, 6.0), 1380),  # bridge covers it all
        (-400, BRIDGE, {"price": 0.5}, (1, 0.0), 0),  # price gate blocks the bridge
        (-1000, {**BRIDGE, **EMS_BUDGET}, {"ems_signal_w": 500}, (1, 6.0), 380),
        (-2000, {**BRIDGE, **EMS_BUDGET}, {"ems_signal_w": 0}, (1, 8.7), 0),
    ],
)
def test_solar_mode(house, s, m, expected, grid_w):
    out = step(M.SOLAR, house, s=s, m=m)
    assert result(out) == expected
    if out.current_a:
        assert out.budget is not None and out.budget.grid_w == pytest.approx(grid_w)


def test_solar_without_bridge_is_pure_solar():
    assert result(step(M.SOLAR, -1300)) == (1, 0.0)


def test_bridge_does_not_apply_to_limited():
    out = step(M.LIMITED, 2000, s=BRIDGE)
    assert result(out) == (3, 11.5)  # normal Limited: 8000 W headroom


# --- Comfort: Limited, then Solar with the bridge ---------------------------------


def test_comfort_below_comfort_soc_is_limited():
    out = step(M.COMFORT, 500, s=CAR_AWARE, m={"car_soc": 40})
    assert result(out) == (3, 13.7)


def test_comfort_above_comfort_soc_is_solar_with_bridge():
    no_sun = step(M.COMFORT, 500, s={**CAR_AWARE, **BRIDGE}, m={"car_soc": 60})
    near_miss = step(M.COMFORT, -400, s={**CAR_AWARE, **BRIDGE}, m={"car_soc": 60})
    assert result(no_sun) == (1, 0.0)
    assert result(near_miss) == (1, 6.0)


def test_comfort_above_comfort_soc_keeps_solar_when_ems_blocks():
    out = step(
        M.COMFORT,
        -2000,
        s={**CAR_AWARE, **EMS_BUDGET},
        m={"car_soc": 60, "ems_signal_w": 0},
    )
    assert result(out) == (1, 8.7)


def test_comfort_without_car_data_is_limited():
    assert result(step(M.COMFORT, 500, m={"car_soc": 90})) == (3, 13.7)


# --- price and EMS ---------------------------------------------------------------


def test_high_price_blocks_grid():
    out = step(M.LIMITED, 500, m={"price": 0.35})
    assert out.reason == Reason.GRID_BLOCKED and out.current_a == 0
    assert out.grid_allowed is False


def test_high_price_still_charges_on_solar():
    assert result(step(M.LIMITED, -6000, m={"price": 0.35})) == (3, 8.7)


def test_price_at_maximum_is_allowed():
    assert step(M.LIMITED, 500, m={"price": 0.30}).grid_allowed


def test_no_price_skips_the_price_check():
    out = step(M.LIMITED, 500, m={"price": None})  # D01
    assert out.grid_allowed and result(out) == (3, 13.7)


def test_ems_budget_caps_every_grid_mode():
    out = step(M.FAST, 500, s=EMS_BUDGET, m={"ems_signal_w": 3000})  # D03
    assert out.budget is not None and out.budget.grid_w == 3000
    assert result(out) == (1, 13.0)


@pytest.mark.parametrize("mode", [M.MIN_1P, M.MIN_3P, M.LIMITED, M.FAST])
def test_ems_zero_stops_grid_modes_even_with_sun(mode):
    out = step(mode, -6000, s=EMS_BUDGET, m={"ems_signal_w": 0})  # D04
    assert out.reason == Reason.GRID_BLOCKED and out.current_a == 0


def test_ems_zero_minimum_mode_may_run_on_solar_when_allowed():
    out = step(M.MIN_1P, -2000, s=SOLAR_ON_BLOCK, m={"ems_signal_w": 0})
    assert result(out) == (1, 6.0)


def test_ems_onoff_ignores_the_budget_value():
    out = step(M.LIMITED, -1000, s=EMS_ONOFF, m={"ems_signal_w": 3000})
    assert result(out) == (3, 15.9)  # 11000 W headroom


def test_missing_ems_signal_closes_the_gate():
    out = step(M.LIMITED, 500, s=EMS_BUDGET, m={"ems_signal_w": None})
    assert out.reason == Reason.GRID_BLOCKED


def test_ems_budget_below_minimum_stops_3p_minimum():
    out = step(M.MIN_3P, 500, s=EMS_BUDGET, m={"ems_signal_w": 3000})
    assert result(out) == (3, 0.0)


# --- minimum modes ------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "phases"), [(M.MIN_1P, 1), (M.MIN_3P, 3)])
def test_minimum_modes_ignore_surplus(mode, phases):
    assert result(step(mode, -6000)) == (phases, 6.0)  # D05


def test_minimum_runs_on_solar_when_grid_is_blocked():
    assert result(step(M.MIN_1P, -2000, m={"price": 0.5})) == (1, 6.0)


def test_minimum_stops_when_solar_alone_is_too_small():
    assert result(step(M.MIN_1P, -800, m={"price": 0.5})) == (1, 0.0)


def test_3p_minimum_with_single_phase_only_is_refused():
    out = step(M.MIN_3P, -6000, s={"single_phase_only": True})  # D07
    assert out.reason == Reason.REFUSED and result(out) == (1, 0.0)


def test_single_phase_only_forces_one_phase():
    assert result(step(M.FAST, 500, s={"single_phase_only": True})) == (1, 16.0)


# --- car ------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [M.LIMITED, M.FAST, M.SOLAR, M.COMFORT])
def test_emergency_charges_to_the_limit_in_every_mode(mode):
    out = step(mode, 500, s=CAR_AWARE, m={"car_soc": 10})  # D06
    assert out.reason == Reason.EMERGENCY and out.emergency
    assert result(out) == (3, 13.7)


def test_emergency_ignores_price_and_ems():
    out = step(
        M.LIMITED,
        500,
        s={**CAR_AWARE, **EMS_BUDGET},
        m={"car_soc": 10, "price": 0.5, "ems_signal_w": 0},
    )
    assert out.grid_allowed and result(out) == (3, 13.7)


def test_emergency_lifts_the_minimum_cap():
    assert result(step(M.MIN_1P, 500, s=CAR_AWARE, m={"car_soc": 10})) == (1, 16.0)


def test_emergency_needs_car_aware():
    assert not step(M.LIMITED, 500, m={"car_soc": 10}).emergency  # D08


def test_target_reached_stops_and_keeps_the_phase():
    out = step(
        M.SOLAR, -6000, s=CAR_AWARE, m={"car_soc": 85, "commanded_phase": Phase.THREE}
    )
    assert out.reason == Reason.TARGET_REACHED and out.target_reached
    assert result(out) == (3, 0.0)


def test_target_reached_in_minimum_mode_keeps_the_forced_phase():
    out = step(M.MIN_3P, 500, s=CAR_AWARE, m={"car_soc": 85})
    assert result(out) == (3, 0.0)


def test_car_limits_narrow_the_current_range():
    car = CarSpec(max_current_a=10, min_current_a=8, battery_capacity_wh=74000)
    c = Controller(CHARGER, car)
    assert result(step(M.FAST, 500, controller=c, s=CAR_AWARE)) == (3, 10.0)
    c = Controller(CHARGER, car)
    assert result(step(M.MIN_1P, 500, controller=c, s=CAR_AWARE)) == (1, 8.0)


def test_car_limits_ignored_without_car_aware():
    car = CarSpec(max_current_a=10, battery_capacity_wh=74000)
    assert result(step(M.FAST, 500, controller=Controller(CHARGER, car))) == (3, 13.7)


def test_no_car_spec_means_no_car_awareness():
    out = step(
        M.FAST, 500, controller=Controller(CHARGER), s=CAR_AWARE, m={"car_soc": 10}
    )
    assert not out.emergency


# --- stops keep the phase -------------------------------------------------------------


def test_off_writes_zero_and_keeps_the_phase():
    out = step(
        M.OFF, -6000, m={"commanded_phase": Phase.THREE, "commanded_current_a": 10}
    )
    assert out.reason == Reason.OFF and result(out) == (3, 0.0)
    assert out.setpoint is not None and not out.setpoint.write_phase


def test_grid_allowed_is_known_without_charging():
    assert step(M.OFF, 500).grid_allowed is True
    high_price = {"price": 0.50}
    assert (
        step(M.OFF, 500, m=high_price, s={"max_cost_rate": 0.30}).grid_allowed is False
    )
    unplugged = {"connection": ConnectionState.DISCONNECTED}
    assert step(M.LIMITED, 500, m=unplugged).grid_allowed is True


def test_insufficient_power_keeps_the_phase():
    out = step(M.SOLAR, 500, m={"commanded_phase": Phase.THREE})
    assert out.reason == Reason.INSUFFICIENT_POWER and result(out) == (3, 0.0)


# --- skipped runs and fail-safe -------------------------------------------------------


@pytest.mark.parametrize(
    ("s", "m", "reason"),
    [
        ({}, {"connection": ConnectionState.ERROR}, Reason.NOT_CONNECTED),
        ({}, {"connection": ConnectionState.UNKNOWN}, Reason.NOT_CONNECTED),
        ({}, {"commanded_phase": None}, Reason.CHARGER_UNAVAILABLE),
        ({}, {"commanded_current_a": None}, Reason.CHARGER_UNAVAILABLE),
        ({"power_limit_w": 0}, {}, Reason.NO_POWER_LIMIT),
    ],
)
def test_skipped_runs_write_nothing(s, m, reason):
    out = step(M.FAST, 500, s=s, m=m)
    assert out.reason == reason
    assert out.phase is None and out.current_a is None and out.setpoint is None


@pytest.mark.parametrize(
    "missing", ["charger_power_w", "applied_current_a", "active_phases"]
)
def test_failsafe_on_a_missing_sensor(missing):
    out = step(
        M.FAST,
        500,
        m={missing: None, "commanded_phase": Phase.THREE, "commanded_current_a": 10.0},
    )
    assert out.reason == Reason.FAILSAFE
    assert result(out) == (1, 7.0)  # safe fallback phase (D11), never above fallback


def test_failsafe_can_keep_the_phase():
    charger = ChargerSpec(failsafe_keeps_phase=True)
    out = step(
        M.FAST,
        500,
        controller=Controller(charger, CAR),
        m={
            "active_phases": None,
            "commanded_phase": Phase.THREE,
            "commanded_current_a": 10,
        },
    )
    assert out.reason == Reason.FAILSAFE and result(out) == (3, 7.0)


def test_failsafe_on_missing_house_power_never_raises_the_current():
    out = step(M.FAST, None, m={"commanded_current_a": 0.0})
    assert out.reason == Reason.FAILSAFE and result(out) == (1, 0.0)


def test_disconnect_resets_to_fallback_after_a_minute():
    c = Controller(CHARGER, CAR)
    off = {"connection": ConnectionState.DISCONNECTED, "commanded_current_a": 16.0}
    first = step(M.LIMITED, 500, controller=c, m=off)
    early = step(M.LIMITED, 500, controller=c, m=off, now=NOW + timedelta(seconds=59))
    late = step(M.LIMITED, 500, controller=c, m=off, now=NOW + RESET_AFTER_DISCONNECT)
    assert first.setpoint is None and early.setpoint is None
    assert late.reason == Reason.NOT_CONNECTED and result(late) == (1, 7.0)
    assert late.setpoint is not None and late.setpoint.write_current
    # The reset prepares the next session; no car draws power.
    assert late.power_w == 0


def test_error_state_never_resets():
    c = Controller(CHARGER, CAR)
    err = {"connection": ConnectionState.ERROR}
    step(M.LIMITED, 500, controller=c, m=err)
    out = step(M.LIMITED, 500, controller=c, m=err, now=NOW + timedelta(minutes=5))
    assert out.setpoint is None


# --- timers ---------------------------------------------------------------------------


def run(c, mode, phase, now, house=500):
    return c.step(settings(mode), measurements(house, commanded_phase=phase), now)


def test_drop_to_one_phase_holds_the_upgrade():
    c = Controller(CHARGER, CAR)
    run(c, M.LIMITED, Phase.THREE, NOW)
    held = run(c, M.LIMITED, Phase.ONE, NOW + timedelta(seconds=10))
    assert held.phase == Phase.ONE
    assert held.phase_hold_until == NOW + timedelta(seconds=310)
    later = run(c, M.LIMITED, Phase.ONE, NOW + timedelta(seconds=311))
    assert later.phase == Phase.THREE


def test_startup_on_one_phase_starts_no_hold():
    c = Controller(CHARGER, CAR)
    out = run(c, M.LIMITED, Phase.ONE, NOW)  # B8
    assert out.phase == Phase.THREE and out.phase_hold_until is None


def test_no_hold_in_fast():
    c = Controller(CHARGER, CAR)
    run(c, M.FAST, Phase.THREE, NOW)
    out = run(c, M.FAST, Phase.ONE, NOW + timedelta(seconds=10))  # D13
    assert out.phase == Phase.THREE


def test_hold_does_not_block_a_downgrade():
    c = Controller(CHARGER, CAR)
    run(c, M.LIMITED, Phase.THREE, NOW)
    run(c, M.LIMITED, Phase.ONE, NOW + timedelta(seconds=10))
    out = run(c, M.LIMITED, Phase.ONE, NOW + timedelta(seconds=20), house=7000)
    assert result(out) == (1, 13.0)


def test_upgrade_starts_the_grace_period():
    c = Controller(CHARGER, CAR)
    run(c, M.LIMITED, Phase.ONE, NOW)
    waiting = run(c, M.LIMITED, Phase.THREE, NOW + timedelta(seconds=10))
    assert waiting.reason == Reason.GRACE_PERIOD and waiting.setpoint is None
    done = run(c, M.LIMITED, Phase.THREE, NOW + timedelta(seconds=10) + GRACE_PERIOD)
    assert done.reason == Reason.CHARGING


# --- efficiency -----------------------------------------------------------------------


def charging(c, power, now, applied=10.0, phases=Phase.ONE, house=500):
    m = measurements(
        house, applied_current_a=applied, charger_power_w=power, active_phases=phases
    )
    return c.step(settings(M.FAST), m, now)


def test_efficiency_learns_only_when_steady():
    c = Controller(CHARGER, CAR)
    assert charging(c, 2070, NOW).efficiency == 1.0  # first sample: no history
    assert charging(c, 2070, NOW).efficiency == pytest.approx(0.97)
    assert charging(c, 2070, NOW).efficiency == pytest.approx(0.949)
    changed = charging(c, 2070, NOW, applied=12.0)
    assert changed.efficiency == pytest.approx(0.949)  # ramp: no learning


def test_efficiency_converges_and_raises_the_current():
    c = Controller(CHARGER, CAR)
    for _ in range(40):
        out = charging(c, 2070, NOW)
    assert out.efficiency == pytest.approx(0.9, abs=1e-4)
    assert result(out) == (3, 15.2)  # 9500 W / (690 V x 0.9)


def test_efficiency_floor():
    c = Controller(CHARGER, CAR)
    for _ in range(40):
        out = charging(c, 1001, NOW, applied=16.0, phases=Phase.THREE)
    assert out.efficiency == pytest.approx(0.85, abs=1e-4)  # D12


def test_low_power_does_not_teach():
    c = Controller(CHARGER, CAR)
    for _ in range(5):
        out = charging(c, 900, NOW)
    assert out.efficiency == 1.0


def test_disconnect_resets_efficiency():
    c = Controller(CHARGER, CAR)
    for _ in range(10):
        charging(c, 2070, NOW)
    m = measurements(500, connection=ConnectionState.DISCONNECTED)
    assert c.step(settings(M.FAST), m, NOW).efficiency == 1.0
