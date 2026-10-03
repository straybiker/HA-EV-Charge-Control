# EV Charge Control

[![Tests](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml)
[![Validate](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)

A Home Assistant integration for smart EV charging. It sets the charge current and the number of phases from your house power, solar surplus, power limit, electricity price, EMS signal and the car's battery level. It also counts the energy that goes into the car.

> [!IMPORTANT]
> **Shadow mode.** This version calculates what it would set and shows it on its sensors. It does **not** write to the charger yet. Run it next to your current charging automation and compare the results.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [User manual](#user-manual)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Seven charge modes:** Off, 1-Phase Minimum, 3-Phases Minimum, Limited, Fast, Solar and Comfort.
- **Capacity tariff:** one power limit for the whole house. It can follow your monthly peak.
- **Solar first:** charges on surplus. A small grid bridge closes the gap when the surplus is just below the minimum.
- **EMS and price:** an EMS signal (watt budget or on/off) and a maximum electricity price control the grid share.
- **Car aware:** emergency, target and comfort battery levels.
- **1 and 3 phases:** switches phases, with a hold time that prevents flapping.
- **Energy:** charged energy, split into grid and solar, for the Energy dashboard or an EMS.
- **Safe by design:** a sensor fault never increases the current. Settings survive restarts.
- **Any charger** whose Home Assistant integration has a current-limit number and a phase select.

## Requirements

- Home Assistant 2026.3 or later.
- Your charger's own integration, with these entities:

  | Entity | Example |
  |---|---|
  | Charger power (W) | The charger's active power. |
  | Applied current limit (A) | The limit that the charger applies now. |
  | Active phases | A sensor that shows 1 or 3. |
  | Connection state | A Mode 3 sensor (A, B1 … D2, E, F), or a binary sensor that is on while a car is connected. |
  | Maximum current (A) | The charger's configured or installation maximum. |
  | Current limit | A `number` entity that the charger accepts. |
  | Phase setting | A `select` entity with a 1-phase and a 3-phase option. |

- **House power without the charger** (W, negative during export). If you only have a grid meter, make a template sensor: grid power − charger power. A sensor smoothed over approximately 15 s gives the best results.
- Optional: the car's battery level, an electricity price, an EMS signal, a monthly peak sensor, the charger's energy meter.

## Installation

**HACS**

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/straybiker/HA-EV-Charge-Control` with the type **Integration**.
3. Install **EV Charge Control** and restart Home Assistant.

**Manual**

1. Copy `custom_components/ev_charge_control` into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

Then go to **Settings → Devices & services → Helpers → Create helper → EV Charge Control**.

## Configuration

The setup has seven steps. To change them later, select **Configure** on the integration page.

| Step | What you enter |
|---|---|
| 1. Charger | Entities: charger power, applied current, active phases, connection state, maximum current. Values: minimum current (6 A), fallback current (7 A), fallback phases (1), voltage (230 V), current step (0.1 A or 1 A), widen small decreases (on for Alfen), keep the phase on a sensor fault (off). Optional: the charger's energy meter. |
| 2. Charger controls | The current-limit `number` and the phase `select`. |
| 3. Phase options | The option of the phase select for 1 phase and for 3 phases. |
| 4. Household | House power without the charger. Optional: solar power, monthly peak. |
| 5. Car | Optional: battery level, battery capacity, car maximum and minimum current. Without a battery level, the battery targets have no effect. |
| 6. Price and EMS | Optional: price sensor (or one of its attributes) and EMS signal. Without a price, the price check is skipped. |
| 7. Tuning | Power update threshold (230 W), phase switch delay (5 min), recalculation interval (10 s), peak factor (90 %). |

The controller uses the **fallback current and phases** after a sensor fault, and one minute after the car is unplugged. This makes the next session start gently. With **Keep the phase on a sensor fault** off, a fault switches to the fallback phases. A charger that stops responding then does not stay on an unintended phase.

## User manual

### The device

The setup creates one device, **EV charger controller**, with these entities:

| Kind | Entity | Function |
|---|---|---|
| Setting | Charge mode | See [charge modes](#charge-modes). |
| Setting | Base power limit (W) | The maximum power of the whole house, charger included. Default 5000 W. |
| Setting | Follow monthly peak | Only with a monthly peak sensor. See [power limit](#power-limit-and-the-capacity-tariff). |
| Setting | Max charging cost (per kWh) | Above this price, the car does not use the grid. Default 0.30. |
| Setting | Target SOC, Comfort SOC, Emergency SOC (%) | Battery levels. They need **Car aware**. Defaults 80, 50 and 20 %. |
| Setting | Solar bridge (W) | The grid power that Solar mode can import to reach the minimum. Default 0 W: solar only. |
| Setting | Car aware | Use the car's battery level. |
| Setting | Charge on solar when EMS blocks | When the EMS signal is 0 W, grid modes charge on solar instead of stopping. |
| Setting | Single phase only | Never use 3 phases. |
| Setting | EMS control, EMS as on/off | The EMS signal limits the grid, as a watt budget or as on/off. |
| Decision | Target current, Target phases, Target power | What the controller sets now. |
| Decision | Effective power limit | The limit in use, after it follows the monthly peak. |
| Decision | Decision | The reason. See [decision values](#decision-values). |
| Decision | Grid allowed, Emergency charging, Target reached | Yes/no details of the decision. |
| Energy | Charged energy, Charged from grid, Charged from solar (kWh) | Totals for the Energy dashboard or an EMS. |
| Diagnostic | Charger efficiency, Solar surplus, Grid share, Phase hold until | More detail. |

Settings keep their value after a restart. The controller runs at the recalculation interval. It also runs immediately when the mode, a setting, the connection or the phase changes.

### Charge modes

| Mode | Behaviour |
|---|---|
| **Off** | No charging. |
| **1-Phase Minimum** | Exactly the minimum current on 1 phase (6 A ≈ 1.4 kW), from grid or solar. |
| **3-Phases Minimum** | Exactly the minimum current on 3 phases (6 A ≈ 4.1 kW). Stops when there is not sufficient power; does not change to 1 phase. Not possible together with Single phase only. |
| **Limited** | Grid up to the power limit, with solar added. |
| **Fast** | As much as the charger accepts, within the power limit. |
| **Solar** | Solar surplus only. When the surplus is just below the minimum, the solar bridge imports the difference. |
| **Comfort** | Limited until the car reaches the comfort SOC, then Solar. Needs Car aware; without it, Comfort operates as Limited. |

All modes stay within the power limit. The car only gets the power that the house leaves available.

### Power limit and the capacity tariff

The **base power limit** is the maximum power that the house can take from the grid, charger included. The car gets the remainder: limit − house power.

The capacity tariff bills the highest quarter-hour of the month. When that peak is set, charging up to it costs nothing extra. With a **monthly peak** sensor in the setup and **Follow monthly peak** on, the limit is the higher of:

- the base power limit, and
- the peak factor (90 %) × the monthly peak.

Example: base 5 kW, monthly peak 8 kW → limit 7.2 kW. The **Effective power limit** sensor shows the value in use.

### Solar charging

- In **Solar** mode, the car charges on the export. Example: with a **Solar bridge** of 1000 W and an export of 400 W, the car charges at the 1.4 kW minimum. The bridge imports the missing 980 W. The bridge never imports more than the difference.
- **Comfort** charges as Limited until the comfort SOC, then as Solar.
- The other modes add solar to their grid share.

### Price and EMS

- **Max charging cost:** with a price sensor, the grid is blocked while the price is above this value. The car can still charge on solar.
- **EMS control:** the EMS signal (in W) limits the grid. As a **budget**, the grid share is at most the signal. As **on/off**, a value above 0 W allows the grid.
- **EMS at 0 W** stops the grid modes, also on solar. **Charge on solar when EMS blocks** lets them continue on solar. Solar mode always continues on solar.

### Car awareness

With **Car aware** on and a valid battery level:

- **Emergency SOC:** below this level, the car charges up to the power limit in all modes except Off. Price and EMS do not block it.
- **Target SOC:** at or above this level, charging stops.
- **Comfort SOC:** the level where Comfort changes from Limited to Solar.

Without a valid battery level, the controller operates as if Car aware is off.

### Phases

The controller uses 3 phases when the power is sufficient for the minimum current on 3 phases. Else it uses 1 phase. After a change to 1 phase, it waits for the **phase switch delay** before it goes back to 3. Thus passing clouds do not switch the contactors repeatedly. After a change to 3 phases, it waits 40 s for the charger to report.

### Energy for your EMS

**Charged energy**, **Charged from grid** and **Charged from solar** count kWh. The values come from the charger's energy meter when you set one, else from the charger power. Use them in the Energy dashboard as individual device consumption, or let your EMS calculate cost and reimbursement. The integration does not calculate money.

### Decision values

| Value | Meaning |
|---|---|
| Charging | Charging at the target current. |
| Emergency charging | Charging because the battery is below the emergency SOC. |
| Off | The mode is Off. |
| Target reached | The battery is at or above the target SOC. |
| Grid blocked | Price or EMS blocks the grid, and there is not sufficient solar. |
| Not enough power | Not sufficient power for the minimum current. |
| Refused | 3-Phases Minimum together with Single phase only. |
| Fail-safe | A necessary sensor is unavailable. |
| Not connected | No car is connected, or the charger reports an error. |
| Charger unavailable | The charger's current or phase setting is unknown. |
| No power limit | The power limit is 0. |
| Waiting after phase switch | A 40 s pause after a change to 3 phases. |

## Troubleshooting

| Symptom | Check |
|---|---|
| The decision stays **Fail-safe**. | Charger power, applied current, active phases or house power is unavailable. |
| The decision stays **Not connected** while a car is connected. | The connection entity must show a Mode 3 state (B1 … D2 = connected), or be a binary sensor that is on. |
| The current goes up and down at each run. | The house power sensor probably includes the charger. It must exclude the charger. |
| **Grid blocked** during daylight. | The price is above Max charging cost, or the EMS signal is 0 W. Turn on **Charge on solar when EMS blocks** to use solar. |
| **Comfort** never changes to Solar. | Car aware is off, or the battery level is unavailable. |
| The target current stays at the fallback current. | The maximum current entity has not sent a value since the start. |

For a support request, download the diagnostics from the device page (⋮ → **Download diagnostics**) and attach them to an [issue](https://github.com/straybiker/HA-EV-Charge-Control/issues).

## Roadmap

- Write to the charger, with a **Control charger** switch, retries, and a repair issue when the charger does not respond.
- A brand icon and the first HACS release.

## Documentation

- [Charging behaviour](docs/behaviour.md): all rules and the design decisions.
- [Engine](docs/engine.md): the decision engine.
- [Home Assistant integration](docs/integration.md): runtime, entities and validation.
- [Test report](docs/test-report.md): the latest test run ([interactive HTML version](docs/test-report.html)).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, the tests and the conventions.

This project replaces [EV Load Balancer](https://github.com/straybiker/HA-load-balancer), a YAML package for the same purpose. It keeps the intent of that package, not its design.

## License

[MIT](LICENSE)
