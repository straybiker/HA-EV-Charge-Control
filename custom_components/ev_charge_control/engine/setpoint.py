"""From power to amps, and from a decision to what is written."""

from __future__ import annotations

import math

from .model import ChargerSpec, Phase, Setpoint

# Guards the rounding against float noise such as 5.999999999 for 6 A.
_EPSILON = 1e-9

# The Alfen ignores some 0.1 A decreases but always accepts 0.2 A.
_SMALL_DECREASE_A = 0.15
_WIDENED_DECREASE_A = 0.2


def to_current(
    power_w: float,
    phase: Phase,
    spec: ChargerSpec,
    efficiency: float,
    min_current_a: float,
    max_current_a: float,
    headroom_w: float | None = None,
) -> float:
    """Current for a power, rounded to the charger step (D16).

    Rounded to the nearest step (halves up), so solar is not left unused.
    When rounding up would take more than the headroom under the power
    limit, rounded down instead. Below the minimum the result is 0.
    """
    watts_per_amp = spec.voltage_v * int(phase) * efficiency
    current = min(power_w / watts_per_amp, max_current_a)
    step = spec.current_step_a
    nearest = math.floor(current / step + 0.5 + _EPSILON) * step
    if headroom_w is not None and nearest * watts_per_amp > headroom_w + _EPSILON:
        nearest = math.floor(current / step + _EPSILON) * step
    current = round(nearest, 3)
    return current if current >= min_current_a else 0.0


def filter_write(
    phase: Phase,
    current_a: float,
    commanded_phase: Phase | None,
    commanded_current_a: float | None,
    spec: ChargerSpec,
    min_current_a: float,
    power_update_threshold_w: float,
) -> Setpoint | None:
    """Decide what to write. None when nothing changes.

    A decrease is written at once. An increase must be worth at least the
    power update threshold, so small solar ripples do not cause writes.
    """
    write_phase = commanded_phase is not None and phase != commanded_phase

    current = current_a
    write_current = False
    if commanded_current_a is not None:
        if spec.widen_small_decreases:
            current = _widen_small_decrease(commanded_current_a, current, min_current_a)
        threshold_a = power_update_threshold_w / (spec.voltage_v * int(phase))
        write_current = current < commanded_current_a or (
            current - commanded_current_a >= threshold_a
        )

    if not (write_phase or write_current):
        return None
    return Setpoint(
        phase=phase,
        current_a=current,
        write_phase=write_phase,
        write_current=write_current,
        zero_before_phase_change=(
            write_phase and commanded_phase == Phase.ONE and phase == Phase.THREE
        ),
    )


def _widen_small_decrease(
    commanded_a: float, target_a: float, min_current_a: float
) -> float:
    step = commanded_a - target_a
    widened = round(commanded_a - _WIDENED_DECREASE_A, 1)
    if target_a > 0 and 0 < step < _SMALL_DECREASE_A and widened >= min_current_a:
        return widened
    return target_a
