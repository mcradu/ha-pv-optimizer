# Heating Optimizer 0.1.0

A separate, **shadow-only** Home Assistant add-on with an Ingress dashboard.

## Install

1. In Home Assistant, add custom repository `https://github.com/mcradu/ha-pv-optimizer` with type **Add-on** if it is not already installed for PV Optimizer.
2. Refresh the add-on store and install **HA Heating Optimizer**.
3. Start the add-on and select **Open Web UI**.
4. Keep the existing `heating_optimizer.yaml` package enabled during the shadow/parity stage.

The app fetches Home Assistant states from the Supervisor's Core API every 30 seconds, uses the physical downstairs/upstairs thermometers and PV Optimizer interface, and displays recommended AC / UFH decisions, why a start or stop would be blocked, minimum-cycle timers, configured morning schedule, battery reserve, and legacy cost/savings metrics. Configuration through the UI is persisted under `/data/settings.json`.

**No actuator writes in 0.1.0.** Neither a request to the API nor a settings change can switch on AC, gas boiler, or underfloor heating. The existing YAML automation remains the sole controller. Set `shadow_mode: true` in the add-on configuration. Disabling it will stop startup rather than engage live control.

## Migration and cutover (NOT YET PERFORMED)

1. **Shadow:** install 0.1.0, compare a week of `recommendations` and source measurements against the active YAML automations, validate morning preheat, upstairs solar, buffer logic, gas economics and safety.
2. **Parity:** migrate weekly/monthly cost aggregation to add-on-owned durable state or InfluxDB without losing historical baselines; implement and regression-test the Home Assistant actuator service calls.
3. **Handoff:** verify backup and rollback; only after a validated active add-on is available, turn off the legacy *control* automations while retaining any necessary observation sensors. Do not turn off the legacy thermostat or boiler actuation without implementing an equivalent.
4. **Remove package:** only when the replacement owns every required raw sensor dependency, all dashboards, and the thermostat/boiler ownership boundaries are verified. This migration is separate from the add-on installation.

Checks: `python3 -m unittest discover -s heating_optimizer/tests -v`. See `DOCS.md` for the complete data contract.
