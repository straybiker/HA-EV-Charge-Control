"""Constants for the EV Charge Control integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "ev_charge_control"
LOGGER = logging.getLogger(__package__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Config flow: charger
CONF_NAME = "name"
CONF_CHARGER_POWER = "charger_power_entity"
CONF_APPLIED_CURRENT = "applied_current_entity"
CONF_ACTIVE_PHASES = "active_phases_entity"
CONF_CONNECTION = "connection_entity"
CONF_MAX_CURRENT = "max_current_a"
CONF_MIN_CURRENT = "min_current_a"
CONF_FALLBACK_CURRENT = "fallback_current_a"
CONF_VOLTAGE = "voltage_v"
CONF_CURRENT_STEP = "current_step_a"
CONF_WIDEN_DECREASES = "widen_small_decreases"
CONF_FAILSAFE_KEEP_PHASE = "failsafe_keeps_phase"

# Config flow: charger controls
CONF_CURRENT_LIMIT = "current_limit_entity"
CONF_PHASE_SELECT = "phase_select_entity"
CONF_PHASE_OPTION_1 = "phase_option_1"
CONF_PHASE_OPTION_3 = "phase_option_3"

# Config flow: household
CONF_HOUSE_POWER = "house_power_entity"
CONF_SOLAR_POWER = "solar_power_entity"

# Config flow: car
CONF_CAR_SOC = "car_soc_entity"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_CAR_MAX_CURRENT = "car_max_current_a"
CONF_CAR_MIN_CURRENT = "car_min_current_a"

# Config flow: price and EMS
CONF_PRICE = "price_entity"
CONF_PRICE_ATTRIBUTE = "price_attribute"
CONF_EMS = "ems_entity"

DEFAULT_NAME = "EV charger controller"
DEFAULT_MAX_CURRENT = 16
DEFAULT_MIN_CURRENT = 6
DEFAULT_FALLBACK_CURRENT = 7
DEFAULT_VOLTAGE = 230
# Current step options: translation keys may not contain a dot.
CURRENT_STEPS = {"0_1": 0.1, "1": 1.0}
DEFAULT_CURRENT_STEP = "0_1"

# Runtime: how often the controller runs. Power sensors do not trigger runs.
DEFAULT_RECALC_INTERVAL_S = 10
