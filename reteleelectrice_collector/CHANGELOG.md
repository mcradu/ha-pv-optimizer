# Changelog

## 0.1.0

- Add Salesforce Experience Cloud login without persisting session tokens.
- Auto-discover PODs or accept an explicit comma-separated POD list.
- Fetch `FindOutMeterLoadData` through the Visualforce A4J curve proxy.
- Parse official 15-minute WI/WE load curves and optional QI/QE reactive curves.
- Normalize intervals in Europe/Bucharest with DST-safe UTC timestamps.
- Write idempotent import/export energy and average power points to InfluxDB 1.x.
- Add first-run backfill, rolling re-sync, health endpoint, status page, and manual sync.
