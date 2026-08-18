from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ChargeInputs:
    battery_soc: float
    battery_power_w: float
    grid_power_w: float
    pv_power_w: float
    grid_connected: bool
    sun_below_horizon: bool
    voltage_l1: float
    voltage_l2: float
    voltage_l3: float
    battery_temperature_c: float
    warning_voltage: float = 248
    critical_voltage: float = 251
    maximum_soc: float = 95
    enabled: bool = True


def calculate_charge(values: ChargeInputs) -> dict[str, Any]:
    maximum_voltage = max(values.voltage_l1, values.voltage_l2, values.voltage_l3)
    current_charge_w = max(-values.battery_power_w, 0)
    available_export_w = max(-values.grid_power_w, 0)
    thermal_limit_w = _thermal_limit(values.battery_temperature_c)
    blockers: list[str] = []

    if not values.enabled:
        blockers.append("charge_optimizer_disabled")
    if not values.grid_connected:
        blockers.append("grid_disconnected")
    if values.sun_below_horizon:
        blockers.append("outside_day_window")
    if values.battery_soc >= values.maximum_soc:
        blockers.append("maximum_charge_soc_reached")
    if thermal_limit_w == 0:
        blockers.append("battery_too_cold")

    target_w = 0
    reason = "Voltage is below the charging intervention threshold."
    voltage_state = "normal"
    if maximum_voltage >= values.critical_voltage:
        voltage_state = "critical"
    elif maximum_voltage >= values.warning_voltage:
        voltage_state = "warning"

    if not blockers and voltage_state != "normal" and available_export_w > 0:
        desired_w = current_charge_w + available_export_w
        if voltage_state == "warning":
            span = max(values.critical_voltage - values.warning_voltage, 0.1)
            factor = min(max((maximum_voltage - values.warning_voltage) / span, 0.25), 1)
            desired_w = current_charge_w + available_export_w * factor
        target_w = int(min(max(desired_w, current_charge_w), thermal_limit_w) // 100 * 100)
        reason = (
            f"Recommend {target_w} W total battery charging to absorb PV export while "
            f"grid voltage is {maximum_voltage:.1f} V."
        )
    elif not blockers and voltage_state != "normal":
        reason = "Grid voltage is high, but there is no exported PV power available to redirect."

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": "blocked" if blockers else ("charge_recommended" if target_w else "monitoring"),
        "shadow": True,
        "target_charge_w": target_w,
        "current_charge_w": round(current_charge_w),
        "available_export_w": round(available_export_w),
        "maximum_grid_voltage": round(maximum_voltage, 2),
        "voltage_state": voltage_state,
        "thermal_charge_limit_w": thermal_limit_w,
        "blockers": blockers,
        "explanation": "No charge intervention: " + ", ".join(blockers) + "." if blockers else reason,
        "inputs": asdict(values),
    }


def _thermal_limit(temperature_c: float) -> int:
    if temperature_c < 0:
        return 0
    if temperature_c <= 10:
        return 2000
    if temperature_c < 12:
        return 2500
    return 5500
