"""Switch settings of the charge controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EvChargeConfigEntry
from .const import DOMAIN
from .engine import ChargeMode
from .entity import init_entity
from .settings import CONTROL_CHARGER, SettingsStore

# The coordinator calculates; entities only read its result, and the
# setting entities write to memory. No update needs to wait for another.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SettingSwitchDescription(SwitchEntityDescription):
    field: str
    default: bool = False


SINGLE_PHASE_ONLY = "single_phase_only"

SWITCHES: tuple[SettingSwitchDescription, ...] = tuple(
    # Settings: the device page lists them under Configuration.
    SettingSwitchDescription(key=key, field=key, entity_category=EntityCategory.CONFIG)
    for key in (
        "car_aware",
        "solar_when_ems_blocks",
        "single_phase_only",
        "ems_control",
        "ems_as_onoff",
    )
)

# Off on a new device: it starts in shadow mode until the user opts in.
CONTROL = SettingSwitchDescription(key=CONTROL_CHARGER, field=CONTROL_CHARGER)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    single_phase_charger = not runtime.coordinator.reader.three_phases
    async_add_entities(
        SettingSwitch(
            entry,
            runtime.store,
            d,
            fixed_on=single_phase_charger and d.key == SINGLE_PHASE_ONLY,
        )
        for d in (CONTROL, *SWITCHES)
    )


class SettingSwitch(SwitchEntity, RestoreEntity):
    """A switch setting. It restores its last value after a restart (D09)."""

    entity_description: SettingSwitchDescription

    def __init__(
        self,
        entry: EvChargeConfigEntry,
        store: SettingsStore,
        description: SettingSwitchDescription,
        *,
        fixed_on: bool = False,
    ) -> None:
        init_entity(self, entry, description)
        self._store = store
        # A charger without a 3-phase option: Single phase only stays on (B18).
        self._fixed_on = fixed_on
        # Control charger is never imported: a new device starts in shadow mode.
        self._attr_is_on = (
            description.default
            if description.key == CONTROL_CHARGER
            else bool(store.initial(description.key, description.default))
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.key == CONTROL_CHARGER:
            # Restored by the coordinator from the entry's own store, which is
            # written at once on every change.
            self._attr_is_on = bool(self._store.get(CONTROL_CHARGER))
            return
        last = await self.async_get_last_state()
        if last is not None and last.state in (STATE_ON, STATE_OFF):
            self._attr_is_on = last.state == STATE_ON
        if self._fixed_on:
            self._attr_is_on = True
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
        if self._fixed_on:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="single_phase_fixed",
            )
        self._set(False)

    def _set(self, on: bool) -> None:
        self._attr_is_on = on
        self._store.set(self.entity_description.field, on)
        self.async_write_ha_state()
