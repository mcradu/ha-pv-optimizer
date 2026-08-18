import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from charge_engine import ChargeInputs, calculate_charge


def base(**changes):
    values = dict(
        battery_soc=60,
        battery_power_w=0,
        grid_power_w=-2000,
        pv_power_w=3000,
        grid_connected=True,
        voltage_l1=246,
        voltage_l2=245,
        voltage_l3=244,
        battery_temperature_c=15,
        forecast_remaining_kwh=50,
        hours_until_sunset=5,
        battery_capacity_kwh=20,
    )
    values.update(changes)
    return ChargeInputs(**values)


class ChargeEngineTests(unittest.TestCase):
    def test_recovered_voltage_prefers_export(self):
        result = calculate_charge(base(), "on")
        self.assertEqual(result["desired_charge_request"], "off")
        self.assertEqual(result["state"], "export_preferred")

    def test_high_voltage_requests_charge(self):
        result = calculate_charge(base(voltage_l1=249.2), "off")
        self.assertEqual(result["desired_charge_request"], "on")
        self.assertEqual(result["state"], "charge_grid_voltage")
        self.assertEqual(result["determining_phase"], "L1")

    def test_sunset_shortfall_requests_charge(self):
        result = calculate_charge(base(forecast_remaining_kwh=2, battery_soc=50), "off")
        self.assertEqual(result["desired_charge_request"], "on")
        self.assertEqual(result["state"], "charge_sunset_catchup")

    def test_no_pv_means_no_action(self):
        result = calculate_charge(base(pv_power_w=50, grid_power_w=100), "on")
        self.assertEqual(result["desired_charge_request"], "no_action")
        self.assertEqual(result["state"], "no_action")

    def test_target_soc_requests_off(self):
        result = calculate_charge(base(battery_soc=100), "on")
        self.assertEqual(result["desired_charge_request"], "off")

    def test_grid_charge_is_never_part_of_decision(self):
        result = calculate_charge(base(voltage_l1=252), "off")
        self.assertNotIn("target_charge_w", result)
        self.assertNotIn("thermal_charge_limit_w", result)


if __name__ == "__main__":
    unittest.main()
