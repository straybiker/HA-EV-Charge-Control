"""Repair issues for renamed or missing source entities."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ev_charge_control.const import DOMAIN
from custom_components.ev_charge_control.watch import (
    MISSING,
    MISSING_GRACE,
    RENAMED,
    issue_id,
)

from .conftest import W, make_entry, setup

SOLAR = "sensor.test_solar"


def _issue(hass: HomeAssistant, kind: str, entry: MockConfigEntry, key: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(kind, entry, key))


async def _after_grace(hass: HomeAssistant) -> None:
    later = dt_util.utcnow() + MISSING_GRACE + timedelta(seconds=1)
    async_fire_time_changed(hass, later)
    await hass.async_block_till_done()


def _registered_solar(hass: HomeAssistant) -> er.RegistryEntry:
    entry = er.async_get(hass).async_get_or_create(
        "sensor", "test", "solar", suggested_object_id="test_solar"
    )
    assert entry.entity_id == SOLAR
    hass.states.async_set(SOLAR, "3000", W)
    return entry


async def test_a_missing_entity_raises_an_issue(hass: HomeAssistant, sources) -> None:
    entry = make_entry(hass, solar_power_entity="sensor.gone")
    await setup(hass, entry)
    # Not before the grace time: a source can appear after a start.
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None
    await _after_grace(hass)
    issue = _issue(hass, MISSING, entry, "solar_power_entity")
    assert issue is not None
    assert issue.translation_placeholders["old"] == "sensor.gone"
    assert issue.translation_placeholders["role"] == "Solar power"
    assert issue.translation_placeholders["step"].endswith("Inputs: the house")
    # The entity exists: no issue.
    assert _issue(hass, MISSING, entry, "house_power_entity") is None


async def test_a_rename_proposes_the_new_entity(hass: HomeAssistant, sources) -> None:
    """The setup is not changed: the issue tells the user what to select."""
    _registered_solar(hass)
    entry = make_entry(hass, solar_power_entity=SOLAR)
    await setup(hass, entry)
    er.async_get(hass).async_update_entity(SOLAR, new_entity_id="sensor.pv_total")
    await hass.async_block_till_done()
    issue = _issue(hass, RENAMED, entry, "solar_power_entity")
    assert issue is not None
    assert issue.translation_placeholders["new"] == "sensor.pv_total"
    assert entry.options["solar_power_entity"] == SOLAR


async def test_a_removed_entity_raises_a_missing_issue(
    hass: HomeAssistant, sources
) -> None:
    _registered_solar(hass)
    entry = make_entry(hass, solar_power_entity=SOLAR)
    await setup(hass, entry)
    er.async_get(hass).async_remove(SOLAR)
    hass.states.async_remove(SOLAR)
    await hass.async_block_till_done()
    assert _issue(hass, MISSING, entry, "solar_power_entity") is not None


async def test_issues_close_when_the_setup_points_at_the_new_entity(
    hass: HomeAssistant, sources
) -> None:
    _registered_solar(hass)
    entry = make_entry(hass, solar_power_entity=SOLAR)
    await setup(hass, entry)
    er.async_get(hass).async_update_entity(SOLAR, new_entity_id="sensor.pv_total")
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(
        entry, options=entry.options | {"solar_power_entity": "sensor.pv_total"}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, RENAMED, entry, "solar_power_entity") is None
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None


async def test_unload_removes_the_issues(hass: HomeAssistant, sources) -> None:
    entry = make_entry(hass, solar_power_entity="sensor.gone")
    await setup(hass, entry)
    await _after_grace(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None


async def test_a_source_that_appears_in_time_raises_nothing(
    hass: HomeAssistant, sources
) -> None:
    """An EMS publishes its sensors only after its first run."""
    entry = make_entry(hass, solar_power_entity="sensor.late")
    await setup(hass, entry)
    hass.states.async_set("sensor.late", "1000", W)
    await _after_grace(hass)
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None


async def test_a_missing_issue_closes_when_the_entity_appears(
    hass: HomeAssistant, sources
) -> None:
    entry = make_entry(hass, solar_power_entity="sensor.late")
    await setup(hass, entry)
    await _after_grace(hass)
    assert _issue(hass, MISSING, entry, "solar_power_entity") is not None
    hass.states.async_set("sensor.late", "1000", W)
    await hass.async_block_till_done()
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None


async def test_unload_cancels_the_missing_check(hass: HomeAssistant, sources) -> None:
    entry = make_entry(hass, solar_power_entity="sensor.gone")
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _after_grace(hass)
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None
