"""What each charge mode asks for. One table instead of scattered branches."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .model import ChargeMode, Phase


class GridRequest(Enum):
    """How much grid power a mode asks for, before gates and EMS."""

    # Only the solar bridge: enough grid to lift a near-miss surplus to the minimum.
    BRIDGE = auto()
    MINIMUM = auto()
    POWER_LIMIT = auto()
    HARDWARE_MAX = auto()


@dataclass(frozen=True, slots=True)
class ModePolicy:
    grid: GridRequest
    # The mode takes its minimum power and never more (except in an emergency).
    capped_at_minimum: bool
    # None: the controller picks 1 or 3 phases from the available power.
    forced_phase: Phase | None
    # Hold a 1 -> 3 upgrade for a while after a drop to 1 phase.
    phase_hold: bool

    @property
    def solar_first(self) -> bool:
        """Solar modes use the grid only through the bridge."""
        return self.grid == GridRequest.BRIDGE


MODE_POLICY: dict[ChargeMode, ModePolicy] = {
    ChargeMode.MIN_1P: ModePolicy(GridRequest.MINIMUM, True, Phase.ONE, False),
    ChargeMode.MIN_3P: ModePolicy(GridRequest.MINIMUM, True, Phase.THREE, False),
    ChargeMode.LIMITED: ModePolicy(GridRequest.POWER_LIMIT, False, None, True),
    ChargeMode.FAST: ModePolicy(GridRequest.HARDWARE_MAX, False, None, False),
    ChargeMode.SOLAR: ModePolicy(GridRequest.BRIDGE, False, None, True),
}


def resolve_mode(
    mode: ChargeMode, car_aware: bool, soc: float | None, comfort_soc: float
) -> ChargeMode:
    """Comfort charges like Limited until the comfort SOC, then like Solar.

    Without trusted car data (D08) Comfort stays Limited. Off has no policy
    and is handled before this is called.
    """
    if mode != ChargeMode.COMFORT:
        return mode
    if car_aware and soc is not None and soc >= comfort_soc:
        return ChargeMode.SOLAR
    return ChargeMode.LIMITED
