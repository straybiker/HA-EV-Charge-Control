"""Energy delivered to the car, split into grid and solar.

The integration only counts kWh. An EMS turns them into cost and
reimbursement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

# Longer gaps (Home Assistant stopped, sensor away) are not integrated: the
# charger power at the start says nothing about the time in between.
MAX_GAP = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class EnergyTotals:
    charged_kwh: float = 0.0
    from_grid_kwh: float = 0.0
    from_solar_kwh: float = 0.0
    # The same, since the start of `day` (local date, ISO). They start again at
    # 0 on the first run of a new day.
    day: str | None = None
    charged_today_kwh: float = 0.0
    from_grid_today_kwh: float = 0.0
    from_solar_today_kwh: float = 0.0


def solar_share(charger_power_w: float | None, house_power_w: float | None) -> float:
    """Part of the charger power covered by export, as a fraction 0..1.

    House power excludes the charger, so its export is what the car can take
    from solar. Unknown values count as grid.
    """
    if not charger_power_w or charger_power_w <= 0 or house_power_w is None:
        return 0.0
    solar_w = min(charger_power_w, max(-house_power_w, 0.0))
    return solar_w / charger_power_w


class EnergyCounter:
    """Integrates charged energy run by run.

    With a charger energy meter the meter delta is used; otherwise the charger
    power of the previous run times the elapsed time (left Riemann sum). The
    grid/solar split uses the conditions of the previous run, when that
    energy was drawn.
    """

    def __init__(self, totals: EnergyTotals | None = None) -> None:
        self.totals = totals or EnergyTotals()
        self._last_time: datetime | None = None
        self._last_power_w: float | None = None
        self._last_share = 0.0
        self._last_meter_kwh: float | None = None

    def update(
        self,
        now: datetime,
        charger_power_w: float | None,
        house_power_w: float | None,
        meter_kwh: float | None = None,
        day: date | None = None,
    ) -> EnergyTotals:
        """Add the energy since the previous run.

        `day` is the local date of `now`; a new day starts the today totals
        at 0. Energy of a step across midnight counts for the new day.
        """
        t = self.totals
        if day is not None and t.day != day.isoformat():
            t = replace(
                t,
                day=day.isoformat(),
                charged_today_kwh=0.0,
                from_grid_today_kwh=0.0,
                from_solar_today_kwh=0.0,
            )
        delta_kwh = self._delta(now, meter_kwh)
        if delta_kwh > 0:
            solar = delta_kwh * self._last_share
            grid = delta_kwh - solar
            t = replace(
                t,
                charged_kwh=t.charged_kwh + delta_kwh,
                from_grid_kwh=t.from_grid_kwh + grid,
                from_solar_kwh=t.from_solar_kwh + solar,
                charged_today_kwh=t.charged_today_kwh + delta_kwh,
                from_grid_today_kwh=t.from_grid_today_kwh + grid,
                from_solar_today_kwh=t.from_solar_today_kwh + solar,
            )
        self.totals = t
        self._last_time = now
        self._last_power_w = charger_power_w
        self._last_share = solar_share(charger_power_w, house_power_w)
        return self.totals

    def _delta(self, now: datetime, meter_kwh: float | None) -> float:
        if meter_kwh is not None:
            last, self._last_meter_kwh = self._last_meter_kwh, meter_kwh
            # A meter that resets or jumps back gives no energy for that step.
            if last is None or meter_kwh < last:
                return 0.0
            return meter_kwh - last
        if self._last_time is None or self._last_power_w is None:
            return 0.0
        elapsed = now - self._last_time
        if elapsed <= timedelta(0) or elapsed > MAX_GAP:
            return 0.0
        return max(self._last_power_w, 0.0) * elapsed.total_seconds() / 3_600_000

    def state(self) -> dict[str, Any]:
        return asdict(self.totals)

    @classmethod
    def restore(cls, state: dict[str, Any] | None) -> EnergyCounter:
        """Rebuild from state(); bad or missing data starts from zero."""
        state = state or {}
        try:
            totals = EnergyTotals(
                **{k: float(v) for k, v in state.items() if k in _NUMBERS}
            )
        except TypeError, ValueError:
            return cls(EnergyTotals())
        day = state.get("day")
        return cls(replace(totals, day=day if isinstance(day, str) else None))


_NUMBERS = set(EnergyTotals.__dataclass_fields__) - {"day"}
