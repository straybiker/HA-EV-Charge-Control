"""Sensors that show the controller's decision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EvChargeConfigEntry
from .coordinator import EvChargeCoordinator, Snapshot
from .engine import Reason
from .entity import init_entity


@dataclass(frozen=True, kw_only=True)
class OutputSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Snapshot], Any]


def _solar_surplus(s: Snapshot) -> int | None:
    return None if s.solar_surplus_w is None else round(s.solar_surplus_w)


def _car_from_grid(s: Snapshot) -> int | None:
    """The part of the target power that comes from the grid; 0 when idle."""
    if not s.output.current_a or s.output.power_w is None:
        return 0
    if s.solar_surplus_w is None:
        return None
    return round(max(s.output.power_w - s.solar_surplus_w, 0.0))


def _car_from_solar(s: Snapshot) -> int | None:
    """The rest of the target power: with Car from grid, the whole target."""
    if not s.output.current_a or s.output.power_w is None:
        return 0
    if s.solar_surplus_w is None:
        return None
    return round(min(s.output.power_w, s.solar_surplus_w))


def _available_from_grid(s: Snapshot) -> int | None:
    """The grid part of Available for the car; the solar surplus is the rest."""
    if s.house_power_w is None:
        return None
    return round(max(s.power_limit_w - max(s.house_power_w, 0.0), 0.0))


def _available(s: Snapshot) -> int | None:
    """What the car could take within the limit, with the house as it is now."""
    if s.house_power_w is None:
        return None
    return round(max(s.power_limit_w - s.house_power_w, 0.0))


def _energy(key: str, field: str) -> OutputSensorDescription:
    """Total charged energy; usable in the Energy dashboard and by an EMS."""
    return OutputSensorDescription(
        key=key,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda s: round(getattr(s.energy, field), 4),
    )


SENSORS: tuple[OutputSensorDescription, ...] = (
    OutputSensorDescription(
        key="target_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.output.current_a,
    ),
    OutputSensorDescription(
        key="target_phases",
        value_fn=lambda s: int(s.output.phase) if s.output.phase is not None else None,
    ),
    OutputSensorDescription(
        key="target_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: (
            round(s.output.power_w) if s.output.power_w is not None else None
        ),
    ),
    OutputSensorDescription(
        key="decision",
        device_class=SensorDeviceClass.ENUM,
        options=[r.value for r in Reason],
        value_fn=lambda s: s.output.reason.value,
    ),
    OutputSensorDescription(
        key="charger_efficiency",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: round(s.output.efficiency * 100, 1),
    ),
    OutputSensorDescription(
        key="solar_surplus",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_solar_surplus,
    ),
    # The key stays grid_share so existing entity IDs do not change.
    OutputSensorDescription(
        key="grid_share",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_car_from_grid,
    ),
    OutputSensorDescription(
        key="car_from_solar",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_car_from_solar,
    ),
    OutputSensorDescription(
        key="available_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_available,
    ),
    OutputSensorDescription(
        key="available_from_grid",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_available_from_grid,
    ),
    OutputSensorDescription(
        key="phase_hold_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.output.phase_hold_until,
    ),
    OutputSensorDescription(
        key="effective_power_limit",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: round(s.power_limit_w),
    ),
    _energy("charged_energy", "charged_kwh"),
    _energy("charged_from_grid", "from_grid_kwh"),
    _energy("charged_from_solar", "from_solar_kwh"),
    # Start again at 0 at local midnight: no utility meter helper needed.
    _energy("charged_today", "charged_today_kwh"),
    _energy("charged_from_grid_today", "from_grid_today_kwh"),
    _energy("charged_from_solar_today", "from_solar_today_kwh"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(OutputSensor(coordinator, entry, d) for d in SENSORS)


class OutputSensor(CoordinatorEntity[EvChargeCoordinator], SensorEntity):
    entity_description: OutputSensorDescription

    def __init__(
        self,
        coordinator: EvChargeCoordinator,
        entry: EvChargeConfigEntry,
        description: OutputSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        init_entity(self, entry, description)

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)
