"""Available: what the car would take now, as if it were charging."""

from __future__ import annotations

import pytest

from custom_components.ev_charge_control.engine import (
    ChargeMode,
    ConnectionState,
    Controller,
)

from .conftest import CAR, CHARGER, NOW, measurements, settings
from .test_controller import GOLDEN

M = ChargeMode
UNPLUGGED = {"connection": ConnectionState.DISCONNECTED}


def available(mode, house_w, s=None, m=None):
    c = Controller(CHARGER, CAR)
    return c.available(
        settings(mode, **(s or {})), measurements(house_w, **(m or {})), NOW
    )


@pytest.mark.parametrize(("name", "mode", "house", "s", "m", "expected"), GOLDEN)
def test_equals_the_target_power(name, mode, house, s, m, expected) -> None:
    c = Controller(CHARGER, CAR)
    st, ms = settings(mode, **s), measurements(house, **m)
    out = c.step(st, ms, NOW)
    assert c.available(st, ms, NOW).total_w == pytest.approx(out.power_w)


def test_solar_mode_offers_only_the_export() -> None:
    a = available(M.SOLAR, -5146, m=UNPLUGGED)
    assert a.solar_w == pytest.approx(5146)
    # Rounding to the nearest 0.1 A step can import up to half a step (D16).
    assert a.grid_w < 0.05 * 230 * 3


def test_limited_adds_the_grid_up_to_the_limit() -> None:
    a = available(M.LIMITED, -4500, s={"power_limit_w": 5200}, m=UNPLUGGED)
    assert a.solar_w == pytest.approx(4500)
    assert a.total_w == pytest.approx(9700, abs=70)


def test_price_above_the_maximum_leaves_only_solar() -> None:
    a = available(M.LIMITED, -4500, s={"max_cost_rate": 0.10}, m=UNPLUGGED)
    assert a.grid_w == 0
    assert a.solar_w == pytest.approx(4500, abs=70)


def test_off_offers_nothing() -> None:
    a = available(M.OFF, -4500, m=UNPLUGGED)
    assert a.total_w == 0


def test_unknown_house_power() -> None:
    assert available(M.LIMITED, None) is None


def test_fast_offers_the_grid_above_the_maximum_price() -> None:
    a = available(
        M.FAST, -4500, s={"max_cost_rate": 0.10, "power_limit_w": 5200}, m=UNPLUGGED
    )
    assert a.solar_w == pytest.approx(4500)
    assert a.grid_w > 4000
