# HA PV Optimizer issue board

This board is the project record for defects, technical decisions, and the release or pull request that resolved each item.

## Backlog

| ID | Priority | Item | Acceptance condition |
|---|---:|---|---|
| PV-011 | 3 | Validate `switch.ss_priority_load` | Controlled test proves ON/OFF effect on PV allocation without enabling grid/gen charging |
| PV-012 | 4 | Post-implementation grid analysis | Calculate voltage response per exported kW and tune thresholds/hysteresis |
| PV-013 | 5 | Full V5.8.2 night-export parity | Evening startup, morning catch-up, dynamic load, counters, notifications, TOU restore, and failsafe match the YAML baseline |
| PV-014 | 6 | Editable Web UI configuration | Settings are validated, saved, and visible without editing add-on JSON manually |
| PV-015 | 7 | Safe write layer | Allowlist, readback, retry, timeout, emergency stop, and restore-last-safe-state are implemented |
| PV-016 | 8 | Parallel shadow comparison | Add-on decisions are compared with the YAML automation for representative days and nights |
| PV-017 | 9 | Controlled activation | Real control is enabled and the YAML automation is retired without overlapping writes |

## In progress

| ID | Item | Target release | Pull request |
|---|---|---|---|
| PV-010 | Replace local JSONL telemetry with InfluxDB measurement `pv_optimizer_charge` | 0.2.4 | Pending |

## Resolved

| ID | Problem | Root cause | Resolution | Release / PR |
|---|---|---|---|---|
| PV-001 | Add-on repository and Ingress UI missing | Project existed only as HA YAML/dashboard logic | Added HAOS repository structure, backend, Web UI, tests, and mandatory shadow mode | 0.1.0 / PR #1 |
| PV-002 | All HA entities unavailable | Supervisor token diagnostics were absent | Added safe API diagnostics and visible health state | 0.1.1 / PR #2 |
| PV-003 | Supervisor token remained unavailable | Incorrect assumptions about token exposure | Added token source fallback and API configuration diagnostics | 0.1.2 / PR #3 |
| PV-004 | Token was not passed to Python | Docker command bypassed S6 `with-contenv` | Started Python through the S6 environment wrapper | 0.1.3 / PR #4 |
| PV-005 | Daytime showed false 100% night SOC thresholds | Time to next sunrise was treated as an active night interval | Suppressed inactive thresholds and improved Decision/mobile UI | 0.1.4 / PR #5 |
| PV-006 | No charging visibility or add-on branding | Charge telemetry and HA assets were missing | Added three-phase charge shadow view, icon, and logo | 0.2.0 / PR #6 |
| PV-007 | Runtime JSON dominated Entity Health | Raw diagnostics were always expanded | Moved diagnostics into a collapsed panel | 0.2.1 / PR #7 |
| PV-008 | Redundant entity discovery added to runtime | MCP access was not used broadly enough during development | Removed runtime discovery; development inspection remains external through MCP | 0.2.1 / PR #8 |
| PV-009 | Charge optimizer attempted to recommend watts | Battery was modeled as a controllable power target instead of a flexible load | Replaced watts with stabilized ON/OFF/NO ACTION shadow requests and sunset trajectory | 0.2.3 / PR #9 |

## Board rules

- Every observed problem receives a `PV-NNN` identifier.
- Every code fix links to its pull request and first released version.
- Reopened problems move back to In progress without deleting their history.
- Add-on versions always increase, including rollback or revert releases.
- Runtime hotfixes must be reflected in Git before an item is marked Resolved.
