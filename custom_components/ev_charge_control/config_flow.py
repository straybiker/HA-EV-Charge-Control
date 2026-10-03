"""Config and options flow: charger outputs, then the inputs and fixed values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)

from .const import (
    CONF_ACTIVE_PHASES,
    CONF_APPLIED_CURRENT,
    CONF_BATTERY_CAPACITY,
    CONF_CAR_MAX_CURRENT,
    CONF_CAR_MIN_CURRENT,
    CONF_CAR_SOC,
    CONF_CHARGER_POWER,
    CONF_CONNECTION,
    CONF_CONTROL_OFF,
    CONF_CURRENT_LIMIT,
    CONF_CURRENT_STEP,
    CONF_EMS,
    CONF_ENERGY_METER,
    CONF_FAILSAFE_KEEP_PHASE,
    CONF_FALLBACK_CURRENT,
    CONF_FALLBACK_PHASE,
    CONF_HOUSE_POWER,
    CONF_INITIAL_SETTINGS,
    CONF_MAX_CURRENT_ENTITY,
    CONF_MIN_CURRENT,
    CONF_MONTHLY_PEAK,
    CONF_NAME,
    CONF_PEAK_FACTOR,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_PHASE_SWITCH_DELAY,
    CONF_POWER_UPDATE_THRESHOLD,
    CONF_PRICE,
    CONF_PRICE_ATTRIBUTE,
    CONF_RECALC_INTERVAL,
    CONF_SOLAR_POWER,
    CONF_VOLTAGE,
    CONF_WIDEN_DECREASES,
    CONTROL_OFF_ACTIONS,
    CURRENT_STEPS,
    DEFAULT_CONTROL_OFF,
    DEFAULT_CURRENT_STEP,
    DEFAULT_FALLBACK_CURRENT,
    DEFAULT_FALLBACK_PHASE,
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_CURRENT,
    DEFAULT_NAME,
    DEFAULT_PEAK_FACTOR_PCT,
    DEFAULT_PHASE_SWITCH_DELAY_MIN,
    DEFAULT_POWER_UPDATE_THRESHOLD_W,
    DEFAULT_RECALC_INTERVAL_S,
    DEFAULT_VOLTAGE,
    DOMAIN,
    HARDWARE_MAX_CURRENT,
    PHASES,
)
from .engine import ConnectionState, connection_from_mode3
from .yaml_import import async_import, package_present


def _entity(
    domain: str | list[str], device_class: str | None = None
) -> selector.EntitySelector:
    if device_class is None:
        return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    )


def _number(low: float, high: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=low,
            max=high,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _amps(max_value: int = 80) -> selector.NumberSelector:
    return _number(1, max_value, 1, "A")


def _choice(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.LIST, translation_key=key
        )
    )


IMPORT_YAML = "import_yaml"


def _offer_import(handler: SchemaCommonFlowHandler) -> bool:
    """Only for the first controller on a system that runs the YAML package."""
    hass = _hass(handler)
    return package_present(hass) and not hass.config_entries.async_entries(DOMAIN)


async def _name_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector()
    }
    if _offer_import(handler):
        fields[vol.Required(IMPORT_YAML, default=True)] = selector.BooleanSelector()
    return vol.Schema(fields)


async def _validate_name(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """With the import on, prefill the next steps and keep the settings."""
    if not user_input.pop(IMPORT_YAML, False):
        return user_input
    options, settings = await async_import(_hass(handler))
    return {**options, CONF_INITIAL_SETTINGS: settings, **user_input}


# Outputs: the two entities the controller writes.
OUTPUTS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CURRENT_LIMIT): _entity("number"),
        vol.Required(CONF_PHASE_SELECT): _entity("select"),
    }
)

# Inputs: what the charger reports. The controller only reads them.
INPUTS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CONNECTION): _entity(["sensor", "binary_sensor"]),
        vol.Required(CONF_CHARGER_POWER): _entity("sensor", SensorDeviceClass.POWER),
        vol.Required(CONF_APPLIED_CURRENT): _entity(
            "sensor", SensorDeviceClass.CURRENT
        ),
        vol.Required(CONF_ACTIVE_PHASES): _entity("sensor"),
        vol.Required(CONF_MAX_CURRENT_ENTITY): _entity(
            ["sensor", "number", "input_number"]
        ),
        vol.Optional(CONF_ENERGY_METER): _entity("sensor", SensorDeviceClass.ENERGY),
    }
)

# Fixed values of the charger, and what it gets when something goes wrong.
LIMITS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MIN_CURRENT, default=DEFAULT_MIN_CURRENT): _amps(),
        vol.Required(CONF_VOLTAGE, default=DEFAULT_VOLTAGE): _number(100, 400, 1, "V"),
        vol.Required(CONF_CURRENT_STEP, default=DEFAULT_CURRENT_STEP): _choice(
            list(CURRENT_STEPS), "current_step"
        ),
        vol.Required(CONF_WIDEN_DECREASES, default=False): selector.BooleanSelector(),
        vol.Required(CONF_FALLBACK_CURRENT, default=DEFAULT_FALLBACK_CURRENT): _amps(),
        vol.Required(CONF_FALLBACK_PHASE, default=DEFAULT_FALLBACK_PHASE): _choice(
            PHASES, "fallback_phase"
        ),
        vol.Required(
            CONF_FAILSAFE_KEEP_PHASE, default=False
        ): selector.BooleanSelector(),
        vol.Required(CONF_CONTROL_OFF, default=DEFAULT_CONTROL_OFF): _choice(
            CONTROL_OFF_ACTIONS, "control_off_action"
        ),
    }
)

HOUSEHOLD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOUSE_POWER): _entity("sensor", SensorDeviceClass.POWER),
        vol.Optional(CONF_SOLAR_POWER): _entity("sensor", SensorDeviceClass.POWER),
        # A sensor, or the number many capacity-tariff setups ratchet up.
        vol.Optional(CONF_MONTHLY_PEAK): _entity(["sensor", "input_number", "number"]),
    }
)

CAR_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CAR_SOC): _entity("sensor", SensorDeviceClass.BATTERY),
        vol.Optional(CONF_BATTERY_CAPACITY): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=250,
                step=0.1,
                unit_of_measurement="kWh",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_CAR_MAX_CURRENT, default=DEFAULT_MAX_CURRENT): _amps(),
        vol.Optional(CONF_CAR_MIN_CURRENT, default=DEFAULT_MIN_CURRENT): _amps(),
    }
)

PRICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_PRICE): _entity("sensor"),
        vol.Optional(CONF_PRICE_ATTRIBUTE): selector.TextSelector(),
        vol.Optional(CONF_EMS): _entity("sensor", SensorDeviceClass.POWER),
    }
)


TUNING_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_POWER_UPDATE_THRESHOLD, default=DEFAULT_POWER_UPDATE_THRESHOLD_W
        ): _number(0, 2000, 10, "W"),
        vol.Required(
            CONF_PHASE_SWITCH_DELAY, default=DEFAULT_PHASE_SWITCH_DELAY_MIN
        ): _number(0, 60, 1, "min"),
        vol.Required(CONF_RECALC_INTERVAL, default=DEFAULT_RECALC_INTERVAL_S): _number(
            5, 60, 1, "s"
        ),
        vol.Required(CONF_PEAK_FACTOR, default=DEFAULT_PEAK_FACTOR_PCT): _number(
            50, 100, 1, "%"
        ),
    }
)


def _hass(handler: SchemaCommonFlowHandler):
    return handler.parent_handler.hass


def _numeric_state(handler: SchemaCommonFlowHandler, entity_id: str) -> float | None:
    state = _hass(handler).states.get(entity_id)
    try:
        return float(state.state) if state is not None else None
    except ValueError:
        return None


def _own_entry_id(handler: SchemaCommonFlowHandler) -> str | None:
    parent = handler.parent_handler
    if isinstance(parent, SchemaOptionsFlowHandler):
        return parent.config_entry.entry_id
    return None


async def _validate_outputs(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    hass = _hass(handler)
    state = hass.states.get(user_input[CONF_PHASE_SELECT])
    if state is None or len(state.attributes.get("options") or []) < 2:
        raise SchemaFlowError("phase_select_unavailable")
    # Two controllers writing the same output would overwrite each other at
    # every run, and neither could confirm its writes.
    own = _own_entry_id(handler)
    others = [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != own]
    if any(
        e.options.get(CONF_CURRENT_LIMIT) == user_input[CONF_CURRENT_LIMIT]
        for e in others
    ):
        raise SchemaFlowError("current_entity_in_use")
    if any(
        e.options.get(CONF_PHASE_SELECT) == user_input[CONF_PHASE_SELECT]
        for e in others
    ):
        raise SchemaFlowError("phase_entity_in_use")
    return user_input


async def _validate_inputs(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    connection = user_input[CONF_CONNECTION]
    if connection.startswith("sensor."):
        state = _hass(handler).states.get(connection)
        if (
            state is not None
            and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            and connection_from_mode3(state.state) == ConnectionState.UNKNOWN
        ):
            raise SchemaFlowError("connection_not_mode3")
    return user_input


async def _validate_limits(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    # The maximum comes from the inputs step; check against its value when it
    # has one.
    max_current = _numeric_state(handler, handler.options[CONF_MAX_CURRENT_ENTITY])
    ceiling = min(max_current or HARDWARE_MAX_CURRENT, HARDWARE_MAX_CURRENT)
    if user_input[CONF_MIN_CURRENT] > ceiling:
        raise SchemaFlowError("min_above_max")
    if not (
        user_input[CONF_MIN_CURRENT] <= user_input[CONF_FALLBACK_CURRENT] <= ceiling
    ):
        raise SchemaFlowError("fallback_out_of_range")
    return user_input


async def _phases_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Offer the options of the phase select chosen in the previous step."""
    state = _hass(handler).states.get(handler.options[CONF_PHASE_SELECT])
    options = list(state.attributes.get("options") or []) if state else []
    choice = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )
    return vol.Schema(
        {
            vol.Required(CONF_PHASE_OPTION_1): choice,
            vol.Required(CONF_PHASE_OPTION_3): choice,
        }
    )


async def _validate_phases(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    if user_input[CONF_PHASE_OPTION_1] == user_input[CONF_PHASE_OPTION_3]:
        raise SchemaFlowError("same_phase_option")
    return user_input


async def _validate_car(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    if user_input.get(CONF_CAR_SOC) and not user_input.get(CONF_BATTERY_CAPACITY):
        raise SchemaFlowError("capacity_required")
    if user_input.get(CONF_CAR_MIN_CURRENT, 0) > user_input.get(
        CONF_CAR_MAX_CURRENT, DEFAULT_MAX_CURRENT
    ):
        raise SchemaFlowError("car_min_above_max")
    return user_input


async def _validate_price(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    attribute = user_input.get(CONF_PRICE_ATTRIBUTE)
    price = user_input.get(CONF_PRICE)
    if attribute and not price:
        raise SchemaFlowError("attribute_without_price")
    if attribute and price:
        state = _hass(handler).states.get(price)
        if state is not None and attribute not in state.attributes:
            raise SchemaFlowError("price_attribute_missing")
    return user_input


# Inputs that belong to one charger, car, house budget or load. Another
# controller reading them can work against this one, so setup warns. Solar
# power, the monthly peak and the price are shared by one house by nature.
_PER_CONTROLLER_INPUTS = (
    CONF_CHARGER_POWER,
    CONF_APPLIED_CURRENT,
    CONF_ACTIVE_PHASES,
    CONF_CONNECTION,
    CONF_MAX_CURRENT_ENTITY,
    CONF_ENERGY_METER,
    CONF_HOUSE_POWER,
    CONF_CAR_SOC,
    CONF_EMS,
)


def _shared_inputs(handler: SchemaCommonFlowHandler) -> list[str]:
    """Lines like '- sensor.x (Garage)' for inputs other controllers also use."""
    own = _own_entry_id(handler)
    ours = [handler.options.get(key) for key in _PER_CONTROLLER_INPUTS]
    lines: list[str] = []
    for entry in _hass(handler).config_entries.async_entries(DOMAIN):
        if entry.entry_id == own:
            continue
        theirs = {entry.options.get(key) for key in _PER_CONTROLLER_INPUTS}
        lines += [
            f"- {entity} ({entry.title})"
            for entity in dict.fromkeys(ours)
            if entity and entity in theirs
        ]
    return lines


async def _shared_schema(handler: SchemaCommonFlowHandler) -> vol.Schema | None:
    """An empty confirmation form, or None to skip the step."""
    return vol.Schema({}) if _shared_inputs(handler) else None


async def _shared_placeholders(handler: SchemaCommonFlowHandler) -> dict[str, str]:
    return {"shared": "\n".join(_shared_inputs(handler))}


def _steps(outputs_step: str) -> dict[str, SchemaFlowFormStep]:
    """Outputs first, then inputs, fixed values, house, car, price and tuning.

    The options flow starts at the outputs ("init"); a new controller first
    gets a name ("user").
    """
    return {
        outputs_step: SchemaFlowFormStep(
            OUTPUTS_SCHEMA, validate_user_input=_validate_outputs, next_step="phases"
        ),
        "phases": SchemaFlowFormStep(
            _phases_schema, validate_user_input=_validate_phases, next_step="inputs"
        ),
        "inputs": SchemaFlowFormStep(
            INPUTS_SCHEMA, validate_user_input=_validate_inputs, next_step="limits"
        ),
        "limits": SchemaFlowFormStep(
            LIMITS_SCHEMA, validate_user_input=_validate_limits, next_step="household"
        ),
        "household": SchemaFlowFormStep(HOUSEHOLD_SCHEMA, next_step="car"),
        "car": SchemaFlowFormStep(
            CAR_SCHEMA, validate_user_input=_validate_car, next_step="price"
        ),
        "price": SchemaFlowFormStep(
            PRICE_SCHEMA, validate_user_input=_validate_price, next_step="tuning"
        ),
        "tuning": SchemaFlowFormStep(TUNING_SCHEMA, next_step="shared"),
        # A warning, not an error: one car can use two chargers, for example.
        "shared": SchemaFlowFormStep(
            _shared_schema,
            description_placeholders=_shared_placeholders,
            next_step=None,
        ),
    }


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        _name_schema, validate_user_input=_validate_name, next_step="outputs"
    ),
    **_steps("outputs"),
}
OPTIONS_FLOW = _steps("init")


class EvChargeControlConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Set up a charge controller: one virtual device per charger."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        return cast(str, options[CONF_NAME])
