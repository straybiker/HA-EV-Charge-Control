# Engine

`custom_components/ev_charge_control/engine/` holds the charge controller. It imports nothing from Home Assistant: it takes plain values and returns a decision. The behaviour it implements is specified in [behaviour.md](behaviour.md).

## Modules

| Module | Job |
|---|---|
| `model.py` | Immutable value types: `ChargerSpec`, `CarSpec`, `Settings`, `Measurements`, `Output`, `Budget`, `Available`, `Setpoint`, and the enums `ChargeMode`, `Phase`, `ConnectionState`, `Reason`. |
| `policy.py` | `MODE_POLICY`: one row per mode (grid request, minimum cap, forced phase, phase hold). `resolve_mode()` turns Comfort into Limited or Solar. |
| `budget.py` | Grid gate, EMS rules, grid allowance, the solar-first rule. Returns a `Budget`. |
| `phases.py` | 1 or 3 phases, with the phase hold. |
| `setpoint.py` | Power to amps (nearest charger step, rounded down at the power limit), and the write filter. |
| `limit.py` | The effective power limit: the limit entity's value times the safety factor. |
| `energy.py` | `EnergyCounter`: charged kWh from a meter or integrated power, split into grid and solar. |
| `average.py` | `ChargingAverage`: mean charger power above 1000 W over a rolling 60-day window, kept per day. |
| `controller.py` | `Controller`: the order of rules, plus the state shared between runs (phase hold, grace period, efficiency, unplug timer). |

## API

```python
from custom_components.ev_charge_control.engine import (
    CarSpec,
    ChargerSpec,
    Controller,
    Measurements,
    Settings,
)

controller = Controller(
    ChargerSpec(max_current_a=16), CarSpec(battery_capacity_wh=74000)
)
out = controller.step(settings, measurements, now)
```

- One `Controller` per charger, kept for the life of the config entry.
- `step()` runs one decision. `now` is passed in, so tests control time.
- `available(settings, measurements, now)` returns what the car would get now, as if it were connected and charging, split into solar and grid. It uses the same plan, phase choice and rounding as `step()` and changes no state. For display only.
- `out.reason`, `out.phase`, `out.current_a`, `out.power_w`: the decision.
- `out.setpoint`: what to write, or `None` when nothing changes. The Home Assistant writer performs it.
- `out.budget`, `out.efficiency`, `out.grid_allowed`, `out.emergency`, `out.target_reached`, `out.phase_hold_until`, `out.grace_until`: diagnostics.

## Tests

- `tests/engine/test_controller.py`: one rule per test, including the 13 original golden cases and 10 Comfort cases, each at a 10 kW and a 6 kW power limit.
- `tests/engine/test_limit.py`, `test_energy.py`, `test_average.py`: the power limit and energy metering, with properties (limit never below the base; charged = grid + solar; totals never decrease).
- `tests/engine/test_policy.py`, `test_setpoint.py`: the table, rounding and the write filter.
- `tests/engine/test_properties.py`: invariants checked with `hypothesis` on random inputs: the current is 0 or within range and a whole step; power never exceeds the headroom; Minimum modes never exceed the minimum; more sun never gives less power in Solar mode; EMS at 0 W imports at most half a step from the grid.
- [test-report.md](test-report.md): the latest run of all tests, with the golden cases next to the YAML package.
