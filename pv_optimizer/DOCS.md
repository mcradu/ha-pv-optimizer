# HA PV Optimizer 0.2.3

This release is a safe migration foundation for `pv_night_battery_export.yaml` V5.8.2.

The Charging tab models the battery as a flexible PV-only consumer and produces stabilized shadow requests: `ON`, `OFF`, or `NO ACTION`. It monitors all three grid voltages, battery temperature, SOC, PV production, grid export, remaining forecast, and the projected sunset energy shortfall. It never sets charging power and never writes to the inverter.

Charge evaluations and transitions are stored in `/data/pv_optimizer_charge_telemetry.jsonl`. The file rotates at 5 MB and the previous segment is retained.

## Safety boundary

- `shadow_mode` is required to remain `true` in this release.
- No Home Assistant service call that writes inverter state is implemented.
- UI controls change only the simulated operating mode.
- Missing, stale, or invalid critical entities produce a blocked decision.

## Web UI

The Ingress UI contains Overview, Control, Decision Inspector, Entity Health, and Settings sections. `Night MAX` is simulated for one calculation cycle and automatically returns to `Auto`.

## Reference baseline

- Package SHA-256: `bdb2d4ca214b60aef950fff0e8d3b81762b367988271c5c08ec60c8af14ae6ba`
- Dashboard SHA-256: `8139a7be2f7966f5bfab4b2ede450ffe59ae499f3442307b52efcf1d995a99cf`

The original files are not bundled because Home Assistant runtime configuration remains the source of truth during shadow comparison.
