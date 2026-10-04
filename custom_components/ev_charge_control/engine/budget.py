"""How much power the car may take, and from where.

All values are AC power at the charger meter, in watts.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Budget, Measurements, Phase, Settings
from .policy import GridRequest, ModePolicy


@dataclass(frozen=True, slots=True)
class Limits:
    """Power figures that follow from the charger, car and voltage."""

    min_1p_w: float
    min_3p_w: float
    max_w: float

    def minimum_w(self, policy: ModePolicy) -> float:
        """The minimum power of a mode: 3 phases only when it forces them."""
        if policy.forced_phase == Phase.THREE:
            return self.min_3p_w
        return self.min_1p_w


def grid_gate_open(
    settings: Settings, m: Measurements, policy: ModePolicy | None = None
) -> bool:
    """May the car use the grid at all?

    Without a price the price check is skipped (D01); Fast skips it too
    (B19). With EMS control on, a missing or zero EMS signal closes the gate.
    """
    price_ok = (
        (policy is not None and policy.ignores_price)
        or m.price is None
        or m.price <= settings.max_cost_rate
    )
    ems_ok = not settings.ems_control or (m.ems_signal_w or 0) > 0
    return price_ok and ems_ok


def ems_stops_charging(settings: Settings, m: Measurements, policy: ModePolicy) -> bool:
    """EMS at 0 W stops the grid modes, also on solar, unless the user lets
    them charge on solar while EMS blocks (D03, D04).

    Solar modes never stop for EMS: EMS blocks only their bridge.
    """
    return (
        settings.ems_control
        and (m.ems_signal_w or 0) <= 0
        and not settings.solar_when_ems_blocks
        and not policy.solar_first
    )


def plan(
    settings: Settings,
    m: Measurements,
    policy: ModePolicy,
    limits: Limits,
    emergency: bool,
    gate_open: bool,
) -> Budget:
    """Return the power request and where it comes from.

    The request is not yet capped by headroom or hardware.
    """
    assert m.house_power_w is not None
    solar_w = max(-m.house_power_w, 0.0)
    headroom_w = max(settings.power_limit_w - m.house_power_w, 0.0)

    if emergency:
        # The emergency floor overrides gates, EMS and mode caps (D06).
        grid_w = settings.power_limit_w
        return Budget(solar_w, grid_w, solar_w + grid_w, headroom_w)

    if ems_stops_charging(settings, m, policy):
        return Budget(solar_w, 0.0, 0.0, headroom_w)

    grid_w = _grid_allowance(settings, m, policy, limits, gate_open)

    if policy.solar_first:
        request_w, grid_w = _solar_first(solar_w, grid_w, limits.min_1p_w)
        return Budget(solar_w, grid_w, request_w, headroom_w)

    request_w = solar_w + grid_w
    if policy.capped_at_minimum:
        # A Minimum mode takes its minimum and never more (D05).
        request_w = min(request_w, limits.minimum_w(policy))
    return Budget(solar_w, grid_w, request_w, headroom_w)


def _grid_allowance(
    settings: Settings,
    m: Measurements,
    policy: ModePolicy,
    limits: Limits,
    gate_open: bool,
) -> float:
    """Grid power the mode may use after the price gate and the EMS."""
    if not gate_open:
        return 0.0
    match policy.grid:
        case GridRequest.BRIDGE:
            request = settings.solar_bridge_w
        case GridRequest.MINIMUM:
            request = limits.minimum_w(policy)
        case GridRequest.POWER_LIMIT:
            request = settings.power_limit_w
        case GridRequest.HARDWARE_MAX:
            request = limits.max_w
    if settings.ems_control and not settings.ems_as_onoff:
        # EMS budget mode: the signal is the grid budget in watts (D03).
        request = min(request, m.ems_signal_w or 0.0)
    return request


def _solar_first(
    solar_w: float, bridge_allowance_w: float, minimum_w: float
) -> tuple[float, float]:
    """Use all solar; import only to close a small gap to the minimum (B1).

    Returns (request, grid share). Enough sun: solar alone. Sun just short
    of the minimum: import the gap, up to the bridge allowance, and charge
    at exactly the minimum. Otherwise: do not charge.
    """
    if solar_w >= minimum_w:
        return solar_w, 0.0
    gap_w = minimum_w - solar_w
    if gap_w <= bridge_allowance_w:
        return minimum_w, gap_w
    return 0.0, 0.0
