"""The device: settings entities, decision sensors, triggers, shadow mode."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache_with_extra_data,
)

from custom_components.ev_charge_control.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import (
    DECISION,
    HOUSE_POWER,
    MODE3,
    MODE_SELECT,
    TARGET_CURRENT,
    TARGET_PHASES,
    setup,
)


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": MODE_SELECT, "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


# Just past the coordinator's 1 s debounce.
_DEBOUNCE = 1.1


async def _tick(hass: HomeAssistant, seconds: float = 11) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_defaults_on_first_creation(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    assert hass.states.get(MODE_SELECT).state == "off"
    assert hass.states.get("number.test_charger_power_limit").state == "5000"
    assert hass.states.get("number.test_charger_target_soc").state == "80"
    assert hass.states.get("number.test_charger_phase_switch_delay").state == "5"
    assert (
        hass.states.get("switch.test_charger_charge_on_solar_when_ems_blocks").state
        == "off"
    )
    assert hass.states.get(DECISION).state == "off"


async def test_settings_restore_after_restart(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    number_extra = {
        "native_value": 7000,
        "native_min_value": 0,
        "native_max_value": 25000,
        "native_step": 100,
        "native_unit_of_measurement": "W",
    }
    mock_restore_cache_with_extra_data(
        hass,
        (
            (State(MODE_SELECT, "limited"), {}),
            (State("switch.test_charger_car_aware", "on"), {}),
            (State("number.test_charger_power_limit", "7000"), number_extra),
        ),
    )
    await setup(hass, entry)
    assert hass.states.get(MODE_SELECT).state == "limited"
    assert hass.states.get("switch.test_charger_car_aware").state == "on"
    assert hass.states.get("number.test_charger_power_limit").state == "7000"
    # 7000 W limit - 500 W house = 6500 W on 3 phases = 9.4 A
    assert hass.states.get(TARGET_CURRENT).state == "9.4"


async def test_mode_change_runs_at_once(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _select(hass, "limited")
    assert hass.states.get(DECISION).state == "charging"
    # 5000 W default limit - 500 W house = 4500 W on 3 phases = 6.5 A
    assert hass.states.get(TARGET_CURRENT).state == "6.5"
    assert hass.states.get(TARGET_PHASES).state == "3"


async def test_power_changes_wait_for_the_tick(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _select(hass, "limited")
    hass.states.async_set(HOUSE_POWER, "3500", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert hass.states.get(TARGET_PHASES).state == "3"  # not recalculated yet
    await _tick(hass)
    assert hass.states.get(TARGET_PHASES).state == "1"
    assert hass.states.get(TARGET_CURRENT).state == "6.5"  # 1500 W on 1 phase


async def test_unplug_runs_at_once(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _select(hass, "limited")
    hass.states.async_set(MODE3, "A")
    # Within the 1 s debounce after the mode change, the run is merged and
    # follows when the debounce ends, well before the 10 s tick.
    await _tick(hass, _DEBOUNCE)
    assert hass.states.get(DECISION).state == "not_connected"


async def test_kw_sensors_are_converted(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.states.async_set(HOUSE_POWER, "0.5", {"unit_of_measurement": "kW"})
    await setup(hass, entry)
    await _select(hass, "limited")
    assert hass.states.get(TARGET_CURRENT).state == "6.5"


async def test_shadow_mode_writes_nothing(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    number_calls = async_mock_service(hass, "number", "set_value")
    select_calls = async_mock_service(hass, "select", "select_option")
    await setup(hass, entry)
    hass.states.async_set(HOUSE_POWER, "-6000", {"unit_of_measurement": "W"})
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": MODE_SELECT, "option": "fast"},
        blocking=True,
    )
    await _tick(hass)
    assert [c for c in select_calls if c.data.get("entity_id") != MODE_SELECT] == []
    assert number_calls == []
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["intended_setpoint"] is not None


async def test_3p_minimum_and_single_phase_only_are_refused(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.test_charger_single_phase_only"},
        blocking=True,
    )
    with pytest.raises(ServiceValidationError):
        await _select(hass, "min_3p")
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.test_charger_single_phase_only"},
        blocking=True,
    )
    await _select(hass, "min_3p")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.test_charger_single_phase_only"},
            blocking=True,
        )


async def test_recalc_interval_rearms_the_timer(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _select(hass, "limited")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.test_charger_recalculation_interval", "value": 60},
        blocking=True,
    )
    await _tick(hass, _DEBOUNCE)  # let the run for the setting change finish
    hass.states.async_set(HOUSE_POWER, "3500", {"unit_of_measurement": "W"})
    await _tick(hass, 20)
    assert hass.states.get(TARGET_PHASES).state == "3"  # 60 s interval now
    await _tick(hass, 61)
    assert hass.states.get(TARGET_PHASES).state == "1"


async def test_diagnostics_redact_the_name(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["options"]["name"] == "**REDACTED**"
    assert diag["settings"]["mode"] == "off"


async def test_unload(hass: HomeAssistant, sources, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
