# Changelog

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
