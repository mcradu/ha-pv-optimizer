"""Read-only, fail-closed comparator for corrected household load forecasts.

No control decisions or Home Assistant actuators are accessed by this module.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

UTC = timezone.utc


def read_forecast(url: str, timeout: float = 3) -> dict:
    if not url.startswith("http://") and not url.startswith("https://"):
        raise ValueError("Forecast URL must use HTTP(S)")
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read(200_000))


def _parse(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Missing timezone")
    return result.astimezone(UTC)


def integrate(points: list[dict], start: datetime, end: datetime) -> dict | None:
    """Exact partial-hour overlap, including local DST transitions via UTC."""
    if end <= start:
        return None
    indexed: dict[datetime, dict] = {}
    for p in points:
        stamp = _parse(p["valid_hour_utc"])
        if stamp.minute or stamp.second or stamp.microsecond:
            raise ValueError("Forecast bucket is not hour-aligned")
        for name in ("p50_w", "upper_w"):
            if not isinstance(p.get(name), (int, float)) or not math.isfinite(p[name]) or p[name] < 0:
                raise ValueError("Invalid forecast power")
        if p["upper_w"] < p["p50_w"]:
            raise ValueError("Upper forecast is below expected load")
        indexed[stamp] = p

    timestamp = start.replace(minute=0, second=0, microsecond=0)
    kwh = upper = 0.0
    coverage = 0.0
    low_hours = 0
    while timestamp < end:
        p = indexed.get(timestamp)
        used = (min(timestamp + timedelta(hours=1), end) - max(timestamp, start)).total_seconds()
        if used > 0:
            if p is None:
                return None  # A gap must never become zero consumption.
            factor = used / 3600 / 1000
            kwh += p["p50_w"] * factor
            upper += p["upper_w"] * factor
            coverage += used / 3600
            low_hours += p.get("confidence") == "low"
        timestamp += timedelta(hours=1)
    return {
        "expected_kwh": round(kwh, 3),
        "upper_kwh": round(upper, 3),
        "hours": round(coverage, 3),
        "low_confidence_hours": low_hours,
    }


def compare_shadow(
    payload: dict,
    now: datetime,
    sunrise: datetime | None,
    sunset: datetime | None,
    sun_below_horizon: bool,
    current_day_kwh: float | None,
    static_night_load_w: float,
) -> dict:
    now = now.astimezone(UTC)
    generated = _parse(payload["generated_at"])
    age = (now - generated).total_seconds() / 60
    if age < -5 or age > 40:
        raise ValueError("Stale or future-dated forecast")
    if payload.get("status") not in ("ready", "degraded"):
        raise ValueError("Forecast marked unavailable")
    points = payload.get("points", [])
    if not isinstance(points, list) or len(points) < 24:
        raise ValueError("Insufficient forecast points")

    result = {
        "state": "shadow_only",
        "used_for_control": False,
        "model_status": payload.get("status"),
        "generated_at": payload["generated_at"],
        "forecast_age_minutes": round(age, 1),
        "backtest": payload.get("backtest", {}),
        "next_sunset": None,
        "next_sunrise": None,
    }
    if not sun_below_horizon and sunset is not None and sunset > now:
        projected = integrate(points, now, min(sunset, now + timedelta(hours=48)))
        if projected is None or projected["low_confidence_hours"]:
            raise ValueError("Incomplete/low-confidence sunset forecast")
        result["next_sunset"] = {
            **projected,
            "legacy_kwh": round(current_day_kwh, 3) if current_day_kwh is not None else None,
            "delta_vs_legacy_kwh": round(projected["expected_kwh"] - current_day_kwh, 3) if current_day_kwh is not None else None,
        }
    if sun_below_horizon and sunrise is not None and sunrise > now:
        projected = integrate(points, now, min(sunrise, now + timedelta(hours=48)))
        if projected is None or projected["low_confidence_hours"]:
            raise ValueError("Incomplete/low-confidence sunrise forecast")
        legacy = max(static_night_load_w, 0) * projected["hours"] / 1000
        result["next_sunrise"] = {
            **projected,
            "legacy_kwh": round(legacy, 3),
            "delta_vs_legacy_kwh": round(projected["expected_kwh"] - legacy, 3),
        }
    return result
