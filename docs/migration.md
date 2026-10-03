# Migrating from EV Load Balancer

This guide moves a Home Assistant installation from the [EV Load Balancer](https://github.com/straybiker/HA-load-balancer) YAML package to this integration. Both can run side by side: the integration starts in shadow mode and writes nothing until you switch **Control charger** on.

## 1. Set up the integration next to the package

Install the integration (see the [README](../README.md#installation)) and add it. Leave the package running. Use the table below to fill in the setup from `ev_loadbalancer_user_config.yaml`.

## 2. Parameter mapping

### Charger (`EV Load Balancer Charger`)

| Package attribute | Integration |
|---|---|
| `active_power` | Setup step 1: Charger power |
| `current_input` | Setup step 1: Applied current limit |
| `phases_input` | Setup step 1: Active phases |
| `connection_state` (template) | Setup step 1: Connection state. Pick the charger's Mode 3 sensor itself; the integration maps the states. |
| `max_current` | Setup step 1: Max current (the entity, not a fixed value) |
| `min_current` | Setup step 1: Min current |
| `default_current` | Setup step 1: Fallback current |
| `default_phases` | Setup step 1: Fallback phases |
| `nominal_voltage` | Setup step 1: Voltage |
| `current_output` | Setup step 2: Current limit |
| `phases_output` | Setup step 2: Phase setting |
| `phase_1_state`, `phase_3_state` | Setup step 3: Option for 1 phase, Option for 3 phases |

Alfen chargers: set **Current step** to 0.1 A and turn **Widen small decreases** on. The package did this in its write script.

### House (`EV Load Balancer House`)

| Package attribute | Integration |
|---|---|
| sensor state (house power without the charger) | Setup step 4: House power without the charger |
| `pv_power` | Setup step 4: Solar power (optional, diagnostics only) |

### Car (`EV Load Balancer Car`)

| Package attribute | Integration |
|---|---|
| `battery_percentage` | Setup step 5: Battery level |
| `battery_capacity_wh` | Setup step 5: Battery capacity, in **kWh** (74000 Wh → 74) |
| `max_current`, `min_current` | Setup step 5: Car max current, Car min current |

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
| `ems_signal` | Setup step 6: EMS signal |
| `electricity_price` | Setup step 6: Electricity price; when the template reads an attribute, enter that attribute as Price attribute |
| `max_cost_rate` | Device: Max charging cost |
| `emergency_soc`, `comfort_soc`, `target_soc` | Device: Emergency SOC, Comfort SOC, Target SOC |
| `power_update_threshold` | Setup step 7: Power update threshold |
| `phase_switch_delay` | Setup step 7: Phase switch delay |

The device settings keep their value across restarts; they replace the package's `input_*` helpers.

### Capacity tariff

If an automation raised `input_number.ev_load_balancer_power_limit` to follow the month's peak, pick the monthly peak sensor in setup step 4 instead and leave **Follow monthly peak** on. The limit becomes the higher of the base power limit and 90 % (setup step 7) of the peak.

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
