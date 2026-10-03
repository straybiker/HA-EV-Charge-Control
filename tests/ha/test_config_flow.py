"""The 6-step setup flow and the options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_control.const import DOMAIN

from .conftest import (
    CAR_SOC,
    CHARGER_STEP,
    CONTROLS_STEP,
    HOUSEHOLD_STEP,
    MODE3,
    OPTIONS,
    PHASE_SELECT,
    PHASES_STEP,
)


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _to_step(hass: HomeAssistant, step: str):
    """Walk the flow with valid input up to the given step."""
    result = await _start(hass)
    for step_id, data in (
        ("user", CHARGER_STEP),
        ("controls", CONTROLS_STEP),
        ("phases", PHASES_STEP),
        ("household", HOUSEHOLD_STEP),
        ("car", {}),
    ):
        if result["step_id"] == step:
            return result
        assert result["step_id"] == step_id
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == step
    return result


async def test_full_flow_creates_entry(hass: HomeAssistant, sources) -> None:
    result = await _to_step(hass, "price")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test charger"
    assert result["data"] == {}
    options = result["options"]
    assert options["current_limit_entity"] == CONTROLS_STEP["current_limit_entity"]
    assert options["phase_option_3"] == "3 Phases"
    assert "price_entity" not in options


async def test_phase_options_come_from_the_select(hass: HomeAssistant, sources) -> None:
    result = await _to_step(hass, "phases")
    schema = result["data_schema"].schema
    option_1 = next(v for k, v in schema.items() if k == "phase_option_1")
    assert option_1.config["options"] == ["1 Phase", "3 Phases"]


async def _error(hass: HomeAssistant, step: str, data: dict) -> str:
    result = await _to_step(hass, step)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.FORM
    return result["errors"]["base"]


async def test_min_above_max(hass: HomeAssistant, sources) -> None:
    data = CHARGER_STEP | {"min_current_a": 20}
    assert await _error(hass, "user", data) == "min_above_max"


async def test_fallback_out_of_range(hass: HomeAssistant, sources) -> None:
    data = CHARGER_STEP | {"fallback_current_a": 32}
    assert await _error(hass, "user", data) == "fallback_out_of_range"


async def test_connection_must_be_mode3(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(MODE3, "charging")
    assert await _error(hass, "user", CHARGER_STEP) == "connection_not_mode3"


async def test_phase_select_needs_options(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(PHASE_SELECT, "x", {"options": []})
    assert await _error(hass, "controls", CONTROLS_STEP) == "phase_select_unavailable"


async def test_one_entry_per_charger(hass: HomeAssistant, sources) -> None:
    MockConfigEntry(domain=DOMAIN, options=OPTIONS).add_to_hass(hass)
    assert await _error(hass, "controls", CONTROLS_STEP) == "current_entity_in_use"


async def test_phase_options_must_differ(hass: HomeAssistant, sources) -> None:
    data = {"phase_option_1": "1 Phase", "phase_option_3": "1 Phase"}
    assert await _error(hass, "phases", data) == "same_phase_option"


async def test_car_needs_capacity(hass: HomeAssistant, sources) -> None:
    assert await _error(hass, "car", {"car_soc_entity": CAR_SOC}) == "capacity_required"


async def test_attribute_needs_price(hass: HomeAssistant, sources) -> None:
    error = await _error(hass, "price", {"price_attribute": "rate_import"})
    assert error == "attribute_without_price"


async def test_price_attribute_must_exist(hass: HomeAssistant, sources) -> None:
    hass.states.async_set("sensor.test_price", "0.2", {"rate_import": 0.25})
    ok = await _to_step(hass, "price")
    result = await hass.config_entries.flow.async_configure(
        ok["flow_id"], {"price_entity": "sensor.test_price", "price_attribute": "nope"}
    )
    assert result["errors"]["base"] == "price_attribute_missing"


async def test_options_flow_edits_and_clears(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        entry, options=entry.options | {"price_entity": "sensor.test_price"}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    charger = {k: v for k, v in CHARGER_STEP.items() if k != "name"} | {
        "max_current_a": 32
    }
    for data in (charger, CONTROLS_STEP, PHASES_STEP, HOUSEHOLD_STEP, {}, {}):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], data
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["max_current_a"] == 32
    assert "price_entity" not in entry.options  # cleared optional field
