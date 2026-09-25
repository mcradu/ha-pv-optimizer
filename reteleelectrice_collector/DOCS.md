# Rețele Electrice Collector

This Home Assistant app collects the official meter load curves exposed by `contulmeu.reteleelectrice.ro` and writes them to InfluxDB at the portal's maximum available granularity.

## What it stores

The portal returns four register types. The collector maps them as follows:

- `WI` → `import_kwh`
- `WE` → `export_kwh`
- `QI` → `reactive_inductive_kvarh` when `include_reactive` is enabled
- `QE` → `reactive_capacitive_kvarh` when `include_reactive` is enabled

For active energy it also calculates average interval power:

- `import_avg_kw`
- `export_avg_kw`

The default measurement is `reteleelectrice_meter_15m`. Tags are `pod` and `source=reteleelectrice`.

## Configuration

Set the Rețele Electrice account `username` and `password` in the Home Assistant app configuration. They are stored by Home Assistant Supervisor and are never committed to Git.

`pod` may be left empty. In that case the app discovers PODs after login. To restrict collection, enter one POD or a comma-separated list.

The default InfluxDB target is:

`home_assistant.one_year.reteleelectrice_meter_15m`

The default server is the managed NAS instance at `http://192.168.0.10:8086`. Existing installations keep their saved app options, so verify the endpoint explicitly after an InfluxDB migration. Credentials remain in Home Assistant Supervisor options and must not be committed to Git.

Set the InfluxDB username and password if the local instance requires authentication.

## Synchronization

On the first successful run, the app backfills `backfill_days` (default 365). For reliability the history is requested from the portal in chunks of at most 31 days.

The portal UI treats the current calendar day as incomplete and clamps downloads to the previous day. The collector follows the same rule: every automatic or manual sync ends at **yesterday** in the configured timezone. This avoids requesting an incomplete day from `FindOutMeterLoadData`, which can return HTTP 500.

After the first successful backfill, every run re-reads the latest `rolling_days` completed days (default 7). If the newest persisted meter timestamp is older than that rolling window, the collector automatically extends the request back to the next missing local day, bounded by `backfill_days`. This closes outage gaps such as a collector being offline for longer than the rolling window. Successful catch-up chunks checkpoint their newest accepted timestamp, so a quota-limited catch-up resumes forward instead of restarting from the oldest gap. Writes are idempotent because InfluxDB uses the same measurement, tags, and timestamp for the same interval.

The effective automatic interval is never shorter than 24 hours. Existing installations that still have an older saved value such as 360 minutes are clamped to 1440 minutes at runtime, so upgrading does not require editing Supervisor options first. A container restart does not trigger a fresh sync when the previous attempt is still inside that interval.

The collector maintains a persistent sliding 24-hour request budget for `FindOutMeterLoadData`. The default budget is 8 requests even though the portal limit is 10, leaving two requests of safety margin. Each load-curve request is reserved and persisted before it is sent, so a failed HTTP request or process crash cannot accidentally hide a consumed request. Manual sync uses the same budget.

Backfill is resumable per POD. Each successful 31-day chunk advances a persistent cursor. If the 24-hour request budget is exhausted, the collector stops before the next portal request and continues from the saved cursor on a later run instead of restarting the whole history.

A manual sync can be triggered from the Ingress page, but it cannot bypass the request budget.

## Freshness monitoring

After a successful batch write, the collector uses the newest timestamp accepted by the InfluxDB v1 write API and reports `freshness_source=write_acknowledgement`. It does not perform a redundant read-back when points were just accepted. If a sync has no newly accepted point, it falls back to querying the target measurement.

The dedicated `reteleelectrice` credential can therefore remain write-only during normal collection. This preserves least-privilege access and avoids false read-verification warnings while still detecting stale source data. A failed write never advances freshness state.

`stale_after_days` defaults to 5 days. When the newest stored point is older than the threshold, the app creates or updates one persistent Home Assistant notification. The same notification is dismissed automatically after fresh data is confirmed. A successful process run alone is not treated as proof that the destination measurement is current.

## Interval timestamps

The portal returns `Q1...Qn` values and a frequency in minutes. The default `interval_timestamp=start` stores Q1 at the start of the first local interval. Set it to `end` if later validation against settlement/PZU data proves the portal labels each quantity by interval end.

Timestamps are converted from `Europe/Bucharest` to UTC before they are written. The conversion is monotonic across daylight-saving transitions and supports non-96-slot days.

## Portal API discovery

Version 0.3.0 adds **Discover portal API** to the Ingress page. The discovery operation authenticates normally, then crawls only static Aura component definitions starting from the known PED components used by the collector. It follows newly discovered `markup://c:PED_*` component references recursively, up to 60 component definitions and depth 5.

For each definition it catalogs the component relationship, Apex `ACTION# Rețele Electrice Collector

This Home Assistant app collects the official meter load curves exposed by `contulmeu.reteleelectrice.ro` and writes them to InfluxDB at the portal's maximum available granularity.

## What it stores

The portal returns four register types. The collector maps them as follows:

- `WI` → `import_kwh`
- `WE` → `export_kwh`
- `QI` → `reactive_inductive_kvarh` when `include_reactive` is enabled
- `QE` → `reactive_capacitive_kvarh` when `include_reactive` is enabled

For active energy it also calculates average interval power:

- `import_avg_kw`
- `export_avg_kw`

The default measurement is `reteleelectrice_meter_15m`. Tags are `pod` and `source=reteleelectrice`.

## Configuration

Set the Rețele Electrice account `username` and `password` in the Home Assistant app configuration. They are stored by Home Assistant Supervisor and are never committed to Git.

`pod` may be left empty. In that case the app discovers PODs after login. To restrict collection, enter one POD or a comma-separated list.

The default InfluxDB target is:

`home_assistant.one_year.reteleelectrice_meter_15m`

The default server is the managed NAS instance at `http://192.168.0.10:8086`. Existing installations keep their saved app options, so verify the endpoint explicitly after an InfluxDB migration. Credentials remain in Home Assistant Supervisor options and must not be committed to Git.

Set the InfluxDB username and password if the local instance requires authentication.

## Synchronization

On the first successful run, the app backfills `backfill_days` (default 365). For reliability the history is requested from the portal in chunks of at most 31 days.

The portal UI treats the current calendar day as incomplete and clamps downloads to the previous day. The collector follows the same rule: every automatic or manual sync ends at **yesterday** in the configured timezone. This avoids requesting an incomplete day from `FindOutMeterLoadData`, which can return HTTP 500.

After the first successful backfill, every run re-reads the latest `rolling_days` completed days (default 7). If the newest persisted meter timestamp is older than that rolling window, the collector automatically extends the request back to the next missing local day, bounded by `backfill_days`. This closes outage gaps such as a collector being offline for longer than the rolling window. Successful catch-up chunks checkpoint their newest accepted timestamp, so a quota-limited catch-up resumes forward instead of restarting from the oldest gap. Writes are idempotent because InfluxDB uses the same measurement, tags, and timestamp for the same interval.

The effective automatic interval is never shorter than 24 hours. Existing installations that still have an older saved value such as 360 minutes are clamped to 1440 minutes at runtime, so upgrading does not require editing Supervisor options first. A container restart does not trigger a fresh sync when the previous attempt is still inside that interval.

The collector maintains a persistent sliding 24-hour request budget for `FindOutMeterLoadData`. The default budget is 8 requests even though the portal limit is 10, leaving two requests of safety margin. Each load-curve request is reserved and persisted before it is sent, so a failed HTTP request or process crash cannot accidentally hide a consumed request. Manual sync uses the same budget.

Backfill is resumable per POD. Each successful 31-day chunk advances a persistent cursor. If the 24-hour request budget is exhausted, the collector stops before the next portal request and continues from the saved cursor on a later run instead of restarting the whole history.

A manual sync can be triggered from the Ingress page, but it cannot bypass the request budget.

## Freshness monitoring

After a successful batch write, the collector uses the newest timestamp accepted by the InfluxDB v1 write API and reports `freshness_source=write_acknowledgement`. It does not perform a redundant read-back when points were just accepted. If a sync has no newly accepted point, it falls back to querying the target measurement.

The dedicated `reteleelectrice` credential can therefore remain write-only during normal collection. This preserves least-privilege access and avoids false read-verification warnings while still detecting stale source data. A failed write never advances freshness state.

`stale_after_days` defaults to 5 days. When the newest stored point is older than the threshold, the app creates or updates one persistent Home Assistant notification. The same notification is dismissed automatically after fresh data is confirmed. A successful process run alone is not treated as proof that the destination measurement is current.

## Interval timestamps

The portal returns `Q1...Qn` values and a frequency in minutes. The default `interval_timestamp=start` stores Q1 at the start of the first local interval. Set it to `end` if later validation against settlement/PZU data proves the portal labels each quantity by interval end.

Timestamps are converted from `Europe/Bucharest` to UTC before they are written. The conversion is monotonic across daylight-saving transitions and supports non-96-slot days.

 descriptors/controllers, PED-related identifier signals, Visualforce-like candidates, safe key/value relations, literal candidates, and sanitized static code contexts. Errors are isolated per component, and the response states whether the crawl hit its component limit.

Discovery is read-only metadata inspection. It does **not** instantiate discovered components, invoke discovered Apex/business methods, call the Visualforce load-curve proxy, or write to InfluxDB. Therefore it does not consume the collector's local `FindOutMeterLoadData` request budget.

The resulting JSON is intended for offline filtering of the portal's exposed frontend surface. It is a catalog of what the authenticated frontend reveals, not a guarantee that Salesforce exposes a complete server-side API registry.

## Reading archive diagnostic

Version 0.1.6 adds a temporary metadata-only probe for `c:PED_Reading_Archive_Tab`, the portal component behind the meter-reading archive. The probe authenticates with the existing account, requests the Aura component definition and instance metadata, and returns only structural dictionary keys, safe Aura/Apex/markup descriptors, and action names. Raw component values are discarded before the HTTP response is built. It does not write meter indexes to InfluxDB and does not call `FindOutMeterLoadData`, so it does not consume the collector's local load-curve request budget.

Use **Probe index archive** on the Ingress page once, then capture only the JSON shown in the Reading archive probe panel. That JSON is designed to exclude POD values, CNP/CUI, meter indexes, passwords, cookies, ViewState, and Aura tokens.

## Security

The collector does not store Salesforce session cookies, ViewState tokens, CNP/CUI values, or passwords in its state file or logs. Authentication/session material lives only in process memory.

Do not paste browser `sid`, ViewState, CSRF, cookies, or copied cURL requests into configuration files.

## Portal compatibility

This is an unofficial collector. It uses the portal's Salesforce Experience Cloud and Visualforce/Aura interfaces. Those interfaces may change without notice. A portal change should fail visibly through the status page and logs rather than silently producing fabricated data.
