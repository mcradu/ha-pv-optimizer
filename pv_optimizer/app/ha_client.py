from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HomeAssistantClient:
    def __init__(self, base_url: str = "http://supervisor/core/api") -> None:
        self.base_url = base_url.rstrip("/")
        self.token_source = ""
        self.token = os.getenv("SUPERVISOR_TOKEN", "")
        if self.token:
            self.token_source = "SUPERVISOR_TOKEN"
        else:
            self.token = os.getenv("HASSIO_TOKEN", "")
            if self.token:
                self.token_source = "HASSIO_TOKEN"

    def get_state(self, entity_id: str) -> dict:
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is unavailable")
        req = Request(
            f"{self.base_url}/states/{entity_id}",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=8) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"HA returned HTTP {exc.code} for {entity_id}") from exc
        except URLError as exc:
            raise RuntimeError(f"HA connection failed for {entity_id}: {exc.reason}") from exc
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return payload

    def get_states(self) -> list[dict]:
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is unavailable")
        req = Request(
            f"{self.base_url}/states",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=12) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"HA returned HTTP {exc.code} while discovering entities") from exc
        except URLError as exc:
            raise RuntimeError(f"HA discovery connection failed: {exc.reason}") from exc
        if not isinstance(payload, list):
            raise RuntimeError("HA entity discovery returned an invalid response")
        return payload
