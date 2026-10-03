# Migrating from EV Load Balancer

This guide moves a Home Assistant installation from the [EV Load Balancer](https://github.com/straybiker/HA-load-balancer) YAML package to this integration. Both can run side by side: the integration starts in shadow mode and writes nothing until you switch **Control charger** on.

## 1. Set up the integration next to the package

Install the integration (see the [README](../README.md#installation)) and add it. Leave the package running.

The setup of the first controller detects the package and offers **Import from EV Load Balancer**. With the import on:

- The setup steps are prefilled. The outputs, phase texts, fixed values, car values and tuning come from the package's template sensors. The input entities come from `ev_loadbalancer_user_config.yaml` when it is in the configuration folder or a `packages` folder below it.
- The new device starts with the package's settings: mode, power limit, battery levels and switches. **Control charger** stays off.

Check each step before you continue: the table below shows where every package parameter goes. Without the import, fill in the steps from the table.

## 2. Parameter mapping

### Charger (`EV Load Balancer Charger`)

| Package attribute | Integration |
|---|---|
| `active_power` | Charger inputs: Charging power |
| `current_input` | Charger inputs: Applied current limit |
| `phases_input` | Charger inputs: Active phases |
| `connection_state` (template) | Charger inputs: Connection state. Pick the charger's Mode 3 sensor itself; the integration maps the states. |
| `max_current` | Charger inputs: Maximum current (the entity, not a fixed value) |
| `min_current` | Charger limits and safety: Minimum current |
| `default_current` | Charger limits and safety: Fallback current |
| `default_phases` | Charger limits and safety: Fallback phases |
| `nominal_voltage` | Charger limits and safety: Voltage per phase |
| `current_output` | Charger outputs: Charging current limit |
| `phases_output` | Charger outputs: Phase setting |
| `phase_1_state`, `phase_3_state` | Phase options: Option for 1 phase, Option for 3 phases |

Alfen chargers: in Charger limits and safety, set **Current step** to 0.1 A and turn **Widen small decreases** on. The package did this in its write script.

### House (`EV Load Balancer House`)

| Package attribute | Integration |
|---|---|
| sensor state (house power without the charger) | House: House power without the charger |
| `pv_power` | House: Solar power (optional, diagnostics only) |

### Car (`EV Load Balancer Car`)

| Package attribute | Integration |
|---|---|
| `battery_percentage` | Car: Battery level |
| `battery_capacity_wh` | Car: Battery capacity, in **kWh** (74000 Wh → 74) |
| `max_current`, `min_current` | Car: Car maximum current, Car minimum current |

### Settings (`EV Load Balancer`)

| Package attribute | Integration |
|---|---|
| state (charge mode) | Device: Charge mode. See [modes](#modes) below. |
| `power_limit` | Device: Base power limit |
| `car_aware` | Device: Car aware |
| `pv_prioritized` | Device: Charge on solar when EMS blocks. Its other job, solar first in Limited, is now Solar mode. |
| `pv_prio_threshold` | Device: Solar bridge |
| `single_phase_only` | Device: Single phase only |
| `ems_control`, `ems_as_onoff` | Device: EMS control, EMS as on/off |
| `ems_signal` | Price and EMS: EMS signal |
| `electricity_price` | Price and EMS: Electricity price; when the template reads an attribute, enter that attribute as Price attribute |
| `max_cost_rate` | Device: Max charging cost |
| `emergency_soc`, `comfort_soc`, `target_soc` | Device: Emergency SOC, Comfort SOC, Target SOC |
| `power_update_threshold` | Tuning: Power update threshold |
| `phase_switch_delay` | Tuning: Phase switch delay |

The device settings keep their value across restarts; they replace the package's `input_*` helpers.

### Capacity tariff

If an automation raised `input_number.ev_load_balancer_power_limit` to follow the month's peak, pick the monthly peak (a sensor or number entity) in the House step instead and leave **Follow monthly peak** on. The limit becomes the higher of the base power limit and 90 % (Peak factor in the Tuning step) of the peak.

## Modes

| Package | Integration |
|---|---|
| Off, 1-Phase Minimum, 3-Phases Minimum, Fast, Comfort | Same name |
| Limited | Limited |
| Limited with `pv_prioritized` on | Solar, with Solar bridge = `pv_prio_threshold` |
| Solar | Solar, with Solar bridge 0 W |

## 3. Compare in shadow mode

Run both for a few days. Compare the device's **Target current** and **Target phases** with what the package sets. The [decision record](behaviour.md#decision-record) explains each intended difference; the [test report](test-report.md) shows them side by side. The most visible ones:

- The current never goes over the power limit by rounding (D16).
- Minimum modes take exactly the minimum, never surplus (D05).
- With EMS control on, the EMS budget caps every grid mode, also Fast and Minimum (D03, D04).
- Without a valid battery level, all SOC rules are off, as if Car aware is off (D08).

## 4. Switch over

1. Turn off the package's automations, so two controllers do not write to the same charger.
2. Switch **Control charger** on.
3. Watch the **Decision** sensor for some charging sessions. A repair issue appears when the charger does not follow the writes.

## 5. Remove the package

When the integration runs as intended, remove `ev_loadbalancer.yaml`, `ev_loadbalancer_user_config.yaml` and their helpers. Update dashboards and automations that use the package's entities: the device's entities replace them.
