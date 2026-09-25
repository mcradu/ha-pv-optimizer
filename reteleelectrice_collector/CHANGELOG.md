# Changelog

## 0.2.1

- Add static-definition-only literal candidates around archive keys such as `methodName` and `sParameterName`.
- Restrict candidates to structural or archive-related identifiers and keep this extraction disabled for the live component instance payload.

## 0.2.0

- Add privacy-filtered key/value relations for archive metadata such as `methodName=...` and `sParameterName=...`.
- Only expose relation values that are structural identifiers or archive-related signals; raw PODs, readings, dates, and account identifiers remain excluded.

## 0.1.9

- Add privacy-filtered identifier contexts around archive-related code signals so method names can be associated with nearby parameters and events.
- Keep only approved structural identifiers and archive-related signals; raw component values remain excluded.

## 0.1.8

- Extend the reading-archive diagnostic to inspect the definitions of the related async callback, date, and pagination Aura components.
- Keep each related probe metadata-only and isolate failures per component so one missing definition does not abort the whole diagnostic.

## 0.1.7

- Extend the reading-archive probe with filtered identifier signals from component code and metadata.
- Surface likely reading/index/service method names while keeping the response metadata-only.

## 0.1.6

- Add an authenticated, metadata-only diagnostic probe for the portal's `PED_Reading_Archive_Tab` Aura component.
- Discover component/controller action descriptors without persisting or returning raw account values, meter indexes, CNP/CUI, cookies, or session material.
- Expose the probe from the Home Assistant Ingress page so the real meter-index endpoint can be identified before any collector writes are added.

## 0.1.5

- Extend rolling synchronization back to the day after the newest persisted meter timestamp when an outage gap falls outside the configured rolling window, bounded by `backfill_days`.
- Checkpoint the newest write-acknowledged timestamp after each successful chunk so long catch-up runs resume forward if the 24-hour portal budget interrupts them.
- Stop issuing a redundant InfluxDB read-back after successful writes; write-only collector credentials now use the acknowledged timestamp directly without false verification warnings.
- Keep read-back as a fallback only when a sync has no newly accepted point.

## 0.1.4

- Change the default automatic sync interval to 24 hours and clamp older saved intervals to at least 1440 minutes at runtime.
- Persist a sliding 24-hour `FindOutMeterLoadData` request budget, defaulting to 8 of the portal's 10 allowed requests.
- Reserve quota before each load-curve call so failed requests and crashes still consume the local safety budget.
- Suppress automatic sync after container restart until the configured interval is due.
- Make historical backfill resumable per POD and pause safely when the request budget is exhausted.
- Expose request usage, remaining budget, reset time, and backfill progress in diagnostics.

## 0.1.3

- Preserve the dedicated Rețele Electrice InfluxDB credential as write-only.
- When a batch write succeeds but the optional read-back query is denied, calculate freshness from the newest timestamp acknowledged by the write API.
- Expose whether freshness came from an InfluxDB query or a successful write acknowledgement.
- Keep query failures fatal when no point was successfully accepted.

## 0.1.2

- Change the default InfluxDB endpoint from the retired Home Assistant add-on to the managed NAS instance at `192.168.0.10:8086`.
- Query the newest timestamp actually stored in `reteleelectrice_meter_15m` after every sync.
- Add a configurable five-day stale-data threshold, status-page diagnostics, and a deduplicated Home Assistant persistent notification.
- Keep InfluxDB and portal credentials in Supervisor runtime options; no credentials are added to Git.

## 0.1.1

- Never request the current calendar day from `FindOutMeterLoadData`; the collector now ends each sync at yesterday, matching the portal UI's completed-day behavior.
- Split backfills into conservative 31-day Visualforce requests instead of sending one very large request.
- Stop retrying business POST requests on HTTP 5xx so the first portal failure is surfaced instead of being hidden behind `Max retries exceeded`.
- Report the failing load-curve date range in diagnostics without exposing account identifiers or session material.
- Add regression tests for completed-day windows and 31-day chunking.

## 0.1.0

- Add Salesforce Experience Cloud login without persisting session tokens.
- Auto-discover PODs or accept an explicit comma-separated POD list.
- Fetch `FindOutMeterLoadData` through the Visualforce A4J curve proxy.
- Parse official 15-minute WI/WE load curves and optional QI/QE reactive curves.
- Normalize intervals in Europe/Bucharest with DST-safe UTC timestamps.
- Write idempotent import/export energy and average power points to InfluxDB 1.x.
- Add first-run backfill, rolling re-sync, health endpoint, status page, and manual sync.
