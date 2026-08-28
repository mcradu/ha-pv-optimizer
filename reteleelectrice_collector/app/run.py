#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from influx import InfluxWriter
from normalize import normalize_curve_payload
from portal import ReteleElectricePortal

VERSION = "0.1.0"
OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/state.json")
HTTP_PORT = 8098
LOG = logging.getLogger("reteleelectrice_collector")

DEFAULTS: dict[str, Any] = {
    "username": "",
    "password": "",
    "pod": "",
    "sync_interval_minutes": 360,
    "rolling_days": 7,
    "backfill_days": 365,
    "timezone": "Europe/Bucharest",
    "interval_timestamp": "start",
    "include_reactive": False,
    "influxdb_url": "http://a0d7b954-influxdb:8086",
    "influxdb_database": "home_assistant",
    "influxdb_retention_policy": "one_year",
    "influxdb_measurement": "reteleelectrice_meter_15m",
    "influxdb_username": "",
    "influxdb_password": "",
}

STATUS_LOCK = threading.Lock()
MANUAL_SYNC = threading.Event()
RUNTIME: dict[str, Any] = {
    "version": VERSION,
    "state": "starting",
    "last_error": "",
    "last_sync": None,
    "last_success": None,
    "next_sync": None,
    "sync_mode": None,
    "pods": [],
    "points_written": 0,
    "records_received": 0,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(default)


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def load_options() -> dict[str, Any]:
    options = dict(DEFAULTS)
    options.update(load_json(OPTIONS_PATH, {}))
    options["sync_interval_minutes"] = max(60, int(options["sync_interval_minutes"]))
    options["rolling_days"] = max(1, int(options["rolling_days"]))
    options["backfill_days"] = max(1, min(1095, int(options["backfill_days"])))
    if options["interval_timestamp"] not in {"start", "end"}:
        raise ValueError("interval_timestamp must be 'start' or 'end'")
    return options


def selected_pods(portal: ReteleElectricePortal, pod_option: str) -> list[str]:
    configured = [value.strip() for value in pod_option.split(",") if value.strip()]
    if configured:
        return configured
    return portal.get_pods()


def chunk_dates(start: date, end: date, maximum_days: int = 365):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=maximum_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def sync_once(options: dict[str, Any]) -> dict[str, Any]:
    state = load_json(STATE_PATH, {})
    first_backfill = not bool(state.get("backfill_complete"))
    days = options["backfill_days"] if first_backfill else options["rolling_days"]
    today = datetime.now(ZoneInfo(str(options["timezone"]))).date()
    start = today - timedelta(days=days - 1)
    mode = "backfill" if first_backfill else "rolling"

    portal = ReteleElectricePortal(options["username"], options["password"])
    influx = InfluxWriter(
        options["influxdb_url"],
        options["influxdb_database"],
        options["influxdb_retention_policy"],
        options["influxdb_measurement"],
        options["influxdb_username"],
        options["influxdb_password"],
    )

    total_written = 0
    total_records = 0
    pods: list[str] = []
    try:
        influx.ping()
        portal.login()
        pods = selected_pods(portal, str(options.get("pod", "")))
        LOG.info("Sync mode=%s, pods=%d, range=%s..%s", mode, len(pods), start, today)

        for pod in pods:
            cnp, cui = portal.get_pod_identity(pod)
            for chunk_start, chunk_end in chunk_dates(start, today):
                payload = portal.get_load_curves(pod, cnp, cui, chunk_start, chunk_end)
                total_records += len(payload.get("ListData") or [])
                points = normalize_curve_payload(
                    payload,
                    timezone_name=str(options["timezone"]),
                    interval_timestamp=str(options["interval_timestamp"]),
                    include_reactive=bool(options["include_reactive"]),
                )
                total_written += influx.write_points(points)
                LOG.info(
                    "POD %s: %s..%s -> %d points",
                    pod,
                    chunk_start,
                    chunk_end,
                    len(points),
                )
    finally:
        portal.close()
        influx.close()

    if total_records == 0:
        raise RuntimeError("The portal returned no load-curve records")

    now = utc_now().isoformat()
    state.update(
        {
            "backfill_complete": True,
            "last_success": now,
            "last_mode": mode,
            "last_start": start.isoformat(),
            "last_end": today.isoformat(),
            "last_points_written": total_written,
        }
    )
    save_state(state)
    return {
        "mode": mode,
        "pods": pods,
        "points_written": total_written,
        "records_received": total_records,
        "last_success": now,
    }


def safe_status(options: dict[str, Any]) -> dict[str, Any]:
    with STATUS_LOCK:
        data = dict(RUNTIME)
    data["influx_target"] = (
        f"{options['influxdb_database']}."
        f"{options['influxdb_retention_policy']}."
        f"{options['influxdb_measurement']}"
    )
    data["pod_mode"] = "configured" if str(options.get("pod", "")).strip() else "auto-discover"
    data["rolling_days"] = options["rolling_days"]
    data["backfill_days"] = options["backfill_days"]
    data["interval_timestamp"] = options["interval_timestamp"]
    return data


class StatusHandler(BaseHTTPRequestHandler):
    server_version = "ReteleElectriceCollector/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("HTTP " + fmt, *args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            with STATUS_LOCK:
                state = RUNTIME.get("state", "unknown")
            self._send_json({"status": "ok", "state": state, "version": VERSION})
            return
        if path == "/api/status":
            self._send_json(safe_status(APP_OPTIONS))
            return
        if path in {"/", ""}:
            body = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/sync":
            MANUAL_SYNC.set()
            self._send_json({"accepted": True}, 202)
            return
        self._send_json({"error": "not found"}, 404)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rețele Electrice Collector</title>
<style>
:root{color-scheme:dark;--bg:#10151b;--card:#17212b;--muted:#8ea0b2;--accent:#ff5a00;--ok:#48c78e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#eef3f7;font-family:system-ui,sans-serif}
main{max-width:900px;margin:auto;padding:24px}.head{display:flex;justify-content:space-between;align-items:center;gap:16px}
h1{font-size:24px;margin:0}.badge{padding:6px 10px;border-radius:999px;background:#24313d}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);padding:16px;border-radius:12px}.label{color:var(--muted);font-size:12px;text-transform:uppercase}.value{font-size:20px;margin-top:6px;word-break:break-word}
button{background:var(--accent);border:0;color:white;padding:10px 14px;border-radius:8px;cursor:pointer}pre{white-space:pre-wrap;background:#0b0f13;padding:14px;border-radius:10px;overflow:auto}
</style></head><body><main><div class="head"><div><h1>Rețele Electrice Collector</h1><div class="label">official 15-minute meter data → InfluxDB</div></div><button onclick="syncNow()">Sync now</button></div>
<div class="grid"><div class="card"><div class="label">State</div><div id="state" class="value">—</div></div><div class="card"><div class="label">Last success</div><div id="success" class="value">—</div></div><div class="card"><div class="label">Points written</div><div id="points" class="value">—</div></div><div class="card"><div class="label">Mode</div><div id="mode" class="value">—</div></div></div>
<div class="card"><div class="label">Diagnostics</div><pre id="diag">Loading…</pre></div></main>
<script>
const $=id=>document.getElementById(id);const fmt=v=>v?new Date(v).toLocaleString():'—';
async function refresh(){try{const r=await fetch('api/status',{cache:'no-store'});const s=await r.json();$('state').textContent=s.state;$('success').textContent=fmt(s.last_success);$('points').textContent=s.points_written??0;$('mode').textContent=s.sync_mode||'—';$('diag').textContent=JSON.stringify(s,null,2)}catch(e){$('state').textContent='disconnected'}}
async function syncNow(){await fetch('api/sync',{method:'POST'});setTimeout(refresh,500)}
refresh();setInterval(refresh,5000);
</script></body></html>"""


def scheduler(options: dict[str, Any]) -> None:
    interval = int(options["sync_interval_minutes"]) * 60
    next_run = time.monotonic()
    while True:
        wait = max(0.0, next_run - time.monotonic())
        if wait > 0 and not MANUAL_SYNC.wait(wait):
            pass
        MANUAL_SYNC.clear()
        started = utc_now().isoformat()
        with STATUS_LOCK:
            RUNTIME.update({"state": "syncing", "last_sync": started, "last_error": ""})
        try:
            result = sync_once(options)
            with STATUS_LOCK:
                RUNTIME.update(
                    {
                        "state": "idle",
                        "last_success": result["last_success"],
                        "sync_mode": result["mode"],
                        "pods": result["pods"],
                        "points_written": result["points_written"],
                        "records_received": result["records_received"],
                        "last_error": "",
                    }
                )
        except Exception as exc:
            LOG.exception("Collector sync failed")
            with STATUS_LOCK:
                RUNTIME.update({"state": "error", "last_error": str(exc)})
        next_run = time.monotonic() + interval
        with STATUS_LOCK:
            RUNTIME["next_sync"] = (utc_now() + timedelta(seconds=interval)).isoformat()


def configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


configure_logging()
APP_OPTIONS = load_options()

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), StatusHandler)
    threading.Thread(target=server.serve_forever, name="status-http", daemon=True).start()
    LOG.info("Rețele Electrice Collector %s started on port %d", VERSION, HTTP_PORT)
    scheduler(APP_OPTIONS)
