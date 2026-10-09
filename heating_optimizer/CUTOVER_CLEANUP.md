# Heating Optimizer – 24h switchover and cleanup contract

**Status:** planned. Do not execute any cleanup while add-on 0.1.0 is shadow-only.  
**Deadline:** explicit go/no-go at most 24 hours after the first independently verified, healthy shadow run. If no-go, end evaluation and keep the known-good legacy controller; do not enable an unverified active add-on.

## Rule: one migration and cleanup window, no orphaned control

The active add-on must implement actual climate commands and have passed shadow-parity/replay, safe-stop and rollback tests BEFORE the cutover. A read-only shadow add-on can never be designated production owner of an AC.

Atomic handover steps:

1. Freeze the currently verified Git SHA, capture the active Home Assistant package/dashboard configuration and add-on settings/state, record HA backup reference, existing helper values, and 24h snapshots from InfluxDB. Freeze manual automation changes during this window.
2. Verify a healthy, active-capable add-on build in staging, 30-minute real-device ON/OFF interlocks, fault/SOC guards, stale telemetry, restart persistence, and Beko service calls. Confirm that the thermostat controls UFH and that the boiler/puffer automation remains under its existing owner.
3. Generate a **dependency report** for `heating_optimizer_*` references in the home-platform repository, PV Optimizer code and settings, HA automations.yaml, dashboards, scripts, scenes, entity registry, InfluxDB ingestion configuration, and live state. Actual HA config and registry may contain references not visible in Git.
4. Disable only legacy AC control automations before enabling the active add-on. Prefer a single deployment with an exclusive-owner guard and assert the invariant **old AC controllers OFF XOR new AC controller ON**. Stop the rollout and restore legacy control if ownership is ambiguous.
5. Activate the add-on controller and observe one complete decision path for each zone, without intentionally rapid-cycling a physical compressor. Verify AC operational state, energy balance, morning/solar thresholds and battery reserve, and the ability to restore the previous controller. Retain explicit alerting on repeated cycles shorter than 30 minutes.
6. **In the same approved cutover window**, remove no-longer-used AC control automation definitions and timer/ownership helpers from the Git-managed HA runtime package only if every reference has been migrated. Clean Lovelace widgets/obsolete navigation at the same time. Batch required HA changes into **one** configuration check and **one** controlled HA Core restart (if a restart is needed). The add-on update itself should only restart the add-on.
7. Confirm active state and all referenced entities after restart. Compare HA/Influx telemetry against the backed-up baseline. Mark the migration and cleanup successful together only when zero dangling dashboard references and zero duplicate actuators are observed.
8. If any step fails, roll back exact source SHA, HA backup/config and add-on state as a unit, disable the new actuator owner, and restore the old control path. Do not drop historical data.

## Initial inventory (Git-managed HA package, 2026-10-09)

| Kind | Count | Cleanup scope at controlled cutover |
| --- | ---: | --- |
| Automations | 10 | Eight AC ownership/control automations are candidates for removal after exclusive handover; two battery-anomaly alert/clear automations need independent review and must remain until replaced. |
| HA timers | 7 | Candidates after active add-on takes over persistent ON/OFF timers and cross-AC stabilization; no timer can be removed if a remaining template references it. |
| Input booleans | 8 | Remove obsolete morning/solar ownership flags and duplicate configuration only once their consumers are migrated. Keep any flags still serving observability or dashboards. |
| Input numbers | 34 | Move adjustable settings into the add-on UI; retain only needed compatibility entities until PV Optimizer and finance consumers are updated. |
| Input datetimes | 8 | Seven weekday target times move into the add-on; financial backfill anchor stays until finance reconciliation is complete. |
| Utility meters | 7 | Preserve until daily/weekly/monthly historical financial summaries have a verified independent replacement. |
| Template entities | 91 | Classify into control-only, active dependency and retained telemetry/financial metrics. Not safe for blanket deletion. |
| Standalone Lovelace | 1 | Update/replace `infrastructure/homeassistant/lovelace/heating_optimizer.yaml`, which currently references ~95 unique Heating Optimizer entities; remove the old dashboard only after Ingress offers all required views. |
| InfluxDB history | Historical | **Never delete historical series** as a cleanup side-effect. Keep archive and migration comparison evidence. |

### Eight legacy AC automation IDs to retire upon verified active handover

- `heating_optimizer_ground_floor_ac_morning_start`
- `heating_optimizer_ground_floor_ac_morning_stop`
- `heating_optimizer_dual_zone_ac_solar_start`
- `heating_optimizer_ground_floor_ac_solar_stop`
- `heating_optimizer_ground_floor_ac_solar_release`
- `heating_optimizer_upstairs_ac_solar_stop`
- `heating_optimizer_upstairs_ac_solar_release`
- `heating_optimizer_ac_start_stabilization_track`

**Not in the above removal set:** `heating_optimizer_battery_unexpectedly_idle_alert`, `heating_optimizer_battery_unexpectedly_idle_clear`. Inspect how the battery monitoring/alert path is used before removing it.

### External dependencies found in code – migrate before dropping corresponding HA entities

PV Optimizer's `pv_optimizer/config.yaml` and `pv_optimizer/app/run.py` still require:

- `sensor.heating_optimizer_ground_floor_temperature`
- `input_number.heating_optimizer_ground_floor_morning_target`
- `input_number.heating_optimizer_ground_floor_ac_solar_stop_temperature`
- `input_number.heating_optimizer_ground_floor_morning_warming_rate`
- `input_boolean.heating_optimizer_ground_floor_ac_solar_control_active`
- `binary_sensor.heating_optimizer_ufh_active`

The shadow Heating Optimizer add-on also temporarily reads legacy fault/finance entities:

- `sensor.heating_optimizer_ground_floor_ac_fault_code` and `sensor.heating_optimizer_upstairs_ac_fault_code` as fallback if the Beko fault bitmap cannot be read directly.
- Legacy cost/savings `sensor.heating_optimizer_*` (today/week/month estimates, all-grid benchmark and heating cost) shown on the Ingress Energy tab.

These dependencies **must not be silently removed**. PV Optimizer must read physical thermometers, its own settings/Heating Optimizer shared control contract, and physical UFH state independently before old compatibility sensors disappear. Financial metrics need add-on-owned persistence or an intentionally retained small read-only HA compatibility package. Historical weekly/monthly reports must not reset unexpectedly.

## Retained outside Heating Optimizer ownership

- `climate.ac_down` and `climate.ac_up` (Beko HomeDirect Local integration).
- Physical Sonoff temperature sensors for ground floor, upstairs, outdoors and puffer.
- `climate.smart_thermostat_2` remains authoritative for whole-house UFH; `switch.sonoff_1000f39cf9` is its actuator.
- Existing boiler/puffer control, weather forecast sources, PV Optimizer and Dyness battery sensors.
- Existing InfluxDB history and other project integrations not owned by Heating Optimizer.

## Cleanup definition of done

- Exactly one AC control owner; two-zone active add-on verified on exact SHA.
- All 30-minute protection, SOC critical shutdown, fault/stale input policies tested and documented.
- All retained sensors/dashboards/financial aggregates produce valid fresh data; no missing UI entities.
- Git/runtime configuration reflects actual installed state; no obsolete AC automations or dead timers remain; all references verified.
- Historical InfluxDB data and backup/rollback artifacts intact.
- Rivet records cutover SHA, backup reference, health and the cleanup evidence in the same release.
