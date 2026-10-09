# Changelog

## 0.2.12
- Add an optional read-only forecast comparator in the Charging UI and /api/status.
- Fetch corrected household hourly forecast from the trusted NAS only once per 15 minutes.
- Compare expected/upper load with the existing horizon-to-sunset and static night-load assumptions.
- Missing, stale, low-confidence or incomplete forecasts fail closed; do not affect battery logic.
- Default disabled; no actuation or optimizer decision changes.

## 0.2.11

- Use the last **24 hours** of heater-free household-load observations instead of
  three hours, capturing the normal daytime and overnight load cycle.
- Preserve all observations across the 24-hour window: the previous 720-point
  storage cap silently discarded most of a full day at the default 30s poll.
- Average each observed hourly band first and then average those hourly means
  so one hour with many samples cannot dominate the household baseline.
- Continue excluding AC and underfloor-heating periods and the first three
  minutes after heating; do not confuse temporary compressor consumption with
  the permanent baseload projected until sunset.
- Maintain backward compatibility with stored 180-minute add-on options:
  runtime enforces at least 1440 minutes even when old Supervisor settings remain.
  Diagnostics now include lookback, hourly coverage and oldest sample age.
- New installations use 1440 minutes by default. Existing installations should
  also update the Configuration UI to 1440 for clarity.
- No active inverter controls; the charge optimizer remains in shadow mode.

## 0.2.10

- Replace the all-day instantaneous household load extrapolation with two phases:
  heating draw until the ground-floor room reaches its configured target, then
  the moving average of heater-free household consumption for the remaining
  hours to sunset.
- Keep a three-hour rolling consumption history in add-on state across restarts.
  Exclude AC/underfloor heating periods and the first three minutes after heating.
  Use a configurable 450 W fallback until twelve clean samples exist.
- Read the ground-floor temperature, morning and solar room targets, and
  warming-rate helpers from Home Assistant. Publish projected heating hours,
  household baseline power and daily remaining-load forecast as diagnostics
  and InfluxDB telemetry.
- Preserve sunset battery-charge targets and all inverter actions in shadow mode.
- The Heating Optimizer consumes the revised PV reachability signal and enforces
  30-minute minimum on/off times before starting/stopping the morning AC.

## 0.2.9

- Add configurable `import_price_ron_per_kwh` and publish it as `sensor.pv_optimizer_import_price`.
- Keep both import cash price and export opportunity price in PV Optimizer as the shared economic-price source for downstream optimizers.
- No inverter or load control changes.

## 0.2.8

- Publish the configured `export_price_ron_per_kwh` as read-only Home Assistant sensor `sensor.pv_optimizer_export_price`.
- Let downstream optimizers consume the same live export/opportunity price instead of duplicating economic configuration.
- Keep the change observability-only; no inverter or load control is added.

## 0.2.7

- Calculate battery-safe `available_solar_headroom_kwh` from the remaining PV forecast after expected house load, battery energy needed for the sunset target, charging efficiency, and the configured forecast safety reserve.
- Expose `battery_target_reachable` explicitly alongside projected sunset shortfall.
- Publish read-only Home Assistant entities for solar headroom, projected sunset shortfall, and battery-target reachability so other optimizers can consume one shared energy model.
- Persist the new headroom and reachability fields in `pv_optimizer_charge` telemetry.
- Keep all inverter control in mandatory shadow mode; the new Home Assistant states are observability/interface signals only.


## 0.2.6

- Add `export_price_ron_per_kwh` to the Home Assistant app Configuration UI, defaulting to `0.11` RON/kWh.
- Calculate and display the estimated value of exportable night surplus.
- Persist the configured export price and estimated surplus value in night-injection telemetry.
- Preserve the existing reserve and export-target rules; price is economic context only.

## 0.2.5

- Persist shadow night-injection decisions to `pv_optimizer_night_injection` in InfluxDB.
- Show the latest night-injection samples in the Decision tab.
- Add deduplicated night state, target, SOC threshold, mode, and blocker changes to Recent events.
- Keep night injection and charging in mandatory shadow mode with independent diagnostics.

## 0.2.4

- Replace local JSONL telemetry with direct InfluxDB 1.x line-protocol writes.
- Default to `home_assistant.one_year` and measurement `pv_optimizer_charge`.
- Keep recent Web UI records in memory without maintaining a second local history.
- Surface InfluxDB target and last write error in runtime diagnostics.
- Keep project issue tracking outside the add-on repository in a dedicated companion repository.

## 0.2.3

- Replace charging-power recommendations with binary `ON`, `OFF`, and `NO ACTION` shadow requests.
- Add voltage and PV hysteresis, five-minute stabilization, and minimum state duration.
- Add sunset SOC trajectory and forecast-based catch-up decisions.
- Keep charging power under exclusive inverter/BMS control; grid and generator charging are never requested.
- Persist every charge evaluation and transition as rotating JSONL telemetry.
- Show recent telemetry, determining phase, projected shortfall, and pending transitions in the Web UI.

## 0.2.1

- Collapse raw runtime diagnostics by default on the Entity Health page.

## 0.2.0

- Add a separate shadow-only daytime charge optimizer.
- Use three-phase voltage, available PV export, SOC, battery power, and battery temperature.
- Apply the configured temperature-dependent charging limits.
- Add a dedicated Charging page to the Ingress UI.
- Add Home Assistant add-on icon and logo assets.

## 0.1.4

- Do not calculate or expose active night SOC thresholds during daytime.
- Suppress the misleading `stop_soc_reached` blocker outside the night window.
- Replace raw JSON as the primary Decision view with a readable summary.
- Improve horizontal tab navigation and compact mobile layouts.

## 0.1.3

- Start Python through S6 `with-contenv` so Supervisor variables reach the process.
- Remove unnecessary Supervisor API permission; Core proxy access remains enabled.

## 0.1.2

- Request an explicit Supervisor API token in addition to Core API proxy access.
- Accept the legacy `HASSIO_TOKEN` environment name as a compatibility fallback.
- Report which token source is available without exposing token contents.

## 0.1.1

- Expose Supervisor API diagnostics without exposing the token.
- Log connection failures once per distinct error.
- Show entity-specific errors and runtime diagnostics in the Web UI.

## 0.1.0

- Add Home Assistant app repository metadata.
- Add read-only Supervisor Core API client.
- Add V5.8.2-compatible shadow calculation engine.
- Add persistent cycle state and restart recovery metadata.
- Add responsive Ingress Web UI with simulated controls.
- Add health, status, decision, configuration, and log APIs.
- Add unit tests and secret-safe diagnostics.
