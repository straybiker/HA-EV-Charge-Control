"""Value types of the decision engine. All are immutable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum


class ChargeMode(StrEnum):
    """Charge modes. The values are the keys Home Assistant translates."""

    OFF = "off"
    MIN_1P = "min_1p"
    MIN_3P = "min_3p"
    LIMITED = "limited"
    FAST = "fast"
    SOLAR = "solar"
    COMFORT = "comfort"


class Phase(IntEnum):
    """Number of charging phases."""

    ONE = 1
    THREE = 3


class ConnectionState(StrEnum):
    """Whether a car is plugged in."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    UNKNOWN = "unknown"


def connection_from_mode3(code: str | None) -> ConnectionState:
    """Map an IEC 61851 Mode 3 state code (A, B1 … D2, E, F)."""
    if code in ("A", "E"):
        return ConnectionState.DISCONNECTED
    if code in ("B1", "B2", "C1", "C2", "D1", "D2"):
        return ConnectionState.CONNECTED
    if code == "F":
        return ConnectionState.ERROR
    return ConnectionState.UNKNOWN


class Reason(StrEnum):
    """Why the controller chose its output. Shown on the decision sensor."""

    CHARGING = "charging"
    EMERGENCY = "emergency"
    OFF = "off"
    TARGET_REACHED = "target_reached"
    GRID_BLOCKED = "grid_blocked"
    INSUFFICIENT_POWER = "insufficient_power"
    REFUSED = "refused"
    FAILSAFE = "failsafe"
    NOT_CONNECTED = "not_connected"
    CHARGER_UNAVAILABLE = "charger_unavailable"
    NO_POWER_LIMIT = "no_power_limit"
    GRACE_PERIOD = "grace_period"


@dataclass(frozen=True, slots=True)
class ChargerSpec:
    """What the charger can do. Set once in the config flow."""

    max_current_a: float = 16
    min_current_a: float = 6
    fallback_current_a: float = 7
    fallback_phase: Phase = Phase.ONE
    # On a sensor fault: keep the current phase instead of the fallback phase.
    failsafe_keeps_phase: bool = False
    voltage_v: float = 230
    # Smallest current change the charger accepts: 0.1 A or 1 A.
    current_step_a: float = 0.1
    # Some chargers (Alfen) ignore a few 0.1 A decreases; write them as 0.2 A.
    widen_small_decreases: bool = False


@dataclass(frozen=True, slots=True)
class CarSpec:
    """What the car can do. Optional; without it the SOC rules do nothing."""

    max_current_a: float = 16
    min_current_a: float = 6
    battery_capacity_wh: float | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings. In Home Assistant these are entities on the device."""

    mode: ChargeMode = ChargeMode.OFF
    power_limit_w: float = 5000
    max_cost_rate: float = 0.30
    target_soc: float = 80
    comfort_soc: float = 50
    emergency_soc: float = 20
    # Grid power Solar mode may import to lift a near-miss surplus to the minimum.
    solar_bridge_w: float = 0
    car_aware: bool = False
    # With EMS at 0 W, grid modes keep charging on solar instead of stopping.
    solar_when_ems_blocks: bool = False
    single_phase_only: bool = False
    ems_control: bool = False
    ems_as_onoff: bool = False
    power_update_threshold_w: float = 230
    phase_hold_s: float = 300


@dataclass(frozen=True, slots=True)
class Measurements:
    """Live values. None means unavailable or unknown."""

    connection: ConnectionState
    house_power_w: float | None
    charger_power_w: float | None
    applied_current_a: float | None
    active_phases: Phase | None
    commanded_phase: Phase | None
    commanded_current_a: float | None
    car_soc: float | None = None
    price: float | None = None
    ems_signal_w: float | None = None


@dataclass(frozen=True, slots=True)
class Budget:
    """Where the target power comes from. Feeds the diagnostic sensors."""

    solar_w: float
    grid_w: float
    request_w: float
    headroom_w: float


@dataclass(frozen=True, slots=True)
class Setpoint:
    """What to write to the charger after filtering."""

    phase: Phase
    current_a: float
    write_phase: bool
    write_current: bool
    zero_before_phase_change: bool


@dataclass(frozen=True, slots=True)
class Output:
    """Result of one controller step.

    phase and current_a are None when the step was skipped. setpoint is
    None when nothing must be written.
    """

    reason: Reason
    phase: Phase | None
    current_a: float | None
    power_w: float | None
    efficiency: float
    grid_allowed: bool | None = None
    emergency: bool = False
    target_reached: bool = False
    budget: Budget | None = None
    setpoint: Setpoint | None = None
    phase_hold_until: datetime | None = None
    grace_until: datetime | None = None
