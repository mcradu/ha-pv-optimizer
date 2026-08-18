from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Any


@dataclass(frozen=True)
class Inputs:
    battery_soc: float
    grid_connected: bool
    sun_below_horizon: bool
    hours_until_sunrise: float
    forecast_kwh: float
    battery_capacity_kwh: float
    minimum_morning_soc: float
    safety_margin_soc: float
    hysteresis_soc: float
    night_load_w: float
    night_min_w: int
    night_max_w: int
    enabled: bool = True


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def calculate(values: Inputs, requested_mode: str = "auto") -> dict[str, Any]:
    needed_kwh = max(values.hours_until_sunrise, 0) * max(values.night_load_w, 0) / 1000
    needed_soc = needed_kwh / max(values.battery_capacity_kwh, 0.1) * 100
    stop_soc = round(_clamp(values.minimum_morning_soc + needed_soc + values.safety_margin_soc, 20, 100))
    start_soc = round(_clamp(stop_soc + values.hysteresis_soc, 0, 100))
    surplus_kwh = round(max(values.battery_soc - stop_soc, 0) / 100 * values.battery_capacity_kwh, 3)

    blockers: list[str] = []
    if not values.enabled:
        blockers.append("optimizer_disabled")
    if not values.grid_connected:
        blockers.append("grid_disconnected")
    if not values.sun_below_horizon:
        blockers.append("outside_night_window")
    if values.battery_soc <= stop_soc:
        blockers.append("stop_soc_reached")
    if values.hours_until_sunrise <= 0:
        blockers.append("sunrise_time_invalid")

    calculated_w = 0
    if not blockers and surplus_kwh > 0:
        calculated_w = ceil((surplus_kwh / values.hours_until_sunrise * 1000) / 100) * 100
        calculated_w = int(_clamp(calculated_w, values.night_min_w, values.night_max_w))
        if requested_mode == "night_max":
            calculated_w = values.night_max_w
        elif requested_mode in {"stop", "failsafe", "day"}:
            calculated_w = 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": "blocked" if blockers else ("exporting_shadow" if calculated_w else "idle"),
        "shadow": True,
        "requested_mode": requested_mode,
        "applied_mode": requested_mode,
        "target_export_w": calculated_w,
        "stop_soc": stop_soc,
        "start_soc": start_soc,
        "needed_until_sunrise_kwh": round(needed_kwh, 3),
        "surplus_kwh": surplus_kwh,
        "blockers": blockers,
        "inputs": asdict(values),
        "explanation": _explain(calculated_w, stop_soc, surplus_kwh, blockers, requested_mode),
    }


def _explain(target: int, stop_soc: int, surplus: float, blockers: list[str], mode: str) -> str:
    if blockers:
        return "No export: " + ", ".join(blockers) + "."
    if mode in {"stop", "failsafe", "day"}:
        return f"{mode.replace('_', ' ').title()} requested; simulated export target is 0 W."
    return f"Shadow target {target} W from {surplus:.3f} kWh surplus while preserving {stop_soc}% SOC."
