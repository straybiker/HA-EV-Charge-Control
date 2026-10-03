"""Control charger: writing, confirmation, the repair issue and hand-over."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.ev_charge_control.const import DOMAIN
from custom_components.ev_charge_control.writer import issue_id

from .conftest import (
    ACTIVE_PHASES,
    APPLIED_CURRENT,
    CONTROL,
    CURRENT_LIMIT,
    DECISION,
    MODE_SELECT,
    PHASE_SELECT,
    make_entry,
    setup,
)

_PHASE_OPTIONS = {"options": ["1 Phase", "3 Phases"]}


class FakeCharger:
    """The charger's own integration: its current-limit and phase services.

    It replaces the number and select services, so the test sets the
    controller's own mode through the restore cache, before it is created.
    """

    def __init__(self, hass: HomeAssistant, *, follows: bool = True) -> None:
        self.hass = hass
        self.follows = follows
        self.calls: list[tuple[str, float | str]] = []
        hass.services.async_register("number", "set_value", self._set_value)
        hass.services.async_register("select", "select_option", self._select)

    async def _set_value(self, call: ServiceCall) -> None:
        value = float(call.data["value"])
        self.calls.append(("current", value))
        self.hass.states.async_set(CURRENT_LIMIT, str(value))
        if self.follows:
            self.hass.states.async_set(
                APPLIED_CURRENT, str(value), {"unit_of_measurement": "A"}
            )

    async def _select(self, call: ServiceCall) -> None:
        option = call.data["option"]
        self.calls.append(("phase", option))
        self.hass.states.async_set(PHASE_SELECT, option, _PHASE_OPTIONS)
        if self.follows:
            self.hass.states.async_set(ACTIVE_PHASES, option)


def _start_in(hass: HomeAssistant, mode: str) -> None:
    mock_restore_cache_with_extra_data(hass, ((State(MODE_SELECT, mode), {}),))


def _on_three_phases(hass: HomeAssistant) -> None:
    hass.states.async_set(PHASE_SELECT, "3 Phases", _PHASE_OPTIONS)
    hass.states.async_set(ACTIVE_PHASES, "3 Phases")


async def _switch(hass: HomeAssistant, on: bool) -> None:
    await hass.services.async_call(
        "switch", "turn_on" if on else "turn_off", {"entity_id": CONTROL}, blocking=True
    )


async def _settle(hass: HomeAssistant, seconds: float = 1.1) -> None:
    """Past the debounce, then until every write sequence has finished."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


async def _tick(hass: HomeAssistant, seconds: float) -> None:
    """Advance time without waiting for sequences that wait for the charger."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def _issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(entry))


async def test_control_is_off_on_a_new_device(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    assert hass.states.get(CONTROL).state == "off"


async def test_writes_0_a_then_the_phase_then_the_current(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    _start_in(hass, "fast")
    await setup(hass, entry)
    charger = FakeCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    # 5000 W limit - 500 W house = 4500 W: 6.5 A on 3 phases, from 1 phase.
    assert charger.calls == [
        ("current", 0.0),
        ("phase", "3 Phases"),
        ("current", 6.5),
    ]
    assert hass.states.get(DECISION).state != "charger_not_responding"


async def test_unconfirmed_writes_raise_a_repair_issue_until_the_charger_follows(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    _on_three_phases(hass)
    _start_in(hass, "fast")
    await setup(hass, entry)
    charger = FakeCharger(hass, follows=False)
    await _switch(hass, True)
    await _tick(hass, 1.1)
    for _ in range(12):
        await _tick(hass, 31)
        if _issue(hass, entry) is not None:
            break
    assert _issue(hass, entry) is not None
    # Retried with the same target, though the current limit already shows it.
    assert charger.calls.count(("current", 6.5)) >= 3
    await _tick(hass, 31)
    assert hass.states.get(DECISION).state == "charger_not_responding"

    charger.follows = True
    for _ in range(6):
        await _tick(hass, 31)
        if _issue(hass, entry) is None:
            break
    assert _issue(hass, entry) is None
    await _tick(hass, 11)
    assert hass.states.get(DECISION).state == "charging"


async def test_fail_safe_writes_are_confirmed_by_the_control_entities(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    """A dead applied-current sensor is a sensor fault, not a charger fault."""
    _on_three_phases(hass)
    hass.states.async_set(CURRENT_LIMIT, "10")
    hass.states.async_set(APPLIED_CURRENT, "unavailable")
    _start_in(hass, "fast")
    await setup(hass, entry)
    charger = FakeCharger(hass, follows=False)
    await _switch(hass, True)
    await _settle(hass)
    assert hass.states.get(DECISION).state == "failsafe"
    assert charger.calls == [("phase", "1 Phase"), ("current", 7.0)]
    assert entry.runtime_data.coordinator.writer.failures == 0


async def test_switching_control_off_hands_over_the_fallback(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    _on_three_phases(hass)
    _start_in(hass, "fast")
    await setup(hass, entry)
    charger = FakeCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    charger.calls.clear()
    await _switch(hass, False)
    await _settle(hass)
    assert charger.calls == [("phase", "1 Phase"), ("current", 7.0)]
    # Control is off: later runs write nothing.
    charger.calls.clear()
    await _settle(hass, 11)
    assert charger.calls == []


@pytest.mark.parametrize(
    ("action", "expected"), [("keep", []), ("stop", [("current", 0.0)])]
)
async def test_other_hand_over_actions(
    hass: HomeAssistant, sources, action: str, expected: list
) -> None:
    _on_three_phases(hass)
    _start_in(hass, "fast")
    await setup(hass, make_entry(hass, control_off_action=action))
    charger = FakeCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    charger.calls.clear()
    await _switch(hass, False)
    await _settle(hass)
    assert charger.calls == expected


async def test_a_restart_clears_an_old_repair_issue(
    hass: HomeAssistant, sources, entry: MockConfigEntry
) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="charger_not_responding",
    )
    await setup(hass, entry)
    assert _issue(hass, entry) is None
