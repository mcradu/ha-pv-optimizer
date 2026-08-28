from __future__ import annotations

import math
from typing import Any, Iterable
from urllib.parse import urljoin

import requests


class InfluxError(RuntimeError):
    pass


def _escape_measurement(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(" ", "\\ ")


def _escape_tag(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace("=", "\\=")
        .replace(" ", "\\ ")
    )


def _field_value(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}i"
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return repr(value)
    return None


def point_to_line(measurement: str, point: dict[str, Any]) -> str | None:
    pod = str(point.get("pod") or "unknown")
    tags = f"pod={_escape_tag(pod)},source=reteleelectrice"
    fields: list[str] = []
    for key in (
        "import_kwh",
        "export_kwh",
        "import_avg_kw",
        "export_avg_kw",
        "reactive_inductive_kvarh",
        "reactive_capacitive_kvarh",
        "slot",
        "frequency_min",
    ):
        if key not in point:
            continue
        encoded = _field_value(point[key])
        if encoded is not None:
            fields.append(f"{key}={encoded}")
    if not fields:
        return None
    return f"{_escape_measurement(measurement)},{tags} {','.join(fields)} {int(point['timestamp'])}"


class InfluxWriter:
    def __init__(
        self,
        url: str,
        database: str,
        retention_policy: str,
        measurement: str,
        username: str = "",
        password: str = "",
        timeout: int = 30,
    ) -> None:
        self.url = url.rstrip("/") + "/"
        self.database = database
        self.retention_policy = retention_policy
        self.measurement = measurement
        self.timeout = timeout
        self.auth = (username, password) if username else None
        self.session = requests.Session()

    def close(self) -> None:
        self.session.close()

    def ping(self) -> None:
        response = self.session.get(urljoin(self.url, "ping"), auth=self.auth, timeout=self.timeout)
        if response.status_code not in (200, 204):
            raise InfluxError(f"InfluxDB ping failed with HTTP {response.status_code}")

    def write_points(self, points: Iterable[dict[str, Any]], batch_size: int = 5000) -> int:
        lines = [line for point in points if (line := point_to_line(self.measurement, point))]
        written = 0
        for offset in range(0, len(lines), batch_size):
            batch = lines[offset : offset + batch_size]
            params = {"db": self.database, "precision": "s"}
            if self.retention_policy:
                params["rp"] = self.retention_policy
            response = self.session.post(
                urljoin(self.url, "write"),
                params=params,
                data="\n".join(batch).encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
                auth=self.auth,
                timeout=self.timeout,
            )
            if response.status_code not in (200, 204):
                detail = response.text[:300].strip()
                raise InfluxError(
                    f"InfluxDB write failed with HTTP {response.status_code}: {detail}"
                )
            written += len(batch)
        return written
