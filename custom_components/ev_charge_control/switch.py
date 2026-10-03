"""Switch settings of the charge controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvChargeConfigEntry
from .const import DOMAIN
from .engine import ChargeMode
from .entity import init_entity
from .settings import FOLLOW_MONTHLY_PEAK, SettingsStore


@dataclass(frozen=True, kw_only=True)
class SettingSwitchDescription(SwitchEntityDescription):
    field: str
    default: bool = False


SWITCHES: tuple[SettingSwitchDescription, ...] = tuple(
    SettingSwitchDescription(key=key, field=key)
    for key in (
        "car_aware",
        "solar_when_ems_blocks",
        "single_phase_only",
        "ems_control",
        "ems_as_onoff",
    )
)

FOLLOW_PEAK = SettingSwitchDescription(
    key=FOLLOW_MONTHLY_PEAK, field=FOLLOW_MONTHLY_PEAK, default=True
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    switches = list(SWITCHES)
    # Following the monthly peak needs a peak sensor from the setup.
    if runtime.coordinator.reader.has_monthly_peak:
        switches.append(FOLLOW_PEAK)
    async_add_entities(SettingSwitch(entry, runtime.store, d) for d in switches)


class SettingSwitch(SwitchEntity, RestoreEntity):
    """A switch setting. It restores its last value after a restart (D09)."""

    entity_description: SettingSwitchDescription

    def __init__(
        self,
        entry: EvChargeConfigEntry,
        store: SettingsStore,
        description: SettingSwitchDescription,
    ) -> None:
        init_entity(self, entry, description)
        self._store = store
        self._attr_is_on = description.default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, STATE_OFF):
            self._attr_is_on = last.state == STATE_ON
        self._store.set(self.entity_description.field, self._attr_is_on, notify=False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (
            self.entity_description.field == "single_phase_only"
            and self._store.get("mode") == ChargeMode.MIN_3P
        ):
            # D07: refuse the combination at the source.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="single_phase_conflicts_mode",
            )
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)

    def _set(self, on: bool) -> None:
        self._attr_is_on = on
        self._store.set(self.entity_description.field, on)
        self.async_write_ha_state()
