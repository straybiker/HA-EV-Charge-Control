"""Fixtures for the Home Assistant tests. All entity ids are fake."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_control.const import DOMAIN

CHARGER_POWER = "sensor.test_charger_power"
APPLIED_CURRENT = "sensor.test_applied_current"
ACTIVE_PHASES = "sensor.test_active_phases"
MODE3 = "sensor.test_mode3"
CURRENT_LIMIT = "number.test_current_limit"
PHASE_SELECT = "select.test_phases"
HOUSE_POWER = "sensor.test_house_power"
CAR_SOC = "sensor.test_car_soc"

CHARGER_STEP = {
    "name": "Test charger",
    "charger_power_entity": CHARGER_POWER,
    "applied_current_entity": APPLIED_CURRENT,
    "active_phases_entity": ACTIVE_PHASES,
    "connection_entity": MODE3,
    "max_current_a": 16,
    "min_current_a": 6,
    "fallback_current_a": 7,
    "voltage_v": 230,
    "current_step_a": "0_1",
    "widen_small_decreases": True,
    "failsafe_keeps_phase": False,
}
CONTROLS_STEP = {
    "current_limit_entity": CURRENT_LIMIT,
    "phase_select_entity": PHASE_SELECT,
}
PHASES_STEP = {"phase_option_1": "1 Phase", "phase_option_3": "3 Phases"}
HOUSEHOLD_STEP = {"house_power_entity": HOUSE_POWER}

OPTIONS = (
    CHARGER_STEP
    | CONTROLS_STEP
    | PHASES_STEP
    | HOUSEHOLD_STEP
    | {
        "car_max_current_a": 16,
        "car_min_current_a": 6,
    }
)

# Device "Test charger" gives entity ids test_charger_<key>.
MODE_SELECT = "select.test_charger_charge_mode"
DECISION = "sensor.test_charger_decision"
TARGET_CURRENT = "sensor.test_charger_target_current"
TARGET_PHASES = "sensor.test_charger_target_phases"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def sources(hass: HomeAssistant) -> None:
    """A connected, idle charger on 1 phase and a house drawing 500 W."""
    w = {"unit_of_measurement": "W", "device_class": "power"}
    hass.states.async_set(CHARGER_POWER, "0", w)
    hass.states.async_set(APPLIED_CURRENT, "0", {"unit_of_measurement": "A"})
    hass.states.async_set(ACTIVE_PHASES, "1 Phase")
    hass.states.async_set(MODE3, "C2")
    hass.states.async_set(CURRENT_LIMIT, "0")
    hass.states.async_set(PHASE_SELECT, "1 Phase", {"options": ["1 Phase", "3 Phases"]})
    hass.states.async_set(HOUSE_POWER, "500", w)


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Test charger", options=OPTIONS)
    entry.add_to_hass(hass)
    return entry


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
