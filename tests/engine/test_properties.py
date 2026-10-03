"""Invariants that must hold for any input."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st

from custom_components.ev_charge_control.engine import (
    ChargeMode,
    Controller,
    Reason,
)

from .conftest import CAR, CHARGER, NOW, measurements, settings

VOLTS = CHARGER.voltage_v
# Rounding to the nearest 0.1 A can overshoot by half a step on 3 phases where
# the power limit does not bind (D16).
HALF_STEP_W = 0.05 * VOLTS * 3 + 1e-6

modes = st.sampled_from([m for m in ChargeMode if m != ChargeMode.OFF])
house = st.floats(min_value=-15000, max_value=15000, allow_nan=False)
limit = st.floats(min_value=1500, max_value=20000, allow_nan=False)
soc = st.one_of(st.none(), st.floats(min_value=0, max_value=100))
price = st.one_of(st.none(), st.floats(min_value=0, max_value=1))
ems = st.one_of(st.none(), st.floats(min_value=0, max_value=12000))
bridge = st.floats(min_value=0, max_value=3000)


def decide(mode, house_w, *, limit_w=10000, car_soc=50, price_eur=0.2, ems_w=None, **s):
    c = Controller(CHARGER, CAR)
    return c.step(
        settings(mode, power_limit_w=limit_w, **s),
        measurements(house_w, car_soc=car_soc, price=price_eur, ems_signal_w=ems_w),
        NOW,
    )


common = dict(
    mode=modes,
    house_w=house,
    limit_w=limit,
    car_soc=soc,
    price_eur=price,
    ems_w=ems,
    car_aware=st.booleans(),
    ems_control=st.booleans(),
    ems_as_onoff=st.booleans(),
    solar_when_ems_blocks=st.booleans(),
    single_phase_only=st.booleans(),
    solar_bridge_w=bridge,
)


@hsettings(max_examples=400, deadline=None)
@given(**common)
def test_current_is_zero_or_within_range(mode, house_w, **kw):
    out = decide(mode, house_w, **kw)
    assert out.current_a == 0 or 6 <= out.current_a <= 16


@hsettings(max_examples=400, deadline=None)
@given(**common)
def test_current_is_a_whole_step(mode, house_w, **kw):
    out = decide(mode, house_w, **kw)
    assert abs(out.current_a * 10 - round(out.current_a * 10)) < 1e-6


@hsettings(max_examples=400, deadline=None)
@given(**common)
def test_power_never_exceeds_the_headroom(mode, house_w, limit_w, **kw):
    out = decide(mode, house_w, limit_w=limit_w, **kw)
    headroom = max(limit_w - house_w, 0)
    assert out.power_w <= headroom + 1e-6


@hsettings(max_examples=300, deadline=None)
@given(
    mode=st.sampled_from([ChargeMode.MIN_1P, ChargeMode.MIN_3P]),
    house_w=house,
    car_soc=soc,
    price_eur=price,
)
def test_minimum_modes_never_exceed_the_minimum(mode, house_w, car_soc, price_eur):
    out = decide(mode, house_w, car_soc=car_soc, price_eur=price_eur, car_aware=True)
    if out.reason != Reason.EMERGENCY:
        assert out.current_a in (0, 6)


@hsettings(max_examples=300, deadline=None)
@given(
    house_w=st.floats(min_value=-12000, max_value=5000),
    more=st.floats(min_value=0, max_value=5000),
    solar_bridge_w=bridge,
)
def test_more_sun_never_gives_less_current_in_solar_mode(house_w, more, solar_bridge_w):
    base = decide(ChargeMode.SOLAR, house_w, solar_bridge_w=solar_bridge_w)
    sunnier = decide(ChargeMode.SOLAR, house_w - more, solar_bridge_w=solar_bridge_w)
    assert sunnier.power_w >= base.power_w - 1e-6


@hsettings(max_examples=300, deadline=None)
@given(
    mode=modes,
    house_w=house,
    solar_when_ems_blocks=st.booleans(),
    solar_bridge_w=bridge,
)
def test_ems_zero_imports_at_most_half_a_step(
    mode, house_w, solar_when_ems_blocks, solar_bridge_w
):
    out = decide(
        mode,
        house_w,
        ems_w=0,
        ems_control=True,
        solar_when_ems_blocks=solar_when_ems_blocks,
        solar_bridge_w=solar_bridge_w,
    )
    solar = max(-house_w, 0)
    assert out.power_w <= solar + HALF_STEP_W
