"""The mode table and Comfort resolution."""

from __future__ import annotations

import pytest

from custom_components.ev_charge_control.engine import (
    MODE_POLICY,
    ChargeMode,
    GridRequest,
    Phase,
    resolve_mode,
)


def test_every_mode_except_off_and_comfort_has_a_policy():
    assert set(MODE_POLICY) == set(ChargeMode) - {ChargeMode.OFF, ChargeMode.COMFORT}


@pytest.mark.parametrize(
    ("mode", "grid", "capped", "phase", "hold"),
    [
        (ChargeMode.MIN_1P, GridRequest.MINIMUM, True, Phase.ONE, False),
        (ChargeMode.MIN_3P, GridRequest.MINIMUM, True, Phase.THREE, False),
        (ChargeMode.LIMITED, GridRequest.POWER_LIMIT, False, None, True),
        (ChargeMode.FAST, GridRequest.HARDWARE_MAX, False, None, False),
        (ChargeMode.SOLAR, GridRequest.BRIDGE, False, None, True),
    ],
)
def test_policy_rows(mode, grid, capped, phase, hold):
    p = MODE_POLICY[mode]
    assert (p.grid, p.capped_at_minimum, p.forced_phase, p.phase_hold) == (
        grid,
        capped,
        phase,
        hold,
    )


def test_only_solar_is_solar_first():
    assert [m for m, p in MODE_POLICY.items() if p.solar_first] == [ChargeMode.SOLAR]


@pytest.mark.parametrize(
    ("car_aware", "soc", "expected"),
    [
        (True, 40, ChargeMode.LIMITED),
        (True, 50, ChargeMode.SOLAR),
        (True, 90, ChargeMode.SOLAR),
        (False, 90, ChargeMode.LIMITED),  # D08: no trusted SOC
        (True, None, ChargeMode.LIMITED),
    ],
)
def test_comfort_resolution(car_aware, soc, expected):
    assert resolve_mode(ChargeMode.COMFORT, car_aware, soc, 50) == expected


def test_other_modes_resolve_to_themselves():
    for mode in MODE_POLICY:
        assert resolve_mode(mode, True, 99, 50) == mode
