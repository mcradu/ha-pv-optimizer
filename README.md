# HA PV Optimizer

Home Assistant OS app repository for PV optimization and official grid-meter data collection.

## Apps

### HA PV Optimizer

`pv_optimizer/` is the safe, explainable PV battery-export optimizer. Version `0.2.6` runs charge and night-injection logic in mandatory shadow mode, exposes an Ingress Web UI, supports a configurable flat export price, and writes diagnostic telemetry to InfluxDB.

See [pv_optimizer/DOCS.md](pv_optimizer/DOCS.md) for configuration and safety details.

### Rețele Electrice Collector

`reteleelectrice_collector/` logs into `contulmeu.reteleelectrice.ro`, downloads the official meter load curves at the portal's maximum available granularity, normalizes WI/WE import/export data, and writes idempotent interval points to InfluxDB. It can auto-discover PODs, perform a first-run backfill, and re-read a rolling window to catch delayed distributor data.

See [reteleelectrice_collector/DOCS.md](reteleelectrice_collector/DOCS.md) for configuration, security, and data-model details.

## Install

1. In Home Assistant, open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/mcradu/ha-pv-optimizer`.
3. Install the app you need from this repository.
