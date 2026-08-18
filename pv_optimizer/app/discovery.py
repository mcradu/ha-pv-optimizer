from __future__ import annotations

from typing import Any


DOMAINS = {"select", "switch", "number"}
DEVICE_MARKERS = ("ss_", "sunsynk", "deye")
CONTROL_MARKERS = ("energy_pattern", "energy pattern", "priority", "work_mode", "work mode", "charge", "solar_sell", "solar sell", "export", "prog", "program", "tou")
SAFE_ATTRIBUTES = ("friendly_name", "options", "min", "max", "step", "unit_of_measurement", "device_class")


def control_candidates(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for item in states:
        entity_id = str(item.get("entity_id", ""))
        domain = entity_id.partition(".")[0]
        attributes = item.get("attributes") or {}
        searchable = f"{entity_id} {attributes.get('friendly_name', '')}".lower()
        if domain not in DOMAINS:
            continue
        if not any(marker in searchable for marker in DEVICE_MARKERS):
            continue
        if not any(marker in searchable for marker in CONTROL_MARKERS):
            continue
        candidates.append({
            "entity_id": entity_id,
            "state": item.get("state"),
            "attributes": {key: attributes[key] for key in SAFE_ATTRIBUTES if key in attributes},
        })
    return sorted(candidates, key=lambda candidate: candidate["entity_id"])
