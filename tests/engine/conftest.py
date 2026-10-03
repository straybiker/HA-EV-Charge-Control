"""Shared defaults: 10 kW limit, 16 A / 6 A charger at 230 V, no car data."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargeMode,
    ChargerSpec,
    ConnectionState,
    Controller,
    Measurements,
    Output,
    Phase,
    Settings,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

CHARGER = ChargerSpec(max_current_a=16, min_current_a=6, voltage_v=230)
CAR = CarSpec(max_current_a=16, min_current_a=6, battery_capacity_wh=74000)
SETTINGS = Settings(power_limit_w=10000)
MEASUREMENTS = Measurements(
    connection=ConnectionState.CONNECTED,
    house_power_w=500,
    charger_power_w=0.0,
    applied_current_a=0.0,
    active_phases=Phase.ONE,
    commanded_phase=Phase.ONE,
    commanded_current_a=0.0,
    car_soc=50,
    price=0.20,
    ems_signal_w=None,
)


def settings(mode: ChargeMode, **kw) -> Settings:
    return replace(SETTINGS, mode=mode, **kw)


def measurements(house_w: float | None, **kw) -> Measurements:
    return replace(MEASUREMENTS, house_power_w=house_w, **kw)


def step(
    mode: ChargeMode,
    house_w: float | None,
    *,
    controller: Controller | None = None,
    now: datetime = NOW,
    s: dict | None = None,
    m: dict | None = None,
) -> Output:
    """One step on a fresh controller unless one is passed."""
    c = controller or Controller(CHARGER, CAR)
    return c.step(settings(mode, **(s or {})), measurements(house_w, **(m or {})), now)


def result(out: Output) -> tuple[int, float]:
    """(phases, amps) for compact assertions."""
    assert out.phase is not None and out.current_a is not None
    return int(out.phase), out.current_a
