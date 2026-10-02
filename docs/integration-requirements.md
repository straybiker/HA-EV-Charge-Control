# Integration requirements

Checklist for Home Assistant and HACS. Sources: developers.home-assistant.io and hacs.xyz. Checked on 03/10/2026.

## Home Assistant

| Requirement | Status |
|---|---|
| Directory `custom_components/<domain>/`, domain equals directory name | Done |
| `__init__.py` with `async_setup` or `async_setup_entry` | Done (`async_setup` only) |
| `manifest.json` with `domain`, `name`, `codeowners`, `dependencies`, `documentation`, `integration_type`, `iot_class`, `requirements`, `version` | Done |
| `version` is SemVer or CalVer | Done (`0.0.1`) |
| `CONFIG_SCHEMA` declared (hassfest warns without it) | Done |
| `brand/icon.png` in the integration directory (Home Assistant 2026.3 and later) | Placeholder |
| `config_flow: true` and `config_flow.py` | Not yet |
| `translations/en.json` for config flow text | Not yet |
| `services.yaml` for each registered action | Not yet |
| `diagnostics.py` | Not yet |
| `icons.json` | Not yet |

Allowed `integration_type`: `device`, `entity`, `hardware`, `helper`, `hub`, `service`, `system`, `virtual`.

Allowed `iot_class`: `assumed_state`, `cloud_polling`, `cloud_push`, `local_polling`, `local_push`, `calculated`.

Current choice: `service` and `calculated`. Review both when the design is ready.

## HACS

| Requirement | Status |
|---|---|
| Public GitHub repository | Done |
| Repository description | Done |
| Repository topics | Done |
| Issues enabled | Done |
| README with install and usage | Draft |
| One integration in `custom_components/<domain>/` | Done |
| Manifest has `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version` | Done |
| `hacs.json` in root with `name` | Done |
| `hacs.json` `homeassistant` minimum version | `2026.3.0` |
| HACS validation workflow (`hacs/action`, category `integration`) | Done |
| hassfest workflow | Done |
| GitHub release per version | Not yet. Create the first release when the integration has behaviour. |

Without a release, HACS uses the latest commit hash as the version.

## Python and Home Assistant versions

Home Assistant 2026.3 is the first release on Python 3.14. This repository requires Python 3.14 and Home Assistant 2026.3 or later. CI tests the latest Home Assistant release only. The lower bound is not tested.
