"""The load-balancing decision.

This is a port of the automation "EV Charging Load Balancer" in the
EV Load Balancer YAML package. Each helper below carries the name of the
YAML variable it replaces, so the two can be compared line by line. The
behaviour is kept as the YAML runs it, except for the defects marked fixed
in docs/known-defects.md. Read that file before changing a formula.
"""

from __future__ import annotations

from datetime import datetime

from .enums import DYNAMIC_MODES, ChargeMode, ConnectionState, Phase, Reason
from .models import CarSpec, ChargerSpec, Decision, Measurements, Settings, TimerState

# Charger power below this is treated as "not charging" for the efficiency
# estimate, because the measurement is too noisy at low power.
EFFICIENCY_MIN_POWER_W = 1000.0

# The estimate divides measured power by the commanded limit, not by the
# drawn current. A car that draws less than its limit looks inefficient and
# would inflate the target. Real charger losses never go below this (D12).
EFFICIENCY_FLOOR = 0.85


def decide(
    spec: ChargerSpec,
    car: CarSpec,
    settings: Settings,
    m: Measurements,
    timers: TimerState,
    now: datetime,
) -> Decision:
    """Compute the phase and current the charger should get."""
    skip = _run_conditions(settings, m, timers, now)
    if skip is not None:
        return skip

    failsafe = _failsafe(spec, m)
    if failsafe is not None:
        return failsafe

    # 3-Phases Minimum cannot run on a single-phase-only installation (D07).
    if settings.mode == ChargeMode.MIN_3P and settings.single_phase_only:
        return Decision(
            reason=Reason.REFUSED, should_write=True, phase=Phase.ONE, current_a=0.0
        )

    # The run conditions guarantee this.
    assert m.household_power_w is not None
    assert m.applied_current_a is not None
    assert m.charger_power_w is not None

    # The YAML reads the house sensor with | int, which truncates.
    household_power = int(m.household_power_w)
    grid_power_limit = int(settings.power_limit_w)
    voltage = int(spec.nominal_voltage_v)
    mode = settings.mode

    car_aware = _car_aware(settings, car, m)
    max_current = _max_current(spec, car, car_aware)
    min_current = _min_current(spec, car, car_aware)
    efficiency = _charger_efficiency(spec, m)

    current_soc = m.car_soc if m.car_soc is not None else 100
    is_emergency = car_aware and current_soc < settings.emergency_soc
    target_reached = car_aware and current_soc >= settings.target_soc
    ems_signal_on = (m.ems_signal_w or 0.0) > 0
    grid_gate_open = _grid_gate_open(settings, m, is_emergency, ems_signal_on)

    desired_grid_w = _desired_grid_w(
        settings,
        voltage,
        max_current,
        min_current,
        grid_power_limit,
        car_aware,
        current_soc,
        is_emergency,
        target_reached,
        grid_gate_open,
    )
    effective_grid_w = _effective_grid_w(settings, m, desired_grid_w, is_emergency)
    solar_surplus_w = _solar_surplus(
        settings, voltage, min_current, household_power, effective_grid_w
    )
    raw_target_w = _raw_target_power(
        settings,
        effective_grid_w,
        solar_surplus_w,
        is_emergency,
        target_reached,
        ems_signal_on,
        _mode_minimum_w(mode, voltage, min_current),
    )
    final_power_w = _adjusted_available_power_final(
        voltage,
        max_current,
        grid_power_limit,
        household_power,
        efficiency,
        raw_target_w,
    )
    phase = _adjusted_phase_selection(
        settings, m, timers, now, voltage, min_current, final_power_w
    )
    current = _adjusted_current_limit(
        voltage, max_current, min_current, final_power_w, phase
    )

    # Execution rule: Off and a zero result both write 0 A, phase is still sent.
    reason = Reason.OFF if mode == ChargeMode.OFF else Reason.OK
    if mode == ChargeMode.OFF:
        current = 0.0

    return Decision(
        reason=reason,
        should_write=True,
        phase=phase,
        current_a=current,
        efficiency=efficiency,
        is_emergency=is_emergency,
        target_reached=target_reached,
        grid_gate_open=grid_gate_open,
        desired_grid_w=desired_grid_w,
        effective_grid_w=effective_grid_w,
        solar_surplus_w=solar_surplus_w,
        raw_target_w=raw_target_w,
        final_power_w=final_power_w,
        max_current_a=max_current,
        min_current_a=min_current,
    )


def _run_conditions(
    settings: Settings, m: Measurements, timers: TimerState, now: datetime
) -> Decision | None:
    """The automation conditions. A failed condition skips the run."""
    if m.connection != ConnectionState.CONNECTED:
        return Decision(reason=Reason.NOT_CONNECTED, should_write=False)
    if m.commanded_phase is None or m.commanded_current_a is None:
        return Decision(reason=Reason.OUTPUTS_UNAVAILABLE, should_write=False)
    if settings.power_limit_w <= 0:
        return Decision(reason=Reason.POWER_LIMIT_ZERO, should_write=False)
    if timers.grace_active(now):
        return Decision(reason=Reason.GRACE_PERIOD, should_write=False)
    return None


def _failsafe(spec: ChargerSpec, m: Measurements) -> Decision | None:
    """Fall back to the default phase when a base sensor is unavailable.

    The current is never raised: a paused charger stays paused.
    """
    base_sensors = (
        m.household_power_w,
        m.applied_current_a,
        m.charger_power_w,
        m.applied_phases,
    )
    if all(value is not None for value in base_sensors):
        return None
    commanded = m.commanded_current_a if m.commanded_current_a is not None else 0.0
    return Decision(
        reason=Reason.FAILSAFE,
        should_write=True,
        phase=spec.default_phases,
        current_a=min(commanded, float(spec.default_current_a)),
    )


def _car_aware(settings: Settings, car: CarSpec, m: Measurements) -> bool:
    """Car data is trusted only when both battery values are available."""
    return (
        settings.car_aware
        and car.battery_capacity_wh is not None
        and m.car_soc is not None
    )


def _max_current(spec: ChargerSpec, car: CarSpec, car_aware: bool) -> float:
    charger_max = int(spec.max_current_a)
    car_max = int(car.max_current_a)
    return min(car_max, charger_max) if car_aware else charger_max


def _min_current(spec: ChargerSpec, car: CarSpec, car_aware: bool) -> float:
    return (
        max(car.min_current_a, spec.min_current_a) if car_aware else spec.min_current_a
    )


def _charger_efficiency(spec: ChargerSpec, m: Measurements) -> float:
    """Measured power over commanded power, between EFFICIENCY_FLOOR and 1.0."""
    assert m.applied_current_a is not None
    assert m.charger_power_w is not None
    phase_count = 3 if m.applied_phases == Phase.THREE else 1
    if m.applied_current_a > 0 and m.charger_power_w > EFFICIENCY_MIN_POWER_W:
        eff = m.charger_power_w / (
            m.applied_current_a * spec.nominal_voltage_v * phase_count
        )
        return min(max(eff, EFFICIENCY_FLOOR), 1.0)
    return 1.0


def _grid_gate_open(
    settings: Settings, m: Measurements, is_emergency: bool, ems_signal_on: bool
) -> bool:
    """May the car buy from the grid, or only scavenge solar surplus?"""
    if is_emergency:
        return True
    # Without a price the price check does not apply, as if the installation
    # had no price feature at all (D01).
    price_ok = (
        m.electricity_price is None or m.electricity_price <= settings.max_cost_rate
    )
    signal_ok = (not settings.ems_control) or ems_signal_on
    return price_ok and signal_ok


def _desired_grid_w(
    settings: Settings,
    voltage: int,
    max_current: float,
    min_current: float,
    grid_power_limit: int,
    car_aware: bool,
    current_soc: int,
    is_emergency: bool,
    target_reached: bool,
    grid_gate_open: bool,
) -> float:
    """What the selected mode wants from the grid before EMS shaving."""
    p_min_1 = min_current * voltage * 1
    p_min_3 = min_current * voltage * 3
    p_fast = max_current * voltage * 3
    mode = settings.mode

    if mode == ChargeMode.OFF:
        return 0
    if is_emergency:
        return grid_power_limit
    if target_reached:
        return 0
    if not grid_gate_open:
        return 0
    if mode == ChargeMode.MIN_1P:
        return p_min_1
    if mode == ChargeMode.MIN_3P:
        return p_min_3
    if mode == ChargeMode.FAST:
        return p_fast
    if mode == ChargeMode.LIMITED:
        return grid_power_limit
    if mode == ChargeMode.COMFORT:
        return (
            grid_power_limit
            if (not car_aware or current_soc < settings.comfort_soc)
            else 0
        )
    return 0


def _effective_grid_w(
    settings: Settings, m: Measurements, desired_grid_w: float, is_emergency: bool
) -> float:
    """Shave the grid request to the EMS budget."""
    ems_budget_w = m.ems_signal_w if m.ems_signal_w is not None else 0.0
    if is_emergency:
        return desired_grid_w
    if settings.mode == ChargeMode.SOLAR:
        return 0
    if settings.ems_control and not settings.ems_as_onoff:
        return min(desired_grid_w, ems_budget_w)
    return desired_grid_w


def _solar_surplus(
    settings: Settings,
    voltage: int,
    min_current: float,
    household_power: int,
    effective_grid_w: float,
) -> float:
    """Exported power, with the PV-priority grid bridge when active.

    The bridge is grid power, so it gets no more than the grid allowance
    left after the price gate and the EMS. Only real solar surplus bypasses
    them (D02).
    """
    p_min_1 = float(min_current) * float(voltage) * 1
    base_surplus = -household_power
    pv_prio_active = settings.mode == ChargeMode.LIMITED and settings.pv_prioritized
    if pv_prio_active and base_surplus < p_min_1:
        allowed_grid_bridge = min(
            float(settings.pv_prio_threshold_w), max(effective_grid_w, 0)
        )
        return max(base_surplus + allowed_grid_bridge, 0)
    return max(base_surplus, 0)


def _mode_minimum_w(mode: ChargeMode, voltage: int, min_current: float) -> float | None:
    """The fixed power of a Minimum mode, or None for the other modes."""
    if mode == ChargeMode.MIN_1P:
        return min_current * voltage * 1
    if mode == ChargeMode.MIN_3P:
        return min_current * voltage * 3
    return None


def _raw_target_power(
    settings: Settings,
    effective_grid_w: float,
    solar_surplus: float,
    is_emergency: bool,
    target_reached: bool,
    ems_signal_on: bool,
    mode_minimum_w: float | None,
) -> float:
    """Total power the mode asks for before the physical cap."""
    mode = settings.mode
    pv_prio_active = mode == ChargeMode.LIMITED and settings.pv_prioritized

    if mode == ChargeMode.OFF:
        return 0
    if is_emergency:
        return effective_grid_w + solar_surplus
    if target_reached:
        return 0
    if (
        settings.ems_control
        and not ems_signal_on
        and not settings.pv_prioritized
        and mode != ChargeMode.SOLAR
    ):
        return 0
    if pv_prio_active and solar_surplus > 0:
        return solar_surplus
    if mode_minimum_w is not None:
        # A Minimum mode takes the minimum and nothing more. Grid and solar
        # may both supply it, but the surplus never raises it (D05).
        return min(mode_minimum_w, effective_grid_w + solar_surplus)
    return effective_grid_w + solar_surplus


def _adjusted_available_power_final(
    voltage: int,
    max_current: float,
    grid_power_limit: int,
    household_power: int,
    efficiency: float,
    raw_target_power: float,
) -> float:
    """Cap by grid headroom and hardware, both corrected for efficiency."""
    grid_headroom = float(grid_power_limit - household_power)
    max_hardware = float(max_current) * float(voltage) * 3
    raw_target_eff = float(raw_target_power) / efficiency
    headroom_adjusted = (grid_headroom / efficiency) if grid_headroom > 0 else 0
    return min(raw_target_eff, headroom_adjusted, max_hardware)


def _adjusted_phase_selection(
    settings: Settings,
    m: Measurements,
    timers: TimerState,
    now: datetime,
    voltage: int,
    min_current: float,
    final_power: float,
) -> Phase:
    """Pick 1 or 3 phases. Hold an upgrade while the switch timer runs."""
    p_min_3 = min_current * voltage * 3
    mode = settings.mode

    if mode == ChargeMode.MIN_1P:
        desired = Phase.ONE
    elif mode == ChargeMode.MIN_3P:
        desired = Phase.THREE
    elif settings.single_phase_only:
        desired = Phase.ONE
    elif final_power >= p_min_3:
        desired = Phase.THREE
    else:
        desired = Phase.ONE

    current_phase = Phase.THREE if m.commanded_phase == Phase.THREE else Phase.ONE
    if (
        desired > current_phase
        and timers.phase_timer_active(now)
        and mode in DYNAMIC_MODES
    ):
        return current_phase
    return desired


def _adjusted_current_limit(
    voltage: int,
    max_current: float,
    min_current: float,
    final_power: float,
    phase: Phase,
) -> float:
    """Convert power to amps and clamp to the current limits."""
    current = round(final_power / (voltage * int(phase)), 1)
    if current < min_current:
        return 0.0
    if current > max_current:
        return float(max_current)
    return current
