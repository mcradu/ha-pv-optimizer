"""Read-only Home Assistant Core state client for the shadow-stage add-on."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HomeAssistantClient:
    def __init__(self, base_url: str = "http://supervisor/core/api", token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else (
            os.getenv("SUPERVISOR_TOKEN") or os.getenv("HASSIO_TOKEN") or ""
        )

    def all_states(self) -> dict:
        if not self.token:
            raise RuntimeError("Supervisor API token is missing")
        request = Request(
            self.base_url + "/states",
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=12) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError("Core API HTTP %s" % exc.code) from exc
        except URLError as exc:
            raise RuntimeError("Core API unavailable: %s" % exc.reason) from exc
        if not isinstance(payload, list):
            raise RuntimeError("Core API /states response is not an array")
        return {
            item["entity_id"]: item
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("entity_id"), str)
        }
