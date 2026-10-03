# EV Charge Control

[![Tests](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/test.yml)
[![Validate](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml/badge.svg)](https://github.com/straybiker/HA-EV-Charge-Control/actions/workflows/validate.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)

A Home Assistant integration for smart EV charging. It sets the charge current and the number of phases from your house power, solar surplus, power limit, electricity price, EMS signal and the car's battery level. It also counts the energy that goes into the car.

> [!IMPORTANT]
> **A new device starts in shadow mode.** It calculates what it would set and shows it on its sensors, but writes nothing until you switch **Control charger** on. See [Taking control of the charger](#taking-control-of-the-charger).

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
- **Capacity tariff:** one power limit for the whole house, from a helper or your EMS, with an optional safety buffer.
- **Solar first:** charges on surplus. A small grid bridge closes the gap when the surplus is just below the minimum.
- **EMS and price:** an EMS signal (watt budget or on/off) and a maximum electricity price control the grid share.
- **Car aware:** emergency, target and comfort battery levels.
- **1 and 3 phases:** switches phases, with a hold time that prevents flapping.
- **Energy:** charged energy, split into grid and solar, for the Energy dashboard or an EMS.
- **Safe by design:** a sensor fault never increases the current. Writes are confirmed, retried and reported as a repair issue when the charger does not follow. Settings survive restarts.
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
- **A power limit entity** (W or kW): a helper or an entity of your EMS, for example this month's capacity tariff peak.
- Optional: the car's battery level, an electricity price, an EMS signal, the charger's energy meter.

## Installation

**HACS**

1. In HACS, open the menu and select **Custom repositories**.
2. Add `https://github.com/straybiker/HA-EV-Charge-Control` with the type **Integration**.
3. Install **EV Charge Control** and restart Home Assistant.

**Manual**

1. Copy `custom_components/ev_charge_control` into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

Then go to **Settings → Devices & services → Add integration → EV Charge Control**. Each setup creates one charge-controller device for one charger.

## Configuration

**Inputs and outputs.** Every few seconds the controller reads its **inputs**, decides how fast the car may charge, and sets its **outputs**.

- **Inputs** are entities the controller only reads: what the charger reports, the house power, and optionally the battery level, the electricity price and an EMS signal.
- **Outputs** are the two entities of your charger's own integration that the controller changes: the charging current limit and the phase setting. It writes to them only while **Control charger** is on.

The setup steps are numbered and named after what they ask for: outputs, inputs or fixed values. To change the setup later, select **Configure** on the integration page; it shows the same steps, without the name.

| Step | Kind | What you enter |
|---|---|---|
| New charge controller | | The device name. On the first controller of a system with the EV Load Balancer YAML package: **Import from EV Load Balancer** (see the [migration guide](docs/migration.md)). |
| Charger outputs | Writes | The charging current limit (`number`) and the phase setting (`select`) of your charger. |
| Phase options | | The option of the phase setting for 1 phase and for 3 phases. |
| Charger inputs | Reads | Connection state, charging power, applied current limit, active phases, maximum current. Optional: energy meter. |
| Charger limits and safety | Fixed | Minimum current (6 A), voltage per phase (230 V), current step (0.1 A or 1 A), widen small decreases (on for Alfen), fallback current (7 A) and phases (1), keep the phases on a sensor fault (off), what the charger gets when Control charger is switched off (fallback). |
| House | Reads | House power without the charger, power limit (sensor or number). Optional: peak factor as a safety buffer (empty: 100 %), solar power. |
| Car (optional) | Reads | Battery level, battery capacity, car maximum and minimum current. Without a battery level, the battery targets have no effect. |
| Price and EMS (optional) | Reads | Price sensor (or one of its attributes), EMS signal. Without a price, the price check is skipped. |
| Tuning | Fixed | Power update threshold (230 W), phase switch delay (5 min), recalculation interval (10 s). |

**More than one controller.** Each controller needs its own charger outputs; setup refuses a current limit or phase setting that another controller uses. When a new controller reads the same charger sensors, battery level, house power, power limit or EMS signal as another one, setup shows a warning with the shared entities before it saves. Two controllers on one house power sensor both take the full headroom and together exceed the power limit. Solar power and the price can be shared.

The controller uses the **fallback current and phases** after a sensor fault, and one minute after the car is unplugged. This makes the next session start gently. With **Keep the phase on a sensor fault** off, a fault switches to the fallback phases. A charger that stops responding then does not stay on an unintended phase.

## User manual

### The device

The setup creates one device, **EV charger controller**, with these entities:

| Kind | Entity | Function |
|---|---|---|
| Setting | Control charger | Write to the charger. Off on a new device. See [Taking control of the charger](#taking-control-of-the-charger). |
| Setting | Charge mode | See [charge modes](#charge-modes). |
| Setting | Max charging cost (per kWh) | Above this price, the car does not use the grid. Default 0.30. |
| Setting | Target SOC, Comfort SOC, Emergency SOC (%) | Battery levels. They need **Car aware**. Defaults 80, 50 and 20 %. |
| Setting | Solar bridge (W) | The grid power that Solar mode can import to reach the minimum. Default 0 W: solar only. |
| Setting | Car aware | Use the car's battery level. |
| Setting | Charge on solar when EMS blocks | When the EMS signal is 0 W, grid modes charge on solar instead of stopping. |
| Setting | Single phase only | Never use 3 phases. |
| Setting | EMS control, EMS as on/off | The EMS signal limits the grid, as a watt budget or as on/off. |
| Decision | Target current, Target phases, Target power | What the controller sets now, or would set with Control charger off. |
| Decision | Effective power limit | The limit in use: the power limit entity × the peak factor. See [power limit](#power-limit-and-the-capacity-tariff). |
| Decision | Decision | The reason. See [decision values](#decision-values). |
| Decision | Grid allowed, Emergency charging, Target reached | Yes/no details of the decision. |
| Energy | Charged energy, Charged from grid, Charged from solar (kWh) | Totals for the Energy dashboard or an EMS. |
| Diagnostic | Charger efficiency, Solar surplus, Grid share, Phase hold until | More detail. |

Settings keep their value after a restart. The controller runs at the recalculation interval. It also runs immediately when the mode, a setting, the connection or the phase changes.

### Taking control of the charger

1. Leave **Control charger** off for some days. Compare **Target current** and **Target phases** with what your current automation does.
2. Turn off the automation that sets the charger now. Two controllers on one charger work against each other.
3. Switch **Control charger** on.

The controller then writes to the charger's current-limit number and phase select. It switches from 1 to 3 phases at 0 A, and it checks that the charger follows each write: the applied current within 30 s, the active phases within 60 s. A write that the charger does not follow is written again at the next run. After 3 in a row, the decision shows **Charger not responding** and a repair issue appears under **Settings → Repairs**. Both clear when the charger follows again.

When you switch **Control charger** off, the charger gets the fallback current and phases once, so it does not stay at a high current that nothing controls. The setup option in Charger limits and safety can change this to *Leave as it is* or *Stop charging (0 A)*.

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

The **power limit** is the most power the house may take from the grid, charger included. The car gets the remainder: limit − house power.

The limit comes from an entity that you pick in the House step: a helper you set by hand, or an entity of your EMS. With the capacity tariff that is usually this month's peak: the tariff bills the highest quarter-hour, so charging up to it costs nothing extra. The EMS decides how the limit follows the peak; the controller only reads it.

The optional **peak factor** is a safety buffer: the controller uses that share of the limit. With 90 % and a peak of 8 kW, the car's limit is 7.2 kW, so a short overshoot stays below the billed peak. Empty means 100 %.

- When the limit entity is unavailable, the controller uses its last value.
- Until the entity has reported a value, the decision is **No power limit** and nothing is written.

The **Effective power limit** sensor shows the value in use.

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
| No power limit | The power limit entity has not reported a value yet, or is 0. |
| Waiting after phase switch | A 40 s pause after a change to 3 phases. |
| Charger not responding | The charger did not follow the last 3 writes. See [Taking control of the charger](#taking-control-of-the-charger). |

## Troubleshooting

| Symptom | Check |
|---|---|
| The decision stays **Fail-safe**. | Charger power, applied current, active phases or house power is unavailable. |
| The decision stays **Not connected** while a car is connected. | The connection entity must show a Mode 3 state (B1 … D2 = connected), or be a binary sensor that is on. |
| The current goes up and down at each run. | The house power sensor probably includes the charger. It must exclude the charger. |
| **Grid blocked** during daylight. | The price is above Max charging cost, or the EMS signal is 0 W. Turn on **Charge on solar when EMS blocks** to use solar. |
| **Comfort** never changes to Solar. | Car aware is off, or the battery level is unavailable. |
| **Charger not responding**, with a repair issue. | The charger is offline, or its integration does not pass the values on. Check the charger's current-limit number and applied current. Switch Control charger off to stop the attempts. |
| The charger changes, but differently from Target current. | Another automation also writes to the charger. Turn it off. |
| The target current stays at the fallback current. | The maximum current entity has not sent a value since the start. |

For a support request, download the diagnostics from the device page (⋮ → **Download diagnostics**) and attach them to an [issue](https://github.com/straybiker/HA-EV-Charge-Control/issues).

## Roadmap

- Listing in the HACS default store.

## Documentation

- [Migrating from EV Load Balancer](docs/migration.md): parameter mapping and switch-over steps.
- [Charging behaviour](docs/behaviour.md): all rules and the design decisions.
- [Engine](docs/engine.md): the decision engine.
- [Home Assistant integration](docs/integration.md): runtime, entities and validation.
- [Test report](docs/test-report.md): the latest test run ([interactive HTML version](docs/test-report.html)).

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, the tests and the conventions.

This project replaces [EV Load Balancer](https://github.com/straybiker/HA-load-balancer), a YAML package for the same purpose. It keeps the intent of that package, not its design. To move over, follow the [migration guide](docs/migration.md).

## License

[MIT](LICENSE)
