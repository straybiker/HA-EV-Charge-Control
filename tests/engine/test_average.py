"""Average charging power over a rolling window (for an EMS)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.ev_charge_control.engine.average import (
    WINDOW_DAYS,
    ChargingAverage,
)

from .conftest import NOW

DAY = date(2026, 10, 4)


def _run(avg: ChargingAverage, powers: list[float], day: date = DAY, start=NOW):
    """One run every 10 s with these charger powers."""
    value = None
    for i, power in enumerate(powers):
        value = avg.update(start + timedelta(seconds=10 * i), power, day)
    return value


def test_unknown_before_any_charging() -> None:
    assert _run(ChargingAverage(), [0, 500, 900]) is None


def test_time_weighted_mean_while_charging() -> None:
    # 10 s at 11 kW and 30 s at 3.7 kW: (110 + 111) / 40 = 5.525 kW.
    value = _run(ChargingAverage(), [11000, 3700, 3700, 3700, 0])
    assert value == pytest.approx(5525)


def test_idle_draw_and_ramps_do_not_count() -> None:
    value = _run(ChargingAverage(), [200, 7400, 7400, 800, 300, 0])
    assert value == pytest.approx(7400)


def test_long_gap_is_not_counted() -> None:
    avg = ChargingAverage()
    avg.update(NOW, 7400, DAY)
    avg.update(NOW + timedelta(seconds=10), 11000, DAY)
    # Home Assistant was stopped for an hour: the 11 kW does not count.
    value = avg.update(NOW + timedelta(hours=1), 0, DAY)
    assert value == pytest.approx(7400)


def test_old_days_leave_the_window() -> None:
    avg = ChargingAverage()
    _run(avg, [3700, 3700], day=DAY)
    later = DAY + timedelta(days=WINDOW_DAYS)
    value = _run(avg, [11000, 11000], day=later, start=NOW + timedelta(days=60))
    assert value == pytest.approx(11000)
    assert list(avg.days) == [later.isoformat()]


def test_survives_a_restore() -> None:
    avg = ChargingAverage()
    _run(avg, [7400, 7400, 0])
    restored = ChargingAverage.restore(avg.state())
    assert restored.average_w == pytest.approx(avg.average_w)


def test_bad_stored_data_is_dropped() -> None:
    restored = ChargingAverage.restore(
        {"days": {"nope": [1, 2], DAY.isoformat(): "x", "2026-10-03": [3700, 3600]}}
    )
    assert restored.days == {"2026-10-03": (3700.0, 3600.0)}
