# HA PV Optimizer 0.2.9

This release is a safe migration foundation for `pv_night_battery_export.yaml` V5.8.2.

The Charging tab models the battery as a flexible PV-only consumer and produces stabilized shadow requests: `ON`, `OFF`, or `NO ACTION`. It monitors all three grid voltages, battery temperature, SOC, PV production, grid export, remaining forecast, and the projected sunset energy shortfall. It never sets charging power and never writes to the inverter.

The Decision tab shows the current shadow night-injection decision and the latest in-memory samples. The same samples are stored in InfluxDB under `pv_optimizer_night_injection`; charging remains in `pv_optimizer_charge`. Recent events record only meaningful night-decision changes, while InfluxDB receives every evaluation cycle.

`export_price_ron_per_kwh` sets the export/injection opportunity price and `import_price_ron_per_kwh` sets the grid import cash price in RON/kWh from the app Configuration UI. The defaults are `0.11` and `1.36463`. PV Optimizer publishes them as `sensor.pv_optimizer_export_price` and `sensor.pv_optimizer_import_price` so downstream economic models use one shared price source. Changing either price does not alter the energy-reserve or export-power rules.

Charge evaluations and transitions are written to InfluxDB measurement `pv_optimizer_charge`. The default target is `home_assistant.one_year`; URL and credentials are configured in the add-on options. The most recent records remain in memory only for the Web UI.

Version 0.2.9 publishes a small read-only Home Assistant energy/economic interface for consumers such as Heating Optimizer:

- `sensor.pv_optimizer_export_price` — configured export/opportunity price in RON/kWh, sourced directly from PV Optimizer options.
- `sensor.pv_optimizer_import_price` — configured grid-import cash price in RON/kWh, sourced directly from PV Optimizer options.
- `sensor.pv_optimizer_available_solar_headroom` — forecast energy that can be consumed before sunset after estimated house load, battery energy still needed to reach the sunset SOC target, charging efficiency, and `forecast_safety_kwh` are reserved.
- `sensor.pv_optimizer_projected_sunset_shortfall` — remaining projected battery energy shortfall at sunset in kWh.
- `binary_sensor.pv_optimizer_battery_target_reachable` — `on` when the configured sunset SOC target is already reached or forecast energy is sufficient to reach it after the safety reserve.

These entities are derived signals only. They do not command the inverter or any load.

## Safety boundary

- `shadow_mode` is required to remain `true` in this release.
- No Home Assistant service call that writes inverter state is implemented.
- UI controls change only the simulated operating mode.
- Missing, stale, or invalid critical entities produce a blocked decision.

## Web UI

The Ingress UI contains Overview, Control, Decision Inspector, Entity Health, and Settings sections. `Night MAX` is simulated for one calculation cycle and automatically returns to `Auto`.

## House load baseline for battery charging (v0.2.11)

PV Optimizer separates active downstairs AC heating from normal household draw
when forecasting sunset battery charge. The compressor's current consumption
is projected only for the estimated period until the room reaches its target.
The remaining hours until sunset use the normal household baseline, built
from **the previous 24 hours** of non-heating load samples.

Sampling details:
- Observe total household load as PV + battery + grid power under the existing
  signed inverter conventions.
- Exclude observations while the downstairs/upstairs AC or underfloor heating
  is active, and for 180 seconds afterwards. This avoids counting the
  compressor as a persistent baseload.
- Retain all eligible observations from the previous rolling 24-hour window.
  At the default 30-second poll, up to ~2,880 observations may be needed.
- Compute one mean for each observed hourly band, then weight each available
  band equally in the 24-hour aggregate. Missing hours do not have invented
  observations: diagnostics show the actual count of covered hours.
- Until there are twelve eligible observations, fall back to 450 W.
- The sample archive is stored under /data in the add-on state and survives
  restarts; filling a complete 24-hour history after first installation
  naturally takes up to a day. Heater-free periods may cover fewer than
  24 hourly bands if heating runs continuously.
- Existing add-ons can retain 180 minutes in Supervisor's stored configuration;
  v0.2.11 enforces an effective minimum of 1440 minutes anyway. Update the
  displayed Configuration option to 1440 for consistency.

The model does **not** assume instantaneous AC draw remains constant all the
way to sunset. The energy interface still supplies the sunset SOC reachability
signal to Heating Optimizer.

## Reference baseline

- Package SHA-256: `bdb2d4ca214b60aef950fff0e8d3b81762b367988271c5c08ec60c8af14ae6ba`
- Dashboard SHA-256: `8139a7be2f7966f5bfab4b2ede450ffe59ae499f3442307b52efcf1d995a99cf`

The original files are not bundled because Home Assistant runtime configuration remains the source of truth during shadow comparison.


## Corrected household load forecast (0.2.12; optional observation only)

The Charge tab can display the forecast loaded from the NAS energy-load-corrector
\`/api/v1/forecast\` read-only API. Defaults: \`load_forecast_shadow_enabled=false\`,
\`load_forecast_shadow_url=http://192.168.0.10:8100/api/v1/forecast\`.
Enable only after the NAS forecast service is installed and exposed on a trusted
LAN IP (never public). The reader fetches at most once per 15 minutes with a
3-second timeout; invalid/stale, missing-hour or low-confidence forecasts
are unavailable rather than substituted with zero. Daytime P50 and the
uncalibrated upper band are compared with the current charge-engine
\`expected_house_load_kwh\` until sunset. After sunset the model P50 is
compared with the existing \`static_night_load_w\` assumption until sunrise.
Diagnostics and Charging UI show the comparison.

No decisions, SOC thresholds, export power, charge requests or sensor
publishing are changed by this feature. It is observation-only even if the
main add-on's \`shadow_mode\` were later changed; any future switch-over
requires a separate reviewed PR and validation. Model backtest is preliminary.

The comparison fields are also appended to existing `pv_optimizer_charge` InfluxDB telemetry on every evaluation when available; `load_forecast_shadow_available` marks absent data without fabricating kWh. These historical snapshots support a 24-hour shadow review. Each row remains read-only decision evidence and does not alter the charge engine.
