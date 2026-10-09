# Heating Optimizer design and migration contract

- Home Assistant source: GET `http://supervisor/core/api/states` using the add-on Supervisor token. Read-only, no websocket required.
- PV source: `binary_sensor.pv_optimizer_battery_target_reachable`, `sensor.pv_optimizer_available_solar_headroom`. If unavailable, solar/morning starts are denied. Battery reserve protection uses actual `sensor.ss_battery_soc`.
- Physical sensors: `sensor.sonoff_a48004a295_temperature` (down), `sensor.sonoff_a48004affc_temperature` (up), `sensor.sonoff_1000f209bd_temperature` (puffer), `sensor.sonoff_10008cfa76_temperature` (outdoor).
- AC status: `climate.ac_down`, `climate.ac_up`. Boiler/UFH are monitored through existing switches and smart thermostat, not commanded by this version.
- Time zone: configured IANA name, defaults to Europe/Bucharest. Weekday morning 06:00, weekend 08:00.
- Morning AC: only start with forecast favourable for >=120 seconds and actual battery > reserve. Stop request after >=1800 seconds ON if forecast adverse for >=300 seconds, target reached or preheat energy budget depleted. Hard battery reserve/fault is an immediate stop **recommendation**. Require 1800 seconds minimum OFF before restart.
- Solar AC: independently assess each zone 08:05–22:30 with grid-import/charge headroom and a 23:00 end limit; 1800-second cycle limits, 2-minute delay on non-solar draw.
- Missing or stale input => no new start command; recommendations include a blocker. Timeouts and last-seen timestamps are visible in UI.
- Energy and historical cost figures from the previous YAML sensors are explicitly marked `legacy_observed`; this is not yet source-of-truth financial replacement.
- Shadow simulation keeps its own simulated transitions in `/data/state.json`; the observed AC status remains separate for parity reporting.
- Settings API: validated JSON body, only allow-listed scalar settings + seven weekdays, write by atomic rename.
- Deployment is a normal Home Assistant add-on update and does not restart Home Assistant Core. Existing YAML package is left unchanged until a separate governed cutover.
