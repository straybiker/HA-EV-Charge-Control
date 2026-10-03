"""The device: settings entities, decision sensors, triggers, shadow mode."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
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
    BASE_LIMIT,
    CHARGED,
    CHARGED_GRID,
    CHARGED_SOLAR,
    CHARGER_ENERGY,
    CHARGER_POWER,
    DECISION,
    EFFECTIVE_LIMIT,
    FOLLOW_PEAK,
    HOUSE_POWER,
    MAX_CURRENT,
    MODE3,
    MODE_SELECT,
    MONTHLY_PEAK,
    TARGET_CURRENT,
    TARGET_PHASES,
    W,
    make_entry,
    setup,
)

# Just past the coordinator's 1 s debounce.
_DEBOUNCE = 1.1


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": MODE_SELECT, "option": option},
        blocking=True,
    )
    await hass.async_block_till_done()


async def _set_number(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
    )
    await hass.async_block_till_done()


async def _tick(hass: HomeAssistant, seconds: float = 11) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_defaults_on_first_creation(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    assert hass.states.get(MODE_SELECT).state == "off"
    assert hass.states.get(BASE_LIMIT).state == "5000"
    assert hass.states.get("number.test_charger_target_soc").state == "80"
    assert (
        hass.states.get("switch.test_charger_charge_on_solar_when_ems_blocks").state
        == "off"
    )
    assert hass.states.get(DECISION).state == "off"
    # Tuning values are setup fields, not entities.
    assert hass.states.get("number.test_charger_phase_switch_delay") is None
    # No monthly peak sensor in the setup: no follow switch.
    assert hass.states.get(FOLLOW_PEAK) is None


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
            (State(BASE_LIMIT, "7000"), number_extra),
        ),
    )
    await setup(hass, entry)
    assert hass.states.get(MODE_SELECT).state == "limited"
    assert hass.states.get("switch.test_charger_car_aware").state == "on"
    assert hass.states.get(BASE_LIMIT).state == "7000"
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
    assert hass.states.get(EFFECTIVE_LIMIT).state == "5000"


async def test_power_changes_wait_for_the_tick(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _select(hass, "limited")
    hass.states.async_set(HOUSE_POWER, "3500", W)
    await hass.async_block_till_done()
    assert hass.states.get(TARGET_PHASES).state == "3"  # not recalculated yet
    await _tick(hass)
    assert hass.states.get(TARGET_PHASES).state == "1"
    assert hass.states.get(TARGET_CURRENT).state == "6.5"  # 1500 W on 1 phase


async def test_recalc_interval_comes_from_the_setup(
    hass: HomeAssistant, sources
) -> None:
    await setup(hass, make_entry(hass, recalc_interval_s=60))
    await _select(hass, "limited")
    await _tick(hass, _DEBOUNCE)
    hass.states.async_set(HOUSE_POWER, "3500", W)
    await _tick(hass, 20)
    assert hass.states.get(TARGET_PHASES).state == "3"  # 60 s interval
    await _tick(hass, 61)
    assert hass.states.get(TARGET_PHASES).state == "1"


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


async def test_kw_sensors_are_converted(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(HOUSE_POWER, "0.5", {"unit_of_measurement": "kW"})
    await setup(hass, make_entry(hass))
    await _select(hass, "limited")
    assert hass.states.get(TARGET_CURRENT).state == "6.5"


async def test_monthly_peak_raises_the_limit(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(MONTHLY_PEAK, "8", {"unit_of_measurement": "kW"})
    await setup(hass, make_entry(hass, monthly_peak_entity=MONTHLY_PEAK))
    assert hass.states.get(FOLLOW_PEAK).state == "on"  # default on
    await _select(hass, "limited")
    # max(5000 W base, 90 % x 8000 W) = 7200 W; 6700 W headroom on 3 phases
    assert hass.states.get(EFFECTIVE_LIMIT).state == "7200"
    assert hass.states.get(TARGET_CURRENT).state == "9.7"


async def test_monthly_peak_from_a_number_entity(hass: HomeAssistant, sources) -> None:
    """Peak automations often ratchet an input_number instead of a sensor."""
    peak = "input_number.test_monthly_peak"
    hass.states.async_set(peak, "8000", {"unit_of_measurement": "W"})
    await setup(hass, make_entry(hass, monthly_peak_entity=peak))
    assert hass.states.get(EFFECTIVE_LIMIT).state == "7200"


async def test_follow_off_uses_the_base_limit(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(MONTHLY_PEAK, "8000", W)
    await setup(hass, make_entry(hass, monthly_peak_entity=MONTHLY_PEAK))
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": FOLLOW_PEAK}, blocking=True
    )
    await _tick(hass, _DEBOUNCE)
    assert hass.states.get(EFFECTIVE_LIMIT).state == "5000"


async def test_unavailable_peak_uses_the_base_limit(
    hass: HomeAssistant, sources
) -> None:
    hass.states.async_set(MONTHLY_PEAK, "unavailable")
    await setup(hass, make_entry(hass, monthly_peak_entity=MONTHLY_PEAK))
    assert hass.states.get(EFFECTIVE_LIMIT).state == "5000"


async def test_max_current_entity_and_its_fallback(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.states.async_set(MAX_CURRENT, "unavailable")
    await setup(hass, entry)
    await _set_number(hass, BASE_LIMIT, 10000)
    await _select(hass, "fast")
    await _tick(hass, _DEBOUNCE)
    # No max seen yet: the 7 A fallback current is the maximum.
    assert hass.states.get(TARGET_CURRENT).state == "7.0"
    hass.states.async_set(MAX_CURRENT, "16", {"unit_of_measurement": "A"})
    await _tick(hass)
    assert hass.states.get(TARGET_CURRENT).state == "13.7"  # 9500 W headroom
    hass.states.async_set(MAX_CURRENT, "unavailable")
    await _tick(hass, 22)
    assert hass.states.get(TARGET_CURRENT).state == "13.7"  # last known 16 A


async def test_energy_from_the_charger_meter(hass: HomeAssistant, sources) -> None:
    kwh = {"unit_of_measurement": "kWh", "device_class": "energy"}
    hass.states.async_set(CHARGER_ENERGY, "100.0", kwh)
    hass.states.async_set(CHARGER_POWER, "4000", W)
    hass.states.async_set(HOUSE_POWER, "-1000", W)  # 1 of 4 kW from solar
    await setup(hass, make_entry(hass, charger_energy_entity=CHARGER_ENERGY))
    hass.states.async_set(CHARGER_ENERGY, "102.0", kwh)
    await _tick(hass)
    assert float(hass.states.get(CHARGED).state) == pytest.approx(2.0)
    assert float(hass.states.get(CHARGED_SOLAR).state) == pytest.approx(0.5)
    assert float(hass.states.get(CHARGED_GRID).state) == pytest.approx(1.5)


async def test_energy_totals_survive_a_reload(hass: HomeAssistant, sources) -> None:
    kwh = {"unit_of_measurement": "kWh", "device_class": "energy"}
    hass.states.async_set(CHARGER_ENERGY, "100.0", kwh)
    entry = make_entry(hass, charger_energy_entity=CHARGER_ENERGY)
    await setup(hass, entry)
    hass.states.async_set(CHARGER_ENERGY, "103.0", kwh)
    await _tick(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await setup(hass, entry)
    assert float(hass.states.get(CHARGED).state) == pytest.approx(3.0)


async def test_shadow_mode_writes_nothing(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    number_calls = async_mock_service(hass, "number", "set_value")
    select_calls = async_mock_service(hass, "select", "select_option")
    await setup(hass, entry)
    hass.states.async_set(HOUSE_POWER, "-6000", W)
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
    single = {"entity_id": "switch.test_charger_single_phase_only"}
    await hass.services.async_call("switch", "turn_on", single, blocking=True)
    with pytest.raises(ServiceValidationError):
        await _select(hass, "min_3p")
    await hass.services.async_call("switch", "turn_off", single, blocking=True)
    await _select(hass, "min_3p")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call("switch", "turn_on", single, blocking=True)


async def test_diagnostics(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["options"]["name"] == "**REDACTED**"
    assert diag["settings"]["mode"] == "off"
    assert diag["tuning"]["recalc_interval_s"] == 10
    assert diag["energy"]["charged_kwh"] == 0


async def test_unload(hass: HomeAssistant, sources, entry: MockConfigEntry) -> None:
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_controller_is_a_regular_device(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.entry_type is None
    assert device.model == "Charge controller"
