# HA PV Optimizer

Home Assistant OS app for safe, explainable PV battery-export optimization.

Version `0.1.0` is deliberately **shadow-only**: it reads Home Assistant entities, reproduces the core V5.8.2 calculations, exposes an Ingress Web UI, and never writes to the inverter.

## Install

1. In Home Assistant, open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/mcradu/ha-pv-optimizer`.
3. Install **HA PV Optimizer**, start it, then select **Open Web UI**.

See [pv_optimizer/DOCS.md](pv_optimizer/DOCS.md) for configuration and safety details.
