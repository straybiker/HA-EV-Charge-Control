"""A charger whose current limit starts at 6 A, stopped by its charging switch (B22).

Without the switch nothing changes: test_charger_control covers that path.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ev_charge_control.const import DOMAIN

from .conftest import (
    APPLIED_CURRENT,
    CURRENT_LIMIT,
    DECISION,
    HOUSE_POWER,
    INPUTS_STEP,
    LIMITS_STEP,
    NAME_STEP,
    OPTIONS,
    OUTPUTS_STEP,
    PHASE_SELECT,
    PHASES_STEP,
    W,
    make_entry,
    setup,
)
from .test_charger_control import (
    FakeCharger,
    _on_three_phases,
    _settle,
    _start_in,
    _switch,
)

CHARGING = "input_boolean.test_charging_enabled"
LIMIT_6A = {"min": 6, "max": 16, "step": 0.1}


class SwitchCharger(FakeCharger):
    """Pauses with its switch; while paused it still reports its last current."""

    def __init__(self, hass: HomeAssistant, *, limit_while_off: bool = True) -> None:
        super().__init__(hass)
        self.limit_while_off = limit_while_off
        hass.services.async_register("input_boolean", "turn_on", self._toggle)
        hass.services.async_register("input_boolean", "turn_off", self._toggle)

    async def _toggle(self, call: ServiceCall) -> None:
        on = call.service == "turn_on"
        self.calls.append(("switch", "on" if on else "off"))
        self.hass.states.async_set(CHARGING, "on" if on else "off")
        if on and not self.limit_while_off:
            self.hass.states.async_set(CURRENT_LIMIT, "6", LIMIT_6A)


def _paused_at_6a(hass: HomeAssistant) -> None:
    _on_three_phases(hass)
    hass.states.async_set(CURRENT_LIMIT, "6", LIMIT_6A)
    hass.states.async_set(APPLIED_CURRENT, "6", {"unit_of_measurement": "A"})
    hass.states.async_set(CHARGING, "off")


def _entry(hass: HomeAssistant, **options) -> MockConfigEntry:
    return make_entry(hass, charging_switch_entity=CHARGING, **options)


async def test_a_start_writes_the_current_then_switches_on(
    hass: HomeAssistant, sources
) -> None:
    _paused_at_6a(hass)
    _start_in(hass, "fast")
    await setup(hass, _entry(hass))
    charger = SwitchCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    # 4500 W headroom on 3 phases: 6.5 A, and never 0 A.
    assert charger.calls == [("current", 6.5), ("switch", "on")]
    assert hass.states.get(DECISION).state == "charging"


async def test_a_stop_switches_off_and_the_switch_confirms_it(
    hass: HomeAssistant, sources
) -> None:
    _paused_at_6a(hass)
    _start_in(hass, "fast")
    entry = _entry(hass)
    await setup(hass, entry)
    charger = SwitchCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    charger.calls.clear()
    # No headroom left: the controller stops.
    hass.states.async_set(HOUSE_POWER, "5000", W)
    await _settle(hass, 11)
    assert charger.calls == [("switch", "off")]
    # The charger still reports 6.5 A while paused; the switch confirms.
    assert entry.runtime_data.coordinator.writer.failures == 0
    charger.calls.clear()
    await _settle(hass, 11)
    assert charger.calls == []


async def test_a_phase_switch_goes_through_the_switch(
    hass: HomeAssistant, sources
) -> None:
    hass.states.async_set(CURRENT_LIMIT, "10", LIMIT_6A)
    hass.states.async_set(APPLIED_CURRENT, "10", {"unit_of_measurement": "A"})
    hass.states.async_set(CHARGING, "on")
    _start_in(hass, "fast")
    await setup(hass, _entry(hass))
    charger = SwitchCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    # From 1 to 3 phases at 6.5 A: the stop is the switch, never 0 A.
    assert charger.calls == [
        ("switch", "off"),
        ("phase", "3 Phases"),
        ("current", 6.5),
        ("switch", "on"),
    ]


async def test_a_limit_shown_only_while_on_is_waited_for(
    hass: HomeAssistant, sources
) -> None:
    _paused_at_6a(hass)
    hass.states.async_set(CURRENT_LIMIT, "unavailable", LIMIT_6A)
    _start_in(hass, "fast")
    await setup(hass, _entry(hass))
    charger = SwitchCharger(hass, limit_while_off=False)
    await _switch(hass, True)
    await _settle(hass)
    assert charger.calls == [("switch", "on"), ("current", 6.5)]


async def test_hand_over_stop_switches_off(hass: HomeAssistant, sources) -> None:
    _paused_at_6a(hass)
    _start_in(hass, "fast")
    await setup(hass, _entry(hass, control_off_action="stop"))
    charger = SwitchCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    charger.calls.clear()
    await _switch(hass, False)
    await _settle(hass)
    assert charger.calls == [("switch", "off")]


async def test_hand_over_fallback_writes_the_current_and_switches_on(
    hass: HomeAssistant, sources
) -> None:
    _paused_at_6a(hass)
    _start_in(hass, "off")
    await setup(hass, _entry(hass))
    charger = SwitchCharger(hass)
    await _switch(hass, True)
    await _settle(hass)
    charger.calls.clear()
    await _switch(hass, False)
    await _settle(hass)
    assert charger.calls == [("phase", "1 Phase"), ("current", 7.0), ("switch", "on")]


# --- setup -----------------------------------------------------------------------


async def _flow(hass: HomeAssistant, outputs: dict, limits: dict | None = None):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    for data in (NAME_STEP, outputs, PHASES_STEP, INPUTS_STEP, limits):
        if data is None:
            break
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
        if result.get("errors"):
            break
    return result


async def test_a_switch_allows_a_current_limit_above_0_a(
    hass: HomeAssistant, sources
) -> None:
    hass.states.async_set(CURRENT_LIMIT, "6", LIMIT_6A)
    hass.states.async_set(CHARGING, "off")
    result = await _flow(hass, OUTPUTS_STEP | {"charging_switch_entity": CHARGING})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phases"


async def test_the_switch_cannot_be_the_phase_setting(
    hass: HomeAssistant, sources
) -> None:
    result = await _flow(hass, OUTPUTS_STEP | {"charging_switch_entity": PHASE_SELECT})
    assert result["errors"]["base"] == "charging_switch_is_phase"


async def test_the_switch_is_not_shared(hass: HomeAssistant, sources) -> None:
    other = OPTIONS | {
        "current_limit_entity": "number.test_other_limit",
        "phase_select_entity": "select.test_other_phases",
        "charging_switch_entity": CHARGING,
    }
    MockConfigEntry(domain=DOMAIN, options=other).add_to_hass(hass)
    result = await _flow(hass, OUTPUTS_STEP | {"charging_switch_entity": CHARGING})
    assert result["errors"]["base"] == "charging_switch_in_use"


async def test_min_current_not_below_the_limit_minimum(
    hass: HomeAssistant, sources
) -> None:
    hass.states.async_set(CURRENT_LIMIT, "6", LIMIT_6A)
    result = await _flow(
        hass,
        OUTPUTS_STEP | {"charging_switch_entity": CHARGING},
        LIMITS_STEP | {"min_current_a": 5},
    )
    assert result["errors"]["base"] == "min_below_current_limit_min"
