# CLAUDE.md

This file guides Claude Code in this repository.

## Project

HACS custom integration `ev_charge_control`. It converts the YAML-based EV load balancer into a Python Home Assistant integration. Scope: EMS signals, capacity-tariff peak limits, pricing, reimbursement.

The repository is public on GitHub (`straybiker/HA-EV-Charge-Control`).

## Status

Repository setup only. Write no behaviour until a design plan exists.

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

## Commands

```powershell
pytest -q
ruff check .
ruff format --check .
```

The shell is PowerShell on Windows 11. Test Windows-facing tooling in `pwsh`, not in Git Bash.
