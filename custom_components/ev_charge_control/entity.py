"""Shared base for all entities of the controller device."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One virtual device per entry.

    It is not linked to the charger's device: that device belongs to the
    charger's own integration.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="EV Charge Control",
        model="Charge controller",
        entry_type=DeviceEntryType.SERVICE,
    )


def init_entity(
    entity: Entity, entry: ConfigEntry, description: EntityDescription
) -> None:
    entity.entity_description = description
    # Settings write their own state; outputs follow the coordinator.
    entity._attr_should_poll = False
    entity._attr_has_entity_name = True
    entity._attr_translation_key = description.translation_key or description.key
    entity._attr_unique_id = f"{entry.entry_id}_{description.key}"
    entity._attr_device_info = device_info(entry)
