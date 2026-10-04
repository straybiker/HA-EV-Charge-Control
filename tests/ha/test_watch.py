"""Repair issues for renamed or missing source entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_control.const import DOMAIN
from custom_components.ev_charge_control.watch import MISSING, RENAMED, issue_id

from .conftest import W, make_entry, setup

SOLAR = "sensor.test_solar"


def _issue(hass: HomeAssistant, kind: str, entry: MockConfigEntry, key: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(kind, entry, key))


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
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, MISSING, entry, "solar_power_entity") is None
