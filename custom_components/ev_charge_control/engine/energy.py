"""Energy delivered to the car, split into grid and solar.

The integration only counts kWh. An EMS turns them into cost and
reimbursement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

# Longer gaps (Home Assistant stopped, sensor away) are not integrated: the
# charger power at the start says nothing about the time in between.
MAX_GAP = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class EnergyTotals:
    charged_kwh: float = 0.0
    from_grid_kwh: float = 0.0
    from_solar_kwh: float = 0.0


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
    ) -> EnergyTotals:
        delta_kwh = self._delta(now, meter_kwh)
        if delta_kwh > 0:
            solar = delta_kwh * self._last_share
            self.totals = EnergyTotals(
                charged_kwh=self.totals.charged_kwh + delta_kwh,
                from_grid_kwh=self.totals.from_grid_kwh + delta_kwh - solar,
                from_solar_kwh=self.totals.from_solar_kwh + solar,
            )
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
        try:
            totals = EnergyTotals(
                **{k: float(v) for k, v in (state or {}).items() if k in _FIELDS}
            )
        except TypeError, ValueError:
            totals = EnergyTotals()
        return cls(totals)


_FIELDS = set(EnergyTotals.__dataclass_fields__)
