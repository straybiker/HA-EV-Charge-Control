"""Repair issues for source entities that are renamed or removed.

The setup stores entity IDs. When the user renames or deletes one of them,
the controller reads nothing and falls back to the fail-safe. The watcher
says so with a repair issue, and proposes the new ID after a rename. It
never changes the setup itself: the user confirms the new entity in
Configure.

Some sources appear only some time after a start: an EMS such as EMHASS
publishes its sensors after its first run. The check for missing entities
therefore waits, and a missing-entity issue closes when the entity appears.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_call_later,
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CONF_ACTIVE_PHASES,
    CONF_APPLIED_CURRENT,
    CONF_CAR_SOC,
    CONF_CHARGER_POWER,
    CONF_CONNECTION,
    CONF_CURRENT_LIMIT,
    CONF_EMS,
    CONF_ENERGY_METER,
    CONF_HOUSE_POWER,
    CONF_MAX_CURRENT_ENTITY,
    CONF_PHASE_SELECT,
    CONF_POWER_LIMIT,
    CONF_PRICE,
    CONF_SOLAR_POWER,
    DOMAIN,
    LOGGER,
)

RENAMED = "input_renamed"
MISSING = "input_missing"

# How long after Home Assistant has started a source may still be missing
# before it is reported.
MISSING_GRACE = timedelta(minutes=10)

# Option key -> the options-flow step that sets it, for the issue text.
STEPS: dict[str, str] = {
    CONF_CURRENT_LIMIT: "init",
    CONF_PHASE_SELECT: "init",
    CONF_CONNECTION: "inputs",
    CONF_CHARGER_POWER: "inputs",
    CONF_APPLIED_CURRENT: "inputs",
    CONF_ACTIVE_PHASES: "inputs",
    CONF_MAX_CURRENT_ENTITY: "inputs",
    CONF_ENERGY_METER: "inputs",
    CONF_HOUSE_POWER: "household",
    CONF_POWER_LIMIT: "household",
    CONF_SOLAR_POWER: "household",
    CONF_CAR_SOC: "car",
    CONF_PRICE: "price",
    CONF_EMS: "price",
}


def issue_id(kind: str, entry: ConfigEntry, key: str) -> str:
    return f"{kind}_{entry.entry_id}_{key}"


@callback
def async_delete_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget every input issue of the entry; the watcher raises them again."""
    for key in STEPS:
        for kind in (RENAMED, MISSING):
            ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry, key))


class InputWatcher:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        # Entity ID -> option key, for the entities the setup uses.
        self._roles: dict[str, str] = {
            entry.options[key]: key for key in STEPS if entry.options.get(key)
        }
        self._unsubscribe: list[CALLBACK_TYPE] = []

    async def async_start(self) -> None:
        """Follow the entity registry from now on; check for missing entities
        once Home Assistant has started and the grace time has passed."""
        async_delete_issues(self._hass, self._entry)
        self._unsubscribe = [
            async_track_entity_registry_updated_event(
                self._hass, list(self._roles), self._on_registry
            ),
            async_track_state_change_event(
                self._hass, list(self._roles), self._on_state
            ),
        ]
        # Runs _on_started at once when Home Assistant is already running, so
        # the list must exist before it adds the timer to it.
        self._unsubscribe.append(async_at_started(self._hass, self._on_started))

    @callback
    def stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        async_delete_issues(self._hass, self._entry)

    @callback
    def _on_started(self, _hass: HomeAssistant) -> None:
        self._unsubscribe.append(
            async_call_later(self._hass, MISSING_GRACE, self._check_missing)
        )

    async def _check_missing(self, _now: datetime) -> None:
        registry = er.async_get(self._hass)
        for entity_id, key in self._roles.items():
            if (
                self._hass.states.get(entity_id) is None
                and registry.async_get(entity_id) is None
            ):
                await self._raise(MISSING, key, old=entity_id)

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        """A source that appears closes its missing-entity issue."""
        if event.data["old_state"] is not None or event.data["new_state"] is None:
            return
        entity_id = event.data["entity_id"]
        ir.async_delete_issue(
            self._hass, DOMAIN, issue_id(MISSING, self._entry, self._roles[entity_id])
        )

    @callback
    def _on_registry(self, event: Event[er.EventEntityRegistryUpdatedData]) -> None:
        data = event.data
        if data["action"] == "update":
            old = data.get("old_entity_id")
            if old is None or old not in self._roles:
                return
            kind, new = RENAMED, data["entity_id"]
        elif data["action"] == "remove":
            old, kind, new = data["entity_id"], MISSING, None
            if old not in self._roles:
                return
        else:
            return
        key = self._roles[old]
        self._entry.async_create_background_task(
            self._hass, self._raise(kind, key, old=old, new=new), name=f"{DOMAIN} issue"
        )

    async def _raise(
        self, kind: str, key: str, *, old: str, new: str | None = None
    ) -> None:
        role, step = await self._labels(key)
        LOGGER.warning(
            "%s (%s) %s; the controller keeps using %s until the setup is changed",
            old,
            role,
            f"was renamed to {new}" if new else "does not exist",
            old,
        )
        for other in (RENAMED, MISSING):
            if other != kind:
                ir.async_delete_issue(
                    self._hass, DOMAIN, issue_id(other, self._entry, key)
                )
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            issue_id(kind, self._entry, key),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=kind,
            translation_placeholders={
                "name": self._entry.title,
                "role": role,
                "step": step,
                "old": old,
                "new": new or "",
            },
        )

    async def _labels(self, key: str) -> tuple[str, str]:
        """The option's label and its step title, in the user's language."""
        step = STEPS[key]
        translations = await async_get_translations(
            self._hass, self._hass.config.language, "options", {DOMAIN}
        )
        base = f"component.{DOMAIN}.options.step.{step}"
        return (
            translations.get(f"{base}.data.{key}", key),
            translations.get(f"{base}.title", step),
        )
