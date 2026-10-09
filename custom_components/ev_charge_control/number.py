"""Number settings of the charge controller."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EvChargeConfigEntry
from .const import CONF_POWER_LIMIT
from .entity import init_entity
from .settings import SettingsStore

# The coordinator calculates; entities only read its result, and the
# setting entities write to memory. No update needs to wait for another.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SettingNumberDescription(NumberEntityDescription):
    field: str
    default: float
    # Settings: the device page lists them under Configuration.
    entity_category: EntityCategory | None = EntityCategory.CONFIG
    # Settings store value = entity value x scale (minutes -> seconds).
    scale: float = 1.0


def _soc(key: str, default: float) -> SettingNumberDescription:
    return SettingNumberDescription(
        key=key,
        field=key,
        default=default,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.BATTERY,
        mode=NumberMode.SLIDER,
    )


NUMBERS: tuple[SettingNumberDescription, ...] = (
    SettingNumberDescription(
        key="max_charging_cost",
        field="max_cost_rate",
        default=0.30,
        native_min_value=0,
        native_max_value=2,
        native_step=0.01,
        mode=NumberMode.BOX,
    ),
    _soc("target_soc", 80),
    _soc("comfort_soc", 50),
    _soc("emergency_soc", 20),
    SettingNumberDescription(
        key="solar_bridge",
        field="solar_bridge_w",
        default=0,
        native_min_value=0,
        native_max_value=5000,
        native_step=50,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        mode=NumberMode.BOX,
    ),
    # Only without a power limit entity in the setup (B10): set by hand or
    # by an automation of the EMS.
    SettingNumberDescription(
        key="power_limit",
        field="power_limit_w",
        default=5000,
        native_min_value=0,
        native_max_value=50000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    store = entry.runtime_data.store
    currency_unit = f"{hass.config.currency}/kWh"
    async_add_entities(
        SettingNumber(
            entry,
            store,
            d,
            unit=currency_unit if d.key == "max_charging_cost" else None,
        )
        for d in NUMBERS
        if d.key != "power_limit" or not entry.options.get(CONF_POWER_LIMIT)
    )


class SettingNumber(RestoreNumber):
    """A number setting. It restores its last value after a restart (D09)."""

    entity_description: SettingNumberDescription

    def __init__(
        self,
        entry: EvChargeConfigEntry,
        store: SettingsStore,
        description: SettingNumberDescription,
        unit: str | None = None,
    ) -> None:
        init_entity(self, entry, description)
        self._store = store
        self._attr_native_value = description.default
        if unit is not None:
            self._attr_native_unit_of_measurement = unit

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        d = self.entity_description
        value = d.default
        initial = self._store.initial(d.key, d.default)
        low, high = d.native_min_value or 0.0, d.native_max_value or 0.0
        if low <= initial <= high:
            value = initial
        last = await self.async_get_last_number_data()
        if (
            last is not None
            and last.native_value is not None
            and low <= last.native_value <= high
        ):
            value = last.native_value
        self._apply(value, notify=False)

    async def async_set_native_value(self, value: float) -> None:
        self._apply(value, notify=True)
        self.async_write_ha_state()

    def _apply(self, value: float, *, notify: bool) -> None:
        d = self.entity_description
        self._attr_native_value = value
        self._store.set(d.field, value * d.scale, notify=notify)
