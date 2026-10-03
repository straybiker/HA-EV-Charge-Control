"""The EV Charge Control integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started

from .const import DOMAIN, PLATFORMS
from .coordinator import EvChargeCoordinator
from .engine import Controller
from .inputs import InputReader, car_spec, charger_spec, tuning
from .settings import SettingsStore
from .writer import ShadowWriter

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class EvChargeRuntime:
    coordinator: EvChargeCoordinator
    store: SettingsStore


type EvChargeConfigEntry = ConfigEntry[EvChargeRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> bool:
    """Set up one charger controller."""
    store = SettingsStore()
    coordinator = EvChargeCoordinator(
        hass,
        entry,
        store,
        Controller(charger_spec(entry.options), car_spec(entry.options)),
        InputReader(hass, entry.options),
        ShadowWriter(),
        tuning(entry.options),
    )
    await coordinator.async_load_energy()
    entry.runtime_data = EvChargeRuntime(coordinator, store)

    # The setting entities restore their values while the platforms load, so
    # the first run uses the user's settings, not the defaults.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(async_at_started(hass, coordinator.async_start))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> bool:
    await entry.runtime_data.coordinator.async_save_energy()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> None:
    """Delete the saved energy totals with the entry."""
    store = EvChargeCoordinator.energy_store(hass, entry)
    await store.async_remove()
