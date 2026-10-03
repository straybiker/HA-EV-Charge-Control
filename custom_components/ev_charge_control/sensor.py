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


def _budget(field: str) -> Callable[[Snapshot], Any]:
    return lambda s: round(getattr(s.output.budget, field)) if s.output.budget else None


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
        value_fn=_budget("solar_w"),
    ),
    OutputSensorDescription(
        key="grid_share",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_budget("grid_w"),
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
