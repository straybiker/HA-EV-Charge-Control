"""The device: settings entities, decision sensors, triggers, shadow mode."""

from __future__ import annotations

import logging
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
    CHARGED,
    CHARGED_GRID,
    CHARGED_SOLAR,
    CHARGER_ENERGY,
    CHARGER_POWER,
    DECISION,
    EFFECTIVE_LIMIT,
    HOUSE_POWER,
    MAX_CURRENT,
    MODE3,
    MODE_SELECT,
    POWER_LIMIT,
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
    # The power limit comes from an entity; the device has no own number.
    assert hass.states.get("number.test_charger_base_power_limit") is None
    assert hass.states.get("number.test_charger_target_soc").state == "80"
    assert (
        hass.states.get("switch.test_charger_charge_on_solar_when_ems_blocks").state
        == "off"
    )
    assert hass.states.get(DECISION).state == "off"
    # Tuning values are setup fields, not entities.
    assert hass.states.get("number.test_charger_phase_switch_delay") is None


async def test_settings_restore_after_restart(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    number_extra = {
        "native_value": 60,
        "native_min_value": 0,
        "native_max_value": 100,
        "native_step": 1,
        "native_unit_of_measurement": "%",
    }
    mock_restore_cache_with_extra_data(
        hass,
        (
            (State(MODE_SELECT, "limited"), {}),
            (State("switch.test_charger_car_aware", "on"), {}),
            (State("number.test_charger_target_soc", "60"), number_extra),
        ),
    )
    await setup(hass, entry)
    assert hass.states.get(MODE_SELECT).state == "limited"
    assert hass.states.get("switch.test_charger_car_aware").state == "on"
    assert hass.states.get("number.test_charger_target_soc").state == "60"
    # 5000 W limit - 500 W house = 4500 W on 3 phases = 6.5 A
    assert hass.states.get(TARGET_CURRENT).state == "6.5"


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


async def test_status_sensors_without_charging(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    """Mode Off: the export and the grid gate are known; nothing is available."""
    hass.states.async_set(HOUSE_POWER, "-2000", W)
    await setup(hass, entry)
    assert hass.states.get("sensor.test_charger_solar_surplus").state == "2000"
    assert hass.states.get("sensor.test_charger_available_for_the_car").state == "0"
    assert hass.states.get("sensor.test_charger_car_from_grid").state == "0"
    assert hass.states.get("sensor.test_charger_car_from_solar").state == "0"
    # No EMS entity in the setup.
    assert hass.states.get("binary_sensor.test_charger_ems_active").state == "unknown"
    assert hass.states.get("binary_sensor.test_charger_grid_allowed").state == "on"


def _available(hass: HomeAssistant) -> tuple[float, float, float]:
    """(total, from grid, from solar) of Available for the car."""
    return tuple(
        float(hass.states.get(f"sensor.test_charger_{key}").state)
        for key in (
            "available_for_the_car",
            "available_from_grid",
            "available_from_solar",
        )
    )


async def test_available_follows_the_mode(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    """Solar mode offers only the export; Limited adds the grid up to the limit."""
    hass.states.async_set(MODE3, "A")
    hass.states.async_set(HOUSE_POWER, "-3000", W)
    await setup(hass, entry)
    await _select(hass, "solar")
    total, grid, solar = _available(hass)
    assert grid == 0
    assert total == solar == pytest.approx(3000, abs=70)
    await _select(hass, "limited")
    # The second change falls in the debounce of the first; it runs after it.
    await _tick(hass, _DEBOUNCE)
    total, grid, solar = _available(hass)
    assert solar == pytest.approx(3000, abs=1)
    assert total == pytest.approx(8000, abs=70)  # 3000 W export + 5000 W limit
    assert total == pytest.approx(grid + solar, abs=1)


async def test_available_is_the_target_while_charging(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.states.async_set(HOUSE_POWER, "-1000", W)
    await setup(hass, entry)
    await _select(hass, "fast")
    target = float(hass.states.get("sensor.test_charger_target_power").state)
    total, grid, solar = _available(hass)
    assert total == pytest.approx(target, abs=1)
    assert solar == pytest.approx(1000, abs=1)
    # Car from grid and Car from solar split the same target.
    car_grid = float(hass.states.get("sensor.test_charger_car_from_grid").state)
    car_solar = float(hass.states.get("sensor.test_charger_car_from_solar").state)
    assert car_grid == pytest.approx(target - 1000, abs=1)
    assert car_solar == pytest.approx(1000, abs=1)


async def test_charger_without_three_phase_option(hass: HomeAssistant, sources) -> None:
    """Single phase only stays on, and the controller stays on 1 phase (B18)."""
    await setup(hass, make_entry(hass, phase_option_3=None))
    single = "switch.test_charger_single_phase_only"
    assert hass.states.get(single).state == "on"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": single}, blocking=True
        )
    assert hass.states.get(single).state == "on"
    # 4500 W headroom would be 3 phases on a 3-phase charger.
    await _select(hass, "fast")
    assert hass.states.get(TARGET_PHASES).state == "1"


async def test_phase_setting_as_a_number_is_read(hass: HomeAssistant, sources) -> None:
    """A number entity reports 1.0 for the value 1."""
    phase = "input_number.test_phase_count"
    hass.states.async_set(phase, "1.0")
    entry = make_entry(
        hass,
        phase_select_entity=phase,
        phase_option_1="1.0",
        phase_option_3="3.0",
    )
    await setup(hass, entry)
    await _select(hass, "fast")
    assert hass.states.get(DECISION).state == "charging"
    assert hass.states.get(TARGET_PHASES).state == "3"


async def test_kw_sensors_are_converted(hass: HomeAssistant, sources) -> None:
    hass.states.async_set(HOUSE_POWER, "0.5", {"unit_of_measurement": "kW"})
    await setup(hass, make_entry(hass))
    await _select(hass, "limited")
    assert hass.states.get(TARGET_CURRENT).state == "6.5"


async def test_power_limit_from_the_entity_with_the_factor(
    hass: HomeAssistant, sources
) -> None:
    hass.states.async_set(POWER_LIMIT, "8", {"unit_of_measurement": "kW"})
    await setup(hass, make_entry(hass, peak_factor_pct=90))
    await _select(hass, "limited")
    # 90 % x 8000 W = 7200 W; 6700 W headroom on 3 phases
    assert hass.states.get(EFFECTIVE_LIMIT).state == "7200"
    assert hass.states.get(TARGET_CURRENT).state == "9.7"


async def test_unavailable_limit_keeps_the_last_value(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    hass.states.async_set(POWER_LIMIT, "unavailable")
    await _tick(hass)
    assert hass.states.get(EFFECTIVE_LIMIT).state == "5000"


async def test_no_limit_value_yet_means_no_power_limit(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER_LIMIT, "unavailable")
    await setup(hass, entry)
    await _select(hass, "limited")
    assert hass.states.get(DECISION).state == "no_power_limit"
    assert hass.states.get(EFFECTIVE_LIMIT).state == "0"


async def test_max_current_entity_and_its_fallback(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    hass.states.async_set(MAX_CURRENT, "unavailable")
    await setup(hass, entry)
    hass.states.async_set(POWER_LIMIT, "10000", W)
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
    # The today sensors count the same energy; they start again at midnight.
    today = hass.states.get("sensor.test_charger_charged_today")
    assert float(today.state) == pytest.approx(2.0)


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


async def test_available_from_grid_while_importing(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    """The house import comes off the limit; nothing is left for solar."""
    await setup(hass, entry)
    await _select(hass, "limited")
    total, grid, solar = _available(hass)
    assert solar == 0
    assert grid == pytest.approx(total, abs=1)
    assert total == pytest.approx(4500, abs=70)  # 5000 W limit − 500 W import


async def test_ems_active_follows_the_signal(hass: HomeAssistant, sources) -> None:
    ems = "sensor.test_ems_signal"
    hass.states.async_set(ems, "0", W)
    await setup(hass, make_entry(hass, ems_entity=ems))
    active = "binary_sensor.test_charger_ems_active"
    assert hass.states.get(active).state == "off"
    hass.states.async_set(ems, "2300", W)
    await _tick(hass)
    assert hass.states.get(active).state == "on"


async def test_average_charging_power_while_charging(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    average = "sensor.test_charger_average_charging_power"
    await setup(hass, entry)
    assert hass.states.get(average).state == "unknown"
    hass.states.async_set(CHARGER_POWER, "7400", W)
    await _tick(hass)
    await _tick(hass)
    assert float(hass.states.get(average).state) == pytest.approx(7400, abs=1)


async def test_debug_log_shows_each_run(
    hass: HomeAssistant, sources, entry: MockConfigEntry, caplog
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.ev_charge_control")
    hass.states.async_set(HOUSE_POWER, "unavailable")
    await setup(hass, entry)
    assert "Run: mode off" in caplog.text
    assert f"Input {HOUSE_POWER} cannot be read" in caplog.text
    hass.states.async_set(HOUSE_POWER, "500", W)
    await _tick(hass)
    assert f"Input {HOUSE_POWER} can be read again" in caplog.text
