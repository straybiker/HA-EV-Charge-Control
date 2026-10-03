"""Diagnostics download for a charge controller."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EvChargeConfigEntry
from .const import CONF_NAME


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EvChargeConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    last = coordinator.reader.last
    setpoint = coordinator.writer.last_setpoint
    extras = coordinator.reader.last_extras
    snapshot = coordinator.data
    return {
        "options": async_redact_data(dict(entry.options), {CONF_NAME}),
        "settings": asdict(runtime.store.snapshot()) | runtime.store.extras(),
        "tuning": asdict(coordinator.tuning),
        "measurements": asdict(last) if last else None,
        "extras": asdict(extras) if extras else None,
        "snapshot": asdict(snapshot) if snapshot else None,
        "energy": coordinator.energy.state(),
        "intended_setpoint": asdict(setpoint) if setpoint else None,
        "last_update_success": coordinator.last_update_success,
    }
