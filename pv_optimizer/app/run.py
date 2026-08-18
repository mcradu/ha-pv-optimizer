#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from engine import Inputs, calculate
from charge_engine import ChargeInputs, calculate_charge
from ha_client import HomeAssistantClient
from telemetry import TelemetryStore

ROOT = Path(__file__).parent
OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/pv_optimizer_state.json")
TELEMETRY_PATH = Path("/data/pv_optimizer_charge_telemetry.jsonl")
LOG = logging.getLogger("pv_optimizer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


DEFAULTS = {
    "poll_interval_seconds": 30,
    "battery_capacity_kwh": 20,
    "minimum_morning_soc": 45,
    "safety_margin_soc": 3,
    "hysteresis_soc": 5,
    "static_night_load_w": 800,
    "night_max_w": 1200,
    "night_min_w": 200,
    "morning_max_w": 700,
    "charge_optimizer_enabled": True,
    "charge_on_voltage": 249,
    "charge_off_voltage": 247,
    "charge_stabilization_seconds": 300,
    "charge_minimum_state_seconds": 300,
    "sunset_target_soc": 100,
    "pv_available_on_w": 300,
    "pv_available_off_w": 100,
    "forecast_safety_kwh": 0.5,
    "shadow_mode": True,
    "entities": {
        "battery_soc": "sensor.ss_battery_soc",
        "pv_power": "sensor.ss_pv_power",
        "battery_power": "sensor.ss_battery_power",
        "grid_power": "sensor.ss_grid_power",
        "grid_connected": "binary_sensor.ss_grid_connected",
        "sun": "sun.sun",
        "forecast_tomorrow": "sensor.energy_production_tomorrow",
        "forecast_today_remaining": "sensor.energy_production_today_remaining",
        "grid_voltage_l1": "sensor.ss_grid_l1_voltage",
        "grid_voltage_l2": "sensor.ss_grid_l2_voltage",
        "grid_voltage_l3": "sensor.ss_grid_l3_voltage",
        "battery_temperature": "sensor.ss_battery_temperature",
    },
}


class Runtime:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.options = self._load_json(OPTIONS_PATH, DEFAULTS)
        if self.options.get("shadow_mode") is not True:
            raise RuntimeError("Version 0.2.3 requires shadow_mode=true")
        self.state = self._load_json(STATE_PATH, {"requested_mode": "auto", "logs": []})
        self.status: dict = {"state": "starting", "shadow": True, "entities": {}, "decision": {}}
        self.client = HomeAssistantClient()
        self.telemetry = TelemetryStore(TELEMETRY_PATH)
        self.last_error_signature = ""

    @staticmethod
    def _load_json(path: Path, fallback: dict) -> dict:
        try:
            data = json.loads(path.read_text())
            merged = dict(fallback)
            merged.update(data)
            if isinstance(fallback.get("entities"), dict) and isinstance(data.get("entities"), dict):
                merged["entities"] = {**fallback["entities"], **data["entities"]}
            return merged
        except (FileNotFoundError, json.JSONDecodeError):
            return dict(fallback)

    def save_state(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True))
        tmp.replace(STATE_PATH)

    def add_log(self, message: str) -> None:
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "message": message}
        self.state.setdefault("logs", []).append(event)
        self.state["logs"] = self.state["logs"][-100:]
        LOG.info(message)

    @staticmethod
    def _number(item: dict, name: str) -> float:
        value = item.get("state")
        if value in (None, "unknown", "unavailable"):
            raise ValueError(f"{name} is {value or 'missing'}")
        return float(value)

    def poll(self) -> None:
        entity_map = self.options["entities"]
        entities: dict[str, dict] = {}
        errors: list[str] = []
        mode = self.state.get("requested_mode", "auto")
        for key, entity_id in entity_map.items():
            try:
                entities[key] = self.client.get_state(entity_id)
            except (RuntimeError, ValueError) as exc:
                entities[key] = {"entity_id": entity_id, "state": "unavailable", "error": str(exc)}
                errors.append(str(exc))

        try:
            soc = self._number(entities["battery_soc"], "battery_soc")
            sun = entities["sun"].get("state")
            next_rising = entities["sun"].get("attributes", {}).get("next_rising")
            if not next_rising:
                raise ValueError("sun.next_rising is missing")
            sunrise = datetime.fromisoformat(next_rising.replace("Z", "+00:00"))
            hours = max((sunrise - datetime.now(timezone.utc)).total_seconds() / 3600, 0)
            forecast = self._number(entities["forecast_tomorrow"], "forecast_tomorrow")
            minimum_soc = float(self.options["minimum_morning_soc"])
            if forecast <= 15:
                minimum_soc = max(minimum_soc, 60)
            elif forecast >= 30:
                minimum_soc = min(minimum_soc, 40)
            decision = calculate(
                Inputs(
                    battery_soc=soc,
                    grid_connected=entities["grid_connected"].get("state") == "on",
                    sun_below_horizon=sun == "below_horizon",
                    hours_until_sunrise=hours,
                    forecast_kwh=forecast,
                    battery_capacity_kwh=float(self.options["battery_capacity_kwh"]),
                    minimum_morning_soc=minimum_soc,
                    safety_margin_soc=float(self.options["safety_margin_soc"]),
                    hysteresis_soc=float(self.options["hysteresis_soc"]),
                    night_load_w=float(self.options["static_night_load_w"]),
                    night_min_w=int(self.options["night_min_w"]),
                    night_max_w=int(self.options["night_max_w"]),
                    enabled=True,
                ),
                mode,
            )
        except (ValueError, KeyError) as exc:
            errors.append(str(exc))
            decision = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": "blocked",
                "shadow": True,
                "target_export_w": 0,
                "blockers": ["invalid_or_missing_entity"],
                "explanation": str(exc),
            }

        try:
            next_setting = entities["sun"].get("attributes", {}).get("next_setting")
            if not next_setting:
                raise ValueError("sun.next_setting is missing")
            sunset = datetime.fromisoformat(next_setting.replace("Z", "+00:00"))
            hours_until_sunset = max((sunset - datetime.now(timezone.utc)).total_seconds() / 3600, 0)
            charge_decision = calculate_charge(
                ChargeInputs(
                    battery_soc=self._number(entities["battery_soc"], "battery_soc"),
                    battery_power_w=self._number(entities["battery_power"], "battery_power"),
                    grid_power_w=self._number(entities["grid_power"], "grid_power"),
                    pv_power_w=self._number(entities["pv_power"], "pv_power"),
                    grid_connected=entities["grid_connected"].get("state") == "on",
                    voltage_l1=self._number(entities["grid_voltage_l1"], "grid_voltage_l1"),
                    voltage_l2=self._number(entities["grid_voltage_l2"], "grid_voltage_l2"),
                    voltage_l3=self._number(entities["grid_voltage_l3"], "grid_voltage_l3"),
                    battery_temperature_c=self._number(entities["battery_temperature"], "battery_temperature"),
                    forecast_remaining_kwh=self._number(entities["forecast_today_remaining"], "forecast_today_remaining"),
                    hours_until_sunset=hours_until_sunset,
                    battery_capacity_kwh=float(self.options["battery_capacity_kwh"]),
                    sunset_target_soc=float(self.options["sunset_target_soc"]),
                    charge_on_voltage=float(self.options["charge_on_voltage"]),
                    charge_off_voltage=float(self.options["charge_off_voltage"]),
                    pv_available_on_w=float(self.options["pv_available_on_w"]),
                    pv_available_off_w=float(self.options["pv_available_off_w"]),
                    forecast_safety_kwh=float(self.options["forecast_safety_kwh"]),
                    enabled=bool(self.options["charge_optimizer_enabled"]),
                ),
                self.state.get("charge_shadow_request", "off"),
            )
            self._apply_charge_stabilization(charge_decision)
        except (ValueError, KeyError) as exc:
            charge_decision = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": "blocked",
                "shadow": True,
                "target_charge_w": 0,
                "blockers": ["invalid_or_missing_charge_entity"],
                "explanation": str(exc),
            }

        self.telemetry.append(self._telemetry_record(entities, charge_decision))

        with self.lock:
            self.status = {
                "state": decision["state"],
                "shadow": True,
                "version": "0.2.3",
                "last_update": datetime.now(timezone.utc).isoformat(),
                "errors": errors,
                "entities": entities,
                "decision": decision,
                "charge_decision": charge_decision,
                "charge_telemetry": self.telemetry.latest(100),
                "requested_mode": self.state.get("requested_mode", "auto"),
                "logs": self.state.get("logs", []),
                "diagnostics": self.diagnostics(),
            }
            if mode == "night_max":
                self.state["requested_mode"] = "auto"
                self.add_log("Night MAX simulated for one cycle; mode reset to Auto")
                self.save_state()
        signature = " | ".join(sorted(set(errors)))
        if signature and signature != self.last_error_signature:
            LOG.error("Home Assistant read failed: %s", signature)
        elif not signature and self.last_error_signature:
            LOG.info("Home Assistant entity reads recovered")
        self.last_error_signature = signature

    def diagnostics(self) -> dict:
        return {
            "version": "0.2.3",
            "shadow": True,
            "supervisor_token_present": bool(self.client.token),
            "supervisor_token_source": self.client.token_source or "none",
            "home_assistant_api_url": self.client.base_url,
            "configured_entity_count": len(self.options.get("entities", {})),
        }

    def _apply_charge_stabilization(self, decision: dict) -> None:
        desired = decision.get("desired_charge_request", "no_action")
        current = self.state.get("charge_shadow_request", "off")
        now = time.time()
        transitioned = False
        if desired == "no_action":
            self.state.pop("charge_candidate_request", None)
            self.state.pop("charge_candidate_since", None)
        elif desired == current:
            self.state.pop("charge_candidate_request", None)
            self.state.pop("charge_candidate_since", None)
        else:
            if self.state.get("charge_candidate_request") != desired:
                self.state["charge_candidate_request"] = desired
                self.state["charge_candidate_since"] = now
            candidate_elapsed = now - float(self.state.get("charge_candidate_since", now))
            state_elapsed = now - float(self.state.get("charge_last_transition", 0))
            if candidate_elapsed >= float(self.options["charge_stabilization_seconds"]) and state_elapsed >= float(self.options["charge_minimum_state_seconds"]):
                current = desired
                self.state["charge_shadow_request"] = current
                self.state["charge_last_transition"] = now
                self.state.pop("charge_candidate_request", None)
                self.state.pop("charge_candidate_since", None)
                transitioned = True
                self.add_log(f"Shadow battery charge request changed to {current.upper()}: {decision.get('explanation', '')}")
                self.save_state()
        decision["recommended_charge_request"] = current
        decision["transitioned"] = transitioned
        decision["pending_request"] = self.state.get("charge_candidate_request")
        decision["pending_seconds"] = round(max(now - float(self.state.get("charge_candidate_since", now)), 0)) if self.state.get("charge_candidate_request") else 0

    @staticmethod
    def _telemetry_record(entities: dict, decision: dict) -> dict:
        def state(key: str):
            return entities.get(key, {}).get("state")
        return {
            "timestamp": decision.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "request": decision.get("recommended_charge_request", "off"),
            "desired": decision.get("desired_charge_request", "no_action"),
            "state": decision.get("state", "blocked"),
            "reason": decision.get("explanation", ""),
            "transitioned": decision.get("transitioned", False),
            "pv_w": state("pv_power"),
            "battery_w": state("battery_power"),
            "grid_w": state("grid_power"),
            "battery_soc": state("battery_soc"),
            "battery_temperature_c": state("battery_temperature"),
            "voltage_l1": state("grid_voltage_l1"),
            "voltage_l2": state("grid_voltage_l2"),
            "voltage_l3": state("grid_voltage_l3"),
            "maximum_voltage": decision.get("maximum_grid_voltage"),
            "determining_phase": decision.get("determining_phase"),
            "forecast_remaining_kwh": state("forecast_today_remaining"),
            "projected_shortfall_kwh": decision.get("projected_sunset_shortfall_kwh"),
        }

    def set_mode(self, mode: str) -> None:
        if mode not in {"auto", "night_max", "stop", "day", "failsafe", "test_500"}:
            raise ValueError("unsupported mode")
        if mode == "test_500":
            mode = "auto"
            self.add_log("Test 500 requested in shadow mode; no inverter command sent")
        else:
            self.add_log(f"Mode changed to {mode} in shadow mode")
        self.state["requested_mode"] = mode
        self.save_state()


RUNTIME = Runtime()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        LOG.debug(fmt, *args)

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok", "shadow": True, "version": "0.2.3"})
        elif path == "/api/status":
            with RUNTIME.lock:
                self._json(RUNTIME.status)
        elif path == "/api/config":
            safe = dict(RUNTIME.options)
            self._json(safe)
        elif path == "/api/diagnostics":
            self._json(RUNTIME.diagnostics())
        else:
            super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = min(int(self.headers.get("Content-Length", 0)), 4096)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, 400)
            return
        if path == "/api/mode":
            try:
                RUNTIME.set_mode(str(body.get("mode", "")))
                RUNTIME.poll()
                self._json({"ok": True, "shadow": True, "requested_mode": RUNTIME.state["requested_mode"]})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
        else:
            self._json({"error": "not found"}, 404)


def poll_loop() -> None:
    while True:
        try:
            RUNTIME.poll()
        except Exception:
            LOG.exception("Unexpected poll failure")
        time.sleep(max(5, int(RUNTIME.options["poll_interval_seconds"])))


if __name__ == "__main__":
    RUNTIME.add_log("PV Optimizer 0.2.3 started with binary charge requests and persistent telemetry in mandatory shadow mode")
    LOG.info(
        "Supervisor API diagnostics: token_present=%s api_url=%s",
        RUNTIME.diagnostics()["supervisor_token_present"],
        RUNTIME.client.base_url,
    )
    threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
