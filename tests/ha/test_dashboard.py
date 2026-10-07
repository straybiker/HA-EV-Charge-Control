"""The controller's dashboard in the sidebar."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    HOUSE_POWER,
    HOUSEHOLD_STEP,
    INPUTS_STEP,
    LIMITS_STEP,
    OUTPUTS_STEP,
    PHASES_STEP,
    TUNING_STEP,
    make_entry,
    setup,
)

# The first controller's dashboard.
PATH = "ev-charge-control"


@pytest.fixture
async def lovelace(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "lovelace", {})


@pytest.fixture
def with_dashboard(hass: HomeAssistant) -> MockConfigEntry:
    return make_entry(hass, dashboard=True)


async def _config(hass: HomeAssistant) -> dict:
    return await hass.data[LOVELACE_DATA].dashboards[PATH].async_load(False)


def _panels(hass: HomeAssistant) -> dict:
    return hass.data.get(DATA_PANELS, {})


async def test_dashboard_in_the_sidebar(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    assert _panels(hass)[PATH].component_name == "lovelace"
    config = await _config(hass)
    assert [view["path"] for view in config["views"]] == ["overview"]
    text = json.dumps(config)
    # The device's own entities and the setup's inputs.
    assert "sensor.test_charger_available_for_the_car" in text
    assert "select.test_charger_charge_mode" in text
    assert HOUSE_POWER in text
    # No custom cards: a fresh install has none.
    assert "custom:" not in text


async def test_shadow_view_with_the_yaml_package(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    hass.states.async_set("sensor.ev_load_balancer_charger", "Test charger")
    await setup(hass, with_dashboard)
    config = await _config(hass)
    assert [view["path"] for view in config["views"]] == ["overview", "shadow"]


async def test_no_dashboard_without_the_option(
    hass: HomeAssistant, sources, lovelace, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    assert PATH not in _panels(hass)


async def test_unload_removes_the_panel(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    assert await hass.config_entries.async_unload(with_dashboard.entry_id)
    await hass.async_block_till_done()
    assert PATH not in _panels(hass)
    assert PATH not in hass.data[LOVELACE_DATA].dashboards


async def test_edits_survive_a_reload(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    mine = {"views": [{"title": "Mine", "path": "mine"}]}
    await hass.data[LOVELACE_DATA].dashboards[PATH].async_save(mine)
    assert await hass.config_entries.async_reload(with_dashboard.entry_id)
    await hass.async_block_till_done()
    assert await _config(hass) == mine


async def _options(hass: HomeAssistant, entry: MockConfigEntry, dashboard: dict):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    steps = (OUTPUTS_STEP, PHASES_STEP, INPUTS_STEP, LIMITS_STEP, HOUSEHOLD_STEP)
    for data in (*steps, {}, {}, TUNING_STEP):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], data
        )
    assert result["step_id"] == "dashboard"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], dashboard
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


async def test_rebuild_discards_the_edits(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    await hass.data[LOVELACE_DATA].dashboards[PATH].async_save({"views": []})
    await _options(hass, with_dashboard, {"dashboard": True, "dashboard_rebuild": True})
    config = await _config(hass)
    assert [view["path"] for view in config["views"]] == ["overview"]
    # An action, not a setting.
    assert "dashboard_rebuild" not in with_dashboard.options


async def test_option_adds_the_dashboard_later(
    hass: HomeAssistant, sources, lovelace, entry: MockConfigEntry
) -> None:
    await setup(hass, entry)
    await _options(hass, entry, {"dashboard": True})
    assert PATH in _panels(hass)
    await _options(hass, entry, {"dashboard": False})
    assert PATH not in _panels(hass)


async def test_named_ev_charge_control(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    assert _panels(hass)[PATH].sidebar_title == "EV Charge Control"
    assert (await _config(hass))["title"] == "EV Charge Control"


async def test_a_second_controller_adds_its_name(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    await setup(hass, with_dashboard)
    garage = MockConfigEntry(
        domain="ev_charge_control",
        title="Garage",
        options=with_dashboard.options
        | {
            "current_limit_entity": "number.test_garage_limit",
            "phase_select_entity": "select.test_garage_phases",
        },
    )
    garage.add_to_hass(hass)
    await setup(hass, garage)
    assert _panels(hass)["ev-charge-control-garage"].sidebar_title == (
        "EV Charge Control Garage"
    )
    assert PATH in _panels(hass)


async def test_a_dashboard_failure_does_not_stop_the_controller(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    with patch(
        "custom_components.ev_charge_control.dashboard.async_setup",
        side_effect=RuntimeError("lovelace changed"),
    ):
        await setup(hass, with_dashboard)
    assert with_dashboard.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.test_charger_decision") is not None


async def test_the_user_names_the_dashboard(
    hass: HomeAssistant, sources, lovelace
) -> None:
    entry = make_entry(hass, dashboard=True, dashboard_title="Garage charger")
    await setup(hass, entry)
    assert _panels(hass)["garage-charger"].sidebar_title == "Garage charger"
    assert PATH not in _panels(hass)


async def test_built_at_startup_is_built_again_once_started(
    hass: HomeAssistant, sources, lovelace, with_dashboard: MockConfigEntry
) -> None:
    """The YAML package's template sensors can load after the integration."""
    hass.set_state(CoreState.not_running)
    await setup(hass, with_dashboard)
    assert [view["path"] for view in (await _config(hass))["views"]] == ["overview"]
    hass.states.async_set("sensor.ev_load_balancer_charger", "Test charger")
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    config = await _config(hass)
    assert [view["path"] for view in config["views"]] == ["overview", "shadow"]
