"""Runs the controller on a timer and on discrete events."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HARDWARE_MAX_CURRENT, LOGGER
from .engine import Controller, Measurements, Output, Reason
from .engine.energy import EnergyCounter, EnergyTotals
from .engine.limit import effective_power_limit
from .inputs import Extras, InputReader, Tuning
from .settings import CONTROL_CHARGER, SettingsStore
from .writer import ChargerWriter

# Merges triggers that arrive together (a mode change plus a tick) into one run.
_DEBOUNCE_S = 1.0
# Energy totals are saved at most this often; a restart loses at most this much.
_ENERGY_SAVE_DELAY_S = 60
_STORAGE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What one run produced. Entities read their state from it."""

    output: Output
    power_limit_w: float
    limit_entity_w: float | None
    # Export of the house, known also when nothing is charging.
    solar_surplus_w: float | None
    max_current_a: float
    energy: EnergyTotals
    computed_at: datetime = field(compare=False)


class EvChargeCoordinator(DataUpdateCoordinator[Snapshot]):
    """Owns the controller and the energy counter.

    The coordinator does not poll by itself: a run must not depend on
    whether any entity listens. It runs on its own interval timer and at
    once when a setting, the connection or the phase changes. Power sensors
    are read at each run but never trigger one.

    The writer gets every run's output. It writes only while Control
    charger is on; switching it off hands the charger over once.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: SettingsStore,
        controller: Controller,
        reader: InputReader,
        writer: ChargerWriter,
        tuning: Tuning,
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
        self.tuning = tuning
        self.energy = EnergyCounter()
        self._energy_store = self.energy_store(hass, entry)
        self._last_max_a: float | None = None
        self._last_limit_w: float | None = None
        self._cancel_timer: CALLBACK_TYPE | None = None
        self._control_was: bool | None = None

    @staticmethod
    def energy_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict]:
        """Where the energy totals of an entry are kept between restarts."""
        return Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.energy")

    async def async_load_energy(self) -> None:
        """Restore the energy totals saved before the last stop."""
        self.energy = EnergyCounter.restore(await self._energy_store.async_load())

    async def async_save_energy(self) -> None:
        """Write the totals now, so an unload or reload loses nothing."""
        await self._energy_store.async_save(self.energy.state())

    async def _async_update_data(self) -> Snapshot:
        now = dt_util.utcnow()
        measurements = self.reader.read()
        extras = self.reader.read_extras()
        max_a = self._max_current(extras)
        self.controller.charger = replace(self.controller.charger, max_current_a=max_a)
        settings = self.store.snapshot()
        limit_w = self._limit(extras)
        power_limit_w = effective_power_limit(limit_w, self.tuning.peak_factor)
        settings = replace(
            settings,
            power_limit_w=power_limit_w,
            power_update_threshold_w=self.tuning.power_update_threshold_w,
            phase_hold_s=self.tuning.phase_hold_s,
        )
        if not self.reader.three_phases:
            settings = replace(settings, single_phase_only=True)
        output = self.controller.step(settings, measurements, now)
        output = self._apply(output, measurements)
        energy = self.energy.update(
            now,
            measurements.charger_power_w,
            measurements.house_power_w,
            extras.meter_kwh,
        )
        self._energy_store.async_delay_save(self.energy.state, _ENERGY_SAVE_DELAY_S)
        return Snapshot(
            output=output,
            power_limit_w=power_limit_w,
            limit_entity_w=limit_w,
            solar_surplus_w=(
                None
                if measurements.house_power_w is None
                else max(-measurements.house_power_w, 0.0)
            ),
            max_current_a=max_a,
            energy=energy,
            computed_at=now,
        )

    def _apply(self, output: Output, measurements: Measurements) -> Output:
        control = bool(self.store.get(CONTROL_CHARGER))
        if self._control_was and not control:
            self.writer.release(measurements)
        elif control and self._control_was is False:
            self.writer.reset()
        self._control_was = control
        self.writer.spec = self.controller.charger
        self.writer.apply(output, measurements, control)
        if control and self.writer.not_responding:
            return replace(output, reason=Reason.CHARGER_NOT_RESPONDING)
        return output

    def _limit(self, extras: Extras) -> float | None:
        """The power limit entity's value, else the last value seen.

        None until it has reported once: the controller then has no power
        limit and writes nothing.
        """
        if extras.power_limit_w is not None and extras.power_limit_w > 0:
            self._last_limit_w = extras.power_limit_w
        return self._last_limit_w

    def _max_current(self, extras: Extras) -> float:
        """The charger maximum for this run.

        From the max current entity: its value, else the last value seen,
        else the fallback current (the safe choice until the charger
        reports). Never above the hardware limit.
        """
        if extras.max_current_a is not None and extras.max_current_a > 0:
            self._last_max_a = min(extras.max_current_a, HARDWARE_MAX_CURRENT)
        if self._last_max_a is not None:
            return self._last_max_a
        return self.controller.charger.fallback_current_a

    async def async_start(self, hass: HomeAssistant) -> None:
        """Start once Home Assistant has started, so sources have loaded."""
        assert self.config_entry is not None
        self._cancel_timer = async_track_time_interval(
            self.hass,
            self._on_tick,
            timedelta(seconds=self.tuning.recalc_interval_s),
            name=f"{DOMAIN} controller",
            cancel_on_shutdown=True,
        )
        self.config_entry.async_on_unload(self._disarm_timer)
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                hass, self.reader.event_entities, self._on_event
            )
        )
        self.config_entry.async_on_unload(self.store.add_listener(self._on_setting))
        await self.async_refresh()

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
    def _on_setting(self, _key: str) -> None:
        self._schedule_run()

    @callback
    def _schedule_run(self) -> None:
        assert self.config_entry is not None
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), name=f"{DOMAIN} run"
        )
