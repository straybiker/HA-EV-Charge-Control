"""Builders with the defaults of the original Jinja test (create_mock_db)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargeMode,
    ChargerSpec,
    ConnectionState,
    Decision,
    Measurements,
    Phase,
    Settings,
    TimerState,
    decide,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

SPEC = ChargerSpec(max_current_a=16, min_current_a=6, nominal_voltage_v=230)
CAR = CarSpec(max_current_a=16, min_current_a=6, battery_capacity_wh=74000)
SETTINGS = Settings(
    mode=ChargeMode.FAST,
    power_limit_w=10000,
    car_aware=False,
    pv_prioritized=False,
    pv_prio_threshold_w=0,
    single_phase_only=False,
    ems_control=False,
    ems_as_onoff=False,
    max_cost_rate=0.30,
    emergency_soc=20,
    comfort_soc=50,
    target_soc=80,
)
MEASUREMENTS = Measurements(
    household_power_w=500,
    charger_power_w=0.0,
    applied_current_a=0.0,
    applied_phases=Phase.ONE,
    connection=ConnectionState.CONNECTED,
    commanded_phase=Phase.ONE,
    commanded_current_a=0.0,
    car_soc=50,
    electricity_price=0.20,
    ems_signal_w=0.0,
)
TIMERS = TimerState()


def run(
    mode: ChargeMode,
    household_w: float,
    *,
    spec: ChargerSpec = SPEC,
    car: CarSpec = CAR,
    timers: TimerState = TIMERS,
    now: datetime = NOW,
    settings: dict | None = None,
    measurements: dict | None = None,
) -> Decision:
    """Run decide() with the defaults and the given overrides."""
    s = replace(SETTINGS, mode=mode, **(settings or {}))
    m = replace(MEASUREMENTS, household_power_w=household_w, **(measurements or {}))
    return decide(spec, car, s, m, timers, now)


@pytest.fixture
def run_case():
    return run
