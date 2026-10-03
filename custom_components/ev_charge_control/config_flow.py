"""Config and options flow: map the charger, house, car and price entities."""

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
    CONF_CURRENT_LIMIT,
    CONF_CURRENT_STEP,
    CONF_EMS,
    CONF_FAILSAFE_KEEP_PHASE,
    CONF_FALLBACK_CURRENT,
    CONF_HOUSE_POWER,
    CONF_MAX_CURRENT,
    CONF_MIN_CURRENT,
    CONF_NAME,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_PRICE,
    CONF_PRICE_ATTRIBUTE,
    CONF_VOLTAGE,
    CONF_WIDEN_DECREASES,
    CURRENT_STEPS,
    DEFAULT_CURRENT_STEP,
    DEFAULT_FALLBACK_CURRENT,
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_CURRENT,
    DEFAULT_NAME,
    DEFAULT_VOLTAGE,
    DOMAIN,
)
from .engine import ConnectionState, connection_from_mode3


def _entity(
    domain: str | list[str], device_class: str | None = None
) -> selector.EntitySelector:
    if device_class is None:
        return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    )


def _amps(max_value: int = 80) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=max_value,
            step=1,
            unit_of_measurement="A",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _charger_schema(with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = selector.TextSelector()
    fields |= {
        vol.Required(CONF_CHARGER_POWER): _entity("sensor", SensorDeviceClass.POWER),
        vol.Required(CONF_APPLIED_CURRENT): _entity(
            "sensor", SensorDeviceClass.CURRENT
        ),
        vol.Required(CONF_ACTIVE_PHASES): _entity("sensor"),
        vol.Required(CONF_CONNECTION): _entity(["sensor", "binary_sensor"]),
        vol.Required(CONF_MAX_CURRENT, default=DEFAULT_MAX_CURRENT): _amps(),
        vol.Required(CONF_MIN_CURRENT, default=DEFAULT_MIN_CURRENT): _amps(),
        vol.Required(CONF_FALLBACK_CURRENT, default=DEFAULT_FALLBACK_CURRENT): _amps(),
        vol.Required(CONF_VOLTAGE, default=DEFAULT_VOLTAGE): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=100,
                max=400,
                step=1,
                unit_of_measurement="V",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_CURRENT_STEP, default=DEFAULT_CURRENT_STEP
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(CURRENT_STEPS),
                mode=selector.SelectSelectorMode.LIST,
                translation_key="current_step",
            )
        ),
        vol.Required(CONF_WIDEN_DECREASES, default=False): selector.BooleanSelector(),
        vol.Required(
            CONF_FAILSAFE_KEEP_PHASE, default=False
        ): selector.BooleanSelector(),
    }
    return vol.Schema(fields)


CONTROLS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CURRENT_LIMIT): _entity("number"),
        vol.Required(CONF_PHASE_SELECT): _entity("select"),
    }
)

HOUSEHOLD_SCHEMA = vol.Schema(
    {vol.Required(CONF_HOUSE_POWER): _entity("sensor", SensorDeviceClass.POWER)}
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


def _hass(handler: SchemaCommonFlowHandler):
    return handler.parent_handler.hass


def _own_entry_id(handler: SchemaCommonFlowHandler) -> str | None:
    parent = handler.parent_handler
    if isinstance(parent, SchemaOptionsFlowHandler):
        return parent.config_entry.entry_id
    return None


async def _validate_charger(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    if user_input[CONF_MIN_CURRENT] > user_input[CONF_MAX_CURRENT]:
        raise SchemaFlowError("min_above_max")
    if not (
        user_input[CONF_MIN_CURRENT]
        <= user_input[CONF_FALLBACK_CURRENT]
        <= user_input[CONF_MAX_CURRENT]
    ):
        raise SchemaFlowError("fallback_out_of_range")
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


async def _validate_controls(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    hass = _hass(handler)
    state = hass.states.get(user_input[CONF_PHASE_SELECT])
    if state is None or len(state.attributes.get("options") or []) < 2:
        raise SchemaFlowError("phase_select_unavailable")
    own = _own_entry_id(handler)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (
            entry.entry_id != own
            and entry.options.get(CONF_CURRENT_LIMIT) == user_input[CONF_CURRENT_LIMIT]
        ):
            raise SchemaFlowError("current_entity_in_use")
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


def _steps(first: str, with_name: bool) -> dict[str, SchemaFlowFormStep]:
    return {
        first: SchemaFlowFormStep(
            _charger_schema(with_name),
            validate_user_input=_validate_charger,
            next_step="controls",
        ),
        "controls": SchemaFlowFormStep(
            CONTROLS_SCHEMA, validate_user_input=_validate_controls, next_step="phases"
        ),
        "phases": SchemaFlowFormStep(
            _phases_schema, validate_user_input=_validate_phases, next_step="household"
        ),
        "household": SchemaFlowFormStep(HOUSEHOLD_SCHEMA, next_step="car"),
        "car": SchemaFlowFormStep(
            CAR_SCHEMA, validate_user_input=_validate_car, next_step="price"
        ),
        "price": SchemaFlowFormStep(
            PRICE_SCHEMA, validate_user_input=_validate_price, next_step=None
        ),
    }


CONFIG_FLOW = _steps("user", with_name=True)
OPTIONS_FLOW = _steps("init", with_name=False)


class EvChargeControlConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Set up a charge controller as a helper."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        return cast(str, options[CONF_NAME])
