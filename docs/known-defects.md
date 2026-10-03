# Known defects kept for parity

The engine reproduces the YAML package as it runs. The items below are places where that behaviour is wrong, unsafe, or differs from the package README. Each one stays until a fix is approved.

Status values:
- `parity`: reproduced on purpose.
- `fixed`: the engine deviates from the YAML. The parity oracle allows this deviation, and only this one.
- `accepted`: the YAML behaviour is correct as designed. No change.
- `adapter`: belongs to the Home Assistant wiring, not the engine.

Tests: `tests/engine/test_known_defects.py` asserts the intended behaviour. Tests for `parity` defects are marked `xfail(strict=True)`. When a fix lands, remove the marker, set the status here to `fixed`, and add a narrow entry to `_fixed_deviation()` in `tests/engine/test_yaml_oracle.py`.

Line numbers refer to `packages/ev_loadbalancer.yaml` at `f47eeca`.

| ID | Status | YAML | Observed | Intended |
|---|---|---|---|---|
| D01 | accepted | LB:396 | An unavailable price is read as 0 €/kWh, so the price gate opens. | Same result, made explicit: without a price the price check is skipped, as if the installation had no price feature. The EMS gate still applies. |
| D02 | fixed | LB:469–482 | The PV-priority bridge adds grid power without checking the price gate or the EMS signal. | Only real solar surplus bypasses the gates. The bridge is grid power: it is capped at the grid allowance left after the price gate and the EMS (`min(pv_prio_threshold, effective_grid_w)`). A closed gate or EMS 0 W gives no bridge; an EMS budget below the threshold caps it. With PV priority off, nothing changes: EMS 0 W stops charging and the EMS budget shapes the grid share. |
| D03 | accepted | LB:453 | EMS budget mode shaves Fast and both Minimum modes. The README said Fast ignores the budget. | The YAML is right: EMS is always in control when enabled. The EV Load Balancer README now says so. |
| D04 | accepted | LB:433, 481 | EMS gating and the EMS-0 rule stop the Minimum modes. The README said EMS only affects Limited, Comfort and Fast. | The YAML is right, as for D03. EMS controls every mode that can use the grid; only Off, Solar and the emergency floor are outside it. |
| D05 | fixed | LB:477, 483 | The Minimum modes add solar surplus. 1-Phase Minimum reaches `max_current` while exporting. | A Minimum mode takes the minimum and nothing more: `min(minimum power, grid share + solar surplus)`. Grid and solar can both supply it, so it still runs on solar when the grid is blocked. The emergency floor still overrides it. |
| D06 | accepted | LB:431, 449 | Emergency uses the grid in Solar mode. The README said Solar never uses the grid. | The YAML is right: the emergency floor overrides every mode except Off. The EV Load Balancer README now says so. |
| D07 | fixed | LB:504–505 | 3-Phases Minimum ignores `single_phase_only`. | The combination is refused: the engine returns reason `refused`, 1 phase and 0 A. The Home Assistant wiring will also reject selecting it. |
| D08 | accepted | LB:409, 412 | Emergency, target and comfort SOC only work with `car_aware` on. The README listed emergency as "all modes". | By design: without car aware the SOC is not trusted. The EV Load Balancer README now says emergency SOC also needs car aware. |
| D09 | adapter | LB:17–109 | Helpers have no `initial`. On first start `target_soc`, `comfort_soc`, `emergency_soc` are 0 and `power_limit` is 1500. With `car_aware` on and `target_soc` 0 the car never charges. | No `initial` is correct for the YAML: a helper with `initial` resets to it on every restart. In the integration, each setting entity restores its last value after a restart and uses a sane default (20/50/80 %, power limit) only when the device is first created. |
| D10 | adapter | LB:325, 376–377 | `power_limit \| int` and `max_current \| int` have no default. An unavailable source aborts the run silently; the charger keeps its last current. | The adapter maps unavailable values to `None` and logs. The engine's types make the abort unreachable. |
| D11 | parity | LB:355 | The fail-safe forces `default_phases`. A fail-safe during 3-phase charging switches to 1 phase. | Keep the commanded phase. |
| D12 | fixed | LB:386–393 | Efficiency uses the commanded current limit, not the drawn current, and has no floor. A car that draws under its limit (1001 W at 16 A on 3 phases) gives eff 0.09 and inflates the target about 11×, up to the hardware maximum. | Efficiency is limited to 0.85–1.0 (`EFFICIENCY_FLOOR` in `balancer.py`). |
| D13 | accepted | LB:511, 589 | No phase-flap protection in Fast. The timer only starts and only holds in the dynamic modes. | By design: Fast is a fixed mode and needs no flap protection. |
| D14 | adapter | LB:416 | `grid_gate_open` renders the string `"true"` in an emergency. Harmless today because `is_emergency` is checked first. | Not applicable to the engine (typed bool). |
| D15 | parity | LB:161 | The write script uses the raw `car_aware` helper, the automation uses the validated value. When the car SOC is unknown, the script applies the car minimum to a current the automation computed with the charger minimum. | One validated value. |
| D16 | parity | LB:518 | `round(1)` can push the current above the headroom by up to 0.05 A × V × phases (about 35 W on 3 phases). | Round down. |
| D17 | adapter | LB:441, 483 | An unknown or unavailable mode behaves like Solar with grid 0. | The adapter maps an unknown mode to Off. |
| D18 | adapter | user config | `max_current` reads a charger sensor whose name is close to the applied-limit sensor. If it is a dynamic limit instead of the hardware rating, the current can ratchet down. | The config flow explains which entity to pick. |
| D19 | adapter | LB:305, 572, 598, 617 | No `max_exceeded: silent` on single-mode script and automations. Concurrent calls log warnings. | Not applicable to the engine. |
