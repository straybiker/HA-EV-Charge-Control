"""The controller's dashboard in the sidebar.

Home Assistant has no public API for an integration to create a dashboard.
The integration registers its own Lovelace panel, as Lovelace does for each
storage dashboard, with the configuration in a store of its own. The panel
shows in Settings > Dashboards, but it is not an item of Lovelace's
dashboard collection: its name and icon come from the integration. The user
can edit it in the UI. The Dashboard option removes it; Rebuild dashboard
discards the edits and generates it again.

Only built-in cards: a fresh install has no custom cards.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as lovelace
from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import (
    CONF_ACTIVE_PHASES,
    CONF_APPLIED_CURRENT,
    CONF_CAR_SOC,
    CONF_CHARGER_POWER,
    CONF_CONNECTION,
    CONF_CURRENT_LIMIT,
    CONF_DASHBOARD,
    CONF_DASHBOARD_TITLE,
    CONF_EMS,
    CONF_HOUSE_POWER,
    CONF_PHASE_OPTION_1,
    CONF_PHASE_OPTION_3,
    CONF_PHASE_SELECT,
    CONF_POWER_LIMIT,
    CONF_PRICE,
    CONF_SOLAR_POWER,
    DOMAIN,
    LOGGER,
)
from .yaml_import import package_present

# Lovelace's own store layout, so its websocket API loads and saves the config.
_LOVELACE_STORE_KEY = "lovelace.{}"
_LOVELACE_STORE_VERSION = 1
_ICON = "mdi:ev-station"
NAME = "EV Charge Control"
# Entities of the EV Load Balancer YAML package, for the shadow comparison.
_YAML_MODE = "input_select.ev_load_balancer_charge_mode"

GRID_BLUE = "#4c8dff"
SOLAR_AMBER = "#f5a524"
HOUSE_PINK = "#e58bbd"
LIMIT_GREY = "#c9d3e0"
# History graphs take a color per entity from 2026.6; older versions get
# their default colors, so the dashboard works on every supported version.
_GRAPH_COLORS = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 6)

# Mode 3 (IEC 61851) states, for chargers that report them.
_MODE3_LABELS = (
    "{'A': 'No car', 'B1': 'Car connected', 'B2': 'Car connected, ready', "
    "'C1': 'Car wants to charge, charger paused', "
    "'D1': 'Car wants to charge, charger paused', 'C2': 'Car charging', "
    "'D2': 'Car charging', 'E': 'Charger off', 'F': 'Charger error'}"
)
_MODE_HELP = (
    "{'off': 'No charging.', "
    "'min_1p': 'Exactly the minimum current on 1 phase, from grid or solar.', "
    "'min_3p': 'Exactly the minimum current on 3 phases.', "
    "'limited': 'Grid up to the power limit, with solar added.', "
    "'fast': 'As much as the charger accepts, within the power limit; "
    "also when the price is above the maximum.', "
    "'solar': 'Solar surplus first; the bridge closes a small gap to the minimum.', "
    "'comfort': 'Limited until the comfort SOC, then Solar.'}"
)
_CONTROL_CONFIRM = (
    "This makes the controller write to the charger. "
    "Turn off any other automation that sets the charger first."
)


def _store_id(entry: ConfigEntry) -> str:
    return f"{DOMAIN}_{entry.entry_id}"


def _store(hass: HomeAssistant, entry: ConfigEntry) -> Store[dict[str, Any]]:
    return Store(
        hass, _LOVELACE_STORE_VERSION, _LOVELACE_STORE_KEY.format(_store_id(entry))
    )


async def async_remove(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the saved dashboard; the next setup with the option builds it anew."""
    await _store(hass, entry).async_remove()


def title(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """The name from the setup. With the default name, the first controller is
    EV Charge Control and the others add their device name."""
    custom = (entry.options.get(CONF_DASHBOARD_TITLE) or "").strip()
    if custom and custom != NAME:
        return custom
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries or entries[0].entry_id == entry.entry_id:
        return NAME
    return f"{NAME} {entry.title}"


def url_path(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """A path from the title; it has the hyphen that Lovelace requires.

    The entry ID is added when another panel already uses the path.
    """
    base = slugify(title(hass, entry), separator="-")
    if frontend.async_panel_exists(hass, base):
        return f"{base}-{entry.entry_id[-6:].lower()}"
    return base


async def async_setup(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Show the dashboard when the option is on; otherwise delete it."""
    if not entry.options.get(CONF_DASHBOARD):
        await async_remove(hass, entry)
        return
    if LOVELACE_DATA not in hass.data:
        LOGGER.warning("Dashboards are not loaded; no dashboard is added")
        return

    path = url_path(hass, entry)
    name = title(hass, entry)
    board = lovelace.LovelaceStorage(
        hass,
        {
            "id": _store_id(entry),
            "url_path": path,
            "title": name,
            "icon": _ICON,
            "mode": "storage",
            "show_in_sidebar": True,
            "require_admin": False,
        },
    )
    try:
        await board.async_load(False)
    except ConfigNotFound:
        first = build(hass, entry)
        await board.async_save(first)
        if hass.state is not CoreState.running:
            # During startup the YAML package's template sensors may not
            # exist yet, which would leave out the shadow view.
            async def _build_again(_hass: HomeAssistant) -> None:
                if await board.async_load(False) == first:
                    await board.async_save(build(hass, entry))

            entry.async_on_unload(async_at_started(hass, _build_again))

    dashboards = hass.data[LOVELACE_DATA].dashboards
    dashboards[path] = board
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        sidebar_title=name,
        sidebar_icon=_ICON,
        frontend_url_path=path,
        config={"mode": "storage"},
        update=True,
    )

    @callback
    def _hide() -> None:
        frontend.async_remove_panel(hass, path)
        dashboards.pop(path, None)

    entry.async_on_unload(_hide)


# --- the configuration ------------------------------------------------------------


def _own_entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Entity IDs of the device by entity key, as the user may have renamed them."""
    prefix = f"{entry.entry_id}_"
    return {
        reg.unique_id.removeprefix(prefix): reg.entity_id
        for reg in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


def _tile(entity: str, name: str, columns: int | str = 6, **extra: Any) -> dict:
    return {
        "type": "tile",
        "entity": entity,
        "name": name,
        "grid_options": {"columns": columns},
        **extra,
    }


def _graph_entity(series: dict) -> dict:
    return (
        series if _GRAPH_COLORS else {k: v for k, v in series.items() if k != "color"}
    )


def _heading(text: str, icon: str) -> dict:
    return {"type": "heading", "heading": text, "icon": icon}


def _section(*cards: dict | None, span: int | None = None) -> dict:
    section: dict[str, Any] = {"type": "grid", "cards": [c for c in cards if c]}
    if span:
        section["column_span"] = span
    return section


def _markdown(content: str, *, text_only: bool = False, **extra: Any) -> dict:
    card = {"type": "markdown", "content": content, "grid_options": {"columns": "full"}}
    if text_only:
        card["text_only"] = True
    return {**card, **extra}


def build(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """The dashboard for one controller, from its setup and its entities."""
    e = _own_entities(hass, entry)
    o = entry.options
    views = [_overview(e, o)]
    if package_present(hass):
        views.append(_shadow(e, o))
    return {"title": title(hass, entry), "views": views}


def _live(e: Mapping[str, str], o: Mapping[str, Any]) -> str:
    """The power and the target setpoint.

    With Control charger on, the big number is the measured charger power.
    In shadow mode nothing is written, so it is the target power, marked
    virtual so it does not read as real charging.
    """
    charger = o[CONF_CHARGER_POWER]
    text = (
        f"{{% set d = state_translated('{e['decision']}') %}}"
        f"{{% set mode = state_translated('{e['charge_mode']}') %}}"
        f"{{% set shadow = is_state('{e['control_charger']}', 'off') %}}"
        f"{{% set w = states('{charger}') | float(0) * (1000 if "
        f"state_attr('{charger}', 'unit_of_measurement') == 'kW' else 1) %}}"
        f"{{% set p = states('{e['target_power']}') | float(0) %}}"
        f"{{% set a = states('{e['target_current']}') %}}"
        f"{{% set ph = states('{e['target_phases']}') %}}"
        "### {% if shadow %}Shadow mode · {% endif %}{{ d }} · {{ mode }}\n"
        "{% if shadow %}# {{ (p / 1000) | round(1) }} kW (Virtual)\n"
        "{% else %}# {{ (w / 1000) | round(1) }} kW\n{% endif %}"
        "{% set has_setpoint = a | is_number and ph | is_number and (a | float) > 0 %}"
        f"{{% if has_setpoint and states('{e['decision']}') == 'not_connected' %}}"
        "Next session starts at **{{ ph }} × {{ a | float | round(1) }} A**"
        "{% elif has_setpoint %}"
        "Target **{{ ph }} × {{ a | float | round(1) }} A**"
        "{% if not shadow %} ({{ (p / 1000) | round(1) }} kW){% endif %}"
        "{% else %}No target setpoint{% endif %}"
    )
    if soc := o.get(CONF_CAR_SOC):
        text += (
            f"\n\n{{% set soc = states('{soc}') %}}"
            "Battery **{{ (soc | float) | round(0) | int if soc | is_number "
            "else '–' }} %**"
            f" · Emergency {{{{ states('{e['emergency_soc']}') | int(0) }}}} %"
            f" · Comfort {{{{ states('{e['comfort_soc']}') | int(0) }}}} %"
            f" · Target {{{{ states('{e['target_soc']}') | int(0) }}}} %"
        )
    return text


def _total_power(e: Mapping[str, str]) -> list[dict]:
    """Total power, red above the effective limit.

    A tile colour cannot follow a template, so two tiles with opposite
    visibility: the threshold of a numeric_state condition may be an entity.
    """
    above = {
        "condition": "numeric_state",
        "entity": e["total_power"],
        "above": e["effective_power_limit"],
    }
    return [
        _tile(e["total_power"], "Total power", 4, color="red", visibility=[above]),
        _tile(
            e["total_power"],
            "Total power",
            4,
            visibility=[{"condition": "not", "conditions": [above]}],
        ),
    ]


def _phase_tiles(e: Mapping[str, str], three: bool) -> list[dict]:
    """Efficiency per phase count, and the phase-switch timers while they run.

    A single-phase charger has neither the 3-phase efficiency nor the grace
    period after a 1 -> 3 switch.
    """

    def running(key: str, name: str) -> dict:
        return _tile(
            e[key],
            name,
            visibility=[
                {
                    "condition": "state",
                    "entity": e[key],
                    "state_not": ["unknown", "unavailable"],
                }
            ],
        )

    tiles = [_tile(e["efficiency_1p"], "Efficiency 1 phase")]
    if three:
        tiles += [
            _tile(e["efficiency_3p"], "Efficiency 3 phases"),
            running("phase_hold_until", "Phase hold until"),
            running("grace_until", "Grace period until"),
        ]
    return tiles


def _power_limit(e: Mapping[str, str], o: Mapping[str, Any]) -> str:
    """The setup's power limit entity, else the device's own number (B10)."""
    return o.get(CONF_POWER_LIMIT) or e["power_limit"]


def _settings_tiles(
    e: Mapping[str, str], o: Mapping[str, Any], three: bool, price: bool
) -> list[dict]:
    """The device settings that are not set elsewhere on the dashboard.

    Only those that do something in this setup: the battery levels need a
    battery level sensor, Single phase only a 3-phase option, and the
    maximum cost a price.
    """
    tiles: list[dict] = []
    if o.get(CONF_CAR_SOC):
        tiles += [
            _tile(e["car_aware"], "Car aware"),
            _tile(e["target_soc"], "Target SOC", 4),
            _tile(e["comfort_soc"], "Comfort SOC", 4),
            _tile(e["emergency_soc"], "Emergency SOC", 4),
        ]
    if three:
        tiles.append(_tile(e["single_phase_only"], "Single phase only"))
    if price:
        tiles.append(_tile(e["max_charging_cost"], "Max charging cost"))
    tiles.append(_tile(e["solar_bridge"], "Solar bridge"))
    return tiles


def _car_state(o: Mapping[str, Any]) -> str:
    """The connection entity in words: a tile would show the bare Mode 3 code."""
    connection = o[CONF_CONNECTION]
    return (
        f"{{% set c = states('{connection}') %}}"
        f"{{% set label = {_MODE3_LABELS} %}}"
        f"Car: **{{{{ label.get(c, state_translated('{connection}')) }}}}**"
    )


def _control_badges(e: Mapping[str, str]) -> list[dict]:
    """Control charger, coloured by what the controller does.

    A badge colour cannot follow a template, so one badge per state: red
    when off, grey without a car, amber with a car that does not charge,
    blue while charging, green at the target. The badges show the Decision
    sensor, not the switch: a badge colour applies only while its entity is
    active, and a switch that is off is not. A tap toggles Control charger.
    """
    control, decision = e["control_charger"], e["decision"]
    on = {"condition": "state", "entity": control, "state": "on"}
    active = ["charging", "emergency"]

    def badge(color: str, *visibility: dict, off: bool = False) -> dict:
        return {
            "type": "entity",
            "entity": decision,
            "icon": "mdi:ev-plug-type2",
            "name": "Control charger off" if off else "Control charger",
            "show_name": off,
            "show_state": not off,
            "color": color,
            "tap_action": {
                "action": "perform-action",
                "perform_action": "switch.toggle",
                "target": {"entity_id": control},
                "confirmation": {
                    "text": (
                        _CONTROL_CONFIRM
                        if off
                        else "Switch Control charger off? The charger gets the "
                        "fallback setpoint once, and the controller stops writing."
                    )
                },
            },
            "visibility": list(visibility),
        }

    def decided(**state: Any) -> dict:
        return {"condition": "state", "entity": decision, **state}

    return [
        badge(
            "red", {"condition": "state", "entity": control, "state": "off"}, off=True
        ),
        badge("grey", on, decided(state="not_connected")),
        badge("blue", on, decided(state=active)),
        badge("green", on, decided(state="target_reached")),
        badge(
            "amber", on, decided(state_not=[*active, "target_reached", "not_connected"])
        ),
    ]


def _overview(e: Mapping[str, str], o: Mapping[str, Any]) -> dict:
    ems = o.get(CONF_EMS)
    price = o.get(CONF_PRICE)
    three = bool(o.get(CONF_PHASE_OPTION_3))
    solar = o.get(CONF_SOLAR_POWER)
    today_grid, today_solar = (
        e["charged_from_grid_today"],
        e["charged_from_solar_today"],
    )
    charged_some = {
        "condition": "or",
        "conditions": [
            {"condition": "numeric_state", "entity": today_grid, "above": 0},
            {"condition": "numeric_state", "entity": today_solar, "above": 0},
        ],
    }
    power_series = [
        {"entity": solar, "name": "Solar production", "color": SOLAR_AMBER}
        if solar
        else None,
        {"entity": o[CONF_CHARGER_POWER], "name": "Car charging", "color": GRID_BLUE},
        {
            "entity": o[CONF_HOUSE_POWER],
            "name": "House without charger",
            "color": HOUSE_PINK,
        },
        {
            "entity": e["effective_power_limit"],
            "name": "Power limit",
            "color": LIMIT_GREY,
        },
    ]
    return {
        "title": "Overview",
        "path": "overview",
        "icon": _ICON,
        "type": "sections",
        "max_columns": 3,
        "badges": _control_badges(e),
        "sections": [
            _section(
                _heading("Live", "mdi:lightning-bolt"),
                _markdown(_live(e, o)),
                _tile(e["grid_share"], "From grid", 4, color="blue"),
                _tile(e["car_from_solar"], "From solar", 4, color="amber"),
                *_total_power(e),
            ),
            _section(
                _heading("Power budget", "mdi:scale-balance"),
                _tile(e["available_power"], "Available for the car", 12),
                {
                    "type": "distribution",
                    "entities": [
                        {
                            "entity": e["available_from_grid"],
                            "name": "From grid",
                            "color": GRID_BLUE,
                        },
                        {
                            "entity": e["available_from_solar"],
                            "name": "From solar",
                            "color": SOLAR_AMBER,
                        },
                    ],
                    "grid_options": {"columns": "full"},
                },
                _tile(e["effective_power_limit"], "Effective limit", 4),
                _tile(e["solar_surplus"], "Solar surplus", 4),
                _tile(o[CONF_HOUSE_POWER], "House without charger", 4),
            ),
            _section(
                _heading("Gates and inputs", "mdi:traffic-light"),
                _markdown(_car_state(o)),
                _tile(e["grid_allowed"], "Grid allowed"),
                _tile(e["ems_active"], "EMS active") if ems else None,
                # The integration's own sensor: it reads the attribute when
                # the setup names one, and it has a unit.
                _tile(e["import_price"], "Import price") if price else None,
                *_phase_tiles(e, three),
                _tile(_power_limit(e, o), "Power limit"),
            ),
            _section(
                _heading("Power today", "mdi:chart-areaspline"),
                {
                    "type": "history-graph",
                    "hours_to_show": 24,
                    "entities": [_graph_entity(s) for s in power_series if s],
                    "grid_options": {"columns": "full", "rows": 6},
                },
                span=3,
            ),
            _section(
                _heading("Decisions today", "mdi:timeline-text-outline"),
                {
                    "type": "history-graph",
                    "hours_to_show": 24,
                    "entities": [
                        x
                        for x in (
                            {"entity": e["decision"], "name": "Decision"},
                            {"entity": e["target_phases"], "name": "Target phases"},
                            {"entity": e["car_connected"], "name": "Car connected"},
                            {"entity": e["control_charger"], "name": "Control charger"},
                            {"entity": e["grid_allowed"], "name": "Grid allowed"},
                            {"entity": e["ems_active"], "name": "EMS active"}
                            if ems
                            else None,
                        )
                        if x
                    ],
                    "grid_options": {"columns": "full", "rows": "auto"},
                },
                span=3,
            ),
            _section(
                _heading("Configuration", "mdi:cog"),
                _tile(
                    e["control_charger"],
                    "Control charger (off: shadow mode)",
                    12,
                    tap_action={"action": "more-info"},
                    icon_tap_action={
                        "action": "toggle",
                        "confirmation": {"text": _CONTROL_CONFIRM},
                    },
                ),
                _tile(e["ems_control"], "EMS control") if ems else None,
                _tile(e["ems_as_onoff"], "EMS as on/off") if ems else None,
                _tile(
                    e["solar_when_ems_blocks"],
                    "Always charge when solar available",
                    12,
                )
                if ems
                else None,
                _tile(
                    e["charge_mode"],
                    "Charge mode",
                    12,
                    features=[{"type": "select-options"}],
                    features_position="bottom",
                ),
                _markdown(
                    f"{{% set help = {_MODE_HELP} %}}"
                    f"{{{{ help.get(states('{e['charge_mode']}'), '') }}}}",
                    text_only=True,
                ),
                *_settings_tiles(e, o, three, bool(price)),
            ),
            _section(
                _heading("Charged today", "mdi:battery-charging-high"),
                _tile(e["charged_today"], "Charged today", 12),
                _tile(today_grid, "From grid today", color="blue"),
                _tile(today_solar, "From solar today", color="amber"),
                {
                    "type": "distribution",
                    "entities": [
                        {"entity": today_grid, "name": "Grid", "color": GRID_BLUE},
                        {"entity": today_solar, "name": "Solar", "color": SOLAR_AMBER},
                    ],
                    "grid_options": {"columns": "full"},
                    "visibility": [charged_some],
                },
                _markdown(
                    "Nothing charged today yet.",
                    text_only=True,
                    visibility=[{"condition": "not", "conditions": [charged_some]}],
                ),
            ),
            _section(
                _heading("Totals since setup", "mdi:sigma"),
                _tile(e["charged_energy"], "Total charged", 12),
                _tile(e["charged_from_grid"], "Total from grid", 12),
                _tile(e["charged_from_solar"], "Total from solar", 12),
                _tile(
                    e["average_charging_power"], "Average charging power (60 days)", 12
                ),
            ),
        ],
    }


def _shadow(e: Mapping[str, str], o: Mapping[str, Any]) -> dict:
    """Shadow controller next to the YAML package that still drives the charger."""
    limit, phase = o[CONF_CURRENT_LIMIT], o[CONF_PHASE_SELECT]
    one, three = o.get(CONF_PHASE_OPTION_1), o.get(CONF_PHASE_OPTION_3)
    compare = (
        f"{{% set t = states('{e['target_current']}') | float(0) %}}"
        f"{{% set y = states('{limit}') | float(0) %}}"
        f"{{% set tp = states('{e['target_phases']}') %}}"
        f"{{% set raw = states('{phase}') %}}"
        f"{{% set yp = '1' if raw == '{one}' else ('3' if raw == '{three}' "
        "else raw) %}"
        "{% set same = (t - y) | abs < 0.35 and tp == yp %}\n"
        "| | Shadow controller | YAML package |\n|---|---|---|\n"
        "| Current | **{{ t }} A** | **{{ y }} A** |\n"
        "| Phases | {{ tp }} | {{ yp }} |\n"
        f"| Mode | {{{{ state_translated('{e['charge_mode']}') }}}} | "
        f"{{{{ states('{_YAML_MODE}') }}}} |\n\n"
        "{{ '✅ Same setpoint' if same else '⚠️ Different setpoint' }} "
        "(difference {{ (t - y) | round(1) }} A; up to 0.3 A is the write "
        "threshold and rounding)"
    )
    return {
        "title": "Shadow comparison",
        "path": "shadow",
        "icon": "mdi:compare-horizontal",
        "type": "sections",
        "max_columns": 4,
        "sections": [
            _section(
                _heading("Shadow vs YAML package", "mdi:compare-horizontal"),
                _markdown(compare),
                _tile(e["decision"], "Decision"),
                _tile(e["charge_mode"], "Shadow mode"),
                _tile(_YAML_MODE, "YAML mode"),
                span=2,
            ),
            _section(
                _heading("Shadow controller", "mdi:ev-station"),
                _tile(e["target_current"], "Target current", 4),
                _tile(e["target_phases"], "Target phases", 4),
                _tile(e["target_power"], "Target power", 4),
                _tile(e["effective_power_limit"], "Effective limit", 4),
                _tile(e["solar_surplus"], "Solar surplus", 4),
                _tile(e["grid_allowed"], "Grid allowed", 4),
                span=2,
            ),
            _section(
                _heading("Last 24 hours", "mdi:chart-line"),
                {
                    "type": "history-graph",
                    "title": "Current: shadow target vs charger",
                    "hours_to_show": 24,
                    "entities": [
                        {"entity": e["target_current"], "name": "Shadow target"},
                        {"entity": limit, "name": "Current limit (YAML)"},
                        {"entity": o[CONF_APPLIED_CURRENT], "name": "Applied"},
                    ],
                    "grid_options": {"columns": "full", "rows": 5},
                },
                {
                    # Charger power is what the YAML package makes the car
                    # draw; the house power shows the room the target had.
                    "type": "history-graph",
                    "title": "Power: shadow target vs charger",
                    "hours_to_show": 24,
                    "entities": [
                        {"entity": e["target_power"], "name": "Shadow target"},
                        {"entity": o[CONF_CHARGER_POWER], "name": "Charger (YAML)"},
                        {"entity": e["total_power"], "name": "Total power"},
                        {
                            "entity": o[CONF_HOUSE_POWER],
                            "name": "House without charger",
                        },
                        {
                            "entity": e["effective_power_limit"],
                            "name": "Effective limit",
                        },
                    ],
                    "grid_options": {"columns": "full", "rows": 5},
                },
                {
                    "type": "history-graph",
                    "title": "Decisions and phases",
                    "hours_to_show": 24,
                    "entities": [
                        {"entity": e["decision"], "name": "Shadow decision"},
                        {"entity": e["target_phases"], "name": "Shadow phases"},
                        {"entity": phase, "name": "Phases (YAML)"},
                    ],
                    "grid_options": {"columns": "full", "rows": 4},
                },
                span=2,
            ),
            _section(
                _heading("Charger and inputs", "mdi:import"),
                _tile(o[CONF_APPLIED_CURRENT], "Applied current", 4),
                _tile(o[CONF_ACTIVE_PHASES], "Active phases", 4),
                _tile(o[CONF_CHARGER_POWER], "Charger power", 4),
                _tile(o[CONF_CONNECTION], "Connection", 4),
                _tile(_power_limit(e, o), "Power limit", 4),
                _tile(o[CONF_EMS], "EMS signal", 4) if o.get(CONF_EMS) else None,
                span=2,
            ),
        ],
    }
