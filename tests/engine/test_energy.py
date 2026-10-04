"""Charged energy, split into grid and solar."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from custom_components.ev_charge_control.engine.energy import (
    MAX_GAP,
    EnergyCounter,
    EnergyTotals,
    solar_share,
)

from .conftest import NOW

A = pytest.approx


def run(counter, seconds, charger_w, house_w, meter=None):
    return counter.update(NOW + timedelta(seconds=seconds), charger_w, house_w, meter)


def test_power_is_integrated_with_the_previous_run():
    c = EnergyCounter()
    run(c, 0, 3600, 500)  # 3.6 kW from the grid
    totals = run(c, 10, 0, 500)  # 10 s later the car stops
    assert totals.charged_kwh == A(0.01)  # 3.6 kW x 10 s
    assert totals.from_grid_kwh == A(0.01)
    assert totals.from_solar_kwh == 0


def test_export_counts_as_solar():
    c = EnergyCounter()
    run(c, 0, 6000, -6000)  # all charger power covered by export
    totals = run(c, 60, 6000, -6000)
    assert totals.from_solar_kwh == A(0.1)
    assert totals.from_grid_kwh == A(0)


def test_partial_solar():
    c = EnergyCounter()
    run(c, 0, 4000, -1000)  # 1 kW from solar, 3 kW from the grid
    totals = run(c, 300, 4000, -1000)  # 5 min = 1/12 h
    assert totals.from_solar_kwh == A(1.0 / 12)
    assert totals.from_grid_kwh == A(3.0 / 12)


def test_long_gap_is_not_integrated():
    c = EnergyCounter()
    run(c, 0, 7000, 0)
    totals = run(c, MAX_GAP.total_seconds() + 1, 7000, 0)
    assert totals.charged_kwh == 0


def test_unknown_power_is_not_integrated():
    c = EnergyCounter()
    run(c, 0, None, 0)
    assert run(c, 10, 7000, 0).charged_kwh == 0


def test_meter_delta_is_used_when_set():
    c = EnergyCounter()
    run(c, 0, 4000, -1000, meter=100.0)
    totals = run(c, 3600, 4000, -1000, meter=104.2)  # meter says 4.2 kWh
    assert totals.charged_kwh == A(4.2)
    assert totals.from_solar_kwh == A(4.2 * 0.25)  # split by the power ratio


def test_meter_reset_is_ignored_for_one_step():
    c = EnergyCounter()
    run(c, 0, 0, 0, meter=100.0)
    run(c, 10, 0, 0, meter=0.5)  # meter reset
    totals = run(c, 20, 0, 0, meter=1.0)
    assert totals.charged_kwh == A(0.5)


def test_meter_outage_is_not_counted_twice():
    """While the meter is away the power counts; the meter's return is a baseline."""
    c = EnergyCounter()
    run(c, 0, 3600, 500, meter=100.0)
    run(c, 10, 3600, 500, meter=None)  # 10 s at 3.6 kW: 0.01 kWh from power
    totals = run(c, 20, 3600, 500, meter=100.5)  # the meter is back
    assert totals.charged_kwh == A(0.01)
    assert run(c, 30, 0, 500, meter=100.6).charged_kwh == A(0.11)


def test_restore_keeps_the_totals():
    c = EnergyCounter()
    run(c, 0, 3600, 500)
    run(c, 3600, 0, 500)
    again = EnergyCounter.restore(c.state())
    assert again.totals == c.totals


def test_restore_from_bad_data_starts_at_zero():
    assert EnergyCounter.restore({"charged_kwh": "x"}).totals == EnergyTotals()
    assert EnergyCounter.restore(None).totals == EnergyTotals()


@pytest.mark.parametrize(
    ("charger", "house", "share"),
    [(4000, -1000, 0.25), (4000, -9000, 1.0), (4000, 500, 0.0), (0, -1000, 0.0)],
)
def test_solar_share(charger, house, share):
    assert solar_share(charger, house) == A(share)


samples = st.lists(
    st.tuples(
        st.floats(min_value=1, max_value=400),  # seconds since previous run
        st.one_of(st.none(), st.floats(min_value=0, max_value=22000)),
        st.one_of(st.none(), st.floats(min_value=-15000, max_value=15000)),
    ),
    min_size=1,
    max_size=40,
)


@given(samples)
def test_charged_is_grid_plus_solar_and_never_decreases(steps):
    c = EnergyCounter()
    t = 0.0
    previous = EnergyTotals()
    for dt, charger, house in steps:
        t += dt
        totals = run(c, t, charger, house)
        assert totals.charged_kwh == A(totals.from_grid_kwh + totals.from_solar_kwh)
        assert totals.charged_kwh >= previous.charged_kwh
        assert totals.from_grid_kwh >= previous.from_grid_kwh - 1e-12
        assert totals.from_solar_kwh >= previous.from_solar_kwh - 1e-12
        previous = totals


def test_today_totals_start_again_on_a_new_day():
    c = EnergyCounter()
    day1, day2 = date(2026, 10, 3), date(2026, 10, 4)
    c.update(NOW, 3600, 500, day=day1)
    first = c.update(NOW + timedelta(seconds=10), 3600, 500, day=day1)
    assert first.charged_today_kwh == A(0.01)
    assert first.day == "2026-10-03"
    second = c.update(NOW + timedelta(seconds=20), 0, 500, day=day2)
    # The step across midnight counts for the new day; the total keeps growing.
    assert second.day == "2026-10-04"
    assert second.charged_today_kwh == A(0.01)
    assert second.charged_kwh == A(0.02)
    assert second.from_grid_today_kwh == A(0.01)


def test_today_totals_survive_a_restore():
    c = EnergyCounter()
    c.update(NOW, 3600, -3600, day=date(2026, 10, 4))
    c.update(NOW + timedelta(seconds=10), 3600, -3600, day=date(2026, 10, 4))
    restored = EnergyCounter.restore(c.state())
    assert restored.totals == c.totals
    assert restored.totals.from_solar_today_kwh == A(0.01)
