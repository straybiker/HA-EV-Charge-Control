"""Read Home Assistant states into engine values.

This is the only module that reads other integrations' entities. Anything
unavailable, unknown or unparsable becomes None; the engine decides what
that means.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.util.unit_conversion import EnergyConverter, PowerConverter

from .const import (
    CONF_ACTIVE_PHASES,
    CONF_APPLIED_CURRENT,
    CONF_BATTERY_CAPACITY,
    CONF_CAR_MAX_CURRENT,
    CONF_CAR_MIN_CURRENT,
    CONF_CAR_SOC,
    CONF_CHARGER_POWER,
    CONF_CONNECTION,
    CONF_CURRENT_LIMIT,
    CONF_CURRENT_STEP,
    CONF_EMS,
    CONF_ENERGY_METER,
    CONF_FAILSAFE_KEEP_PHASE,
    CONF_FALLBACK_CURRENT,
    CONF_FALLBACK_PHASE,
    CONF_HOUSE_POWER,
    CONF_MAX_CURRENT_ENTITY,
    CONF_MIN_CURRENT,
    CONF_PEAK_FACTOR,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_PHASE_SWITCH_DELAY,
    CONF_POWER_LIMIT,
    CONF_POWER_UPDATE_THRESHOLD,
    CONF_PRICE,
    CONF_PRICE_ATTRIBUTE,
    CONF_RECALC_INTERVAL,
    CONF_SOLAR_POWER,
    CONF_VOLTAGE,
    CONF_WIDEN_DECREASES,
    CURRENT_STEPS,
    DEFAULT_CURRENT_STEP,
    DEFAULT_FALLBACK_CURRENT,
    DEFAULT_FALLBACK_PHASE,
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_CURRENT,
    DEFAULT_PHASE_SWITCH_DELAY_MIN,
    DEFAULT_POWER_UPDATE_THRESHOLD_W,
    DEFAULT_RECALC_INTERVAL_S,
    DEFAULT_VOLTAGE,
    NUMBER_DOMAINS,
)
from .engine import (
    CarSpec,
    ChargerSpec,
    ConnectionState,
    Measurements,
    Phase,
    connection_from_mode3,
)

_INVALID = (STATE_UNAVAILABLE, STATE_UNKNOWN, "", "none", "None")
_DIGIT = re.compile(r"\d")


def charger_spec(options: Mapping[str, Any]) -> ChargerSpec:
    return ChargerSpec(
        min_current_a=float(options.get(CONF_MIN_CURRENT, DEFAULT_MIN_CURRENT)),
        fallback_current_a=float(
            options.get(CONF_FALLBACK_CURRENT, DEFAULT_FALLBACK_CURRENT)
        ),
        voltage_v=float(options.get(CONF_VOLTAGE, DEFAULT_VOLTAGE)),
        current_step_a=CURRENT_STEPS.get(
            options.get(CONF_CURRENT_STEP, DEFAULT_CURRENT_STEP), 0.1
        ),
        widen_small_decreases=bool(options.get(CONF_WIDEN_DECREASES, False)),
        failsafe_keeps_phase=bool(options.get(CONF_FAILSAFE_KEEP_PHASE, False)),
        fallback_phase=Phase(
            int(options.get(CONF_FALLBACK_PHASE, DEFAULT_FALLBACK_PHASE))
        ),
    )


@dataclass(frozen=True, slots=True)
class Tuning:
    """Fixed values from the setup."""

    power_update_threshold_w: float
    phase_hold_s: float
    recalc_interval_s: float
    peak_factor: float


def tuning(options: Mapping[str, Any]) -> Tuning:
    return Tuning(
        power_update_threshold_w=float(
            options.get(CONF_POWER_UPDATE_THRESHOLD, DEFAULT_POWER_UPDATE_THRESHOLD_W)
        ),
        phase_hold_s=60
        * float(options.get(CONF_PHASE_SWITCH_DELAY, DEFAULT_PHASE_SWITCH_DELAY_MIN)),
        recalc_interval_s=float(
            options.get(CONF_RECALC_INTERVAL, DEFAULT_RECALC_INTERVAL_S)
        ),
        # Optional safety buffer below the power limit; empty means 100 %.
        peak_factor=float(options.get(CONF_PEAK_FACTOR) or 100) / 100,
    )


@dataclass(frozen=True, slots=True)
class Extras:
    """Values read each run that are not controller measurements."""

    max_current_a: float | None = None
    power_limit_w: float | None = None
    meter_kwh: float | None = None
    solar_power_w: float | None = None


def car_spec(options: Mapping[str, Any]) -> CarSpec | None:
    """No SOC sensor means no car data at all."""
    if not options.get(CONF_CAR_SOC):
        return None
    capacity = options.get(CONF_BATTERY_CAPACITY)
    return CarSpec(
        max_current_a=float(options.get(CONF_CAR_MAX_CURRENT, DEFAULT_MAX_CURRENT)),
        min_current_a=float(options.get(CONF_CAR_MIN_CURRENT, DEFAULT_MIN_CURRENT)),
        battery_capacity_wh=float(capacity) * 1000 if capacity else None,
    )


class InputReader:
    """Reads the mapped entities of one config entry."""

    def __init__(self, hass: HomeAssistant, options: Mapping[str, Any]) -> None:
        self._hass = hass
        self._options = dict(options)
        self.last: Measurements | None = None
        self.last_extras: Extras | None = None

    def read_extras(self) -> Extras:
        o = self._options
        self.last_extras = Extras(
            max_current_a=self._number(o[CONF_MAX_CURRENT_ENTITY]),
            power_limit_w=self._power(o.get(CONF_POWER_LIMIT)),
            meter_kwh=self._energy(o.get(CONF_ENERGY_METER)),
            solar_power_w=self._power(o.get(CONF_SOLAR_POWER)),
        )
        return self.last_extras

    @property
    def three_phases(self) -> bool:
        """Whether the phase setting has a 3-phase option (B18)."""
        return bool(self._options.get(CONF_PHASE_OPTION_3))

    @property
    def event_entities(self) -> list[str]:
        """Entities whose changes trigger an immediate run.

        Power sensors are left out on purpose: they update every second.
        """
        return [self._options[CONF_CONNECTION], self._options[CONF_PHASE_SELECT]]

    def read(self) -> Measurements:
        o = self._options
        self.last = Measurements(
            connection=self._connection(o[CONF_CONNECTION]),
            house_power_w=self._power(o[CONF_HOUSE_POWER]),
            charger_power_w=self._power(o[CONF_CHARGER_POWER]),
            applied_current_a=self.applied_current(),
            active_phases=self.active_phases(),
            commanded_phase=self.commanded_phase(),
            commanded_current_a=self.commanded_current(),
            car_soc=self._number(o.get(CONF_CAR_SOC)),
            price=self._number(o.get(CONF_PRICE), o.get(CONF_PRICE_ATTRIBUTE)),
            ems_signal_w=self._power(o.get(CONF_EMS)),
        )
        return self.last

    # Single values, read fresh while a write waits for the charger.

    def applied_current(self) -> float | None:
        return self._number(self._options[CONF_APPLIED_CURRENT])

    def commanded_current(self) -> float | None:
        return self._number(self._options[CONF_CURRENT_LIMIT])

    def active_phases(self) -> Phase | None:
        o = self._options
        return self._phases(
            o[CONF_ACTIVE_PHASES],
            o.get(CONF_PHASE_OPTION_1),
            o.get(CONF_PHASE_OPTION_3),
        )

    def commanded_phase(self) -> Phase | None:
        o = self._options
        return self._commanded_phase(
            o[CONF_PHASE_SELECT], o.get(CONF_PHASE_OPTION_1), o.get(CONF_PHASE_OPTION_3)
        )

    def _state(self, entity_id: str | None) -> State | None:
        if not entity_id:
            return None
        state = self._hass.states.get(entity_id)
        if state is None or state.state in _INVALID:
            return None
        return state

    def _number(
        self, entity_id: str | None, attribute: str | None = None
    ) -> float | None:
        if not entity_id:
            return None
        if attribute:
            state = self._hass.states.get(entity_id)
            raw = state.attributes.get(attribute) if state else None
        else:
            state = self._state(entity_id)
            raw = state.state if state else None
        try:
            return float(raw) if raw is not None else None
        except TypeError, ValueError:
            return None

    def _power(self, entity_id: str | None) -> float | None:
        state = self._state(entity_id)
        value = self._number(entity_id)
        if state is None or value is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit and unit != UnitOfPower.WATT and unit in PowerConverter.VALID_UNITS:
            return PowerConverter.convert(value, unit, UnitOfPower.WATT)
        return value

    def _energy(self, entity_id: str | None) -> float | None:
        """An energy meter in kWh (Wh and MWh are converted)."""
        state = self._state(entity_id)
        value = self._number(entity_id)
        if state is None or value is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        if (
            unit
            and unit != UnitOfEnergy.KILO_WATT_HOUR
            and unit in EnergyConverter.VALID_UNITS
        ):
            return EnergyConverter.convert(value, unit, UnitOfEnergy.KILO_WATT_HOUR)
        return value

    def _connection(self, entity_id: str) -> ConnectionState:
        state = self._state(entity_id)
        if state is None:
            return ConnectionState.UNKNOWN
        if entity_id.startswith("binary_sensor."):
            if state.state == STATE_ON:
                return ConnectionState.CONNECTED
            if state.state == STATE_OFF:
                return ConnectionState.DISCONNECTED
            return ConnectionState.UNKNOWN
        return connection_from_mode3(state.state)

    def _phases(
        self, entity_id: str, option_1: str | None, option_3: str | None
    ) -> Phase | None:
        """Accept 1/3, the phase select's own option texts, or text with a digit."""
        state = self._state(entity_id)
        if state is None:
            return None
        return _parse_phase(state.state, option_1, option_3)

    def _commanded_phase(
        self, entity_id: str, option_1: str | None, option_3: str | None
    ) -> Phase | None:
        state = self._state(entity_id)
        if state is None:
            return None
        numeric = entity_id.split(".", 1)[0] in NUMBER_DOMAINS
        if _is_option(state.state, option_1, numeric):
            return Phase.ONE
        if _is_option(state.state, option_3, numeric):
            return Phase.THREE
        if not option_3:
            # No 3-phase option (B18): any other option is not 1 phase, so the
            # controller writes the 1-phase option back.
            return Phase.THREE
        return None


def _is_option(state: str, option: str | None, numeric: bool) -> bool:
    """A number entity reports 3.0 for the value 3."""
    if option is None:
        return False
    if not numeric:
        return state == option
    try:
        return float(state) == float(option)
    except ValueError:
        return False


def _parse_phase(text: str, option_1: str | None, option_3: str | None) -> Phase | None:
    if text == option_1:
        return Phase.ONE
    if text == option_3:
        return Phase.THREE
    match = _DIGIT.search(text)
    if match and match.group() == "1":
        return Phase.ONE
    if match and match.group() == "3":
        return Phase.THREE
    return None
