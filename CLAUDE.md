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

The decision engine exists in `custom_components/ev_charge_control/engine/` and is documented in `docs/engine.md`. Nothing is wired to Home Assistant yet.

## Engine rules

- `engine/` imports nothing from `homeassistant`. It takes values, never entity IDs.
- The engine reproduces the YAML package as it runs. `docs/known-defects.md` lists the deviations from the README that are kept on purpose. Do not fix one without approval; when you do, remove its `xfail` in `tests/engine/test_known_defects.py` and update the doc.
- `tests/engine/test_yaml_oracle.py` is the parity gate. It needs `../EV_Loadbalancer` checked out and is skipped in CI. Run it locally after every engine change. A deviation from the YAML is allowed only through a narrow entry in `_fixed_deviation()` that names a `fixed` defect.

## Reference projects

Sibling folders are read-only reference. Paths are in `docs/sources.md`.

- `../EV_Loadbalancer/` ([straybiker/HA-load-balancer](https://github.com/straybiker/HA-load-balancer)) is the source of truth for behaviour. Use its README, logic and tests during the conversion.
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
pytest -q
ruff check .
ruff format --check .
```

The shell is PowerShell on Windows 11. Test Windows-facing tooling in `pwsh`, not in Git Bash.
