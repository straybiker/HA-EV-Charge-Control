"""Runs the controller on a timer and on discrete events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

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
from .engine import (
    Available,
    ConnectionState,
    Controller,
    Measurements,
    Output,
    Reason,
    Settings,
)
from .engine.average import ChargingAverage
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
    # As the controller reads it from the connection entity.
    connection: ConnectionState
    power_limit_w: float
    limit_entity_w: float | None
    # Export of the house, known also when nothing is charging.
    solar_surplus_w: float | None
    # House including the charger, as measured.
    total_power_w: float | None
    # The import price the controller read, per kWh.
    price: float | None
    # Learned efficiency by phase count ("1", "3").
    efficiencies: dict[str, float]
    # What the car would take now in the current mode, also without a car.
    available: Available | None
    # None when the setup has no EMS entity.
    ems_signal_w: float | None
    max_current_a: float
    energy: EnergyTotals
    # Mean charger power while charging, over a rolling window.
    average_charging_power_w: float | None
    computed_at: datetime = field(compare=False)


class EvChargeCoordinator(DataUpdateCoordinator[Snapshot]):
    """Owns the controller and the energy counter.

    The coordinator does not poll by itself: a run must not depend on
    whether any entity listens. It runs on its own interval timer and at
    once when a setting or the phase changes or the car connects or
    disconnects. Power sensors are read at each run but never trigger one.

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
        self.average = ChargingAverage()
        self._energy_store = self.energy_store(hass, entry)
        self._last_max_a: float | None = None
        self._last_limit_w: float | None = None
        self._cancel_timer: CALLBACK_TYPE | None = None
        self._control_was: bool | None = None

    @staticmethod
    def energy_store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
        """Where the energy totals of an entry are kept between restarts."""
        return Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.energy")

    async def async_load_state(self) -> None:
        """Restore what was saved before the last stop.

        The energy totals, the average, the learned charger efficiencies and
        Control charger. The switch is
        saved here at once when it changes, not through the entity restore
        state that Home Assistant writes only every 15 minutes: after a crash
        the controller must not write to the charger again because a recent
        "off" was lost.
        """
        state = await self._energy_store.async_load() or {}
        self.energy = EnergyCounter.restore(state)
        self.average = ChargingAverage.restore(state.get("average"))
        self.controller.restore_efficiency(state.get("efficiency"))
        self.store.set(CONTROL_CHARGER, bool(state.get(CONTROL_CHARGER)), notify=False)

    async def async_save_state(self) -> None:
        """Write the state now, so an unload, reload or crash loses nothing."""
        await self._energy_store.async_save(self._stored_state())

    def _stored_state(self) -> dict[str, Any]:
        return {
            **self.energy.state(),
            "average": self.average.state(),
            "efficiency": self.controller.efficiency_state(),
            CONTROL_CHARGER: bool(self.store.get(CONTROL_CHARGER)),
        }

    async def _async_update_data(self) -> Snapshot:
        now = dt_util.utcnow()
        measurements = self.reader.read()
        extras = self.reader.read_extras()
        max_a = self._max_current(extras)
        self.controller.charger = replace(self.controller.charger, max_current_a=max_a)
        settings = self.store.snapshot()
        limit_w = self._limit(extras, settings.power_limit_w)
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
            dt_util.as_local(now).date(),
        )
        average_w = self.average.update(
            now, measurements.charger_power_w, dt_util.as_local(now).date()
        )
        available = self.controller.available(settings, measurements, now)
        _log_run(settings, measurements, power_limit_w, output, available)
        self._energy_store.async_delay_save(self._stored_state, _ENERGY_SAVE_DELAY_S)
        return Snapshot(
            output=output,
            connection=measurements.connection,
            power_limit_w=power_limit_w,
            limit_entity_w=limit_w,
            ems_signal_w=measurements.ems_signal_w,
            solar_surplus_w=(
                None
                if measurements.house_power_w is None
                else max(-measurements.house_power_w, 0.0)
            ),
            total_power_w=(
                None
                if measurements.house_power_w is None
                or measurements.charger_power_w is None
                else measurements.house_power_w + measurements.charger_power_w
            ),
            price=measurements.price,
            efficiencies=self.controller.efficiency_state(),
            available=available,
            max_current_a=max_a,
            energy=energy,
            average_charging_power_w=average_w,
            computed_at=now,
        )

    def _apply(self, output: Output, measurements: Measurements) -> Output:
        control = bool(self.store.get(CONTROL_CHARGER))
        if self._control_was and not control:
            LOGGER.debug("Control charger off: handing the charger over")
            self.writer.release(measurements)
        elif control and self._control_was is False:
            LOGGER.debug("Control charger on: the controller writes from now on")
            self.writer.reset()
        self._control_was = control
        self.writer.spec = self.controller.charger
        self.writer.apply(output, measurements, control)
        if control and self.writer.not_responding:
            return replace(output, reason=Reason.CHARGER_NOT_RESPONDING)
        return output

    def _limit(self, extras: Extras, own_w: float) -> float | None:
        """The power limit entity's value, else the last value seen.

        None until it has reported once: the controller then has no power
        limit and writes nothing. Without an entity in the setup, the
        device's own Power limit number (B10).
        """
        if not self.reader.power_limit_entity:
            return own_w
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
    def _on_event(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if not self.reader.triggers_run(
            entity_id, event.data["old_state"], event.data["new_state"]
        ):
            return
        LOGGER.debug("%s changed: run now", entity_id)
        self._schedule_run()

    @callback
    def _on_setting(self, key: str) -> None:
        LOGGER.debug("Setting %s changed: run now", key)
        if key == CONTROL_CHARGER:
            # Saved at once: see async_load_state.
            assert self.config_entry is not None
            self.config_entry.async_create_background_task(
                self.hass, self.async_save_state(), name=f"{DOMAIN} save"
            )
        self._schedule_run()

    @callback
    def _schedule_run(self) -> None:
        assert self.config_entry is not None
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), name=f"{DOMAIN} run"
        )


def _log_run(
    settings: Settings,
    m: Measurements,
    power_limit_w: float,
    out: Output,
    available: Available | None,
) -> None:
    """One line per run: what the controller read and what it decided."""
    if not LOGGER.isEnabledFor(logging.DEBUG):
        return
    target = (
        f"{int(out.phase)} x {out.current_a:.1f} A ({out.power_w or 0:.0f} W)"
        if out.phase is not None and out.current_a is not None
        else "no setpoint"
    )
    LOGGER.debug(
        "Run: mode %s, %s, house %s W, charger %s W, limit %.0f W, price %s, "
        "EMS %s W, SOC %s %% -> %s, %s, grid %s, available %s W",
        settings.mode.value,
        m.connection.value if m.connection is not None else None,
        m.house_power_w,
        m.charger_power_w,
        power_limit_w,
        m.price,
        m.ems_signal_w,
        m.car_soc,
        out.reason.value,
        target,
        "allowed" if out.grid_allowed else "blocked",
        None if available is None else round(available.total_w),
    )
