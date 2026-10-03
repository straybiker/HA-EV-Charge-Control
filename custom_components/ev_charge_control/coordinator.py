"""Runs the controller on a timer and on discrete events."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER
from .engine import Controller, Output
from .inputs import InputReader
from .settings import RECALC_INTERVAL, SettingsStore
from .writer import ChargerWriter

# Merges triggers that arrive together (a mode change plus a tick) into one run.
_DEBOUNCE_S = 1.0


class EvChargeCoordinator(DataUpdateCoordinator[Output]):
    """Owns the controller. Its data is the latest controller output.

    The coordinator does not poll by itself: a run must not depend on
    whether any entity listens. It runs on its own interval timer and at
    once when the mode, a setting, the connection or the phase changes.
    Power sensors are read at each run but never trigger one.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: SettingsStore,
        controller: Controller,
        reader: InputReader,
        writer: ChargerWriter,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,
            always_update=False,
            request_refresh_debouncer=Debouncer(
                hass, LOGGER, cooldown=_DEBOUNCE_S, immediate=True
            ),
        )
        self.store = store
        self.controller = controller
        self.reader = reader
        self.writer = writer
        self._cancel_timer: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> Output:
        measurements = self.reader.read()
        output = self.controller.step(
            self.store.snapshot(), measurements, dt_util.utcnow()
        )
        await self.writer.async_apply(output)
        return output

    async def async_start(self, hass: HomeAssistant) -> None:
        """Start once Home Assistant has started, so sources have loaded."""
        assert self.config_entry is not None
        self._arm_timer()
        self.config_entry.async_on_unload(self._disarm_timer)
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                hass, self.reader.event_entities, self._on_event
            )
        )
        self.config_entry.async_on_unload(self.store.add_listener(self._on_setting))
        await self.async_refresh()

    @callback
    def _arm_timer(self) -> None:
        self._disarm_timer()
        self._cancel_timer = async_track_time_interval(
            self.hass,
            self._on_tick,
            timedelta(seconds=self.store.recalc_interval_s),
            name=f"{DOMAIN} controller",
            cancel_on_shutdown=True,
        )

    @callback
    def _disarm_timer(self) -> None:
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_request_refresh()

    @callback
    def _on_event(self, _event: Event[EventStateChangedData]) -> None:
        self._schedule_run()

    @callback
    def _on_setting(self, key: str) -> None:
        if key == RECALC_INTERVAL and self._cancel_timer is not None:
            self._arm_timer()
        self._schedule_run()

    @callback
    def _schedule_run(self) -> None:
        assert self.config_entry is not None
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), name=f"{DOMAIN} run"
        )
