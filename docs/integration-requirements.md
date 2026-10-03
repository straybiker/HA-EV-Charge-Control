# Integration requirements

Checklist for Home Assistant and HACS. Sources: developers.home-assistant.io and hacs.xyz. Checked on 03/10/2026.

## Home Assistant

| Requirement | Status |
|---|---|
| Directory `custom_components/<domain>/`, domain equals directory name | Done |
| `__init__.py` with `async_setup` or `async_setup_entry` | Done (`async_setup_entry`, `async_unload_entry`) |
| `manifest.json` with `domain`, `name`, `codeowners`, `dependencies`, `documentation`, `integration_type`, `iot_class`, `requirements`, `version` | Done |
| `version` is SemVer or CalVer | Done (`0.1.0`) |
| `CONFIG_SCHEMA` declared (hassfest warns without it) | Done (`config_entry_only_config_schema`) |
| `brand/icon.png` in the integration directory (Home Assistant 2026.3 and later) | Placeholder |
| `config_flow: true` and `config_flow.py` | Done (`SchemaConfigFlowHandler`, options flow reloads the entry) |
| `strings.json` and `translations/*.json` | Done (`en`, `nl`). Custom integrations ship fully written text: `[%key:…%]` references are resolved only for core. Selector option keys must match `[a-z0-9-_]+`. |
| `services.yaml` for each registered action | Not needed: no actions |
| `diagnostics.py` | Done |
| `icons.json` | Done |
| hassfest passes locally | Done: `docker run --rm -v "<repo>:/github/workspace" ghcr.io/home-assistant/hassfest` |

Allowed `integration_type`: `device`, `entity`, `hardware`, `helper`, `hub`, `service`, `system`, `virtual`.

Allowed `iot_class`: `assumed_state`, `cloud_polling`, `cloud_push`, `local_polling`, `local_push`, `calculated`.

Current choice: `helper` and `calculated`.

`integration_type`:
- One config entry creates one virtual device: the EV charger controller. It owns no car and no charger. It works on entities that already exist in Home Assistant.
- `helper` is for an integration that provides an entity to help with automations, like `derivative`, `group` or `generic_thermostat`. That matches.
- `device` is for a single real device, like ESPHome. The real charger already has its own integration, so `device` does not fit.
- `hub` is for a gateway to multiple devices or services. `virtual` only points to another integration. Neither fits.

`iot_class`:
- `local_push` and `local_polling` mean direct communication with the device. The controller has none. It sends commands through the charger's own integration.
- `calculated` means the integration does no communication of its own and provides a calculated result. That matches.
- Core's `generic_thermostat` uses `local_polling`. The value has no runtime effect. hassfest only checks that it is valid.
- Change to `local_push` or `local_polling` only if the controller must talk to the charger directly.

## HACS

| Requirement | Status |
|---|---|
| Public GitHub repository | Done |
| Repository description | Done |
| Repository topics | Done |
| Issues enabled | Done |
| README with install and usage | Done |
| One integration in `custom_components/<domain>/` | Done |
| Manifest has `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version` | Done |
| `hacs.json` in root with `name` | Done |
| `hacs.json` `homeassistant` minimum version | `2026.3.0` |
| HACS validation workflow (`hacs/action`, category `integration`) | Done |
| hassfest workflow | Done |
| GitHub release per version | Not yet. Create the first release when the integration has behaviour. |

Without a release, HACS uses the latest commit hash as the version.

## Python and Home Assistant versions

Home Assistant 2026.3 is the first release on Python 3.14. This repository requires Python 3.14 and Home Assistant 2026.3 or later.

Tests run against the Home Assistant version that `pytest-homeassistant-custom-component` pins in `requirements-dev.txt` (now 2026.9.4). Bump that pin for each Home Assistant release. The 2026.3 lower bound is not tested.

The test harness does not run on native Windows (it imports `fcntl`). On Windows, run the engine tests natively and the full suite with `scripts/test-ha.ps1` (Docker).
