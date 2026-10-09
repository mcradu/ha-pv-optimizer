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

1. **Shadow (max 24h):** verify the exact installed SHA and healthy runtime, then start a *single* 24-hour validation window. Compare `recommendations` and actual device transitions against YAML; cover morning preheat, solar zone starts/stops, battery/temperature guards and 30-minute physical dwell. If a natural transition does not occur, exercise it via a tested replay, **not** by artificially cycling the physical AC. At the 24-hour limit issue an explicit **go/no-go** decision; never silently extend shadow for a week.
2. **Parity and readiness:** validate safe HA service calls, exclusive single-controller ownership, stale-telemetry behaviour, Supervisor restart and automatic/manual rollback in an active-capable version. Financial history migration can follow later *if* the old observability entities are intentionally retained; it is not a reason to delay a validated control handoff.
3. **Handoff (go only):** verify backup and rollback; only after a validated active add-on is available, gate/disable the legacy AC *control* automations while retaining necessary observation sensors, and enable exactly one active controller. Do not turn off the existing thermostat, boiler, or UFH fallback. **No-go:** keep legacy YAML active and close the shadow evaluation with explicit blockers. Never turn on the unimplemented active mode of v0.1.0.
4. **Cleanup as part of cutover:** in the same approved handover window, disable and retire the old AC control automations, remove obsolete helpers/timers and replace the old Lovelace dashboard **only after their consumers have migrated**. Keep residual read-only HA compatibility sensors or financial aggregates until PV Optimizer and historical UI no longer need them. Never delete InfluxDB history or thermostat/boiler integrations. Follow [CUTOVER_CLEANUP.md](CUTOVER_CLEANUP.md) as the mandatory dependency audit, ownership, backup and rollback checklist. If the cutover is no-go, do not delete the working YAML controller.

Checks: `python3 -m unittest discover -s heating_optimizer/tests -v`. See `DOCS.md` for the complete data contract.
