# EV Charge Control

[![Tests](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml)
[![Validate](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)

A Home Assistant integration for EV smart charging.

> **Status: planning.** The repository is set up. The integration has no behaviour yet. Do not install it.

## Planned scope

- Charge modes that follow solar surplus, price and car state.
- Peak limits for the Belgian capacity tariff (capaciteitstarief).
- Energy management system (EMS) signals.
- Dynamic electricity prices.
- EV reimbursement tracking.

## Relationship to EV Load Balancer

This project is the Python integration successor of [EV Load Balancer](https://github.com/straybiker/HA-load-balancer). That project is a YAML package for the same purpose.

The YAML package stays the behaviour reference until this integration reaches parity.

## Installation

Not yet available. When the first release exists, add this repository to HACS as a custom repository of type *Integration*.

## Development

Requires Python 3.14 and Home Assistant 2026.3 or later.

```powershell
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

More information:

- [Integration requirements](docs/integration-requirements.md)
- [Reference sources](docs/sources.md)

## License

[MIT](LICENSE)
