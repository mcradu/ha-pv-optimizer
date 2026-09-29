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

## Reading archive diagnostic

Version 0.1.6 adds a temporary metadata-only probe for `c:PED_Reading_Archive_Tab`, the portal component behind the meter-reading archive. The probe authenticates with the existing account, requests the Aura component definition and instance metadata, and returns only structural dictionary keys, safe Aura/Apex/markup descriptors, and action names. Raw component values are discarded before the HTTP response is built. It does not write meter indexes to InfluxDB and does not call `FindOutMeterLoadData`, so it does not consume the collector's local load-curve request budget.

Use **Probe index archive** on the Ingress page once, then capture only the JSON shown in the Reading archive probe panel. That JSON is designed to exclude POD values, CNP/CUI, meter indexes, passwords, cookies, ViewState, and Aura tokens.

From version 0.3.3 the probe UI reads the HTTP response body as text before attempting JSON parsing. If Ingress or the backend returns HTML/plain text instead of JSON, the panel shows the HTTP status and the first 2000 characters of that raw response so the proxy/backend failure can be diagnosed directly.

Version 0.3.4 intentionally returns the metadata extraction itself to the compact 0.2.1 implementation. The later `static_code_contexts` expansion is removed because the production probe could hold the process busy long enough for the Home Assistant watchdog health request to fail and restart the app.

Version 0.3.5 adds only bounded identifier-token windows around a small set of archive anchors. It does not emit raw code windows and caps the output to 24 contexts, which keeps the diagnostic lightweight while preserving variable names adjacent to `methodName` and `listaParam`.


## Live meter-reading validation

Version 0.3.6 adds a separate **Probe latest meter readings** button. The Reading Archive component metadata identifies the portal service as `RetriveSingleSelf` with parameters `pod`, `startDt`, and `endDt`. The diagnostic uses that contract over a bounded 120-day range and shows a sanitized response in the Ingress UI.

This probe is intentionally **not** a production meter-index feed yet. The portal exposes several register/type codes, and their exact import/export semantics must be confirmed from a real response before a value is labelled as the declarable consumption or production index. No response from this probe is written to InfluxDB.

Once the live register mapping is validated, the supported follow-up is to persist the official cumulative indexes separately from `reteleelectrice_meter_15m` and expose them to Energy Reporting/Home Assistant.

## Security

The collector does not store Salesforce session cookies, ViewState tokens, CNP/CUI values, or passwords in its state file or logs. Authentication/session material lives only in process memory.

Do not paste browser `sid`, ViewState, CSRF, cookies, or copied cURL requests into configuration files.

## Portal compatibility

This is an unofficial collector. It uses the portal's Salesforce Experience Cloud and Visualforce/Aura interfaces. Those interfaces may change without notice. A portal change should fail visibly through the status page and logs rather than silently producing fabricated data.


## 0.3.7 probe fix

The first 0.3.6 live probe showed `A4J response did not contain asyncResponse JSON`. The issue was the request contract, not proof that the archive was empty: the probe was posting `RetriveSingleSelf` through the load-curve Visualforce page with only POD/start/end.

Version 0.3.7 uses the dedicated Reading Archive page, obtains the POD account identity through the already authenticated POD-details flow, sends the full six-parameter Reading Archive request and accepts the additional Salesforce partial-response formats used by that page.

The result remains diagnostic-only. Do not use a register for declaration until a successful live response confirms its meaning.


## Official cumulative meter indexes

Version 0.4.0 promotes the Reading Archive from diagnostic-only to a persisted data source after live validation.

The live archive returned cumulative `EA` and `EAP` registers. Their meaning was cross-checked against the official 15-minute Rețele Electrice curves over multiple complete months:

- `EA` follows summed `import_kwh`, so it is stored as `import_index_kwh`;
- `EAP` follows summed `export_kwh`, so it is stored as `export_index_kwh`.

The default measurement is `reteleelectrice_meter_index`. Each point stores only:

- `import_index_kwh`;
- `export_index_kwh`;
- `measure_date`;
- `reading_type`;
- `meter_serial`;
- `constant`.

The POD remains a tag, matching the 15-minute measurement. Customer personal/company identifiers are not written.

The portal supplies a reading date rather than a time of day, so the InfluxDB timestamp is local midnight on that official reading date. Re-reading the same archive entry is idempotent.

The latest stored official reading is also exposed in collector status. Downstream reporting should display the official reading date prominently: an archive value is an exact index for that date, not an estimate of the physical meter index on a later day.
