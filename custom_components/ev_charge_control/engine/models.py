"""Input, state and output models of the decision engine.

All models are frozen. The engine never mutates its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import ChargeMode, ConnectionState, Phase, Reason


@dataclass(frozen=True, slots=True)
class ChargerSpec:
    """Static charger properties."""

    max_current_a: float
    min_current_a: float = 6
    default_current_a: float = 7
    default_phases: Phase = Phase.ONE
    nominal_voltage_v: int = 230


@dataclass(frozen=True, slots=True)
class CarSpec:
    """Static car properties. battery_capacity_wh is None when unknown."""

    max_current_a: float = 16
    min_current_a: float = 6
    battery_capacity_wh: int | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """User settings. These were input_* helpers in the YAML package."""

    mode: ChargeMode
    power_limit_w: int
    car_aware: bool = False
    pv_prioritized: bool = False
    pv_prio_threshold_w: float = 0
    single_phase_only: bool = False
    ems_control: bool = False
    ems_as_onoff: bool = False
    max_cost_rate: float = 0.30
    emergency_soc: int = 20
    comfort_soc: int = 50
    target_soc: int = 80
    power_update_threshold_w: float = 230
    phase_switch_delay_min: int = 5


@dataclass(frozen=True, slots=True)
class Measurements:
    """Live values. None means the source is unavailable or unknown."""

    household_power_w: float | None
    charger_power_w: float | None
    applied_current_a: float | None
    applied_phases: Phase | None
    connection: ConnectionState
    commanded_phase: Phase | None
    commanded_current_a: float | None
    car_soc: int | None = None
    electricity_price: float | None = None
    ems_signal_w: float | None = None


@dataclass(frozen=True, slots=True)
class TimerState:
    """Deadlines of the two timers. None means idle."""

    phase_switch_until: datetime | None = None
    grace_until: datetime | None = None

    def phase_timer_active(self, now: datetime) -> bool:
        """True while the phase-switch timer runs."""
        return self.phase_switch_until is not None and now < self.phase_switch_until

    def grace_active(self, now: datetime) -> bool:
        """True while the sensor grace period runs."""
        return self.grace_until is not None and now < self.grace_until


@dataclass(frozen=True, slots=True)
class Decision:
    """Result of one balancer run.

    When should_write is False the run was skipped and phase and current_a
    are None. The diagnostic fields are None whenever the calculation did not
    reach them.
    """

    reason: Reason
    should_write: bool
    phase: Phase | None = None
    current_a: float | None = None
    efficiency: float | None = None
    is_emergency: bool | None = None
    target_reached: bool | None = None
    grid_gate_open: bool | None = None
    desired_grid_w: float | None = None
    effective_grid_w: float | None = None
    solar_surplus_w: float | None = None
    raw_target_w: float | None = None
    final_power_w: float | None = None
    max_current_a: float | None = None
    min_current_a: float | None = None


@dataclass(frozen=True, slots=True)
class Setpoint:
    """What the adapter must write to the charger, after filtering."""

    phase: Phase
    current_a: float
    write_phase: bool
    write_current: bool
    zero_before_phase_change: bool
    min_current_a: float
