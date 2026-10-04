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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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
    CONF_PRICE_ATTRIBUTE,
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
        await board.async_save(build(hass, entry))

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
    connection = o[CONF_CONNECTION]
    text = (
        f"{{% set d = state_translated('{e['decision']}') %}}"
        f"{{% set mode = state_translated('{e['charge_mode']}') %}}"
        f"{{% set p = states('{e['target_power']}') | float(0) %}}"
        f"{{% set a = states('{e['target_current']}') %}}"
        f"{{% set ph = states('{e['target_phases']}') %}}"
        f"{{% set c = states('{connection}') %}}"
        f"{{% set label = {_MODE3_LABELS} %}}"
        "### {{ d }} · {{ mode }}\n"
        "# {{ (p / 1000) | round(1) }} kW\n"
        "{% set has_setpoint = a | is_number and ph | is_number and (a | float) > 0 %}"
        f"{{% if has_setpoint and states('{e['decision']}') == 'not_connected' %}}"
        "Next session starts at **{{ ph }} × {{ a | float | round(1) }} A**"
        "{% elif has_setpoint %}"
        "**{{ ph }} × {{ a | float | round(1) }} A** target setpoint"
        "{% else %}Not charging{% endif %}\n\n"
        f"{{{{ label.get(c, state_translated('{connection}')) }}}}"
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


def _overview(e: Mapping[str, str], o: Mapping[str, Any]) -> dict:
    ems = o.get(CONF_EMS)
    price = o.get(CONF_PRICE)
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
        "badges": [
            {
                "type": "entity",
                "entity": e["control_charger"],
                "name": "Control charger",
                "show_name": True,
                "show_state": True,
                # No fixed colour: the badge follows the state, grey when off.
                "tap_action": {"action": "more-info"},
            }
        ],
        "sections": [
            _section(
                _heading("Live", "mdi:lightning-bolt"),
                _markdown(_live(e, o)),
                _tile(e["grid_share"], "Car from grid", color="blue"),
                _tile(e["car_from_solar"], "Car from solar", color="amber"),
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
                _tile(e["available_from_grid"], "Available from grid", color="blue"),
                _tile(e["available_from_solar"], "Available from solar", color="amber"),
                _tile(e["effective_power_limit"], "Effective limit", 4),
                _tile(e["solar_surplus"], "Solar surplus", 4),
                _tile(o[CONF_HOUSE_POWER], "House without charger", 4),
            ),
            _section(
                _heading("Gates and inputs", "mdi:gate"),
                _tile(e["grid_allowed"], "Grid allowed"),
                _tile(e["ems_active"], "EMS active") if ems else None,
                _tile(
                    price,
                    "Import price",
                    **(
                        {"state_content": o[CONF_PRICE_ATTRIBUTE]}
                        if o.get(CONF_PRICE_ATTRIBUTE)
                        else {}
                    ),
                )
                if price
                else None,
                _tile(e["charger_efficiency"], "Charger efficiency"),
                _tile(o[CONF_POWER_LIMIT], "Power limit"),
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
                    "PV prioritized (charge on solar when EMS blocks)",
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
            ),
            _section(
                _heading("Charged today", "mdi:battery-charging-high"),
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
                _tile(o[CONF_POWER_LIMIT], "Power limit", 4),
                _tile(o[CONF_EMS], "EMS signal", 4) if o.get(CONF_EMS) else None,
                span=2,
            ),
        ],
    }
