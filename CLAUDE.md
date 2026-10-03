# CLAUDE.md

This file guides Claude Code in this repository.

## Project

HACS custom integration `ev_charge_control`. It converts the YAML-based EV load balancer into a Python Home Assistant integration. Scope: EMS signals, capacity-tariff peak limits, pricing, reimbursement.

The repository is public on GitHub (`straybiker/HA-EV-Charge-Control`).

## Design constraints

- One config entry is one virtual device: the EV charger controller.
- The integration owns no car and no charger. It uses sensors and devices that already exist in Home Assistant.
- It talks to the real charger only through the charger's own integration (entities and actions). It never opens its own connection to the charger.

## Status

The decision engine (`custom_components/ev_charge_control/engine/`, `docs/engine.md`) and the Home Assistant wiring (config flow, device, settings and decision entities) exist. The integration runs in shadow mode: it computes the setpoint but `ShadowWriter` writes nothing to the charger.

## Engine rules

- `engine/` imports nothing from `homeassistant`. It takes values, never entity IDs.
- `docs/behaviour.md` is the specification. Change it, the engine and its tests together.
- Charging behaviour is decided by the user. Implement code and doc changes freely, but ask before changing what the controller does with current, phases, grid, solar, EMS, SOC or timers, and record each decision in the decision record of `docs/behaviour.md`.
- Do not copy the YAML package's structure. It is a reference for intent, not for design.

## Reference projects

Sibling folders are read-only reference. Paths are in `docs/sources.md`.

- `../EV_Loadbalancer/` ([straybiker/HA-load-balancer](https://github.com/straybiker/HA-load-balancer)) is the YAML package this integration replaces. Use it to understand intent; where it differs from `docs/behaviour.md`, the decision record explains why.
- `../HomeAssistant/packages/ems.yaml` holds the peak-limit and reimbursement logic.
- `../IdegisModbus/` and `../alfen_modbus/` show the integration and CI patterns used by this author.

## Rules

- Home Assistant code is async. No blocking I/O in the event loop.
- Use `DataUpdateCoordinator` for polled or computed data.
- Keep hassfest and the HACS action green. See `docs/integration-requirements.md`.
- Python 3.14. Home Assistant 2026.3 or later.
- Comments explain why. Do not write changelog comments. Git is the changelog.
- Never commit secrets, tokens, `.env` files, real entity IDs of private devices or patient-like personal data. The repository is public.
- ENTSO-e prices are quarter-hourly: 96 slots per day, not 24.
- Before every commit, review the documentation (`README.md`, `docs/*.md`, `CLAUDE.md`) against the change and update what is out of date. A commit never leaves the docs describing old behaviour.

## Commands

```powershell
pytest -q                 # Windows: engine + translation tests; tests/ha is skipped
.\scripts\test-ha.ps1     # full suite in Docker (the HA test harness needs Linux)
ruff check .
ruff format --check .
```

- Test report: after a change to behaviour or tests, rebuild `docs/test-report.html` with `python scripts/report/collect.py` then `python scripts/report/build.py`, and commit it with the change. Use the Windows venv's python; collect.py needs Docker.
- Translations: `strings.json` and `translations/en.json` must stay identical; `translations/nl.json` must have the same keys. `tests/test_translations.py` checks both.
- Run hassfest locally before pushing manifest, strings or icons changes: `docker run --rm -v "<repo>:/github/workspace" ghcr.io/home-assistant/hassfest`.
- The shell is PowerShell on Windows 11. Test Windows-facing tooling in `pwsh`, not in Git Bash.
