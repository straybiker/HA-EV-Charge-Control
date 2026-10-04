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
from homeassistant.util.unit_conversion import EnergyConverter, PowerConverter

from . import dashboard
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
    CONF_DASHBOARD,
    CONF_DASHBOARD_REBUILD,
    CONF_DASHBOARD_TITLE,
    CONF_EMS,
    CONF_ENERGY_METER,
    CONF_FAILSAFE_KEEP_PHASE,
    CONF_FALLBACK_CURRENT,
    CONF_FALLBACK_PHASE,
    CONF_HOUSE_POWER,
    CONF_INITIAL_SETTINGS,
    CONF_MAX_CURRENT_ENTITY,
    CONF_MIN_CURRENT,
    CONF_NAME,
    CONF_PEAK_FACTOR,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_PHASE_SWITCH_DELAY,
    CONF_PHASE_SWITCH_ON,
    CONF_PHASE_VALUE_1,
    CONF_PHASE_VALUE_3,
    CONF_POWER_LIMIT,
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
    DEFAULT_PHASE_SWITCH_DELAY_MIN,
    DEFAULT_POWER_UPDATE_THRESHOLD_W,
    DEFAULT_RECALC_INTERVAL_S,
    DEFAULT_VOLTAGE,
    DOMAIN,
    HARDWARE_MAX_CURRENT,
    NUMBER_DOMAINS,
    PHASES,
    SELECT_DOMAINS,
    SWITCH_DOMAINS,
)
from .engine import ConnectionState, Phase, connection_from_mode3
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
    fields[vol.Required(CONF_DASHBOARD, default=True)] = selector.BooleanSelector()
    fields[vol.Optional(CONF_DASHBOARD_TITLE, default=dashboard.NAME)] = (
        selector.TextSelector()
    )
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
        vol.Required(CONF_CURRENT_LIMIT): _entity(list(NUMBER_DOMAINS)),
        vol.Required(CONF_PHASE_SELECT): _entity(
            [*SELECT_DOMAINS, *SWITCH_DOMAINS, *NUMBER_DOMAINS]
        ),
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
        # A helper or an EMS entity, for example the capacity tariff peak.
        vol.Required(CONF_POWER_LIMIT): _entity(["sensor", "input_number", "number"]),
        vol.Optional(CONF_PEAK_FACTOR): _number(50, 100, 1, "%"),
        vol.Optional(CONF_SOLAR_POWER): _entity("sensor", SensorDeviceClass.POWER),
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


def _check_unit(
    handler: SchemaCommonFlowHandler,
    entity_id: str | None,
    units: set[str],
    error: str,
) -> None:
    """A value without a known unit would be read in the wrong unit.

    Entities that have no state yet are not checked: the controller reads
    them once they report.
    """
    if not entity_id:
        return
    state = _hass(handler).states.get(entity_id)
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return
    if state.attributes.get("unit_of_measurement") not in units:
        raise SchemaFlowError(error)


def _check_power_units(
    handler: SchemaCommonFlowHandler, *entity_ids: str | None
) -> None:
    for entity_id in entity_ids:
        _check_unit(
            handler, entity_id, PowerConverter.VALID_UNITS, "power_unit_unknown"
        )


def _own_entry_id(handler: SchemaCommonFlowHandler) -> str | None:
    parent = handler.parent_handler
    if isinstance(parent, SchemaOptionsFlowHandler):
        return parent.config_entry.entry_id
    return None


async def _validate_outputs(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    hass = _hass(handler)
    limit = hass.states.get(user_input[CONF_CURRENT_LIMIT])
    # The controller stops the car with 0 A; a number that starts higher
    # would refuse every stop.
    if limit is not None and (limit.attributes.get("min") or 0) > 0:
        raise SchemaFlowError("current_limit_min_not_zero")
    phase_entity = user_input[CONF_PHASE_SELECT]
    if _domain(phase_entity) in SELECT_DOMAINS:
        state = hass.states.get(phase_entity)
        if state is None or not state.attributes.get("options"):
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
    _check_power_units(handler, user_input[CONF_CHARGER_POWER])
    _check_unit(
        handler,
        user_input.get(CONF_ENERGY_METER),
        EnergyConverter.VALID_UNITS,
        "energy_unit_unknown",
    )
    return user_input


async def _validate_household(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    _check_power_units(
        handler,
        user_input[CONF_HOUSE_POWER],
        user_input[CONF_POWER_LIMIT],
        user_input.get(CONF_SOLAR_POWER),
    )
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
    if not handler.options.get(CONF_PHASE_OPTION_3) and user_input[
        CONF_FALLBACK_PHASE
    ] != str(int(Phase.ONE)):
        raise SchemaFlowError("fallback_needs_three_phases")
    limit = _hass(handler).states.get(handler.options[CONF_CURRENT_LIMIT])
    number_step = limit.attributes.get("step") if limit is not None else None
    if (
        number_step
        and float(number_step) > CURRENT_STEPS[user_input[CONF_CURRENT_STEP]]
    ):
        raise SchemaFlowError("current_step_too_fine")
    return user_input


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


async def _phases_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    """Ask how the phase setting says 1 and 3 phases; it depends on its kind."""
    phase_entity = handler.options[CONF_PHASE_SELECT]
    domain = _domain(phase_entity)
    if domain in SWITCH_DOMAINS:
        return vol.Schema(
            {
                vol.Required(CONF_PHASE_SWITCH_ON, default="3"): _choice(
                    PHASES, "fallback_phase"
                )
            }
        )
    if domain in NUMBER_DOMAINS:
        value = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=100, step=1, mode=selector.NumberSelectorMode.BOX
            )
        )
        return vol.Schema(
            {
                vol.Required(CONF_PHASE_VALUE_1, default=1): value,
                # Empty for a charger that only charges on 1 phase (B18).
                vol.Optional(CONF_PHASE_VALUE_3): value,
            }
        )
    state = _hass(handler).states.get(phase_entity)
    options = list(state.attributes.get("options") or []) if state else []
    choice = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )
    return vol.Schema(
        {
            vol.Required(CONF_PHASE_OPTION_1): choice,
            # Empty for a charger that only charges on 1 phase (B18).
            vol.Optional(CONF_PHASE_OPTION_3): choice,
        }
    )


async def _validate_phases(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Store the phase options as the texts or values the entity uses.

    A switch uses "on" and "off"; a number its two values. The setup's other
    code then treats every kind the same way.
    """
    domain = _domain(handler.options[CONF_PHASE_SELECT])
    if domain in SWITCH_DOMAINS:
        three_on = user_input[CONF_PHASE_SWITCH_ON] == "3"
        return user_input | {
            CONF_PHASE_OPTION_1: "off" if three_on else "on",
            CONF_PHASE_OPTION_3: "on" if three_on else "off",
        }
    if domain in NUMBER_DOMAINS:
        one = float(user_input[CONF_PHASE_VALUE_1])
        three = user_input.get(CONF_PHASE_VALUE_3)
        if three is not None and float(three) == one:
            raise SchemaFlowError("same_phase_option")
        return user_input | {
            CONF_PHASE_OPTION_1: str(one),
            CONF_PHASE_OPTION_3: None if three is None else str(float(three)),
        }
    if user_input[CONF_PHASE_OPTION_1] == user_input.get(CONF_PHASE_OPTION_3):
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
    _check_power_units(handler, user_input.get(CONF_EMS))
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
    CONF_POWER_LIMIT,
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


DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DASHBOARD, default=False): selector.BooleanSelector(),
        vol.Optional(CONF_DASHBOARD_TITLE): selector.TextSelector(),
        vol.Required(CONF_DASHBOARD_REBUILD, default=False): selector.BooleanSelector(),
    }
)


async def _validate_dashboard(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild is an action, not a setting: delete the saved dashboard now.

    The reload after the options flow then builds it again.
    """
    if user_input.pop(CONF_DASHBOARD_REBUILD, False):
        entry_id = _own_entry_id(handler)
        entry = _hass(handler).config_entries.async_get_entry(entry_id or "")
        if entry is not None:
            await dashboard.async_remove(_hass(handler), entry)
    return user_input


def _steps(outputs_step: str, *, options: bool) -> dict[str, SchemaFlowFormStep]:
    """Outputs first, then inputs, fixed values, house, car, price and tuning.

    The options flow starts at the outputs ("init") and ends with the
    dashboard; a new controller first gets a name ("user"), where the
    dashboard is asked too.
    """
    after_tuning = "dashboard" if options else "shared"
    steps = {
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
        "household": SchemaFlowFormStep(
            HOUSEHOLD_SCHEMA, validate_user_input=_validate_household, next_step="car"
        ),
        "car": SchemaFlowFormStep(
            CAR_SCHEMA, validate_user_input=_validate_car, next_step="price"
        ),
        "price": SchemaFlowFormStep(
            PRICE_SCHEMA, validate_user_input=_validate_price, next_step="tuning"
        ),
        "tuning": SchemaFlowFormStep(TUNING_SCHEMA, next_step=after_tuning),
        # A warning, not an error: one car can use two chargers, for example.
        "shared": SchemaFlowFormStep(
            _shared_schema,
            description_placeholders=_shared_placeholders,
            next_step=None,
        ),
    }
    if options:
        steps["dashboard"] = SchemaFlowFormStep(
            DASHBOARD_SCHEMA,
            validate_user_input=_validate_dashboard,
            next_step="shared",
        )
    return steps


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        _name_schema, validate_user_input=_validate_name, next_step="outputs"
    ),
    **_steps("outputs", options=False),
}
OPTIONS_FLOW = _steps("init", options=True)


class EvChargeControlConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Set up a charge controller: one virtual device per charger."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        return cast(str, options[CONF_NAME])
