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

    def test_exposes_battery_safe_solar_headroom(self):
        result = calculate_charge(base(), "off")
        self.assertTrue(result["battery_target_reachable"])
        self.assertEqual(result["projected_sunset_shortfall_kwh"], 0)
        self.assertAlmostEqual(result["available_solar_headroom_kwh"], 36.862, places=3)

    def test_shortfall_blocks_battery_target_reachable_and_headroom(self):
        result = calculate_charge(base(forecast_remaining_kwh=2, battery_soc=50), "off")
        self.assertFalse(result["battery_target_reachable"])
        self.assertEqual(result["available_solar_headroom_kwh"], 0)
        self.assertGreater(result["projected_sunset_shortfall_kwh"], 0)

    def test_already_reached_target_is_reachable(self):
        result = calculate_charge(base(battery_soc=100, forecast_remaining_kwh=0), "on")
        self.assertTrue(result["battery_target_reachable"])


    def test_heating_load_is_only_projected_until_room_target(self):
        result = calculate_charge(base(
            battery_soc=74,
            forecast_remaining_kwh=18.252,
            hours_until_sunset=13,
            pv_power_w=0,
            battery_power_w=1050,
            grid_power_w=0,
            baseline_house_load_w=450,
            heating_active=True,
            heating_hours_until_target=1.25,
        ), "off")
        self.assertTrue(result["battery_target_reachable"])
        self.assertAlmostEqual(result["expected_house_load_kwh"], 6.6, places=2)
        self.assertAlmostEqual(result["heating_hours_until_target"], 1.25)
        self.assertEqual(result["baseline_house_load_w"], 450)

    def test_after_target_only_baseline_is_used(self):
        result = calculate_charge(base(
            pv_power_w=0,
            battery_power_w=1100,
            grid_power_w=0,
            hours_until_sunset=10,
            baseline_house_load_w=400,
            heating_active=True,
            heating_hours_until_target=0,
        ), "off")
        self.assertAlmostEqual(result["expected_house_load_kwh"], 4.0)

    def test_heating_window_is_bounded_by_sunset(self):
        result = calculate_charge(base(
            pv_power_w=0,
            battery_power_w=1200,
            grid_power_w=0,
            hours_until_sunset=2,
            baseline_house_load_w=450,
            heating_active=True,
            heating_hours_until_target=8,
        ), "off")
        self.assertEqual(result["heating_hours_until_target"], 2)
        self.assertAlmostEqual(result["expected_house_load_kwh"], 2.4)

    def test_heater_off_projects_household_average_only(self):
        result = calculate_charge(base(
            pv_power_w=0,
            battery_power_w=1200,
            grid_power_w=0,
            baseline_house_load_w=450,
            heating_active=False,
            heating_hours_until_target=4,
            hours_until_sunset=12,
        ), "off")
        self.assertEqual(result["heating_hours_until_target"], 0)
        self.assertAlmostEqual(result["expected_house_load_kwh"], 5.4)


if __name__ == "__main__":
    unittest.main()
