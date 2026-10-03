"""Power to amps, and the write filter."""

from __future__ import annotations

import pytest

from custom_components.ev_charge_control.engine import ChargerSpec, Phase
from custom_components.ev_charge_control.engine.setpoint import (
    filter_write,
    to_current,
)

SPEC = ChargerSpec()
ALFEN = ChargerSpec(widen_small_decreases=True)
WHOLE_AMPS = ChargerSpec(current_step_a=1.0)


# --- to_current -------------------------------------------------------------


@pytest.mark.parametrize(
    ("power", "phase", "spec", "expected"),
    [
        (9500, Phase.THREE, SPEC, 13.8),  # 13.77 rounds to the nearest step
        (9500, Phase.THREE, WHOLE_AMPS, 14.0),
        (4140, Phase.THREE, SPEC, 6.0),  # exact minimum despite float noise
        (1380, Phase.ONE, SPEC, 6.0),
        (1379, Phase.ONE, SPEC, 6.0),  # 5.996 A rounds up to the minimum
        (1360, Phase.ONE, SPEC, 0.0),  # 5.9 A: below the minimum
        (20000, Phase.ONE, SPEC, 16.0),  # capped at the maximum
    ],
)
def test_to_current(power, phase, spec, expected):
    assert to_current(power, phase, spec, 1.0, 6, 16) == expected


def test_to_current_is_within_half_a_step():
    for power in range(4140, 11040, 7):  # from the 3-phase minimum up
        amps = to_current(power, Phase.THREE, SPEC, 1.0, 6, 16)
        assert abs(amps * 690 - power) <= 0.05 * 690 + 1e-6


def test_rounds_down_when_rounding_up_exceeds_the_headroom():
    # 13.77 A: 13.8 A would draw 9522 W against 9500 W of headroom.
    assert to_current(9500, Phase.THREE, SPEC, 1.0, 6, 16, headroom_w=9500) == 13.7


def test_rounds_up_when_there_is_headroom():
    assert to_current(9500, Phase.THREE, SPEC, 1.0, 6, 16, headroom_w=9600) == 13.8


def test_round_down_at_the_limit_can_drop_below_the_minimum():
    # 6.0 A needs 1380 W; with 1379 W of headroom the current is 0.
    assert to_current(1379, Phase.ONE, SPEC, 1.0, 6, 16, headroom_w=1379) == 0.0


def test_efficiency_raises_the_current_for_the_same_power():
    assert to_current(9000, Phase.THREE, SPEC, 0.9, 6, 16) == 14.5


# --- filter_write ---------------------------------------------------------------


def write(target, commanded=10.0, phase=Phase.THREE, commanded_phase=Phase.THREE, **kw):
    return filter_write(
        phase,
        target,
        commanded_phase,
        commanded,
        kw.get("spec", SPEC),
        6,
        kw.get("threshold", 230),
    )


@pytest.mark.parametrize(
    ("phase", "target", "writes"),
    [
        (Phase.THREE, 10.3, False),  # 0.3 A < 230 W / 690 V
        (Phase.THREE, 10.4, True),
        (Phase.ONE, 10.9, False),  # 0.9 A < 230 W / 230 V
        (Phase.ONE, 11.0, True),
    ],
)
def test_increase_needs_the_threshold(phase, target, writes):
    sp = write(target, phase=phase, commanded_phase=phase)
    assert (sp is not None) is writes


def test_decrease_is_written_at_once():
    sp = write(9.9)
    assert sp is not None and sp.write_current and sp.current_a == 9.9


def test_nothing_to_write():
    assert write(10.0) is None


def test_alfen_small_decrease_is_widened():
    sp = write(9.9, spec=ALFEN)
    assert sp is not None and sp.current_a == 9.8


def test_widening_stops_at_the_minimum():
    sp = write(6.0, commanded=6.1, spec=ALFEN)
    assert sp is not None and sp.current_a == 6.0


def test_widening_ignores_stop():
    sp = write(0.0, spec=ALFEN)
    assert sp is not None and sp.current_a == 0.0


def test_phase_upgrade_zeroes_first():
    sp = write(10.0, commanded_phase=Phase.ONE)
    assert sp is not None and sp.write_phase and sp.zero_before_phase_change


def test_phase_downgrade_does_not_zero_first():
    sp = write(10.0, phase=Phase.ONE)
    assert sp is not None and sp.write_phase and not sp.zero_before_phase_change


def test_unknown_commanded_values_write_nothing():
    assert filter_write(Phase.THREE, 12.0, None, None, SPEC, 6, 230) is None
