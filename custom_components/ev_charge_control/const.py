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
# Device settings imported from the EV Load Balancer package; used only when a
# setting entity is created, before it has a state to restore.
CONF_INITIAL_SETTINGS = "initial_settings"
CONF_CHARGER_POWER = "charger_power_entity"
CONF_APPLIED_CURRENT = "applied_current_entity"
CONF_ACTIVE_PHASES = "active_phases_entity"
CONF_CONNECTION = "connection_entity"
CONF_MAX_CURRENT_ENTITY = "max_current_entity"
CONF_MIN_CURRENT = "min_current_a"
CONF_FALLBACK_CURRENT = "fallback_current_a"
CONF_VOLTAGE = "voltage_v"
CONF_CURRENT_STEP = "current_step_a"
CONF_WIDEN_DECREASES = "widen_small_decreases"
CONF_FAILSAFE_KEEP_PHASE = "failsafe_keeps_phase"
CONF_FALLBACK_PHASE = "fallback_phase"
CONF_ENERGY_METER = "charger_energy_entity"

# Config flow: charger controls
CONF_CURRENT_LIMIT = "current_limit_entity"
CONF_PHASE_SELECT = "phase_select_entity"
CONF_PHASE_OPTION_1 = "phase_option_1"
CONF_PHASE_OPTION_3 = "phase_option_3"
# The phase options step asks these for a switch or a number; the flow
# turns them into the two phase options above.
CONF_PHASE_SWITCH_ON = "phase_switch_on"
CONF_PHASE_VALUE_1 = "phase_value_1"
CONF_PHASE_VALUE_3 = "phase_value_3"
CONF_CONTROL_OFF = "control_off_action"

# Config flow: household
CONF_HOUSE_POWER = "house_power_entity"
CONF_SOLAR_POWER = "solar_power_entity"
CONF_POWER_LIMIT = "power_limit_entity"

# Config flow: car
CONF_CAR_SOC = "car_soc_entity"
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_CAR_MAX_CURRENT = "car_max_current_a"
CONF_CAR_MIN_CURRENT = "car_min_current_a"

# Config flow: price and EMS
CONF_PRICE = "price_entity"
CONF_PRICE_ATTRIBUTE = "price_attribute"
CONF_EMS = "ems_entity"

# Config flow: tuning
CONF_POWER_UPDATE_THRESHOLD = "power_update_threshold_w"
CONF_PHASE_SWITCH_DELAY = "phase_switch_delay_min"
CONF_RECALC_INTERVAL = "recalc_interval_s"
CONF_PEAK_FACTOR = "peak_factor_pct"

# The controller's dashboard in the sidebar.
CONF_DASHBOARD = "dashboard"
CONF_DASHBOARD_REBUILD = "dashboard_rebuild"
CONF_DASHBOARD_TITLE = "dashboard_title"

DEFAULT_NAME = "EV charger controller"
DEFAULT_MAX_CURRENT = 16
DEFAULT_MIN_CURRENT = 6
DEFAULT_FALLBACK_CURRENT = 7
DEFAULT_VOLTAGE = 230
PHASES = ["1", "3"]
# Entity kinds that can switch the charger between 1 and 3 phases.
SELECT_DOMAINS = ("select", "input_select")
SWITCH_DOMAINS = ("switch", "input_boolean")
NUMBER_DOMAINS = ("number", "input_number")
DEFAULT_FALLBACK_PHASE = "1"
# A charger reporting a higher maximum is ignored above this.
HARDWARE_MAX_CURRENT = 32
# Current step options: translation keys may not contain a dot.
CURRENT_STEPS = {"0_1": 0.1, "1": 1.0}
DEFAULT_CURRENT_STEP = "0_1"
# What the charger gets when Control charger is switched off.
CONTROL_OFF_FALLBACK = "fallback"
CONTROL_OFF_KEEP = "keep"
CONTROL_OFF_STOP = "stop"
CONTROL_OFF_ACTIONS = [CONTROL_OFF_FALLBACK, CONTROL_OFF_KEEP, CONTROL_OFF_STOP]
DEFAULT_CONTROL_OFF = CONTROL_OFF_FALLBACK

# Tuning defaults, as in the EV Load Balancer package.
DEFAULT_POWER_UPDATE_THRESHOLD_W = 230
DEFAULT_PHASE_SWITCH_DELAY_MIN = 5
# How often the controller runs. Power sensors do not trigger runs.
DEFAULT_RECALC_INTERVAL_S = 10
