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
MAX_CURRENT = "sensor.test_max_current"
CHARGER_ENERGY = "sensor.test_charger_energy"
CURRENT_LIMIT = "number.test_current_limit"
PHASE_SELECT = "select.test_phases"
HOUSE_POWER = "sensor.test_house_power"
MONTHLY_PEAK = "sensor.test_monthly_peak"
CAR_SOC = "sensor.test_car_soc"

CHARGER_STEP = {
    "name": "Test charger",
    "charger_power_entity": CHARGER_POWER,
    "applied_current_entity": APPLIED_CURRENT,
    "active_phases_entity": ACTIVE_PHASES,
    "connection_entity": MODE3,
    "max_current_entity": MAX_CURRENT,
    "min_current_a": 6,
    "fallback_current_a": 7,
    "fallback_phase": "1",
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
TUNING_STEP = {
    "power_update_threshold_w": 230,
    "phase_switch_delay_min": 5,
    "recalc_interval_s": 10,
    "peak_factor_pct": 90,
}

OPTIONS = (
    CHARGER_STEP
    | CONTROLS_STEP
    | PHASES_STEP
    | HOUSEHOLD_STEP
    | {"car_max_current_a": 16, "car_min_current_a": 6}
    | TUNING_STEP
)

# Device "Test charger" gives entity ids test_charger_<key>.
MODE_SELECT = "select.test_charger_charge_mode"
BASE_LIMIT = "number.test_charger_base_power_limit"
DECISION = "sensor.test_charger_decision"
TARGET_CURRENT = "sensor.test_charger_target_current"
TARGET_PHASES = "sensor.test_charger_target_phases"
EFFECTIVE_LIMIT = "sensor.test_charger_effective_power_limit"
FOLLOW_PEAK = "switch.test_charger_follow_monthly_peak"
CHARGED = "sensor.test_charger_charged_energy"
CHARGED_GRID = "sensor.test_charger_charged_from_grid"
CHARGED_SOLAR = "sensor.test_charger_charged_from_solar"

W = {"unit_of_measurement": "W", "device_class": "power"}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def sources(hass: HomeAssistant) -> None:
    """A connected, idle 16 A charger on 1 phase and a house drawing 500 W."""
    hass.states.async_set(CHARGER_POWER, "0", W)
    hass.states.async_set(APPLIED_CURRENT, "0", {"unit_of_measurement": "A"})
    hass.states.async_set(ACTIVE_PHASES, "1 Phase")
    hass.states.async_set(MODE3, "C2")
    hass.states.async_set(MAX_CURRENT, "16", {"unit_of_measurement": "A"})
    hass.states.async_set(CURRENT_LIMIT, "0")
    hass.states.async_set(PHASE_SELECT, "1 Phase", {"options": ["1 Phase", "3 Phases"]})
    hass.states.async_set(HOUSE_POWER, "500", W)


def make_entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test charger", options=OPTIONS | options
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    return make_entry(hass)


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
