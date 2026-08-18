from __future__ import annotations

import base64
from collections import deque
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InfluxTelemetry:
    def __init__(self, options: dict[str, Any], recent_limit: int = 500, measurement_option: str = "influxdb_measurement", default_measurement: str = "pv_optimizer_charge") -> None:
        self.enabled = bool(options.get("influxdb_enabled", True))
        self.url = str(options.get("influxdb_url", "")).rstrip("/")
        self.database = str(options.get("influxdb_database", "home_assistant"))
        self.retention_policy = str(options.get("influxdb_retention_policy", "one_year"))
        self.measurement = str(options.get(measurement_option, default_measurement))
        self.username = str(options.get("influxdb_username", ""))
        self.password = str(options.get("influxdb_password", ""))
        self.recent = deque(maxlen=recent_limit)
        self.last_error = ""

    def append(self, record: dict[str, Any]) -> None:
        self.recent.append(record)
        if not self.enabled:
            self.last_error = "InfluxDB telemetry is disabled"
            return
        try:
            self._write(record)
            self.last_error = ""
        except RuntimeError as exc:
            self.last_error = str(exc)

    def latest(self, limit: int = 100) -> list[dict]:
        return list(self.recent)[-max(1, min(limit, self.recent.maxlen or 500)):]

    def _write(self, record: dict[str, Any]) -> None:
        if not self.url:
            raise RuntimeError("InfluxDB URL is missing")
        tag_names = ("request", "desired", "state", "determining_phase", "mode", "shadow")
        tags = {key: record[key] for key in tag_names if record.get(key) not in (None, "")}
        tags.setdefault("shadow", "true")
        excluded = {"timestamp", "reason", "blockers", *tag_names}
        fields = {key: value for key, value in record.items() if key not in excluded}
        fields["reason"] = record.get("reason", "")
        fields["blockers"] = ",".join(record.get("blockers", []))
        line = _line_protocol(self.measurement, tags, fields, record.get("timestamp"))
        query = urlencode({"db": self.database, "rp": self.retention_policy, "precision": "ns"})
        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if self.username or self.password:
            credentials = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        request = Request(f"{self.url}/write?{query}", data=line.encode(), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                if response.status not in (200, 204):
                    raise RuntimeError(f"InfluxDB returned HTTP {response.status}")
        except HTTPError as exc:
            raise RuntimeError(f"InfluxDB returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"InfluxDB connection failed: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"InfluxDB connection failed: {exc}") from exc


def _escape_tag(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def _field(value: Any) -> str | None:
    if value is None or value in ("unknown", "unavailable", ""):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    try:
        return str(float(value))
    except (TypeError, ValueError):
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        return f'"{escaped}"'


def _line_protocol(measurement: str, tags: dict, fields: dict, timestamp: str | None) -> str:
    tag_set = ",".join(f"{_escape_tag(key)}={_escape_tag(value)}" for key, value in tags.items())
    field_set = ",".join(f"{_escape_tag(key)}={encoded}" for key, value in fields.items() if (encoded := _field(value)) is not None)
    if not field_set:
        field_set = "valid=false"
    instant = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")) if timestamp else datetime.now().astimezone()
    nanoseconds = int(instant.timestamp() * 1_000_000_000)
    return f"{_escape_tag(measurement)},{tag_set} {field_set} {nanoseconds}"
