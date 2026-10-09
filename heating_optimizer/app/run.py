#!/usr/bin/env python3
"""Self-contained Home Assistant Ingress app for Heating Optimizer v0.1.0.

Production heat actuation is intentionally impossible in this version.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from engine import DEFAULT_SETTINGS, ENTITY_IDS, evaluate
from ha_client import HomeAssistantClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("heating_optimizer")
ROOT = Path(__file__).resolve().parent
OPTIONS_PATH = Path("/data/options.json")
SETTINGS_PATH = Path("/data/settings.json")
STATE_PATH = Path("/data/state.json")
DAYS = tuple(DEFAULT_SETTINGS["morning_schedule"])
MUTABLE_SETTINGS = {
    key for key in DEFAULT_SETTINGS if key not in ("morning_schedule",)
}
# Constrain numerical settings so a typo cannot silently disable the guards.
RANGES = {
    "morning_target_c": (18, 25),
    "morning_warming_rate_c_per_h": (0.2, 2.0),
    "morning_safety_minutes": (0, 60),
    "morning_fallback_deficit_c": (0.2, 2.0),
    "morning_reserve_soc": (20, 60),
    "absolute_min_soc": (20, 40),
    "battery_capacity_kwh": (5, 60),
    "morning_base_load_kw": (0.1, 3.0),
    "solar_recovery_hours": (0.5, 8),
    "morning_ac_kw": (0.1, 2.0),
    "solar_start_down_c": (18, 25),
    "solar_stop_down_c": (18, 25),
    "solar_start_up_c": (18, 25),
    "solar_stop_up_c": (18, 25),
    "solar_headroom_down_kwh": (0, 20),
    "solar_headroom_up_kwh": (0, 20),
    "solar_surplus_down_w": (0, 5000),
    "solar_surplus_up_w": (0, 5000),
    "solar_max_grid_down_w": (0, 2000),
    "solar_max_grid_up_w": (0, 2000),
    "solar_max_battery_down_w": (0, 2000),
    "solar_max_battery_up_w": (0, 2000),
    "ufh_target_c": (18, 25),
    "comfort_band_c": (0.1, 1),
    "gas_price_ron_per_kwh": (0, 2),
    "gas_efficiency_pct": (70, 100),
}


def read_json(path: Path, fallback: dict) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JSON must contain an object")
        return raw
    except (OSError, ValueError, json.JSONDecodeError):
        return copy.deepcopy(fallback)


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_suffix(".new")
    candidate.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(candidate, path)


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict):
        raise ValueError("Expected JSON settings object")
    unknown = set(settings) - MUTABLE_SETTINGS - {"morning_schedule"}
    if unknown:
        raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
    result = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in settings.items():
        if key == "morning_schedule":
            if not isinstance(value, dict) or set(value) != set(DAYS):
                raise ValueError("morning_schedule must include exactly seven weekdays")
            for day, clock in value.items():
                if not isinstance(clock, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
                    raise ValueError("Invalid time for " + day)
            result[key] = dict(value)
        elif isinstance(DEFAULT_SETTINGS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(key + " must be a boolean")
            result[key] = value
        elif key in RANGES:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(key + " must be numeric")
            lo, hi = RANGES[key]
            if not lo <= value <= hi:
                raise ValueError(key + " must be in [%s, %s]" % (lo, hi))
            result[key] = float(value)
        else:
            # Fixed safety limits are not UI-editable in this release.
            if value != DEFAULT_SETTINGS[key]:
                raise ValueError(key + " is fixed for safety in v0.1.0")
            result[key] = value
    if result["solar_start_down_c"] >= result["solar_stop_down_c"]:
        raise ValueError("Downstairs solar start must be lower than solar stop")
    if result["solar_start_up_c"] >= result["solar_stop_up_c"]:
        raise ValueError("Upstairs solar start must be lower than solar stop")
    return result


# The old YAML helpers are used only as ONE-TIME input at initial install.
# Once persisted, all configuration is owned by this add-on.
LEGACY_SETTINGS = {
    "morning_enabled": "input_boolean.heating_optimizer_ground_floor_ac_schedule_enabled",
    "comfort_fallback_enabled": "input_boolean.heating_optimizer_ground_floor_ac_comfort_fallback_enabled",
    "solar_down_enabled": "input_boolean.heating_optimizer_ground_floor_ac_solar_enabled",
    "solar_up_enabled": "input_boolean.heating_optimizer_upstairs_ac_solar_enabled",
    "morning_target_c": "input_number.heating_optimizer_ground_floor_morning_target",
    "morning_warming_rate_c_per_h": "input_number.heating_optimizer_ground_floor_morning_warming_rate",
    "morning_safety_minutes": "input_number.heating_optimizer_ground_floor_morning_safety_margin",
    "morning_fallback_deficit_c": "input_number.heating_optimizer_ground_floor_morning_fallback_deficit",
    "morning_reserve_soc": "input_number.heating_optimizer_morning_battery_reserve",
    "absolute_min_soc": "input_number.heating_optimizer_battery_absolute_min_soc",
    "battery_capacity_kwh": "input_number.heating_optimizer_battery_usable_capacity",
    "morning_base_load_kw": "input_number.heating_optimizer_morning_expected_base_load",
    "solar_recovery_hours": "input_number.heating_optimizer_morning_solar_recovery_hours",
    "morning_ac_kw": "input_number.heating_optimizer_ground_floor_ac_estimated_average_input_power",
    "solar_start_down_c": "input_number.heating_optimizer_ground_floor_ac_solar_start_temperature",
    "solar_stop_down_c": "input_number.heating_optimizer_ground_floor_ac_solar_stop_temperature",
    "solar_start_up_c": "input_number.heating_optimizer_upstairs_ac_solar_start_temperature",
    "solar_stop_up_c": "input_number.heating_optimizer_upstairs_ac_solar_stop_temperature",
    "solar_headroom_down_kwh": "input_number.heating_optimizer_ground_floor_ac_solar_min_headroom",
    "solar_headroom_up_kwh": "input_number.heating_optimizer_upstairs_ac_solar_min_headroom",
    "solar_surplus_down_w": "input_number.heating_optimizer_ground_floor_ac_solar_start_surplus",
    "solar_surplus_up_w": "input_number.heating_optimizer_upstairs_ac_solar_start_surplus",
    "solar_max_grid_down_w": "input_number.heating_optimizer_ground_floor_ac_solar_max_grid_import",
    "solar_max_grid_up_w": "input_number.heating_optimizer_upstairs_ac_solar_max_grid_import",
    "solar_max_battery_down_w": "input_number.heating_optimizer_ground_floor_ac_solar_max_battery_discharge",
    "solar_max_battery_up_w": "input_number.heating_optimizer_upstairs_ac_solar_max_battery_discharge",
    "ufh_target_c": "input_number.heating_optimizer_target_temperature",
    "comfort_band_c": "input_number.heating_optimizer_comfort_band",
    "gas_price_ron_per_kwh": "input_number.heating_optimizer_gas_price",
    "gas_efficiency_pct": "input_number.heating_optimizer_boiler_efficiency",
}


def import_legacy_settings(states: dict) -> dict:
    imported = {}
    for key, entity in LEGACY_SETTINGS.items():
        value = states.get(entity, {}).get("state")
        if not isinstance(value, str) or value in ("unknown", "unavailable", ""):
            continue
        if isinstance(DEFAULT_SETTINGS[key], bool):
            if value in ("on", "off"):
                imported[key] = value == "on"
        else:
            try:
                imported[key] = float(value)
            except (TypeError, ValueError):
                continue
    schedule = {}
    for day in DAYS:
        entity = "input_datetime.heating_optimizer_morning_target_time_" + day
        value = states.get(entity, {}).get("state")
        if isinstance(value, str) and re.fullmatch(r"(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d)?", value):
            schedule[day] = value[:5]
    if len(schedule) == 7:
        imported["morning_schedule"] = schedule
    # Legacy entities could contain invalid/inconsistent values; defaults
    # and validated subsets are safer than failing the entire first poll.
    valid = {}
    for key, value in imported.items():
        try:
            validate_settings({**valid, key: value})
        except ValueError:
            continue
        valid[key] = value
    return valid


class Runtime:
    def __init__(
        self,
        options_path: Path = OPTIONS_PATH,
        settings_path: Path = SETTINGS_PATH,
        state_path: Path = STATE_PATH,
        client=None,
    ):
        self.lock = threading.RLock()
        self.options_path = options_path
        self.settings_path = settings_path
        self.state_path = state_path
        self.options = read_json(options_path, {})
        # Future active versions require a separate governed migration.
        if self.options.get("shadow_mode") is not True:
            raise RuntimeError("Heating Optimizer 0.1.0 requires shadow_mode=true")
        self.timezone = ZoneInfo(str(self.options.get("timezone", "Europe/Bucharest")))
        self.settings = validate_settings(read_json(settings_path, DEFAULT_SETTINGS))
        self.tracker = read_json(state_path, {})
        self.client = client if client is not None else HomeAssistantClient()
        self.status: dict = {
            "mode": "shadow", "state": "starting", "version": "0.1.0",
            "last_update": None, "decision": None, "errors": [],
            "events": [], "health": "starting",
        }
        self.last_signature = None

    def poll(self) -> None:
        now = datetime.now(self.timezone)
        try:
            states = self.client.all_states()
            with self.lock:
                if not self.settings_path.exists():
                    imported = import_legacy_settings(states)
                    self.settings = validate_settings({**self.settings, **imported})
                    atomic_json(self.settings_path, self.settings)
                    LOG.info("Imported %d legacy Heating Optimizer settings", len(imported))
                decision = evaluate(states, self.settings, self.tracker, now)
                events = self.status.get("events", [])
                signature = tuple(
                    (zone, decision["zones"][zone]["recommendation"])
                    for zone in ("down", "up")
                )
                if signature != self.last_signature and any(
                    value != "hold" for _, value in signature
                ):
                    events.append({
                        "timestamp": now.isoformat(),
                        "down": decision["zones"]["down"]["recommendation"],
                        "up": decision["zones"]["up"]["recommendation"],
                        "note": "shadow_only_no_actuator_calls",
                    })
                    events = events[-200:]
                self.last_signature = signature
                self.status = {
                    "mode": "shadow", "state": "ready", "health": "healthy",
                    "version": "0.1.0", "last_update": now.isoformat(),
                    "decision": decision, "errors": [], "events": events,
                    "configured_entities": len(ENTITY_IDS),
                    "available_entities": sum(
                        1 for item in decision["observations"].values()
                        if item["value"] is not None
                    ),
                    "control_enabled": False,
                }
                atomic_json(self.state_path, self.tracker)
        except (RuntimeError, ValueError, KeyError, OSError, TypeError) as exc:
            with self.lock:
                self.status.update({
                    "state": "degraded", "health": "degraded",
                    "last_update": now.isoformat(), "errors": [str(exc)],
                })
            LOG.warning("Read/evaluation failed: %s", exc)

    def get_status(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.status)

    def get_settings(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.settings)

    def set_settings(self, supplied: dict) -> dict:
        with self.lock:
            # Partial PATCH-like update while preserving complete weekday map.
            merged = {**self.settings, **supplied}
            validated = validate_settings(merged)
            atomic_json(self.settings_path, validated)
            self.settings = validated
            # Resimulate from a clean state to avoid stale simulated timers
            # when the target, schedule or guard thresholds change.
            self.tracker = {}
            atomic_json(self.state_path, self.tracker)
            return copy.deepcopy(self.settings)


RUNTIME = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        LOG.info(fmt, *args)

    def _json(self, payload, status=200):
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            status = RUNTIME.get_status()
            # The process is healthy even if Home Assistant is temporarily
            # unreachable; avoid a watchdog restart loop during an outage.
            self._json({"status": "ok", "source_health": status["health"],
                        "mode": "shadow", "version": "0.1.0"})
        elif path == "/api/status":
            self._json(RUNTIME.get_status())
        elif path == "/api/settings":
            self._json(RUNTIME.get_settings())
        elif path in ("/", "/index.html", "/app.js", "/style.css"):
            # All content loaded through HA Ingress under its own prefix.
            name = "index.html" if path == "/" else path.lstrip("/")
            filename = ROOT / "static" / name
            if not filename.is_file():
                self._json({"error": "not_found"}, 404)
                return
            data = filename.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {
                "index.html": "text/html; charset=utf-8",
                "app.js": "text/javascript; charset=utf-8",
                "style.css": "text/css; charset=utf-8",
            }[name])
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._json({"error": "not_found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/settings":
            self._json({"error": "not_found"}, 404)
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._json({"error": "JSON_content_type_required"}, 415)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 16384:
            self._json({"error": "invalid_payload_length"}, 413)
            return
        try:
            supplied = json.loads(self.rfile.read(length))
            if not isinstance(supplied, dict):
                raise ValueError("Expected a settings JSON object")
            # Ingress must be the only route to this add-on.
            updated = RUNTIME.set_settings(supplied)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        except OSError as exc:
            self._json({"error": "Unable to persist settings", "detail": str(exc)}, 503)
        else:
            self._json({"ok": True, "settings": updated})


def main():
    global RUNTIME
    RUNTIME = Runtime()
    RUNTIME.poll()
    def loop():
        while True:
            time.sleep(max(10, min(300, int(RUNTIME.options.get("poll_interval_seconds", 30)))))
            RUNTIME.poll()
    threading.Thread(target=loop, name="heating-poll", daemon=True).start()
    LOG.info("Heating Optimizer 0.1.0 SHADOW ONLY started; actuator writes disabled")
    ThreadingHTTPServer(("0.0.0.0", 8098), Handler).serve_forever()


if __name__ == "__main__":
    main()
