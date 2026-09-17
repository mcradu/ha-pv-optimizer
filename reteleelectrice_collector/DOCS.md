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

After the first successful backfill, every run re-reads the latest `rolling_days` completed days (default 7). Writes are idempotent because InfluxDB uses the same measurement, tags, and timestamp for the same interval. This rolling window also handles delayed publication or corrections by the distributor.

A manual sync can be triggered from the Ingress page.

## Freshness monitoring

After every sync, the collector queries the newest timestamp actually stored in `reteleelectrice_meter_15m`. The status page shows that timestamp, its age, and whether it is fresh.

`stale_after_days` defaults to 5 days. When the newest stored point is older than the threshold, the app creates or updates one persistent Home Assistant notification. The same notification is dismissed automatically after fresh data is confirmed. A successful process run alone is not treated as proof that the destination measurement is current.

## Interval timestamps

The portal returns `Q1...Qn` values and a frequency in minutes. The default `interval_timestamp=start` stores Q1 at the start of the first local interval. Set it to `end` if later validation against settlement/PZU data proves the portal labels each quantity by interval end.

Timestamps are converted from `Europe/Bucharest` to UTC before they are written. The conversion is monotonic across daylight-saving transitions and supports non-96-slot days.

## Security

The collector does not store Salesforce session cookies, ViewState tokens, CNP/CUI values, or passwords in its state file or logs. Authentication/session material lives only in process memory.

Do not paste browser `sid`, ViewState, CSRF, cookies, or copied cURL requests into configuration files.

## Portal compatibility

This is an unofficial collector. It uses the portal's Salesforce Experience Cloud and Visualforce/Aura interfaces. Those interfaces may change without notice. A portal change should fail visibly through the status page and logs rather than silently producing fabricated data.
