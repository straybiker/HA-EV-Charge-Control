"""Binary sensors that show why the controller decided."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EvChargeConfigEntry
from .coordinator import EvChargeCoordinator
from .engine import Output
from .entity import init_entity


@dataclass(frozen=True, kw_only=True)
class OutputBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Output], bool | None]


BINARY_SENSORS: tuple[OutputBinaryDescription, ...] = (
    OutputBinaryDescription(key="grid_allowed", value_fn=lambda o: o.grid_allowed),
    OutputBinaryDescription(key="emergency", value_fn=lambda o: o.emergency),
    OutputBinaryDescription(key="target_reached", value_fn=lambda o: o.target_reached),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvChargeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        OutputBinarySensor(coordinator, entry, d) for d in BINARY_SENSORS
    )


class OutputBinarySensor(CoordinatorEntity[EvChargeCoordinator], BinarySensorEntity):
    entity_description: OutputBinaryDescription

    def __init__(
        self,
        coordinator: EvChargeCoordinator,
        entry: EvChargeConfigEntry,
        description: OutputBinaryDescription,
    ) -> None:
        super().__init__(coordinator)
        init_entity(self, entry, description)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)
