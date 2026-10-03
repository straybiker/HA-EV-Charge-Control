"""Filter a decision into what is written to the charger.

This is a port of the script "Set EV load balancer charger parameter". The
script owns the minimum-current rule, the Alfen 0.2 A workaround and the
write hysteresis. The adapter owns the I/O and the wait loops.
"""

from __future__ import annotations

from .enums import Phase
from .models import CarSpec, ChargerSpec, Decision, Measurements, Setpoint, Settings

# The Alfen ignores some 0.1 A decreases. A step this small is widened to 0.2 A.
ALFEN_SMALL_STEP_A = 0.15
ALFEN_WIDENED_STEP_A = 0.2


def filter_setpoint(
    d: Decision,
    spec: ChargerSpec,
    car: CarSpec,
    settings: Settings,
    m: Measurements,
) -> Setpoint:
    """Turn a decision into a setpoint. The decision must have should_write."""
    if d.phase is None or d.current_a is None:
        raise ValueError("filter_setpoint needs a decision with phase and current")

    # The script reads the raw car_aware helper, not the validated value.
    min_current = max(
        car.min_current_a if settings.car_aware else spec.min_current_a,
        spec.min_current_a,
    )
    final_current = 0.0 if d.current_a < min_current else float(d.current_a)

    write_phase = m.commanded_phase is not None and d.phase != m.commanded_phase
    zero_before = (
        write_phase and m.commanded_phase == Phase.ONE and d.phase == Phase.THREE
    )

    commanded = m.commanded_current_a if m.commanded_current_a is not None else 0.0
    set_current = _alfen_step_workaround(commanded, final_current, min_current)

    write_current = m.commanded_current_a is not None and _passes_hysteresis(
        spec, settings, d.phase, commanded, set_current
    )

    return Setpoint(
        phase=d.phase,
        current_a=set_current,
        write_phase=write_phase,
        write_current=write_current,
        zero_before_phase_change=zero_before,
        min_current_a=min_current,
    )


def _alfen_step_workaround(
    current_value: float, target_current: float, min_current: float
) -> float:
    """Write a 0.1 A decrease as 0.2 A unless that goes below the minimum."""
    step = current_value - target_current
    if (
        target_current > 0
        and 0 < step < ALFEN_SMALL_STEP_A
        and (current_value - ALFEN_WIDENED_STEP_A) >= min_current
    ):
        return round(current_value - ALFEN_WIDENED_STEP_A, 1)
    return target_current


def _passes_hysteresis(
    spec: ChargerSpec,
    settings: Settings,
    phase: Phase,
    current_value: float,
    target_current: float,
) -> bool:
    """Decreases are written at once. Increases need the power threshold."""
    threshold = settings.power_update_threshold_w / (
        float(spec.nominal_voltage_v) * int(phase)
    )
    return (target_current < current_value) or (
        (target_current - current_value) >= threshold
    )
