import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from charge_engine import ChargeInputs, calculate_charge


def base(**changes):
    values = dict(
        battery_soc=60,
        battery_power_w=-1000,
        grid_power_w=-2000,
        pv_power_w=5000,
        grid_connected=True,
        sun_below_horizon=False,
        voltage_l1=249,
        voltage_l2=247,
        voltage_l3=246,
        battery_temperature_c=15,
    )
    values.update(changes)
    return ChargeInputs(**values)


class ChargeEngineTests(unittest.TestCase):
    def test_warning_voltage_recommends_bounded_charge(self):
        result = calculate_charge(base())
        self.assertEqual(result["state"], "charge_recommended")
        self.assertEqual(result["target_charge_w"], 1600)
        self.assertEqual(result["voltage_state"], "warning")

    def test_critical_voltage_uses_available_export(self):
        result = calculate_charge(base(voltage_l1=252))
        self.assertEqual(result["target_charge_w"], 3000)
        self.assertEqual(result["voltage_state"], "critical")

    def test_temperature_limits_charge(self):
        result = calculate_charge(base(voltage_l1=252, battery_temperature_c=8, grid_power_w=-5000))
        self.assertEqual(result["target_charge_w"], 2000)
        self.assertEqual(result["thermal_charge_limit_w"], 2000)

    def test_night_blocks_charge_optimization(self):
        result = calculate_charge(base(sun_below_horizon=True))
        self.assertEqual(result["target_charge_w"], 0)
        self.assertIn("outside_day_window", result["blockers"])

    def test_full_battery_blocks_charge_optimization(self):
        result = calculate_charge(base(battery_soc=96))
        self.assertIn("maximum_charge_soc_reached", result["blockers"])


if __name__ == "__main__":
    unittest.main()
