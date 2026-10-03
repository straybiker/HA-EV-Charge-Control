"""Applying the controller's output to the charger.

Writes go only through the charger's own entities: its current-limit
number and its phase select. A write counts as confirmed when the charger
follows it, so a charger integration that accepts a value but does not
pass it on is noticed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    CONF_ACTIVE_PHASES,
    CONF_APPLIED_CURRENT,
    CONF_CONTROL_OFF,
    CONF_CURRENT_LIMIT,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONTROL_OFF_KEEP,
    CONTROL_OFF_STOP,
    DEFAULT_CONTROL_OFF,
    DOMAIN,
    LOGGER,
)
from .engine import ChargerSpec, ConnectionState, Measurements, Output, Phase, Setpoint
from .inputs import InputReader

# How long the charger may take to follow a write, as in the EV Load
# Balancer package.
ZERO_TIMEOUT_S = 30
PHASE_TIMEOUT_S = 60
CURRENT_TIMEOUT_S = 30
# Unconfirmed writes in a row before the repair issue is raised.
MAX_UNCONFIRMED = 3


def issue_id(entry: ConfigEntry) -> str:
    return f"charger_not_responding_{entry.entry_id}"


class ChargerWriter:
    """Writes setpoints while Control charger is on.

    One write sequence runs at a time, in the background, so a slow charger
    never delays a controller run. Runs that come while a sequence is still
    waiting for the charger write nothing. An unconfirmed write is retried
    at the next run, also when the controller sees nothing new to write.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        reader: InputReader,
        spec: ChargerSpec,
        power_update_threshold_w: float,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._reader = reader
        self.spec = spec
        self._threshold_w = power_update_threshold_w
        o = entry.options
        self._current_entity: str = o[CONF_CURRENT_LIMIT]
        self._phase_entity: str = o[CONF_PHASE_SELECT]
        self._applied_entity: str = o[CONF_APPLIED_CURRENT]
        self._active_entity: str = o[CONF_ACTIVE_PHASES]
        self._options = {
            Phase.ONE: o[CONF_PHASE_OPTION_1],
            Phase.THREE: o[CONF_PHASE_OPTION_3],
        }
        self._off_action: str = o.get(CONF_CONTROL_OFF, DEFAULT_CONTROL_OFF)
        self.last_setpoint: Setpoint | None = None
        self.failures = 0
        self._retry = False
        self._task: asyncio.Task | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def not_responding(self) -> bool:
        return self.failures >= MAX_UNCONFIRMED

    def apply(self, output: Output, m: Measurements, control: bool) -> None:
        """Start writing this run's setpoint, if there is one and control is on."""
        setpoint = output.setpoint
        if setpoint is None and self._retry and control:
            setpoint = _full_setpoint(output, m)
        if setpoint is not None:
            self.last_setpoint = setpoint
        if not control or setpoint is None or self.busy:
            return
        self._retry = False
        by_charger = m.connection == ConnectionState.CONNECTED
        self._start(self._write(setpoint, by_charger))

    def release(self, m: Measurements) -> None:
        """Control charger was switched off: hand over the charger once."""
        self.reset()
        action = self._off_action
        if action == CONTROL_OFF_KEEP:
            return
        if action == CONTROL_OFF_STOP:
            phase = m.commanded_phase or m.active_phases or self.spec.fallback_phase
            current = 0.0
        else:
            phase, current = self.spec.fallback_phase, self.spec.fallback_current_a
        setpoint = Setpoint(
            phase=phase,
            current_a=current,
            write_phase=m.commanded_phase != phase,
            write_current=True,
            zero_before_phase_change=(
                m.commanded_phase == Phase.ONE and phase == Phase.THREE
            ),
        )
        self.last_setpoint = setpoint
        self._start(self._hand_over(setpoint))

    @callback
    def reset(self) -> None:
        """Forget failures and stop a running sequence."""
        self.cancel()
        self.failures = 0
        self._retry = False
        ir.async_delete_issue(self._hass, DOMAIN, issue_id(self._entry))

    @callback
    def cancel(self) -> None:
        if self.busy:
            assert self._task is not None
            self._task.cancel()
        self._task = None

    def _start(self, coro) -> None:
        self._task = self._entry.async_create_background_task(
            self._hass, coro, name=f"{DOMAIN} write"
        )

    # --- sequences ------------------------------------------------------------

    async def _write(self, sp: Setpoint, by_charger: bool) -> None:
        try:
            confirmed = await self._sequence(sp, by_charger)
        except HomeAssistantError as err:
            LOGGER.warning("Writing to the charger failed: %s", err)
            confirmed = False
        self._record(confirmed)

    async def _hand_over(self, sp: Setpoint) -> None:
        """Write once without confirmation; control is off from now on."""
        try:
            await self._sequence(sp, by_charger=False)
        except HomeAssistantError as err:
            LOGGER.warning("Handing the charger over failed: %s", err)

    async def _sequence(self, sp: Setpoint, by_charger: bool) -> bool:
        """0 A before a 1 -> 3 switch, then the phase, then the current."""
        if sp.zero_before_phase_change:
            await self._set_current(0.0)
            # Go on after the timeout, as the package does: the phase change
            # matters more than a charger that is slow to report 0 A.
            await self._wait_for(
                *self._current_is(0.0, sp.phase, by_charger), ZERO_TIMEOUT_S
            )
        if sp.write_phase:
            await self._set_phase(sp.phase)
            if not await self._wait_for(
                *self._phase_is(sp.phase, by_charger), PHASE_TIMEOUT_S
            ):
                return False
        if sp.write_current or sp.zero_before_phase_change:
            await self._set_current(sp.current_a)
            if not await self._wait_for(
                *self._current_is(sp.current_a, sp.phase, by_charger),
                CURRENT_TIMEOUT_S,
            ):
                return False
        return True

    # Confirmation: by the charger's own sensors while a car is connected;
    # without a car they may not follow, so the control entities count.

    def _current_is(
        self, current_a: float, phase: Phase, by_charger: bool
    ) -> tuple[str, Callable[[], bool]]:
        if by_charger:
            return self._applied_entity, lambda: self._applied_near(current_a, phase)
        return self._current_entity, lambda: _same(
            self._reader.commanded_current(), current_a
        )

    def _phase_is(
        self, phase: Phase, by_charger: bool
    ) -> tuple[str, Callable[[], bool]]:
        if by_charger:
            return self._active_entity, lambda: self._reader.active_phases() == phase
        return self._phase_entity, lambda: self._reader.commanded_phase() == phase

    def _applied_near(self, current_a: float, phase: Phase) -> bool:
        """Within the power update threshold, and never stricter than half a step."""
        applied = self._reader.applied_current()
        if applied is None:
            return False
        tolerance = max(
            self._threshold_w / (self.spec.voltage_v * int(phase)),
            self.spec.current_step_a / 2,
        )
        return abs(applied - current_a) < tolerance + 1e-9

    def _record(self, confirmed: bool) -> None:
        if confirmed:
            if self.failures:
                LOGGER.info("The charger follows the writes again")
            self.failures = 0
            ir.async_delete_issue(self._hass, DOMAIN, issue_id(self._entry))
            return
        self.failures += 1
        self._retry = True
        LOGGER.warning("The charger did not confirm write %s in a row", self.failures)
        if self.failures == MAX_UNCONFIRMED:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                issue_id(self._entry),
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="charger_not_responding",
                translation_placeholders={"name": self._entry.title},
            )

    # --- the charger's entities ---------------------------------------------------

    async def _set_current(self, current_a: float) -> None:
        await self._hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": self._current_entity, "value": current_a},
            blocking=True,
        )

    async def _set_phase(self, phase: Phase) -> None:
        await self._hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": self._phase_entity, "option": self._options[phase]},
            blocking=True,
        )

    async def _wait_for(
        self, entity_id: str, check: Callable[[], bool], timeout_s: float
    ) -> bool:
        """True as soon as check() holds, False after the timeout."""
        if check():
            return True
        done: asyncio.Future[bool] = self._hass.loop.create_future()

        @callback
        def _changed(_event: Event[EventStateChangedData]) -> None:
            if not done.done() and check():
                done.set_result(True)

        @callback
        def _expired(_now) -> None:
            if not done.done():
                done.set_result(False)

        unsub_state = async_track_state_change_event(self._hass, entity_id, _changed)
        unsub_timer = async_call_later(self._hass, timeout_s, _expired)
        try:
            return await done
        finally:
            unsub_state()
            unsub_timer()


def _same(value: float | None, target: float) -> bool:
    return value is not None and abs(value - target) < 0.01


def _full_setpoint(output: Output, m: Measurements) -> Setpoint | None:
    """The whole target, for a retry: the write filter saw nothing to change."""
    if output.phase is None or output.current_a is None:
        return None
    actual = m.active_phases or m.commanded_phase
    return Setpoint(
        phase=output.phase,
        current_a=output.current_a,
        write_phase=actual != output.phase,
        write_current=True,
        zero_before_phase_change=actual == Phase.ONE and output.phase == Phase.THREE,
    )
