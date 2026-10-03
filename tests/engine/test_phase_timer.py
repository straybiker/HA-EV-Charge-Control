"""Timer transitions. The first nine cases mirror the original trigger test."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.ev_charge_control.engine import (
    GRACE_SECONDS,
    ChargeMode,
    ConnectionState,
    Phase,
    TimerState,
    on_commanded_phase_change,
)

from .conftest import NOW, SETTINGS

CONNECTED = ConnectionState.CONNECTED
DISCONNECTED = ConnectionState.DISCONNECTED


def transition(prev, new, mode=ChargeMode.SOLAR, connection=CONNECTED, state=None):
    settings = replace(SETTINGS, mode=mode)
    return on_commanded_phase_change(
        prev, new, settings, connection, NOW, state or TimerState()
    )


@pytest.mark.parametrize(
    ("prev", "new", "mode", "connection", "starts"),
    [
        (Phase.THREE, Phase.ONE, ChargeMode.SOLAR, CONNECTED, True),
        (Phase.ONE, Phase.THREE, ChargeMode.SOLAR, CONNECTED, False),
        (Phase.THREE, Phase.ONE, ChargeMode.FAST, CONNECTED, False),
        (Phase.THREE, Phase.ONE, ChargeMode.SOLAR, DISCONNECTED, False),
        (None, Phase.ONE, ChargeMode.SOLAR, CONNECTED, True),  # from unavailable
        (Phase.ONE, Phase.ONE, ChargeMode.SOLAR, CONNECTED, False),
        (None, Phase.ONE, ChargeMode.SOLAR, CONNECTED, True),  # startup
        (Phase.THREE, Phase.ONE, ChargeMode.MIN_1P, CONNECTED, False),
        (Phase.THREE, Phase.ONE, ChargeMode.MIN_3P, CONNECTED, False),
        (Phase.THREE, Phase.ONE, ChargeMode.LIMITED, CONNECTED, True),
        (Phase.THREE, Phase.ONE, ChargeMode.COMFORT, CONNECTED, True),
    ],
)
def test_phase_switch_timer_start(prev, new, mode, connection, starts):
    state = transition(prev, new, mode, connection)
    if starts:
        assert state.phase_switch_until == NOW + timedelta(minutes=5)
        assert state.phase_timer_active(NOW)
    else:
        assert state.phase_switch_until is None


def test_phase_switch_delay_follows_settings():
    settings = replace(SETTINGS, mode=ChargeMode.SOLAR, phase_switch_delay_min=10)
    state = on_commanded_phase_change(
        Phase.THREE, Phase.ONE, settings, CONNECTED, NOW, TimerState()
    )
    assert state.phase_switch_until == NOW + timedelta(minutes=10)


@pytest.mark.parametrize(
    ("prev", "new", "mode", "connection", "starts"),
    [
        (Phase.ONE, Phase.THREE, ChargeMode.SOLAR, CONNECTED, True),
        (Phase.ONE, Phase.THREE, ChargeMode.FAST, DISCONNECTED, True),  # no gating
        (Phase.THREE, Phase.ONE, ChargeMode.SOLAR, CONNECTED, False),
        (None, Phase.THREE, ChargeMode.SOLAR, CONNECTED, False),
        (Phase.THREE, Phase.THREE, ChargeMode.SOLAR, CONNECTED, False),
    ],
)
def test_grace_period_start(prev, new, mode, connection, starts):
    state = transition(prev, new, mode, connection)
    if starts:
        assert state.grace_until == NOW + timedelta(seconds=GRACE_SECONDS)
        assert state.grace_active(NOW)
    else:
        assert state.grace_until is None


def test_untouched_timer_is_kept():
    running = TimerState(grace_until=NOW + timedelta(seconds=10))
    state = transition(Phase.THREE, Phase.ONE, state=running)
    assert state.grace_until == running.grace_until
    assert state.phase_switch_until is not None


def test_restart_overwrites_running_timer():
    running = TimerState(phase_switch_until=NOW + timedelta(seconds=10))
    state = transition(Phase.THREE, Phase.ONE, state=running)
    assert state.phase_switch_until == NOW + timedelta(minutes=5)


def test_timer_is_idle_at_and_after_deadline():
    state = TimerState(phase_switch_until=NOW, grace_until=NOW)
    assert not state.phase_timer_active(NOW)
    assert not state.grace_active(NOW)
    assert state.phase_timer_active(NOW - timedelta(seconds=1))
