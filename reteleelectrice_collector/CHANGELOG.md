# Changelog

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
