"""Binary sensors that show why the controller decided."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EvChargeConfigEntry
from .coordinator import EvChargeCoordinator, Snapshot
from .engine import ConnectionState
from .entity import init_entity

# The coordinator calculates; entities only read its result, and the
# setting entities write to memory. No update needs to wait for another.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OutputBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Snapshot], bool | None]


def _car_connected(s: Snapshot) -> bool | None:
    """Unknown while the connection entity is unavailable or unreadable."""
    if s.connection == ConnectionState.CONNECTED:
        return True
    if s.connection == ConnectionState.DISCONNECTED:
        return False
    return None


BINARY_SENSORS: tuple[OutputBinaryDescription, ...] = (
    OutputBinaryDescription(
        key="car_connected",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=_car_connected,
    ),
    OutputBinaryDescription(
        key="grid_allowed", value_fn=lambda s: s.output.grid_allowed
    ),
    # Details of the decision, which already says emergency and target.
    OutputBinaryDescription(
        key="emergency",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.output.emergency,
    ),
    OutputBinaryDescription(
        key="target_reached",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.output.target_reached,
    ),
    # The EMS signal as the controller reads it: above 0 W the EMS allows the
    # grid. Unknown when the setup has no EMS entity.
    OutputBinaryDescription(
        key="ems_active",
        value_fn=lambda s: None if s.ems_signal_w is None else s.ems_signal_w > 0,
    ),
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
