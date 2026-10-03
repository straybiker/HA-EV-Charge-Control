"""Phase choice."""

from __future__ import annotations

from .model import Phase, Settings
from .policy import ModePolicy


def choose_phase(
    policy: ModePolicy,
    settings: Settings,
    current_3p_a: float,
    min_current_a: float,
    commanded: Phase | None,
    hold_active: bool,
) -> Phase:
    """Pick 1 or 3 phases.

    Three phases when the available power gives at least the minimum current
    on three phases. A held upgrade stays on the commanded phase.
    """
    if policy.forced_phase is not None:
        return policy.forced_phase
    if settings.single_phase_only:
        return Phase.ONE
    desired = Phase.THREE if current_3p_a >= min_current_a else Phase.ONE
    if (
        desired == Phase.THREE
        and commanded == Phase.ONE
        and policy.phase_hold
        and hold_active
    ):
        return Phase.ONE
    return desired
