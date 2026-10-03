"""The charge mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvChargeConfigEntry
from .const import DOMAIN
from .engine import ChargeMode
from .entity import init_entity
from .settings import SettingsStore

MODE = SelectEntityDescription(key="charge_mode", options=[m.value for m in ChargeMode])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChargeModeSelect(entry, entry.runtime_data.store)])


class ChargeModeSelect(SelectEntity, RestoreEntity):
    """The charge mode. It restores its last value after a restart (D09)."""

    def __init__(self, entry: EvChargeConfigEntry, store: SettingsStore) -> None:
        init_entity(self, entry, MODE)
        self._store = store
        self._attr_current_option = ChargeMode.OFF.value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        option = ChargeMode.OFF.value
        if last is not None and last.state in self.options:
            option = last.state
        self._attr_current_option = option
        self._store.set("mode", ChargeMode(option), notify=False)

    async def async_select_option(self, option: str) -> None:
        if option == ChargeMode.MIN_3P and self._store.get("single_phase_only"):
            # D07: 3-Phases Minimum cannot run on a single-phase-only setup.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="mode_conflicts_single_phase",
            )
        self._attr_current_option = option
        self._store.set("mode", ChargeMode(option))
        self.async_write_ha_state()
