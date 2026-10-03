"""Shared base for all entities of the controller device."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One virtual device per entry.

    A regular device, as the integration type says. It is not linked to
    the charger's device: that device belongs to the charger's own
    integration.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="EV Charge Control",
        model="Charge controller",
        # Explicit None: devices registered as a service by earlier versions
        # become regular devices; leaving the key out would keep the old type.
        entry_type=None,
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
