# Reference sources

Paths are relative to this repository. The folders are read-only reference for the conversion. Do not copy files from them without a reason.

## EV Load Balancer (behaviour reference)

GitHub: [straybiker/HA-load-balancer](https://github.com/straybiker/HA-load-balancer). Local: `../EV_Loadbalancer/`.

The YAML package stays the source of truth for behaviour until this integration reaches parity.

| Path | Content |
|---|---|
| `../EV_Loadbalancer/README.md` | Charge modes, decision flow, behaviour matrix, EMS configuration |
| `../EV_Loadbalancer/packages/` | `ev_loadbalancer.yaml` (logic), `ev_loadbalancer_user_config.yaml` (user mapping) |
| `../EV_Loadbalancer/tests/` | Tests for output and trigger logic |
| `../EV_Loadbalancer/dashboards/` | Logic dashboard |

## Live Home Assistant configuration

| Path | Content |
|---|---|
| `../HomeAssistant/packages/ems.yaml` | Capacity tariff model, peak limits, EV reimbursement sensors |
| `../HomeAssistant/packages/ev_loadbalancer.yaml` | Live variant of the load balancer |
| `../HomeAssistant/packages/ev_live_update.yaml` | Charging notification |
| `../HomeAssistant/packages/emhass.yaml` | EMHASS optimiser payload |
| `../HomeAssistant/automations.yaml` | Peak ratchet and monthly reset automations |

The two `ev_loadbalancer.yaml` copies differ. Compare them before the conversion starts.

## Integration patterns

| Path | Content |
|---|---|
| `../IdegisModbus/` | Coordinator, config flow, diagnostics, tests, CI |
| `../alfen_modbus/` | Alfen charger integration and simulator |
| `../HomeAssistant-Knowledgebase/` | Guides and tooling notes |
