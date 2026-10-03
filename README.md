# EV Charge Control

[![Tests](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml)
[![Validate](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)

A Home Assistant integration for EV smart charging. It decides the charge current and phase count from your house power, solar surplus, power limit, electricity price, EMS signal and the car's battery level.

> **Status: shadow mode.** The integration calculates what it would set and shows it on its sensors, but it does not write to the charger yet. Run it next to your current charging automation and compare.

## How it works

One setup creates one device, the **EV charger controller**. It does not talk to the charger itself: it reads the entities of your charger's own integration and, once writing is enabled, sets the charger's current-limit and phase entities.

| Mode | What it does |
|---|---|
| Off | No charging. |
| 1-Phase Minimum / 3-Phases Minimum | Exactly the minimum current, from grid or solar. |
| Limited | Grid up to the power limit, solar on top. |
| Fast | As much as the charger takes, within the power limit. |
| Solar | Solar surplus first. A small grid bridge lifts a near-miss surplus to the minimum. |
| Comfort | Limited until the car reaches the comfort SOC, then Solar. |

The full rules, with the reason for each, are in [Charging behaviour](docs/behaviour.md).

## Installation

1. Copy `custom_components/ev_charge_control` into your Home Assistant `config/custom_components/` folder, or add this repository to HACS as a custom repository of type *Integration*.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Helpers → Create helper → EV Charge Control**.

Requires Home Assistant 2026.3 or later.

## Setup

The setup asks in six steps for:

1. **Charger**: its power, applied current limit, active phases and connection state (a Mode 3 sensor or a binary sensor), its current range, voltage and current step.
2. **Charger controls**: its current-limit number and phase select.
3. **Phase options**: which option of the phase select means 1 phase and which 3 phases.
4. **Household**: house power **without** the charger (negative while exporting).
5. **Car** (optional): battery level and capacity, car current range.
6. **Price and EMS** (optional): price sensor or attribute, EMS signal in watts.

**Configure** on the integration page reopens the same steps.

## The device

| Kind | Entities |
|---|---|
| Settings | Charge mode; power limit; max charging cost; target, comfort and emergency SOC; solar bridge; car aware; charge on solar when EMS blocks; single phase only; EMS control; EMS as on/off |
| Configuration | Power update threshold; phase switch delay; recalculation interval |
| Decision | Target current; target phases; target power; decision; grid allowed; emergency charging; target reached |
| Diagnostic | Charger efficiency; solar surplus; grid share; phase hold until |

Settings keep their value across restarts. The controller runs every 10 s (configurable) and at once when the mode, a setting, the connection or the phase changes. Power sensor updates do not trigger a run.

## Relationship to EV Load Balancer

This project is the Python integration successor of [EV Load Balancer](https://github.com/straybiker/HA-load-balancer), a YAML package for the same purpose.

The integration keeps the package's intent but not its design. Where its behaviour differs, [the decision record](docs/behaviour.md#decision-record) explains why.

## Development

Python 3.14.

**Linux or CI:** the full suite.

```bash
pip install -r requirements-dev.txt
pytest -q
```

**Windows:** the Home Assistant test harness needs Linux. Run the engine and translation tests natively, and the full suite in Docker.

```powershell
pip install -r requirements-dev-windows.txt
pytest -q
.\scripts\test-ha.ps1
```

Lint with `ruff check .` and `ruff format --check .`.

**Test report:** [docs/test-report.html](docs/test-report.html) shows the full test run, hassfest, the golden cases at a 6 kW and 10 kW power limit next to what the EV Load Balancer YAML package does, and the decision record. Download the file and open it in a browser. Rebuild it (Docker needed; the YAML column needs `../EV_Loadbalancer` checked out):

```powershell
python scripts/report/collect.py
python scripts/report/build.py
```

More information:

- [Charging behaviour](docs/behaviour.md)
- [Engine design](docs/engine.md)
- [Integration requirements](docs/integration-requirements.md)
- [Reference sources](docs/sources.md)

## License

[MIT](LICENSE)
