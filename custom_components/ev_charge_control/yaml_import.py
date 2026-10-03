"""Import the setup from the EV Load Balancer YAML package.

The package keeps its configuration in template sensors. Their rendered
attributes give the outputs, fixed values and settings. The input entities
only appear in the templates themselves, so they come from the package's
user-config file when it can be found in the configuration folder.

The parsing functions are pure, so they are tested without Home Assistant.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    CONF_FALLBACK_CURRENT,
    CONF_FALLBACK_PHASE,
    CONF_HOUSE_POWER,
    CONF_MAX_CURRENT_ENTITY,
    CONF_MIN_CURRENT,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_PHASE_SWITCH_DELAY,
    CONF_POWER_LIMIT,
    CONF_POWER_UPDATE_THRESHOLD,
    CONF_PRICE,
    CONF_PRICE_ATTRIBUTE,
    CONF_SOLAR_POWER,
    CONF_VOLTAGE,
    CONF_WIDEN_DECREASES,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

CHARGER = "sensor.ev_load_balancer_charger"
HOUSE = "sensor.ev_load_balancer_house"
CAR = "sensor.ev_load_balancer_car"
BALANCER = "sensor.ev_load_balancer"

# The template sensors' unique_id in the user-config file.
_BLOCKS = {
    "charger": "ev_load_balancer_charger",
    "house": "ev_load_balancer_house",
    "car": "ev_load_balancer_car",
    "balancer": "ev_load_balancer",
}

# Package attribute -> setup option, per template sensor.
_INPUTS = {
    "charger": {
        "active_power": CONF_CHARGER_POWER,
        "current_input": CONF_APPLIED_CURRENT,
        "phases_input": CONF_ACTIVE_PHASES,
        "connection_state": CONF_CONNECTION,
        "max_current": CONF_MAX_CURRENT_ENTITY,
    },
    "house": {"state": CONF_HOUSE_POWER, "pv_power": CONF_SOLAR_POWER},
    "car": {"battery_percentage": CONF_CAR_SOC},
    "balancer": {
        "power_limit": CONF_POWER_LIMIT,
        "ems_signal": CONF_EMS,
        "electricity_price": CONF_PRICE,
    },
}

_ENTITY = re.compile(r"\b((?:sensor|binary_sensor|number|input_number)\.[a-z0-9_]+)")
_STATE_ATTR = re.compile(
    r"state_attr\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
_DEFINES_CHARGER = re.compile(
    r"^\s*(?:-\s+)?unique_id:\s*['\"]?ev_load_balancer_charger['\"]?\s*$", re.MULTILINE
)
_KEY = re.compile(r"^(\s*)(?:-\s+)?([a-z_0-9]+):(.*)$")

# Package charge mode -> integration charge mode.
_MODES = {
    "Off": "off",
    "1-Phase Minimum": "min_1p",
    "3-Phases Minimum": "min_3p",
    "Limited": "limited",
    "Fast": "fast",
    "Solar": "solar",
    "Comfort": "comfort",
}


# --- pure parsing ---------------------------------------------------------------------


def parse_package(text: str) -> dict[str, dict[str, str]]:
    """The raw value text of each key, per template sensor of the user config.

    Nested keys, such as those under ``attributes:``, count as keys of the
    block. A multi-line template (``>`` or ``|``) runs until a line at the
    indent of its key or lower, so its lines stay with it.
    """
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    key: str | None = None
    key_indent = 0
    in_scalar = False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _KEY.match(line)
        if match and not (in_scalar and len(match.group(1)) > key_indent):
            indent, name, rest = match.groups()
            rest = rest.strip()
            if name == "unique_id":
                current = blocks.setdefault(rest.strip("'\""), {})
                key, in_scalar = None, False
                continue
            if current is not None:
                key, key_indent = name, len(indent)
                in_scalar = rest.startswith((">", "|"))
                current[key] = rest
            continue
        if current is not None and key is not None and line.strip():
            current[key] += "\n" + line.strip()
    return blocks


def entity_in(raw: str | None) -> str | None:
    """The first entity a template value reads."""
    match = _ENTITY.search(raw or "")
    return match.group(1) if match else None


def input_options(text: str) -> dict[str, Any]:
    """Setup options for the input entities found in the user-config file."""
    blocks = parse_package(text)
    options: dict[str, Any] = {}
    for block, keys in _INPUTS.items():
        values = blocks.get(_BLOCKS[block], {})
        for attribute, option in keys.items():
            entity = entity_in(values.get(attribute))
            if entity:
                options[option] = entity
    price = _STATE_ATTR.search(
        blocks.get(_BLOCKS["balancer"], {}).get("electricity_price", "")
    )
    if price:
        options[CONF_PRICE] = price.group(1)
        options[CONF_PRICE_ATTRIBUTE] = price.group(2)
    return options


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "on", "yes", "1")
    return bool(value)


def value_options(
    charger: Mapping[str, Any], car: Mapping[str, Any], balancer: Mapping[str, Any]
) -> dict[str, Any]:
    """Setup options from the rendered attributes of the package's sensors."""
    options: dict[str, Any] = {}
    for option, attribute in (
        (CONF_CURRENT_LIMIT, "current_output"),
        (CONF_PHASE_SELECT, "phases_output"),
        (CONF_PHASE_OPTION_1, "phase_1_state"),
        (CONF_PHASE_OPTION_3, "phase_3_state"),
    ):
        if isinstance(charger.get(attribute), str) and charger[attribute]:
            options[option] = charger[attribute]
    for option, source, attribute in (
        (CONF_MIN_CURRENT, charger, "min_current"),
        (CONF_FALLBACK_CURRENT, charger, "default_current"),
        (CONF_VOLTAGE, charger, "nominal_voltage"),
        (CONF_CAR_MAX_CURRENT, car, "max_current"),
        (CONF_CAR_MIN_CURRENT, car, "min_current"),
        (CONF_POWER_UPDATE_THRESHOLD, balancer, "power_update_threshold"),
        (CONF_PHASE_SWITCH_DELAY, balancer, "phase_switch_delay"),
    ):
        number = _number(source.get(attribute))
        if number is not None:
            options[option] = number
    phases = _number(charger.get("default_phases"))
    if phases in (1, 3):
        options[CONF_FALLBACK_PHASE] = str(int(phases))
    capacity = _number(car.get("battery_capacity_wh"))
    if capacity:
        options[CONF_BATTERY_CAPACITY] = capacity / 1000
    if CONF_CURRENT_LIMIT in options:
        # The package always wrote in 0.1 A steps and widened small decreases.
        options[CONF_CURRENT_STEP] = "0_1"
        options[CONF_WIDEN_DECREASES] = True
    return options


def initial_settings(mode: str | None, balancer: Mapping[str, Any]) -> dict[str, Any]:
    """Device settings, keyed by setting entity, from the package's settings.

    Control charger is never imported: a new device starts in shadow mode.
    """
    pv_first = _bool(balancer.get("pv_prioritized"))
    settings: dict[str, Any] = {}
    if mode in _MODES:
        settings["charge_mode"] = _MODES[mode]
        # Limited with solar priority is the package's way to charge solar first
        # with a bridge; that is Solar mode here.
        if mode == "Limited" and pv_first:
            settings["charge_mode"] = "solar"
    for key, attribute in (
        ("max_charging_cost", "max_cost_rate"),
        ("target_soc", "target_soc"),
        ("comfort_soc", "comfort_soc"),
        ("emergency_soc", "emergency_soc"),
    ):
        number = _number(balancer.get(attribute))
        if number is not None:
            settings[key] = number
    bridge = _number(balancer.get("pv_prio_threshold"))
    if bridge is not None:
        # The package's Solar mode was pure solar.
        settings["solar_bridge"] = 0.0 if mode == "Solar" else bridge
    for key, attribute in (
        ("car_aware", "car_aware"),
        ("single_phase_only", "single_phase_only"),
        ("ems_control", "ems_control"),
        ("ems_as_onoff", "ems_as_onoff"),
    ):
        if attribute in balancer:
            settings[key] = _bool(balancer[attribute])
    if "pv_prioritized" in balancer:
        settings["solar_when_ems_blocks"] = pv_first
    return settings


# --- Home Assistant -------------------------------------------------------------------


def package_present(hass: HomeAssistant) -> bool:
    return hass.states.get(CHARGER) is not None


def _find_user_config(config_dir: str) -> str | None:
    """The text of the YAML file that defines the package's charger sensor.

    Looks in the configuration folder and in packages folders below it, not
    in the whole tree, so the search stays fast.
    """
    root = Path(config_dir)
    candidates = [*root.glob("*.yaml"), *root.glob("packages/**/*.yaml")]
    for path in sorted(candidates):
        try:
            text = path.read_text("utf-8")
        except OSError, UnicodeDecodeError:
            continue
        # The package's logic file reads the same sensor; only the file that
        # defines it holds the input entities.
        if _DEFINES_CHARGER.search(text):
            return text
    return None


async def async_import(hass: HomeAssistant) -> tuple[dict[str, Any], dict[str, Any]]:
    """Setup options and initial device settings from the package."""

    def attributes(entity_id: str) -> Mapping[str, Any]:
        state = hass.states.get(entity_id)
        return state.attributes if state else {}

    options = value_options(attributes(CHARGER), attributes(CAR), attributes(BALANCER))
    text = await hass.async_add_executor_job(_find_user_config, hass.config.config_dir)
    if text:
        options |= input_options(text)
    balancer = hass.states.get(BALANCER)
    settings = initial_settings(
        balancer.state if balancer else None, attributes(BALANCER)
    )
    return options, settings
