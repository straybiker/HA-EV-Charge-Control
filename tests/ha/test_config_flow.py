"""The setup flow and the options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_control.const import DOMAIN

from .conftest import (
    CAR_SOC,
    CHARGER_POWER,
    CURRENT_LIMIT,
    HOUSE_POWER,
    HOUSEHOLD_STEP,
    INPUTS_STEP,
    LIMITS_STEP,
    MODE3,
    NAME_STEP,
    OPTIONS,
    OUTPUTS_STEP,
    PHASE_SELECT,
    PHASES_STEP,
    TUNING_STEP,
)


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _to_step(hass: HomeAssistant, step: str):
    """Walk the flow with valid input up to the given step."""
    result = await _start(hass)
    for step_id, data in (
        ("user", NAME_STEP),
        ("outputs", OUTPUTS_STEP),
        ("phases", PHASES_STEP),
        ("inputs", INPUTS_STEP),
        ("limits", LIMITS_STEP),
        ("household", HOUSEHOLD_STEP),
        ("car", {}),
        ("price", {}),
    ):
        if result["step_id"] == step:
            return result
        assert result["step_id"] == step_id
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == step
    return result


async def test_full_flow_creates_entry(hass: HomeAssistant, sources) -> None:
    result = await _to_step(hass, "tuning")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test charger"
    assert result["data"] == {}
    options = result["options"]
    assert options["current_limit_entity"] == OUTPUTS_STEP["current_limit_entity"]
    assert options["phase_option_3"] == "3 Phases"
    assert "price_entity" not in options
    assert options["max_current_entity"] == INPUTS_STEP["max_current_entity"]
    assert options["control_off_action"] == "fallback"
    # Tuning defaults, as in the EV Load Balancer package.
    assert {k: options[k] for k in TUNING_STEP} == TUNING_STEP


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
    # The max current entity reports 16 A.
    data = LIMITS_STEP | {"min_current_a": 20}
    assert await _error(hass, "limits", data) == "min_above_max"


async def test_fallback_out_of_range(hass: HomeAssistant, sources) -> None:
    data = LIMITS_STEP | {"fallback_current_a": 32}
    assert await _error(hass, "limits", data) == "fallback_out_of_range"


async def test_connection_must_be_mode3(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(MODE3, "charging")
    assert await _error(hass, "inputs", INPUTS_STEP) == "connection_not_mode3"


async def test_phase_select_needs_options(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(PHASE_SELECT, "x", {"options": []})
    assert await _error(hass, "outputs", OUTPUTS_STEP) == "phase_select_unavailable"


async def test_one_entry_per_charger(hass: HomeAssistant, sources) -> None:
    MockConfigEntry(domain=DOMAIN, options=OPTIONS).add_to_hass(hass)
    assert await _error(hass, "outputs", OUTPUTS_STEP) == "current_entity_in_use"


async def test_phase_setting_is_not_shared(hass: HomeAssistant, sources) -> None:
    """A two-socket charger: own current limits, one phase setting."""
    other = OPTIONS | {"current_limit_entity": "number.test_socket_2_limit"}
    MockConfigEntry(domain=DOMAIN, options=other).add_to_hass(hass)
    assert await _error(hass, "outputs", OUTPUTS_STEP) == "phase_entity_in_use"


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
    limits = LIMITS_STEP | {"fallback_current_a": 8}
    tuning = TUNING_STEP | {"recalc_interval_s": 30}
    steps = (OUTPUTS_STEP, PHASES_STEP, INPUTS_STEP, limits, HOUSEHOLD_STEP, {}, {})
    for data in (*steps, tuning):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], data
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The options change reloads the entry; let that finish inside the test.
    await hass.async_block_till_done()
    assert entry.options["fallback_current_a"] == 8
    assert entry.options["recalc_interval_s"] == 30
    assert "price_entity" not in entry.options  # cleared optional field


async def test_shared_inputs_give_a_warning_step(hass: HomeAssistant, sources) -> None:
    """Another controller on other outputs but the same charger sensors."""
    other = OPTIONS | {
        "current_limit_entity": "number.test_other_limit",
        "phase_select_entity": "select.test_other_phases",
    }
    MockConfigEntry(domain=DOMAIN, title="Garage", options=other).add_to_hass(hass)
    result = await _to_step(hass, "tuning")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "shared"
    shared = result["description_placeholders"]["shared"]
    assert f"- {CHARGER_POWER} (Garage)" in shared
    assert f"- {HOUSE_POWER} (Garage)" in shared
    # A warning only: submitting continues.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY


def _package(hass: HomeAssistant) -> None:
    """The EV Load Balancer package's template sensors, as Home Assistant has them."""
    hass.states.async_set(
        "sensor.ev_load_balancer_charger",
        "Test charger",
        {
            "current_output": CURRENT_LIMIT,
            "phases_output": PHASE_SELECT,
            "phase_1_state": "1 Phase",
            "phase_3_state": "3 Phases",
            "min_current": 6,
            "default_current": 8,
            "default_phases": 1,
            "nominal_voltage": 230,
        },
    )
    hass.states.async_set(
        "sensor.ev_load_balancer",
        "Limited",
        {"power_limit": 6000, "car_aware": True, "pv_prioritized": False},
    )


def _suggested(result, key: str):
    marker = next(k for k in result["data_schema"].schema if k == key)
    return (marker.description or {}).get("suggested_value")


async def test_first_controller_can_import_the_package(
    hass: HomeAssistant, sources
) -> None:
    _package(hass)
    result = await _start(hass)
    assert "import_yaml" in result["data_schema"].schema
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NAME_STEP | {"import_yaml": True}
    )
    assert result["step_id"] == "outputs"
    assert _suggested(result, "current_limit_entity") == CURRENT_LIMIT
    for data in (OUTPUTS_STEP, PHASES_STEP, INPUTS_STEP):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == "limits"
    assert _suggested(result, "fallback_current_a") == 8
    for data in (LIMITS_STEP | {"fallback_current_a": 8}, HOUSEHOLD_STEP, {}, {}, {}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options["initial_settings"]["charge_mode"] == "limited"
    assert "import_yaml" not in entry.options
    await hass.async_block_till_done()
    assert hass.states.get("select.test_charger_charge_mode").state == "limited"
    assert hass.states.get("number.test_charger_base_power_limit").state == "6000.0"
    assert hass.states.get("switch.test_charger_car_aware").state == "on"
    # Imported or not, a new device starts in shadow mode.
    assert hass.states.get("switch.test_charger_control_charger").state == "off"


async def test_no_import_offer_for_a_second_controller(
    hass: HomeAssistant, sources
) -> None:
    _package(hass)
    MockConfigEntry(domain=DOMAIN, options=OPTIONS).add_to_hass(hass)
    result = await _start(hass)
    assert "import_yaml" not in result["data_schema"].schema


async def test_no_import_offer_without_the_package(
    hass: HomeAssistant, sources
) -> None:
    result = await _start(hass)
    assert "import_yaml" not in result["data_schema"].schema
