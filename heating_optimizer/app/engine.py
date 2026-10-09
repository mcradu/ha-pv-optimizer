"""Pure, side-effect-free heating recommendation engine.

The v0.1 branch is deliberately shadow-only. The adapter never sends
climate/boiler/UFH service calls, even if settings or UI are manipulated.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "morning_enabled": True,
    "comfort_fallback_enabled": True,
    "solar_down_enabled": True,
    "solar_up_enabled": True,
    "morning_target_c": 22.5,
    "morning_warming_rate_c_per_h": 0.8,
    "morning_safety_minutes": 10,
    "morning_fallback_deficit_c": 0.5,
    "morning_reserve_soc": 25,
    "absolute_min_soc": 20,
    "battery_capacity_kwh": 20,
    "morning_base_load_kw": 0.45,
    "solar_recovery_hours": 3,
    "morning_ac_kw": 0.7,
    "solar_start_down_c": 22.0,
    "solar_stop_down_c": 23.0,
    "solar_start_up_c": 22.3,
    "solar_stop_up_c": 23.0,
    "solar_headroom_down_kwh": 0.6,
    "solar_headroom_up_kwh": 0.6,
    "solar_surplus_down_w": 1000,
    "solar_surplus_up_w": 1000,
    "solar_max_grid_down_w": 200,
    "solar_max_grid_up_w": 200,
    "solar_max_battery_down_w": 200,
    "solar_max_battery_up_w": 200,
    "min_on_seconds": 1800,
    "min_off_seconds": 1800,
    "pv_on_stable_seconds": 120,
    "pv_off_stable_seconds": 300,
    "non_solar_delay_seconds": 120,
    "ufh_target_c": 22.5,
    "comfort_band_c": 0.3,
    "gas_price_ron_per_kwh": 0.26319,
    "gas_efficiency_pct": 95,
    "morning_schedule": {
        "monday": "06:00", "tuesday": "06:00", "wednesday": "06:00",
        "thursday": "06:00", "friday": "06:00",
        "saturday": "08:00", "sunday": "08:00",
    },
}

ENTITY_IDS = {
    "down_temp": "sensor.sonoff_a48004a295_temperature",
    "up_temp": "sensor.sonoff_a48004affc_temperature",
    "outside_temp": "sensor.sonoff_10008cfa76_temperature",
    "puffer_temp": "sensor.sonoff_1000f209bd_temperature",
    "ac_down": "climate.ac_down",
    "ac_up": "climate.ac_up",
    "boiler": "switch.sonoff_1000f209bd",
    "ufh_switch": "switch.sonoff_1000f39cf9",
    "ufh_thermostat": "climate.smart_thermostat_2",
    "soc": "sensor.ss_battery_soc",
    "battery_temp": "sensor.ss_battery_temperature",
    "battery_power": "sensor.ss_battery_power",
    "grid_power": "sensor.ss_grid_power",
    "pv_reachable": "binary_sensor.pv_optimizer_battery_target_reachable",
    "pv_headroom": "sensor.pv_optimizer_available_solar_headroom",
    "sunset_shortfall": "sensor.pv_optimizer_projected_sunset_shortfall",
    "fault_down": "sensor.heating_optimizer_ground_floor_ac_fault_code",
    "fault_up": "sensor.heating_optimizer_upstairs_ac_fault_code",
    "financial_day": "sensor.heating_optimizer_ground_floor_ac_net_savings_today_estimated",
    "financial_week": "sensor.heating_optimizer_ground_floor_ac_net_savings_week_total_estimated",
    "financial_month": "sensor.heating_optimizer_ground_floor_ac_net_savings_month_total_estimated",
    "all_grid_day": "sensor.heating_optimizer_ground_floor_ac_all_grid_cost_today_estimated",
    "all_grid_week": "sensor.heating_optimizer_ground_floor_ac_all_grid_cost_week_total_estimated",
    "all_grid_month": "sensor.heating_optimizer_ground_floor_ac_all_grid_cost_month_total_estimated",
    "heat_cost": "sensor.heating_optimizer_heating_cost_today_estimated",
    "pv_export_price": "sensor.pv_optimizer_export_price",
    "pv_import_price": "sensor.pv_optimizer_import_price",
}


def state(states: dict, key: str) -> str | None:
    item = states.get(ENTITY_IDS[key])
    if not isinstance(item, dict):
        return None
    raw = str(item.get("state", "unknown"))
    return None if raw in ("unknown", "unavailable", "none", "None", "") else raw


def number(states: dict, key: str) -> float | None:
    val = state(states, key)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def fault_code(states: dict, zone: str) -> float | None:
    """Prefer the device's direct local fault bitmap, not a legacy template."""
    raw = states.get(ENTITY_IDS["ac_" + zone], {})
    if isinstance(raw, dict):
        attrs = raw.get("attributes", {})
        if isinstance(attrs, dict) and attrs.get("tuya_fault_bitmap") is not None:
            try:
                return float(attrs["tuya_fault_bitmap"])
            except (TypeError, ValueError):
                return None
    # Compatibility only until the YAML-derived observability sensors are removed.
    return number(states, "fault_" + zone)


def _observation(states: dict, key: str) -> dict:
    raw = states.get(ENTITY_IDS[key], {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "entity": ENTITY_IDS[key],
        "value": state(states, key),
        "updated": raw.get("last_updated"),
    }


def _stable(tracker: dict, key: str, value: bool | None, now_ts: float) -> float:
    previous = tracker.get(key, {})
    if previous.get("value") != value:
        tracker[key] = {"value": value, "since": now_ts}
        return 0
    return max(now_ts - float(previous.get("since", now_ts)), 0)


def _time_of_day(time: str, now: datetime) -> datetime:
    hour, minute = (int(piece) for piece in time.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _zone(
    zone: str,
    now: datetime,
    settings: dict,
    states: dict,
    tracker: dict,
    pv_on_elapsed: float,
    pv_off_elapsed: float,
    morning: dict,
    solar: dict,
) -> dict:
    current = tracker.setdefault("zones", {}).setdefault(
        zone, {"simulated_on": False, "mode": None, "last_transition": 0.0}
    )
    now_ts = now.timestamp()
    on = bool(current["simulated_on"])
    since = max(now_ts - float(current.get("last_transition", 0)), 0)
    observed = state(states, "ac_" + zone)
    room = number(states, zone + "_temp")
    fault = fault_code(states, zone)
    pv_status = state(states, "pv_reachable")
    reason: list[str] = []
    action = "hold"
    proposed_mode = current.get("mode")
    has_sensor = room is not None and observed is not None
    # AC fault is sourced from the existing device integration during
    # transition. Unknown fault values fail closed for any new start.
    healthy = fault == 0
    soc = number(states, "soc")
    battery_safe = soc is not None and soc > max(
        float(settings["absolute_min_soc"]), float(settings["morning_reserve_soc"])
    )
    budget_ok = bool(morning["budget_ok"])
    morning_wanted = (
        zone == "down" and settings["morning_enabled"]
        and morning["window"] and room is not None
        and room < settings["morning_target_c"]
        and (morning["predictive_due"] and budget_ok or morning["comfort_fallback"])
    )
    solar_wanted = (
        settings["solar_" + zone + "_enabled"] and solar["within_start_window"]
        and room is not None and room < settings["solar_start_" + zone + "_c"]
        and solar["headroom_ok_" + zone] and solar["surplus_ok_" + zone]
        and solar["grid_ok_" + zone] and solar["battery_draw_ok_" + zone]
    )
    start_mode = "morning" if morning_wanted else "solar" if solar_wanted else None
    if not has_sensor:
        reason.append("temperature_or_AC_unavailable")
    if not healthy:
        reason.append("AC_fault_unknown_or_nonzero")
    if not battery_safe:
        reason.append("battery_SOC_below_reserve_or_unknown")
    if pv_status != "on":
        reason.append("PV_sunset_target_not_reachable")
    if on:
        fault_stop = fault is not None and fault != 0
        reserve_stop = soc is not None and soc <= max(
            float(settings["absolute_min_soc"]), float(settings["morning_reserve_soc"])
        )
        missing_critical = not has_sensor or fault is None or soc is None
        if fault_stop or reserve_stop or missing_critical:
            action = "would_stop"
            reason.append(
                "hardware_fault" if fault_stop else
                "battery_reserve_guard" if reserve_stop else "critical_telemetry_missing"
            )
        elif since < settings["min_on_seconds"]:
            reason.append("minimum_ON_remaining_%ds" % int(settings["min_on_seconds"] - since))
        else:
            active_mode = current.get("mode")
            if pv_status != "on" and pv_off_elapsed >= settings["pv_off_stable_seconds"]:
                action = "would_stop"
                reason.append("sunset_recharge_forecast_adverse")
            elif active_mode == "morning":
                if room is not None and room >= settings["morning_target_c"]:
                    action = "would_stop"
                    reason.append("morning_target_reached")
                elif morning["expired"]:
                    action = "would_stop"
                    reason.append("morning_window_expired")
                elif not settings["morning_enabled"]:
                    action = "would_stop"
                    reason.append("morning_schedule_disabled")
                elif not morning["budget_ok"] and not morning["comfort_fallback"]:
                    action = "would_stop"
                    reason.append("morning_energy_budget_exhausted")
            elif active_mode == "solar":
                if not settings["solar_" + zone + "_enabled"] or solar["end_window"]:
                    action = "would_stop"
                    reason.append("solar_schedule_ended")
                elif room is not None and room >= settings["solar_stop_" + zone + "_c"]:
                    action = "would_stop"
                    reason.append("solar_target_reached")
                elif not solar["headroom_ok_" + zone]:
                    action = "would_stop"
                    reason.append("solar_headroom_exhausted")
                elif solar["nonsolar_elapsed_" + zone] >= settings["non_solar_delay_seconds"]:
                    action = "would_stop"
                    reason.append("grid_or_battery_draw_excessive")
    else:
        if start_mode is None:
            reason.append("no_start_demand_or_energy")
        elif not has_sensor or not healthy or not battery_safe:
            pass
        elif pv_status != "on" or pv_on_elapsed < settings["pv_on_stable_seconds"]:
            reason.append("await_favourable_PV_forecast")
        elif since < settings["min_off_seconds"]:
            reason.append("minimum_OFF_remaining_%ds" % int(settings["min_off_seconds"] - since))
        elif start_mode == "solar" and now_ts - tracker.get("last_any_ac_start", 0) < 120:
            reason.append("AC_start_stabilization")
        else:
            action = "would_start"
            proposed_mode = start_mode
            reason.append("eligible_" + start_mode)
    if action in ("would_start", "would_stop"):
        # This simulates commands for parity comparison; no commands are sent.
        current["simulated_on"] = action == "would_start"
        current["mode"] = proposed_mode if action == "would_start" else None
        current["last_transition"] = now_ts
        if action == "would_start":
            tracker["last_any_ac_start"] = now_ts
    return {
        "observed_hvac_mode": observed,
        "room_temperature_c": room,
        "target_temperature_c": (
            settings["morning_target_c"] if current.get("mode") == "morning"
            else settings["solar_stop_" + zone + "_c"]
        ),
        "simulated_on": current["simulated_on"],
        "simulated_mode": current.get("mode"),
        "recommendation": action,
        "reasons": reason,
        "seconds_in_simulated_state": round(since),
        "minimum_on_seconds": settings["min_on_seconds"],
        "minimum_off_seconds": settings["min_off_seconds"],
    }


def evaluate(states: dict, settings: dict, tracker: dict, now: datetime) -> dict:
    """Evaluate recommendations against raw HA states; mutation is simulation only."""
    now_ts = now.timestamp()
    pv_value = state(states, "pv_reachable")
    pv_true = True if pv_value == "on" else False if pv_value == "off" else None
    pv_elapsed = _stable(tracker.setdefault("stability", {}), "pv", pv_true, now_ts)
    grid = number(states, "grid_power")
    battery_w = number(states, "battery_power")
    headroom = number(states, "pv_headroom")
    soc = number(states, "soc")
    down = number(states, "down_temp")
    up = number(states, "up_temp")
    battery_temp = number(states, "battery_temp")
    schedule = settings["morning_schedule"][now.strftime("%A").lower()]
    target_time = _time_of_day(schedule, now)
    deficit = max(settings["morning_target_c"] - down, 0) if down is not None else 0
    warmup_h = deficit / max(settings["morning_warming_rate_c_per_h"], 0.01)
    lead_minutes = warmup_h * 60 + settings["morning_safety_minutes"]
    predicted_start = target_time - timedelta(minutes=lead_minutes)
    morning_window = predicted_start <= now <= target_time + timedelta(hours=2)
    predictive = predicted_start <= now < target_time and deficit > 0
    comfort = (
        settings["comfort_fallback_enabled"] and target_time <= now < target_time + timedelta(hours=2)
        and deficit >= settings["morning_fallback_deficit_c"]
        and soc is not None
        and soc > max(settings["morning_reserve_soc"], settings["absolute_min_soc"]) + 5
    )
    reserve = max(settings["morning_reserve_soc"], settings["absolute_min_soc"])
    capacity = settings["battery_capacity_kwh"]
    usable_kwh = max((soc - reserve) / 100 * capacity, 0) if soc is not None else 0
    base_energy_kwh = settings["morning_base_load_kw"] * settings["solar_recovery_hours"]
    required_kwh = warmup_h * settings["morning_ac_kw"]
    budget_kwh = max(usable_kwh - base_energy_kwh, 0)
    projected_soc = (
        soc - (base_energy_kwh + required_kwh) / capacity * 100
        if soc is not None else None
    )
    discharge_limit_w = (
        2000 if battery_temp is not None and battery_temp <= 10
        else 2500 if battery_temp is not None and battery_temp < 12
        else 5500 if battery_temp is not None else 0
    )
    budget_ok = (
        soc is not None and soc > reserve and projected_soc is not None
        and projected_soc >= reserve
        and required_kwh <= budget_kwh
        and discharge_limit_w >= settings["morning_ac_kw"] * 1000
    )
    # Grid import is positive and battery discharge is positive.
    surplus_w = (max(-(grid or 0), 0) + max(-(battery_w or 0), 0)) if (
        grid is not None and battery_w is not None
    ) else None
    h = now.hour * 60 + now.minute
    solar = {
        "within_start_window": 8 * 60 + 5 <= h < 22 * 60 + 30,
        "end_window": h >= 23 * 60,
    }
    for zone in ("down", "up"):
        solar["headroom_ok_" + zone] = (
            headroom is not None and headroom >= settings["solar_headroom_" + zone + "_kwh"]
        )
        solar["surplus_ok_" + zone] = (
            surplus_w is not None and surplus_w >= settings["solar_surplus_" + zone + "_w"]
        )
        solar["grid_ok_" + zone] = (
            grid is not None and grid <= settings["solar_max_grid_" + zone + "_w"]
        )
        solar["battery_draw_ok_" + zone] = (
            battery_w is not None and battery_w <= settings["solar_max_battery_" + zone + "_w"]
        )
        nonsolar = (
            None if grid is None or battery_w is None else
            not (solar["grid_ok_" + zone] and solar["battery_draw_ok_" + zone])
        )
        elapsed = _stable(
            tracker.setdefault("stability", {}),
            "non_solar_" + zone, nonsolar, now_ts
        )
        solar["nonsolar_elapsed_" + zone] = elapsed if nonsolar else 0
    morning = {
        "schedule_target": schedule,
        "predicted_start": predicted_start.isoformat(),
        "warmup_minutes": round(lead_minutes, 1),
        "required_ac_kwh": round(required_kwh, 3),
        "heating_energy_budget_kwh": round(budget_kwh, 3),
        "projected_soc_at_recovery": round(projected_soc, 1) if projected_soc is not None else None,
        "reserve_soc": reserve,
        "budget_ok": budget_ok,
        "window": morning_window,
        "predictive_due": predictive,
        "comfort_fallback": comfort,
        "expired": now >= target_time + timedelta(hours=2),
    }
    zones = {
        zone: _zone(
            zone, now, settings, states, tracker,
            pv_elapsed if pv_true else 0, pv_elapsed if pv_true is not True else 0,
            morning, solar
        ) for zone in ("down", "up")
    }
    ufh_demand = up is not None and up < settings["ufh_target_c"] - settings["comfort_band_c"]
    financial = {}
    for key in (
        "financial_day", "financial_week", "financial_month", "all_grid_day",
        "all_grid_week", "all_grid_month", "heat_cost"
    ):
        financial[key] = number(states, key)
    financial["source"] = "legacy_observed"
    observations = {
        key: _observation(states, key)
        for key in ENTITY_IDS if key not in (
            "financial_day", "financial_week", "financial_month", "all_grid_day",
            "all_grid_week", "all_grid_month", "heat_cost"
        )
    }
    return {
        "timestamp": now.isoformat(),
        "mode": "shadow",
        "source": "ha_core_api",
        "zones": zones,
        "ufh": {
            "demand": ufh_demand,
            "observed_switch": state(states, "ufh_switch"),
            "thermostat": state(states, "ufh_thermostat"),
            "action": "monitor_only",
        },
        "boiler": {
            "puffer_temperature_c": number(states, "puffer_temp"),
            "observed_switch": state(states, "boiler"),
            "action": "monitor_only",
            "on_below_c": 50,
            "off_above_c": 60,
        },
        "battery": {
            "soc": soc, "reserve_soc": reserve,
            "temperature_c": battery_temp,
            "discharge_limit_w": discharge_limit_w,
            "sunset_target_reachable": pv_true,
            "pv_stable_seconds": round(pv_elapsed),
            "headroom_kwh": headroom,
            "sunset_shortfall_kwh": number(states, "sunset_shortfall"),
            "surplus_w": round(surplus_w) if surplus_w is not None else None,
        },
        "rooms": {
            "down_temperature_c": down,
            "up_temperature_c": up,
            "outdoor_temperature_c": number(states, "outside_temp"),
        },
        "morning": morning,
        "solar": solar,
        "financial": financial,
        "observations": observations,
    }
