"""The EV Charge Control integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.start import async_at_started

from . import dashboard
from .const import CONF_INITIAL_SETTINGS, DOMAIN, LOGGER, PLATFORMS
from .coordinator import EvChargeCoordinator
from .engine import Controller
from .inputs import InputReader, car_spec, charger_spec, tuning
from .settings import SettingsStore
from .watch import InputWatcher, async_delete_issues
from .writer import ChargerWriter, issue_id

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class EvChargeRuntime:
    coordinator: EvChargeCoordinator
    store: SettingsStore


type EvChargeConfigEntry = ConfigEntry[EvChargeRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> bool:
    """Set up one charger controller."""
    store = SettingsStore(entry.options.get(CONF_INITIAL_SETTINGS))
    spec = charger_spec(entry.options)
    reader = InputReader(hass, entry.options)
    tune = tuning(entry.options)
    coordinator = EvChargeCoordinator(
        hass,
        entry,
        store,
        Controller(spec, car_spec(entry.options)),
        reader,
        ChargerWriter(hass, entry, reader, spec, tune.power_update_threshold_w),
        tune,
    )
    # A repair issue from before the restart says nothing about the charger
    # now; the writer raises it again when the charger still does not follow.
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))
    await coordinator.async_load_state()
    entry.runtime_data = EvChargeRuntime(coordinator, store)

    # The setting entities restore their values while the platforms load, so
    # the first run uses the user's settings, not the defaults.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # After the platforms: the dashboard refers to their entity IDs. It uses
    # Lovelace internals, so a failure there must not stop the controller.
    try:
        await dashboard.async_setup(hass, entry)
    except Exception:  # noqa: BLE001
        LOGGER.warning("The dashboard could not be set up", exc_info=True)
    entry.async_on_unload(async_at_started(hass, coordinator.async_start))
    watcher = InputWatcher(hass, entry)
    await watcher.async_start()
    entry.async_on_unload(watcher.stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> bool:
    coordinator = entry.runtime_data.coordinator
    coordinator.writer.cancel()
    await coordinator.async_save_state()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EvChargeConfigEntry) -> None:
    """Delete the saved energy totals, the dashboard and any repair issue."""
    store = EvChargeCoordinator.energy_store(hass, entry)
    await store.async_remove()
    await dashboard.async_remove(hass, entry)
    ir.async_delete_issue(hass, DOMAIN, issue_id(entry))
    async_delete_issues(hass, entry)
