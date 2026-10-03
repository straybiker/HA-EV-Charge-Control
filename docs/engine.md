# Decision engine

`custom_components/ev_charge_control/engine/` is a pure-Python port of the EV Load Balancer YAML package ([straybiker/HA-load-balancer](https://github.com/straybiker/HA-load-balancer), `packages/ev_loadbalancer.yaml`). It imports nothing from Home Assistant.

The engine reproduces the YAML as it runs, not as the README describes it, except for the defects marked `fixed` in [known-defects.md](known-defects.md) (D02, D05, D07, D12). Do not change a formula without updating that list and its test.

Line numbers below (`LB:n`) refer to `packages/ev_loadbalancer.yaml` at commit `f47eeca`.

## Public API

| Function | Port of | Purpose |
|---|---|---|
| `decide(spec, car, settings, m, timers, now) -> Decision` | automation "EV Charging Load Balancer" (LB:308–554) | Phase and current the charger should get |
| `filter_setpoint(decision, spec, car, settings, m) -> Setpoint` | script "Set EV load balancer charger parameter" (LB:158–305) | What to write, after the minimum rule, the Alfen workaround and hysteresis |
| `on_commanded_phase_change(prev, new, settings, connection, now, state) -> TimerState` | automations at LB:574–617 | Phase-switch timer and sensor grace period |

The adapter (later plan) maps entities to values, calls these three functions, and performs the I/O.

## Inputs

### `ChargerSpec`

| Field | YAML attribute | Default |
|---|---|---|
| `max_current_a` | `charger.max_current` | required |
| `min_current_a` | `charger.min_current` | 6 |
| `default_current_a` | `charger.default_current` | 7 |
| `default_phases` | `charger.default_phases` | 1 |
| `nominal_voltage_v` | `charger.nominal_voltage` | 230 |

### `CarSpec`

| Field | YAML attribute | Default |
|---|---|---|
| `max_current_a` | `car.max_current` | 16 |
| `min_current_a` | `car.min_current` | 6 |
| `battery_capacity_wh` | `car.battery_capacity_wh` | `None` (unknown) |

### `Settings`

| Field | YAML helper | Default |
|---|---|---|
| `mode` | `input_select.ev_load_balancer_charge_mode` | required |
| `power_limit_w` | `input_number.ev_load_balancer_power_limit` | required |
| `car_aware` | `input_boolean.ev_load_balancer_car_aware` | False |
| `pv_prioritized` | `input_boolean.ev_load_balancer_pv_prioritized` | False |
| `pv_prio_threshold_w` | `input_number.ev_load_balancer_pv_prio_threshold` | 0 |
| `single_phase_only` | `input_boolean.ev_load_balancer_single_phase_only` | False |
| `ems_control` | `input_boolean.ev_load_balancer_ems_control` | False |
| `ems_as_onoff` | `input_boolean.ev_load_balancer_ems_as_onoff` | False |
| `max_cost_rate` | `input_number.ev_max_charging_cost` (€/kWh) | 0.30 |
| `emergency_soc` | `input_number.ev_load_balancer_emergency_soc` | 20 |
| `comfort_soc` | `input_number.ev_load_balancer_comfort_soc` | 50 |
| `target_soc` | `input_number.ev_load_balancer_target_soc` | 80 |
| `power_update_threshold_w` | `power_update_threshold` attribute | 230 |
| `phase_switch_delay_min` | `phase_switch_delay` attribute | 5 |

### `Measurements`

`None` means unavailable or unknown.

| Field | YAML source | Unit | When `None` |
|---|---|---|---|
| `household_power_w` | `sensor.ev_load_balancer_house` state | W, net, charger excluded, negative = export | fail-safe |
| `charger_power_w` | `charger.active_power` | W | fail-safe |
| `applied_current_a` | `charger.current_input` | A | fail-safe |
| `applied_phases` | `charger.phases_input` | 1 or 3 | fail-safe |
| `connection` | `charger.connection_state` | enum | run skipped unless `CONNECTED` |
| `commanded_phase` | state of the `phases_output` select | 1 or 3 | run skipped |
| `commanded_current_a` | state of the `current_output` number | A | run skipped |
| `car_soc` | `car.battery_percentage` | % | car awareness off, SOC treated as 100 |
| `electricity_price` | `electricity_price` attribute | €/kWh | price check skipped (D01) |
| `ems_signal_w` | `ems_signal` attribute | W | treated as 0 (gate closed when EMS is on) |

### `TimerState`

`phase_switch_until` and `grace_until` are deadlines. A timer is active while `now < deadline`.

## The decision (`decide`)

Constants: `p_min_1 = min_current · V`, `p_min_3 = min_current · V · 3`, `p_fast = max_current · V · 3`, `max_hardware = max_current · V · 3`.

| Step | YAML | Rule |
|---|---|---|
| 1 Run conditions | LB:319–327 | Skip (`should_write=False`) unless connected, both outputs have a value, `power_limit > 0`, and the grace timer is idle. |
| 2 Fail-safe | LB:332–358 | If any base measurement is `None`: phase = `default_phases`, current = `min(commanded_current, default_current)`. The current is never raised. |
| 2b Refusal | — | 3-Phases Minimum with `single_phase_only`: reason `refused`, 1 phase, 0 A (D07). |
| 3 `car_aware` | LB:373 | `settings.car_aware and battery_capacity_wh is not None and car_soc is not None` |
| 4 Current limits | LB:376–383 | `max = min(car.max, charger.max)` and `min = max(car.min, charger.min)` when car-aware, else charger values. |
| 5 Efficiency | LB:386–393 | `charger_power / (applied_current · V · applied_phases)`, limited to 0.85–1.0 (D12), when `applied_current > 0` and `charger_power > 1000`, else `1.0`. |
| 6 Gates | LB:396–421 | `is_emergency = car_aware and soc < emergency_soc`. `target_reached = car_aware and soc >= target_soc`. `grid_gate_open = is_emergency or (price_ok and (not ems_control or ems_signal > 0))` with `price_ok = price is None or price <= max_cost_rate` (D01). |
| 7 `desired_grid_w` | LB:425–442 | Off → 0. Emergency → `power_limit`. Target reached → 0. Gate closed → 0. 1P min → `p_min_1`. 3P min → `p_min_3`. Fast → `p_fast`. Limited → `power_limit`. Comfort → `power_limit` if `not car_aware or soc < comfort_soc`, else 0. Solar → 0. |
| 8 `effective_grid_w` | LB:446–457 | Emergency → desired. Solar → 0. EMS budget mode (`ems_control and not ems_as_onoff`) → `min(desired, ems_signal_w)`. Else desired. |
| 9 Solar surplus | LB:464–473 | `base = −household`. With PV priority (Limited only) and `base < p_min_1`: `max(base + bridge, 0)` with `bridge = min(pv_prio_threshold, max(effective_grid_w, 0))` (D02). Else `max(base, 0)`. |
| 10 `raw_target_w` | LB:475–484 | Off → 0. Emergency → effective + surplus. Target reached → 0. EMS on, signal 0, PV priority off, mode ≠ Solar → 0. PV priority active and surplus > 0 → surplus. Minimum modes → `min(minimum power, effective + surplus)` (D05). Else effective + surplus. |
| 11 Final power | LB:487–495 | `min(raw / eff, headroom / eff if headroom > 0 else 0, max_hardware)` with `headroom = power_limit − household`. |
| 12 Phase | LB:498–515 | 1P min → 1. 3P min → 3. `single_phase_only` → 1. `final >= p_min_3` → 3. Else 1. A 1→3 upgrade is held at the commanded phase while the phase timer is active and the mode is Limited, Solar or Comfort. |
| 13 Current | LB:517–522 | `round(final / (V · phases), 1)`. Below `min` → 0. Above `max` → `max`. |
| 14 Execution | LB:526–551 | Off → 0 A. The phase is always sent. |

### Behaviour per mode (gate open, no EMS, no emergency)

`S` = exported power (0 when importing). `HR` = `(power_limit − household) / eff`.

| Mode | Phase | Power |
|---|---|---|
| Off | 1 | 0 |
| 1-Phase Minimum | 1 | `min(p_min_1, HR)`; grid and solar may both supply it (D05) |
| 3-Phases Minimum | 3; refused with `single_phase_only` (D07) | `min(p_min_3, HR)`; 0 below 6 A, no fallback to 1 phase |
| Fast | by `p_min_3`, no timer hold (D13, by design) | `min(p_fast + S, HR)` |
| Limited | dynamic, timer hold | `HR` |
| Limited + PV priority | dynamic | `S` when `S ≥ p_min_1`; `S + bridge` when `0 < S + bridge`; falls back to `HR` when import ≥ bridge. Charging stops in between (dead band). The bridge is grid power: 0 when the price gate is closed or the EMS gives 0 W, capped by the EMS budget (D02). Real solar surplus always charges. |
| Solar | dynamic | `min(S, HR)` |
| Comfort | dynamic | Limited below `comfort_soc` (or when not car-aware), Solar above |

Emergency (car-aware and SOC below `emergency_soc`) requests `power_limit + S` in every mode except Off, including Solar and the Minimum modes (D06, by design). It bypasses price, EMS and target checks. `HR` still applies.

## The write filter (`filter_setpoint`)

| Step | YAML | Rule |
|---|---|---|
| Minimum | LB:164–170 | `min = max(car.min if settings.car_aware else charger.min, charger.min)`. The raw flag is used, not the validated one (D15). Current below `min` → 0. |
| Phase | LB:173–226 | `write_phase` when the commanded phase differs. `zero_before_phase_change` only for 1→3. |
| Alfen workaround | LB:230–239 | A decrease `0 < step < 0.15 A` is written as `commanded − 0.2`, unless that drops below `min`. |
| Hysteresis | LB:242–255 | `threshold = power_update_threshold / (V · phases)`. A decrease is always written. An increase needs `target − commanded ≥ threshold`. With defaults: 1.0 A on 1 phase, 0.333 A on 3 phases. |

The adapter performs the writes in this order: zero the current (1→3 only) and wait for `applied_current == 0`; select the phase and wait for `applied_phases` to follow; write the current and wait for `|applied − target| < threshold`. The YAML polls every second with 30, 60 and 30 attempts.

## Timers (`on_commanded_phase_change`)

Called when the commanded phase (the select state) changes.

| Timer | YAML | Starts when | Duration |
|---|---|---|---|
| Phase switch | LB:574–598 | new = 1, previous ≠ 1 (including unknown), mode in {Limited, Solar, Comfort}, connected | `phase_switch_delay_min` |
| Grace period | LB:600–617 | previous = 1, new = 3 | 40 s |

A start on a running timer restarts it. While the grace period runs, `decide` skips with `GRACE_PERIOD`.

## Tests

- `tests/engine/test_golden_output.py`: the 13 cases of the original Jinja test, with the template's actual values.
- `tests/engine/test_phase_timer.py`: the 9 trigger cases plus the grace rule.
- `tests/engine/test_modes.py`, `test_setpoint.py`: behaviour the Jinja tests did not cover.
- `tests/engine/test_known_defects.py`: the intended behaviour per defect. `xfail(strict=True)` for defects kept for parity, normal tests for fixed ones.
- `tests/engine/test_yaml_oracle.py`: renders the YAML variable chain with Jinja and compares it with `decide()` on 15,120 cases. A mismatch passes only when `_fixed_deviation()` names the fixed defect that explains it, and each fix must show up at least once. Runs only when `../EV_Loadbalancer` is checked out next to this repository. It is the parity gate.

Run everything with `pytest -q`.
