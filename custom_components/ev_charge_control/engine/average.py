"""Average charging power over a rolling window, for planning by an EMS.

Energy divided by time while the charger draws more than a threshold, so
the idle draw and the ramps at the start and end of a session do not pull
the average down. Kept per local day; days outside the window drop out.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .energy import MAX_GAP

CHARGING_THRESHOLD_W = 1000.0
WINDOW_DAYS = 60


class ChargingAverage:
    """Time-weighted mean charger power while charging, over WINDOW_DAYS.

    Left Riemann sum, as the energy counter: the power of the previous run
    counts for the time since then. A step is counted on the day it ends.
    """

    def __init__(self, days: dict[str, tuple[float, float]] | None = None) -> None:
        # Local date (ISO) -> (energy in Wh, charging time in s).
        self.days = dict(days or {})
        self._last_time: datetime | None = None
        self._last_power_w: float | None = None

    def update(
        self, now: datetime, charger_power_w: float | None, day: date
    ) -> float | None:
        """Add the step since the previous run and return the average (W)."""
        if self._last_time is not None and self._last_power_w is not None:
            elapsed = (now - self._last_time).total_seconds()
            charging = self._last_power_w > CHARGING_THRESHOLD_W
            if charging and 0 < elapsed <= MAX_GAP.total_seconds():
                wh, seconds = self.days.get(day.isoformat(), (0.0, 0.0))
                self.days[day.isoformat()] = (
                    wh + self._last_power_w * elapsed / 3600,
                    seconds + elapsed,
                )
        self._last_time = now
        self._last_power_w = charger_power_w
        oldest = (day - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        self.days = {d: v for d, v in self.days.items() if d >= oldest}
        return self.average_w

    @property
    def average_w(self) -> float | None:
        """None until the car has charged above the threshold in the window."""
        seconds = sum(s for _, s in self.days.values())
        if seconds <= 0:
            return None
        return sum(wh for wh, _ in self.days.values()) * 3600 / seconds

    def state(self) -> dict[str, Any]:
        return {"days": {d: [wh, s] for d, (wh, s) in self.days.items()}}

    @classmethod
    def restore(cls, state: dict[str, Any] | None) -> ChargingAverage:
        """Rebuild from state(); bad entries are dropped."""
        days: dict[str, tuple[float, float]] = {}
        raw = (state or {}).get("days")
        if isinstance(raw, dict):
            for d, value in raw.items():
                try:
                    date.fromisoformat(d)
                    wh, seconds = (float(x) for x in value)
                except TypeError, ValueError:
                    continue
                days[d] = (wh, seconds)
        return cls(days)
