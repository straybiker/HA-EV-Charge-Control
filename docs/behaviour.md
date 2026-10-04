# Charging behaviour

This is the specification of the charge controller. The code in `custom_components/ev_charge_control/engine/` implements it, and `tests/engine/` checks it. Change this file, the code and the tests together.

All power values are AC power at the charger meter, in watts. "House power" excludes the charger; negative means export.

## Modes

| Mode | Takes from the grid | Uses solar | Limit | Phases | Phase hold |
|---|---|---|---|---|---|
| Off | nothing | no | 0 A | unchanged | — |
| 1-Phase Minimum | up to the minimum | yes | exactly the minimum | 1 | no |
| 3-Phases Minimum | up to the minimum | yes | exactly the minimum | 3 | no |
| Limited | up to the power limit | yes, on top | power limit | 1 or 3 | yes |
| Fast | up to the hardware maximum, also above the maximum price | yes, on top | power limit | 1 or 3 | no |
| Solar | only the bridge | yes, first | power limit | 1 or 3 | yes |
| Comfort | as Limited below the comfort SOC, as Solar from the comfort SOC | | | | |

Comfort needs trusted car data. Without it Comfort stays Limited.

## Order of rules

Each run applies the first rule that matches.

1. **Not connected.** Write nothing. After 60 s unplugged, write the fallback setpoint (1 phase, fallback current) once, so the next session starts gently. The target current and phases then show that setpoint; the target power is 0 W, as no car draws power. A charger in error never gets the reset.
2. **Charger unavailable** (current limit or phase setting unknown), **power limit 0**, or **grace period** (40 s after a 1→3 switch): write nothing.
3. **Fail-safe.** House power, charger power, applied current or active phases unknown: set `min(current setting, fallback current)` and the fallback phase (1). The current never goes up on a sensor fault, and a charger that stops responding is not left on an unintended phase. The charger option "Keep the phase on a sensor fault" keeps the current phase instead.
4. **Refused.** 3-Phases Minimum with single phase only: 1 phase, 0 A. The Home Assistant entities also block selecting this combination.
5. **Off.** 0 A, phase unchanged.
6. **Target reached** (car aware, SOC ≥ target): 0 A.
7. **Emergency** (car aware, SOC < emergency SOC): grid allowance = power limit, plus all solar. Price, EMS and the Minimum cap do not apply. Off is the only mode that ignores the emergency.
8. **Normal charging:** the power budget below.

## Power budget

- **Solar** = export = `max(−house power, 0)`.
- **Headroom** = `max(power limit − house power, 0)`.
- **Grid gate.** The grid is allowed when the price is at or below the maximum cost (no price: the check is skipped) and, with EMS control on, the EMS signal is above 0 W (no signal: closed). Fast skips the price check; the EMS check stays (B19).
- **What skips what.** No rule skips the power limit. Fast skips the price check. The emergency skips the price, the EMS and the Minimum cap. Solar and Comfort from the comfort SOC let the price and the EMS block only the bridge.
- **Grid allowance.** Gate closed: 0. Otherwise the mode's request (bridge, minimum, power limit or hardware maximum). With EMS in budget mode, capped at the EMS signal in watts. With EMS in on/off mode, the signal only opens or closes the gate.
- **EMS at 0 W** stops Minimum, Limited and Fast, also on solar, unless "Charge on solar when EMS blocks" is on: then they charge on solar only. Solar (and Comfort from the comfort SOC) keeps charging on solar; EMS blocks only its bridge.
- **Request.**
  - Minimum modes: `min(solar + grid allowance, minimum)`. Grid and solar may both supply the minimum; the surplus never raises it.
  - Limited, Fast: `solar + grid allowance`.
  - Solar: solar first. Solar ≥ 1-phase minimum: charge on solar alone. Solar below the minimum, but the gap fits within the bridge and the grid allowance: charge at exactly the minimum and import only the gap. Otherwise: no charging.
- **Target power** = `min(request, headroom, hardware maximum)`.

## Power limit

- **Power limit:** read at each run from a required entity (sensor or number, W or kW): a helper or an entity of the EMS. With a capacity tariff, the EMS gives it a floor and lets it follow the paid peak, for example max(default, 90 % × monthly peak). A raw monthly peak is not a good limit where the tariff resets it at the start of the month.
- **Effective power limit** = peak factor × power limit. The peak factor is an optional setup field (50–100 %, empty: 100 %): a safety buffer, so a held charging power stays below the billed peak.
- Limit unavailable: the last known value. No value since start: 0, so the controller has no power limit and writes nothing.
- The controller uses the effective limit everywhere the rules above say "power limit".

## Charger maximum

- Read every run from the max current entity picked in setup.
- Unavailable: the last known value. No value since start: the fallback current is the maximum. Never above 32 A.

## Phases

- Minimum modes use their own phase count. Single phase only forces 1 phase in the other modes.
- **Single-phase charger.** Without an option for 3 phases in the setup, Single phase only is always on and cannot be switched off. The fallback phases must be 1. Any other state of the phase setting counts as "not 1 phase", so the controller writes the 1-phase option.
- Otherwise 3 phases when the target power gives at least the minimum current on 3 phases, else 1.
- **Phase hold.** After the charger drops from 3 to 1 phase in Limited, Solar or Comfort, a 1→3 upgrade waits for the phase switch delay (default 5 min). A downgrade is never held. Seeing the charger on 1 phase after a restart is not a drop and starts no hold.
- **Grace period.** After the charger goes from 1 to 3 phases, the controller waits 40 s for the charger sensors to catch up.
- **Stops keep the phase.** When a run ends at 0 A (Off, target reached, not enough power, grid blocked), the phase stays as it is. Minimum modes keep their own phase.

## Current

- `current = target power / (voltage × phases × efficiency)`, capped at the maximum current, then **rounded to the nearest** current step (0.1 A or 1 A; halves round up), so solar surplus is not left unused. When rounding up would take more than the headroom under the power limit, the current is **rounded down** instead: the power limit is never exceeded. Below the minimum current the result is 0 A. Where the power limit does not bind, the charger can take up to half a step more than the target, at most about 35 W on 3 phases at 0.1 A (for example a few watts of import while charging on solar).
- The minimum and maximum come from the charger, narrowed by the car when car data is trusted.

## Efficiency

The ratio of measured charger power to commanded power (`current × voltage × phases`), so the controller can ask for a little more current to use the power it was given.

- Learned as a running average, weight 0.3 per sample.
- A sample counts only when the applied current was the same as in the previous run and the charger draws more than 1 kW.
- Limited to 0.85–1.0. A car drawing less than its limit would otherwise look like a very inefficient charger.
- Reset to 1.0 when the car is unplugged.

## Writing

What the controller writes, before the charger control below applies it.

- A decrease is written at once.
- An increase is written only when it is worth at least the power update threshold (default 230 W), so solar ripple causes no writes.
- "Widen small decreases" (on for Alfen): a decrease below 0.15 A is written as 0.2 A, unless that drops below the minimum. Some chargers ignore 0.1 A decreases.
- Going from 1 to 3 phases: current 0 A first, then the phase, then the current.

## Charger control

- **Control charger** (a switch on the device, off on a new device) turns writing on. While it is off, nothing is written and the decision sensors show what would be written (shadow mode).
- Writes go to the charger's current-limit number and phase setting (a select, switch or number), in this order: 0 A (only before a 1→3 switch), phase, current.
- **Confirmation.** With a car connected, a write counts as confirmed when the charger follows: the applied current comes within the power update threshold of the written value (never stricter than half a current step) within 30 s, and the active phases match within 60 s. Without a car the charger's sensors may not follow, and with the applied current or active phases unavailable (fail-safe) they cannot: then the current-limit number and the phase setting must show the written value, so a sensor fault is not reported as a charger fault. After the 0 A step the sequence goes on after at most 30 s, confirmed or not.
- **One write at a time.** A write sequence runs in the background. Runs that come while it waits for the charger write nothing.
- **Retry.** A write that is not confirmed is written again at the next run, also when the write filter sees nothing new.
- **Not responding.** After 3 unconfirmed writes in a row, a repair issue is raised and the decision becomes `charger_not_responding`. The controller keeps retrying at each run. The first confirmed write closes the issue. A restart or switching Control charger off also closes it.
- **Switching control off** hands the charger over once, without confirmation. A setup option sets what it gets:
  - **Fallback current and phases** (default): the fallback phase and fallback current.
  - **Leave as it is**: nothing is written.
  - **Stop charging**: 0 A, phase unchanged.

## Energy

The integration counts energy only; an EMS turns it into cost and reimbursement.

- **Charged energy:** from the charger's own energy meter when one is set in setup (a meter that resets or jumps back adds nothing for that step), otherwise charger power × time between runs (gaps over 5 min are not counted).
- **From solar / from grid:** each step is split with the conditions of the previous run: solar = `min(charger power, export)`, where export comes from house power without the charger; the rest is grid.
- Totals in kWh, `total_increasing`, usable in the Energy dashboard. They survive restarts (saved at most every 60 s and on unload).
- **Today:** the same three values since local midnight. The first run of a new day starts them at 0; the energy of a step across midnight counts for the new day.

## Decision sensor values

| Value | Meaning |
|---|---|
| `charging` | Charging at the shown current |
| `emergency` | Charging because the SOC is below the emergency SOC |
| `off` | Mode is Off |
| `target_reached` | SOC at or above the target |
| `grid_blocked` | Price or EMS blocks the grid and there is not enough solar |
| `insufficient_power` | Not enough power for the minimum current |
| `refused` | 3-Phases Minimum with single phase only |
| `failsafe` | A required sensor is unavailable |
| `not_connected` | No car plugged in, or the charger reports an error |
| `charger_unavailable` | The charger's current or phase setting is unknown |
| `no_power_limit` | The power limit entity has no value yet, or is 0 |
| `grace_period` | Waiting after a 1→3 phase switch |
| `charger_not_responding` | The charger did not follow the last 3 writes (shown while Control charger is on) |

## Decision record

The controller has the same purpose as the [EV Load Balancer](https://github.com/straybiker/HA-load-balancer) YAML package. These decisions record where and why it behaves differently. D items correct the package's behaviour; B items come from the redesign. The [test report](test-report.md) shows both side by side for the golden cases.

A change to the charging behaviour adds or updates a row here.

| ID | Topic | Decision |
|---|---|---|
| D01 | Price unavailable | Skip the price check, as if there were no price feature. EMS still applies. |
| D02 | Grid bridge vs gates | The bridge is grid power: it obeys the price gate and the EMS. |
| D03 | EMS budget in Fast and Minimum | EMS is always in control when enabled. The budget caps every grid mode. |
| D04 | EMS 0 W in Minimum modes | Same as D03: EMS 0 W stops them. |
| D05 | Minimum modes and surplus | A Minimum mode takes the minimum and never more. |
| D06 | Emergency in Solar | The emergency floor overrides every mode except Off, also Solar. |
| D07 | 3-Phases Minimum + single phase only | Refused. |
| D08 | SOC rules without car aware | Emergency, target and comfort SOC need car aware and a valid SOC. |
| D09 | Settings after a restart | Settings restore their last value. Defaults apply only when the device is first created. |
| D11 | Phase on fail-safe | Safe fallback phase by default, so a charger that loses communication is not stuck on an unintended phase. A charger option lets the user keep the phase instead. |
| D12 | Efficiency | Limited to 0.85–1.0. |
| D13 | Phase hold in Fast | Not needed: Fast is a fixed mode. |
| D16 | Rounding | Round up (to the nearest step) when there is headroom; round down when rounding up would exceed the power limit. |
| B1 | PV priority purpose | Maximise solar use and minimise import. The bridge closes a small gap to the minimum and is never used beyond it. |
| B2 | Solar mode | Solar mode is "solar first + bridge" (bridge 0 W = pure solar). Limited never uses the bridge. Comfort from its comfort SOC runs as Solar, so it gets the bridge. |
| B3 | PV priority switch | Renamed "Charge on solar when EMS blocks". Its only job: with EMS at 0 W, grid modes charge on solar instead of stopping. |
| B4 | Stops and phases | A stop keeps the current phase; the phase is chosen when charging restarts. |
| B5 | Phase hold after restart | Starts only on a real 3→1 change. |
| B6 | Efficiency learning | Running average, steady samples only, reset on unplug. |
| B7 | Charger quirks | Current step (0.1 A or 1 A) and "widen small decreases" are charger options. |
| B8 | Recalculation | Fixed interval (default 10 s), plus at once on mode, settings and connection changes. Power sensor updates do not trigger a run. |
| B9 | Parameter sources | Each parameter of the YAML package's user config has one place: measurements and the charger maximum are existing entities; fixed values (currents, voltage, phase texts, tuning, peak factor) are setup fields; the power limit is an existing entity; the runtime settings are device entities. |
| B10 | Power limit | From a required entity (helper or EMS); the EMS, not the integration, makes it follow the monthly peak. Effective limit = peak factor × limit; the optional peak factor is a safety buffer (empty: 100 %). Unavailable: last known value; none yet: no power limit. |
| B11 | Money | No cost or reimbursement sensors. The integration provides charged energy, split into grid and solar; an EMS calculates cost and reimbursement. |
| B12 | Energy source | The charger's energy meter when set, else integrated charger power. |
| B13 | Charger maximum | From an entity; last known value when unavailable; fallback current until a first value; never above 32 A. |
| B14 | Control charger | A device switch, off on a new device: a new controller starts in shadow mode until the user switches it on. |
| B15 | Confirmation | The charger must follow: applied current within 30 s, active phases within 60 s, as in the YAML package. Without a car, or with those sensors unavailable, the control entities confirm. |
| B16 | Not responding | Retry at each run; after 3 unconfirmed writes in a row a repair issue and decision `charger_not_responding`; the first confirmed write clears both. |
| B17 | Control switched off | Hand the charger over once. Setup option: fallback current and phases (default), leave as it is, or stop (0 A). |
| B18 | Single-phase charger | The option for 3 phases is optional. Without it, Single phase only is forced on and its switch refuses to turn off; 3-Phases Minimum is refused and the fallback phases must be 1. |
| B19 | Fast and the price | Fast skips the maximum charging cost: it uses the grid up to the power limit also when the price is high. The EMS and the power limit still apply. Without this, Fast sets the same current as Limited, because both are capped by the headroom under the power limit. |
