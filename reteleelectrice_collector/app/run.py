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

import requests

from influx import InfluxError, InfluxWriter
from normalize import normalize_curve_payload
from portal import ReteleElectricePortal

VERSION = "0.1.4"
OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/state.json")
HTTP_PORT = 8098
PORTAL_MAX_CHUNK_DAYS = 31
PORTAL_REQUEST_WINDOW = timedelta(hours=24)
HA_API_URL = "http://supervisor/core/api/services/persistent_notification"
STALE_NOTIFICATION_ID = "reteleelectrice_collector_data_stale"
LOG = logging.getLogger("reteleelectrice_collector")

DEFAULTS: dict[str, Any] = {
    "username": "",
    "password": "",
    "pod": "",
    "sync_interval_minutes": 1440,
    "rolling_days": 7,
    "backfill_days": 365,
    "timezone": "Europe/Bucharest",
    "interval_timestamp": "start",
    "include_reactive": False,
    "influxdb_url": "http://192.168.0.10:8086",
    "influxdb_database": "home_assistant",
    "influxdb_retention_policy": "one_year",
    "influxdb_measurement": "reteleelectrice_meter_15m",
    "influxdb_username": "",
    "influxdb_password": "",
    "stale_after_days": 5,
    "portal_request_limit_24h": 8,
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
    "latest_data_timestamp": None,
    "data_age_days": None,
    "data_fresh": None,
    "freshness_source": None,
    "freshness_query_error": "",
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
    options["sync_interval_minutes"] = max(1440, int(options["sync_interval_minutes"]))
    options["rolling_days"] = max(1, int(options["rolling_days"]))
    options["backfill_days"] = max(1, min(1095, int(options["backfill_days"])))
    options["stale_after_days"] = max(1, min(30, int(options["stale_after_days"])))
    options["portal_request_limit_24h"] = max(1, min(10, int(options["portal_request_limit_24h"])))
    if options["interval_timestamp"] not in {"start", "end"}:
        raise ValueError("interval_timestamp must be 'start' or 'end'")
    return options


class PortalRateLimitError(RuntimeError):
    pass


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def portal_request_status(
    state: dict[str, Any],
    limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    cutoff = current - PORTAL_REQUEST_WINDOW
    retained: list[datetime] = []
    for value in state.get("portal_request_history", []):
        parsed = _parse_utc(str(value))
        if parsed is not None and cutoff < parsed <= current:
            retained.append(parsed)
    retained.sort()
    history = [item.isoformat() for item in retained]
    remaining = max(0, limit - len(history))
    reset_at = (
        (retained[0] + PORTAL_REQUEST_WINDOW).isoformat()
        if retained and remaining == 0
        else None
    )
    return {
        "portal_request_history": history,
        "portal_requests_24h": len(history),
        "portal_requests_remaining": remaining,
        "portal_request_limit_24h": limit,
        "portal_limit_reset_at": reset_at,
    }


def reserve_portal_request(
    state: dict[str, Any],
    limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    status = portal_request_status(state, limit, current)
    if status["portal_requests_remaining"] <= 0:
        state.update(status)
        save_state(state)
        raise PortalRateLimitError(
            f"Portal request budget exhausted: {status['portal_requests_24h']}/{limit} "
            f"in the last 24h; next slot at {status['portal_limit_reset_at']}"
        )
    history = list(status["portal_request_history"])
    history.append(current.isoformat())
    state["portal_request_history"] = history
    status = portal_request_status(state, limit, current)
    state.update(status)
    save_state(state)
    return status


def seconds_until_scheduled_sync(
    state: dict[str, Any],
    interval_minutes: int,
    now: datetime | None = None,
) -> float:
    current = (now or utc_now()).astimezone(timezone.utc)
    anchor = _parse_utc(state.get("last_sync_attempt") or state.get("last_success"))
    if anchor is None:
        return 0.0
    due_at = anchor + timedelta(minutes=interval_minutes)
    return max(0.0, (due_at - current).total_seconds())


def backfill_start_for_pod(
    state: dict[str, Any],
    pod: str,
    default_start: date,
    end: date,
) -> date:
    cursors = state.get("backfill_cursor_by_pod") or {}
    raw = cursors.get(pod)
    if not raw:
        return default_start
    try:
        cursor = date.fromisoformat(str(raw))
    except ValueError:
        return default_start
    return min(max(default_start, cursor), end + timedelta(days=1))


def data_freshness(
    latest_timestamp: str | None,
    stale_after_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not latest_timestamp:
        return {"latest_data_timestamp": None, "data_age_days": None, "data_fresh": False}
    latest = datetime.fromisoformat(latest_timestamp.replace("Z", "+00:00"))
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    current = now or utc_now()
    age_seconds = max(0.0, (current - latest.astimezone(timezone.utc)).total_seconds())
    return {
        "latest_data_timestamp": latest.astimezone(timezone.utc).isoformat(),
        "data_age_days": round(age_seconds / 86400, 2),
        "data_fresh": age_seconds <= stale_after_days * 86400,
    }


def call_persistent_notification(service: str, payload: dict[str, Any]) -> bool:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        LOG.warning("SUPERVISOR_TOKEN is unavailable; Home Assistant notification skipped")
        return False
    try:
        response = requests.post(
            f"{HA_API_URL}/{service}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=10,
        )
        if response.status_code not in (200, 201):
            LOG.warning(
                "Home Assistant notification %s failed with HTTP %d: %s",
                service,
                response.status_code,
                response.text[:200].strip(),
            )
            return False
        return True
    except requests.RequestException as exc:
        LOG.warning("Home Assistant notification %s failed: %s", service, exc)
        return False


def update_stale_notification(freshness: dict[str, Any], stale_after_days: int) -> None:
    if freshness["data_fresh"]:
        call_persistent_notification(
            "dismiss", {"notification_id": STALE_NOTIFICATION_ID}
        )
        return
    latest = freshness["latest_data_timestamp"] or "necunoscut"
    age = freshness["data_age_days"]
    age_text = f"{age:.2f} zile" if isinstance(age, (int, float)) else "necunoscută"
    call_persistent_notification(
        "create",
        {
            "notification_id": STALE_NOTIFICATION_ID,
            "title": "Date Rețele Electrice neactualizate",
            "message": (
                f"Measurement-ul reteleelectrice_meter_15m nu are date mai noi de "
                f"{stale_after_days} zile. Ultimul punct: {latest}; vechime: {age_text}. "
                "Verifică Rețele Electrice Collector și conexiunea către InfluxDB."
            ),
        },
    )


def resolve_latest_timestamp(
    influx: InfluxWriter,
    latest_accepted_epoch: int | None,
) -> tuple[datetime, str, str]:
    try:
        latest = influx.latest_timestamp()
        if latest is not None:
            return latest, "influx_query", ""
    except InfluxError as exc:
        if latest_accepted_epoch is None:
            raise
        LOG.warning(
            "InfluxDB read verification unavailable after successful write; "
            "using the newest timestamp accepted by the write API: %s",
            exc,
        )
        return (
            datetime.fromtimestamp(latest_accepted_epoch, tz=timezone.utc),
            "write_acknowledgement",
            str(exc),
        )

    if latest_accepted_epoch is None:
        raise RuntimeError("InfluxDB target measurement has no points after sync")
    LOG.warning(
        "InfluxDB latest-point query returned no series after a successful write; "
        "using the newest timestamp accepted by the write API"
    )
    return (
        datetime.fromtimestamp(latest_accepted_epoch, tz=timezone.utc),
        "write_acknowledgement",
        "latest-point query returned no series",
    )


def selected_pods(portal: ReteleElectricePortal, pod_option: str) -> list[str]:
    configured = [value.strip() for value in pod_option.split(",") if value.strip()]
    if configured:
        return configured
    return portal.get_pods()


def chunk_dates(start: date, end: date, maximum_days: int = PORTAL_MAX_CHUNK_DAYS):
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=maximum_days - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def sync_window(options: dict[str, Any], state: dict[str, Any], today: date) -> tuple[date, date, str]:
    first_backfill = not bool(state.get("backfill_complete"))
    days = options["backfill_days"] if first_backfill else options["rolling_days"]

    # The portal UI itself clamps curve downloads to the latest completed day.
    # Asking FindOutMeterLoadData for the current date can produce an HTTP 500.
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    mode = "backfill" if first_backfill else "rolling"
    return start, end, mode


def sync_once(options: dict[str, Any]) -> dict[str, Any]:
    state = load_json(STATE_PATH, {})
    attempt_started = utc_now()
    state["last_sync_attempt"] = attempt_started.isoformat()
    limit = int(options["portal_request_limit_24h"])
    state.update(portal_request_status(state, limit, attempt_started))
    save_state(state)

    today = datetime.now(ZoneInfo(str(options["timezone"]))).date()
    start, end, mode = sync_window(options, state, today)

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
    latest_data_timestamp: str | None = None
    latest_accepted_epoch: int | None = None
    freshness_source = ""
    freshness_query_error = ""
    try:
        influx.ping()
        portal.login()
        pods = selected_pods(portal, str(options.get("pod", "")))
        LOG.info("Sync mode=%s, pods=%d, range=%s..%s", mode, len(pods), start, end)

        for pod in pods:
            pod_start = (
                backfill_start_for_pod(state, pod, start, end)
                if mode == "backfill"
                else start
            )
            if pod_start > end:
                continue

            cnp, cui = portal.get_pod_identity(pod)
            for chunk_start, chunk_end in chunk_dates(pod_start, end):
                budget = reserve_portal_request(state, limit)
                LOG.info(
                    "Portal request budget before load-curve call: used=%d remaining=%d limit=%d",
                    budget["portal_requests_24h"],
                    budget["portal_requests_remaining"],
                    limit,
                )
                payload = portal.get_load_curves(pod, cnp, cui, chunk_start, chunk_end)
                total_records += len(payload.get("ListData") or [])
                points = normalize_curve_payload(
                    payload,
                    timezone_name=str(options["timezone"]),
                    interval_timestamp=str(options["interval_timestamp"]),
                    include_reactive=bool(options["include_reactive"]),
                )
                written = influx.write_points(points)
                total_written += written
                if written:
                    point_timestamps = [
                        int(point["timestamp"])
                        for point in points
                        if point.get("timestamp") is not None
                    ]
                    if point_timestamps:
                        newest = max(point_timestamps)
                        latest_accepted_epoch = max(
                            latest_accepted_epoch or newest,
                            newest,
                        )
                if mode == "backfill":
                    cursors = dict(state.get("backfill_cursor_by_pod") or {})
                    cursors[pod] = (chunk_end + timedelta(days=1)).isoformat()
                    state["backfill_cursor_by_pod"] = cursors
                    save_state(state)
                LOG.info(
                    "POD %s: %s..%s -> %d points",
                    pod,
                    chunk_start,
                    chunk_end,
                    len(points),
                )

        latest, freshness_source, freshness_query_error = resolve_latest_timestamp(
            influx,
            latest_accepted_epoch,
        )
        latest_data_timestamp = latest.isoformat()
    finally:
        portal.close()
        influx.close()

    if total_records == 0:
        raise RuntimeError("The portal returned no load-curve records")

    backfill_complete = bool(state.get("backfill_complete"))
    if mode == "backfill":
        cursors = state.get("backfill_cursor_by_pod") or {}
        backfill_complete = bool(pods) and all(
            backfill_start_for_pod(
                {"backfill_cursor_by_pod": cursors},
                pod,
                start,
                end,
            ) > end
            for pod in pods
        )

    now_dt = utc_now()
    now = now_dt.isoformat()
    freshness = data_freshness(
        latest_data_timestamp,
        int(options["stale_after_days"]),
        now=now_dt,
    )
    state.update(
        {
            "backfill_complete": backfill_complete,
            "last_success": now,
            "last_mode": mode,
            "last_start": start.isoformat(),
            "last_end": end.isoformat(),
            "last_points_written": total_written,
            "freshness_source": freshness_source,
            "freshness_query_error": freshness_query_error,
            **portal_request_status(state, limit, now_dt),
            **freshness,
        }
    )
    save_state(state)
    return {
        "mode": mode,
        "pods": pods,
        "points_written": total_written,
        "records_received": total_records,
        "last_success": now,
        "backfill_complete": backfill_complete,
        "freshness_source": freshness_source,
        "freshness_query_error": freshness_query_error,
        **portal_request_status(state, limit, now_dt),
        **freshness,
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
    data["portal_chunk_days"] = PORTAL_MAX_CHUNK_DAYS
    data["latest_day_policy"] = "yesterday"
    data["stale_after_days"] = options["stale_after_days"]
    persisted = load_json(STATE_PATH, {})
    data.update(
        portal_request_status(
            persisted,
            int(options["portal_request_limit_24h"]),
        )
    )
    data["effective_sync_interval_minutes"] = options["sync_interval_minutes"]
    data["backfill_complete"] = bool(persisted.get("backfill_complete"))
    data["backfill_cursor_by_pod"] = persisted.get("backfill_cursor_by_pod", {})
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
<div class="grid"><div class="card"><div class="label">State</div><div id="state" class="value">—</div></div><div class="card"><div class="label">Last success</div><div id="success" class="value">—</div></div><div class="card"><div class="label">Latest data</div><div id="latest" class="value">—</div></div><div class="card"><div class="label">Data age</div><div id="age" class="value">—</div></div><div class="card"><div class="label">Points written</div><div id="points" class="value">—</div></div><div class="card"><div class="label">Mode</div><div id="mode" class="value">—</div></div></div>
<div class="card"><div class="label">Diagnostics</div><pre id="diag">Loading…</pre></div></main>
<script>
const $=id=>document.getElementById(id);const fmt=v=>v?new Date(v).toLocaleString():'—';
async function refresh(){try{const r=await fetch('api/status',{cache:'no-store'});const s=await r.json();$('state').textContent=s.state;$('success').textContent=fmt(s.last_success);$('latest').textContent=fmt(s.latest_data_timestamp);$('age').textContent=s.data_age_days==null?'—':`${s.data_age_days} days`;$('points').textContent=s.points_written??0;$('mode').textContent=s.sync_mode||'—';$('diag').textContent=JSON.stringify(s,null,2)}catch(e){$('state').textContent='disconnected'}}
async function syncNow(){await fetch('api/sync',{method:'POST'});setTimeout(refresh,500)}
refresh();setInterval(refresh,5000);
</script></body></html>"""


def scheduler(options: dict[str, Any]) -> None:
    interval_minutes = int(options["sync_interval_minutes"])
    interval = interval_minutes * 60
    persisted = load_json(STATE_PATH, {})
    initial_wait = seconds_until_scheduled_sync(
        persisted,
        interval_minutes,
    )
    next_run = time.monotonic() + initial_wait
    if initial_wait > 0:
        with STATUS_LOCK:
            RUNTIME["state"] = "idle"
            RUNTIME["next_sync"] = (utc_now() + timedelta(seconds=initial_wait)).isoformat()
        LOG.info(
            "Startup sync suppressed; next automatic sync in %.0f seconds",
            initial_wait,
        )

    while True:
        wait = max(0.0, next_run - time.monotonic())
        manual = False
        if wait > 0:
            manual = MANUAL_SYNC.wait(wait)
        MANUAL_SYNC.clear()

        started = utc_now().isoformat()
        with STATUS_LOCK:
            RUNTIME.update({"state": "syncing", "last_sync": started, "last_error": ""})
        try:
            result = sync_once(options)
            update_stale_notification(result, int(options["stale_after_days"]))
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
                        "latest_data_timestamp": result["latest_data_timestamp"],
                        "data_age_days": result["data_age_days"],
                        "data_fresh": result["data_fresh"],
                        "freshness_source": result["freshness_source"],
                        "freshness_query_error": result["freshness_query_error"],
                        "portal_requests_24h": result["portal_requests_24h"],
                        "portal_requests_remaining": result["portal_requests_remaining"],
                        "portal_request_limit_24h": result["portal_request_limit_24h"],
                        "portal_limit_reset_at": result["portal_limit_reset_at"],
                    }
                )
        except PortalRateLimitError as exc:
            LOG.warning("Collector sync paused by portal request budget: %s", exc)
            persisted = load_json(STATE_PATH, {})
            budget = portal_request_status(
                persisted,
                int(options["portal_request_limit_24h"]),
            )
            with STATUS_LOCK:
                RUNTIME.update(
                    {
                        "state": "rate_limited",
                        "last_error": str(exc),
                        **budget,
                    }
                )
        except Exception as exc:
            LOG.exception("Collector sync failed")
            persisted = load_json(STATE_PATH, {})
            freshness = data_freshness(
                persisted.get("latest_data_timestamp"),
                int(options["stale_after_days"]),
            )
            if not freshness["data_fresh"]:
                update_stale_notification(freshness, int(options["stale_after_days"]))
            with STATUS_LOCK:
                RUNTIME.update(
                    {
                        "state": "error",
                        "last_error": str(exc),
                        **freshness,
                    }
                )

        next_run = time.monotonic() + interval
        with STATUS_LOCK:
            RUNTIME["next_sync"] = (utc_now() + timedelta(seconds=interval)).isoformat()
        if manual:
            LOG.info("Manual sync completed; automatic schedule reset to the configured interval")

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
