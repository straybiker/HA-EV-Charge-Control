"""Enumerations shared by the decision engine."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ChargeMode(StrEnum):
    """Charge modes. Values equal the YAML input_select options."""

    OFF = "Off"
    MIN_1P = "1-Phase Minimum"
    MIN_3P = "3-Phases Minimum"
    LIMITED = "Limited"
    FAST = "Fast"
    SOLAR = "Solar"
    COMFORT = "Comfort"


# Modes where the phase-switch timer holds a 1 -> 3 phase upgrade.
DYNAMIC_MODES = frozenset({ChargeMode.LIMITED, ChargeMode.SOLAR, ChargeMode.COMFORT})


class Phase(IntEnum):
    """Number of charging phases."""

    ONE = 1
    THREE = 3


class ConnectionState(StrEnum):
    """Charger connection state as the YAML user config maps it."""

    DISCONNECTED = "Disconnected"
    CONNECTED = "Connected"
    ERROR = "Error"
    UNAVAILABLE = "unavailable"

    @classmethod
    def from_mode3(cls, code: str | None) -> ConnectionState:
        """Map an IEC 61851 Mode 3 state code to a connection state."""
        if code in ("A", "E"):
            return cls.DISCONNECTED
        if code in ("B1", "B2", "C1", "D1", "C2", "D2"):
            return cls.CONNECTED
        if code == "F":
            return cls.ERROR
        return cls.UNAVAILABLE


class Reason(StrEnum):
    """Why the engine produced a decision."""

    OK = "ok"
    OFF = "off"
    FAILSAFE = "failsafe"
    REFUSED = "refused"
    NOT_CONNECTED = "not_connected"
    OUTPUTS_UNAVAILABLE = "outputs_unavailable"
    POWER_LIMIT_ZERO = "power_limit_zero"
    GRACE_PERIOD = "grace_period"
