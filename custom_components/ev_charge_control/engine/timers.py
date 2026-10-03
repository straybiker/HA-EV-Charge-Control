"""Timer transitions.

Ports of the automations "Phase Switching Timer Control" and "Phase 1p to
3p Sensor Grace Period". Both react to a change of the commanded phase.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .enums import DYNAMIC_MODES, ConnectionState, Phase
from .models import Settings, TimerState

GRACE_SECONDS = 40


def on_commanded_phase_change(
    prev: Phase | None,
    new: Phase | None,
    settings: Settings,
    connection: ConnectionState,
    now: datetime,
    state: TimerState,
) -> TimerState:
    """Return the timer state after the commanded phase changed."""
    phase_switch_until = state.phase_switch_until
    grace_until = state.grace_until

    # Hold 1 -> 3 upgrades for a while after a drop to 1 phase, so a cloudy
    # day does not flap the contactors.
    if (
        new == Phase.ONE
        and prev != Phase.ONE
        and settings.mode in DYNAMIC_MODES
        and connection == ConnectionState.CONNECTED
    ):
        phase_switch_until = now + timedelta(
            minutes=int(settings.phase_switch_delay_min)
        )

    # After a 1 -> 3 upgrade the charger sensors lag. Pause balancing.
    if prev == Phase.ONE and new == Phase.THREE:
        grace_until = now + timedelta(seconds=GRACE_SECONDS)

    return TimerState(phase_switch_until=phase_switch_until, grace_until=grace_until)
