import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from engine import Inputs, calculate


def base(**changes):
    values = dict(
        battery_soc=90,
        grid_connected=True,
        sun_below_horizon=True,
        hours_until_sunrise=10,
        forecast_kwh=25,
        battery_capacity_kwh=20,
        minimum_morning_soc=45,
        safety_margin_soc=3,
        hysteresis_soc=5,
        night_load_w=800,
        night_min_w=200,
        night_max_w=1200,
        enabled=True,
    )
    values.update(changes)
    return Inputs(**values)


class EngineTests(unittest.TestCase):
    def test_normal_target_is_bounded(self):
        result = calculate(base())
        self.assertEqual(result["stop_soc"], 88)
        self.assertEqual(result["target_export_w"], 200)
        self.assertEqual(result["state"], "exporting_shadow")

    def test_disconnected_grid_blocks(self):
        result = calculate(base(grid_connected=False))
        self.assertEqual(result["target_export_w"], 0)
        self.assertIn("grid_disconnected", result["blockers"])

    def test_night_max_is_limited(self):
        result = calculate(base(battery_soc=100, hours_until_sunrise=2, night_max_w=1100), "night_max")
        self.assertEqual(result["target_export_w"], 1100)

    def test_stop_mode_is_zero(self):
        result = calculate(base(battery_soc=100), "stop")
        self.assertEqual(result["target_export_w"], 0)

    def test_soc_floor_blocks(self):
        result = calculate(base(battery_soc=60))
        self.assertIn("stop_soc_reached", result["blockers"])


if __name__ == "__main__":
    unittest.main()
