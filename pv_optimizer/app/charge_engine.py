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
    voltage_l1: float
    voltage_l2: float
    voltage_l3: float
    battery_temperature_c: float
    forecast_remaining_kwh: float
    hours_until_sunset: float
    battery_capacity_kwh: float
    sunset_target_soc: float = 100
    charge_on_voltage: float = 249
    charge_off_voltage: float = 247
    pv_available_on_w: float = 300
    pv_available_off_w: float = 100
    forecast_safety_kwh: float = 0.5
    enabled: bool = True


def calculate_charge(values: ChargeInputs, current_request: str = "off") -> dict[str, Any]:
    maximum_voltage = max(values.voltage_l1, values.voltage_l2, values.voltage_l3)
    determining_phase = ("L1", "L2", "L3")[(values.voltage_l1, values.voltage_l2, values.voltage_l3).index(maximum_voltage)]
    current_charge_w = max(-values.battery_power_w, 0)
    available_export_w = max(-values.grid_power_w, 0)
    estimated_house_load_w = max(values.pv_power_w + values.battery_power_w + values.grid_power_w, 0)
    energy_needed_kwh = max(values.sunset_target_soc - values.battery_soc, 0) / 100 * values.battery_capacity_kwh
    expected_load_kwh = estimated_house_load_w / 1000 * max(values.hours_until_sunset, 0)
    expected_chargeable_kwh = max(values.forecast_remaining_kwh - expected_load_kwh, 0) * 0.95
    sunset_shortfall_kwh = max(energy_needed_kwh + values.forecast_safety_kwh - expected_chargeable_kwh, 0)
    blockers: list[str] = []

    if not values.enabled:
        blockers.append("charge_optimizer_disabled")
    if not values.grid_connected:
        blockers.append("grid_disconnected")
    if values.battery_temperature_c < 0:
        blockers.append("battery_too_cold")

    pv_state = "available" if values.pv_power_w >= values.pv_available_on_w else "unavailable" if values.pv_power_w <= values.pv_available_off_w else "uncertain"
    catchup_needed = sunset_shortfall_kwh > 0 and values.battery_soc < values.sunset_target_soc
    voltage_high = maximum_voltage >= values.charge_on_voltage and available_export_w > 0
    voltage_recovered = maximum_voltage <= values.charge_off_voltage

    desired_request = current_request
    reason = "Holding the previous request inside the voltage or PV hysteresis band."
    state = "holding"
    if blockers:
        desired_request = "off"
        state = "blocked"
        reason = "Charge request OFF: " + ", ".join(blockers) + "."
    elif pv_state == "unavailable":
        desired_request = "no_action"
        state = "no_action"
        reason = "No action: PV production is not available."
    elif values.battery_soc >= values.sunset_target_soc:
        desired_request = "off"
        state = "export_preferred"
        reason = "Charge request OFF: sunset SOC target is reached."
    elif catchup_needed:
        desired_request = "on"
        state = "charge_sunset_catchup"
        reason = f"Charge request ON: projected sunset shortfall is {sunset_shortfall_kwh:.2f} kWh."
    elif voltage_high:
        desired_request = "on"
        state = "charge_grid_voltage"
        reason = f"Charge request ON: {determining_phase} is {maximum_voltage:.1f} V with PV export available."
    elif voltage_recovered and pv_state == "available":
        desired_request = "off"
        state = "export_preferred"
        reason = f"Charge request OFF: maximum grid voltage recovered to {maximum_voltage:.1f} V."

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": state,
        "shadow": True,
        "desired_charge_request": desired_request,
        "current_charge_request": current_request,
        "maximum_grid_voltage": round(maximum_voltage, 2),
        "determining_phase": determining_phase,
        "pv_state": pv_state,
        "current_charge_w": round(current_charge_w),
        "available_export_w": round(available_export_w),
        "estimated_house_load_w": round(estimated_house_load_w),
        "energy_needed_by_sunset_kwh": round(energy_needed_kwh, 3),
        "expected_chargeable_before_sunset_kwh": round(expected_chargeable_kwh, 3),
        "projected_sunset_shortfall_kwh": round(sunset_shortfall_kwh, 3),
        "catchup_needed": catchup_needed,
        "blockers": blockers,
        "explanation": reason,
        "inputs": asdict(values),
    }
