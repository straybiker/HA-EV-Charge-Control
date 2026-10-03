# Home Assistant integration

This file describes how `custom_components/ev_charge_control/` connects the [engine](engine.md) to Home Assistant. The charging rules are in [behaviour.md](behaviour.md).

## Design

- One config entry is one virtual device: the **EV charger controller**.
- The integration owns no charger and no car. It reads entities that already exist and writes to the charger only through the charger's own integration: its current-limit number and phase select.
- The engine is pure Python. All Home Assistant code stays outside `engine/`.

```
entities of other integrations ─▶ InputReader ─▶ Controller.step() ─▶ ChargerWriter
                                       ▲                │
              setting entities ─▶ SettingsStore         ▼
                                                    Snapshot ─▶ decision and energy entities
```

## Modules

| Module | Job |
|---|---|
| `__init__.py` | Sets up an entry: builds the controller, loads the energy totals, loads the platforms, starts the coordinator after Home Assistant has started. Saves the totals on unload and deletes them when the entry is removed. |
| `config_flow.py` | The 7-step setup and the options flow (`SchemaConfigFlowHandler`). All values go into `entry.options`; an options change reloads the entry. |
| `inputs.py` | Turns options into `ChargerSpec`, `CarSpec` and `Tuning`. `InputReader` reads the source entities into `Measurements` and `Extras` and converts units (kW → W, Wh → kWh). |
| `settings.py` | `SettingsStore`: the values of the setting entities, with listeners. Gives the engine a `Settings` snapshot. |
| `coordinator.py` | `EvChargeCoordinator`: runs the controller, applies the effective power limit and the tuning values, counts energy and publishes a `Snapshot`. |
| `writer.py` | `ChargerWriter`: runs the write sequence while Control charger is on, waits for the charger to confirm, retries, raises and clears the repair issue, and hands the charger over when control is switched off. |
| `entity.py` | Shared device info and unique IDs. |
| `select.py`, `number.py`, `switch.py` | Setting entities. They restore their last value and write it into the `SettingsStore`. |
| `sensor.py`, `binary_sensor.py` | Decision, energy and diagnostic entities. Each reads one value from the `Snapshot`. |
| `diagnostics.py` | Options (name redacted), settings, tuning, the latest inputs and snapshot, the energy state, the last setpoint and the writer state. |

## Runtime

- **Triggers.** The coordinator has no `update_interval`. Its own timer runs it at the recalculation interval, so a run does not depend on listening entities. A setting change, the connection entity and the phase entity also start a run. Power sensors are read at each run but never start one: they can change every second.
- **Debounce.** Triggers within 1 s are merged into one run.
- **Start.** The first run happens when Home Assistant has started, so source entities have loaded. Setting entities restore their values while the platforms load, so the first run uses the user's settings.
- **Charger maximum.** Read at each run from the max current entity. See [behaviour.md](behaviour.md#charger-maximum).
- **Writing.** The coordinator gives every output to the writer. A write sequence runs as a background task of the entry, so a slow charger never delays a run; it waits for state changes with a timeout instead of polling. While it runs, later runs write nothing. The rules are in [behaviour.md](behaviour.md#charger-control).
- **Repair issue.** `charger_not_responding_<entry_id>`, not fixable. Deleted on the first confirmed write, when Control charger is switched off, at setup (it describes the charger before the restart) and when the entry is removed.
- **Energy.** `EnergyCounter` totals are saved with `homeassistant.helpers.storage.Store`, at most every 60 s and on unload.
- **Old entries.** An entry made before an option existed uses that option's default. An entry with a fixed maximum current keeps it.

## Entities

- All entities belong to the controller device (`DeviceEntryType.SERVICE`) and use translation keys.
- Settings are `RestoreEntity` / `RestoreNumber` entities. A default applies only when the device is first created (decision D09).
- Selecting 3-Phases Minimum while Single phase only is on, or the reverse, raises `ServiceValidationError`.
- **Follow monthly peak** exists only when a monthly peak sensor is set.
- **Control charger** is off on a new device. The decision `charger_not_responding` comes from the writer; the engine never returns it.
- The energy sensors are `energy` / `total_increasing` in kWh, so the Energy dashboard accepts them.

## Manifest

| Key | Value | Reason |
|---|---|---|
| `integration_type` | `helper` | It provides calculated entities on top of other integrations, like `derivative` or `generic_thermostat`. It is not a device or a hub: the charger already has its own integration. |
| `iot_class` | `calculated` | It has no connection of its own to any device. |
| `config_flow` | `true` | Setup and options only through the UI. `CONFIG_SCHEMA` is `config_entry_only_config_schema`. |
| `requirements` | none | |

## Validation

- **hassfest** checks the manifest, translations, icons and config flow. It runs in CI (`validate.yml`) and locally in Docker (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- **HACS action** checks the repository: description, topics, issues, `hacs.json` and the brand icon.
- Translations: custom integrations ship the full text in `strings.json` and `translations/*.json`; `[%key:…%]` references only work in core. Selector option keys must match `[a-z0-9-_]+`.
- Home Assistant 2026.3 is the first release on Python 3.14 and the minimum version (`hacs.json`). The tests run against the version that `pytest-homeassistant-custom-component` pins in `requirements-dev.txt`.
- Brand images ship in `brand/`: `icon.png` (256 × 256) and `icon@2x.png` (512 × 512), trimmed, transparent background. `tests/test_manifest.py` checks the sizes.
- HACS offers GitHub releases as versions. The Release workflow checks that the tag equals the manifest version.
