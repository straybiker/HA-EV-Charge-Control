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
    return {
        "options": async_redact_data(dict(entry.options), {CONF_NAME}),
        "settings": asdict(runtime.store.snapshot()),
        "recalc_interval_s": runtime.store.recalc_interval_s,
        "measurements": asdict(last) if last else None,
        "output": asdict(coordinator.data) if coordinator.data else None,
        "intended_setpoint": asdict(setpoint) if setpoint else None,
        "last_update_success": coordinator.last_update_success,
    }
