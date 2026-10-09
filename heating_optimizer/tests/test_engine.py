import copy
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from engine import DEFAULT_SETTINGS, ENTITY_IDS, evaluate


TZ = ZoneInfo("Europe/Bucharest")
START = datetime(2026, 10, 9, 4, 36, tzinfo=TZ)


def source(**values):
    baseline = {
        "down_temp": "21.5",
        "up_temp": "23.6",
        "outside_temp": "10.5",
        "puffer_temp": "59.1",
        "ac_down": "off",
        "ac_up": "off",
        "boiler": "off",
        "ufh_switch": "off",
        "ufh_thermostat": "heat",
        "soc": "74",
        "battery_temp": "14",
        "battery_power": "420",
        "grid_power": "10",
        "pv_reachable": "on",
        "pv_headroom": "5.0",
        "sunset_shortfall": "0",
        "fault_down": "0",
        "fault_up": "0",
    }
    baseline.update(values)
    return {
        ENTITY_IDS[k]: {"entity_id": ENTITY_IDS[k], "state": v}
        for k, v in baseline.items()
    }


class ShadowEngineTests(unittest.TestCase):
    def setUp(self):
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.tracker = {}
        self.states = source()

    def at(self, minutes, **changed):
        states = dict(self.states)
        for key, value in changed.items():
            states[ENTITY_IDS[key]] = {"entity_id": ENTITY_IDS[key], "state": value}
        return evaluate(states, self.settings, self.tracker,
                        START + timedelta(minutes=minutes))

    def test_safely_delays_start_until_pv_is_stable(self):
        result = self.at(0)
        self.assertEqual(result["zones"]["down"]["recommendation"], "hold")
        result = self.at(3)
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_start")
        self.assertEqual(result["zones"]["down"]["simulated_mode"], "morning")
        self.assertFalse(result["ufh"]["demand"])

    def test_five_minute_pv_dropout_cannot_cycle_compressor(self):
        self.at(0)
        self.at(3)
        a = self.at(10, pv_reachable="off")
        self.assertEqual(a["zones"]["down"]["recommendation"], "hold")
        b = self.at(16, pv_reachable="off")
        self.assertEqual(b["zones"]["down"]["recommendation"], "hold")
        c = self.at(34, pv_reachable="off")
        self.assertEqual(c["zones"]["down"]["recommendation"], "would_stop")
        d = self.at(37, pv_reachable="on")
        self.assertEqual(d["zones"]["down"]["recommendation"], "hold")
        e = self.at(62, pv_reachable="on")
        self.assertEqual(e["zones"]["down"]["recommendation"], "hold")
        f = self.at(65, pv_reachable="on")
        self.assertEqual(f["zones"]["down"]["recommendation"], "would_start")

    def test_battery_reserve_can_stop_immediately(self):
        self.at(0)
        self.at(3)
        result = self.at(4, soc="20")
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_stop")
        self.assertIn("battery_reserve_guard", result["zones"]["down"]["reasons"])

    def test_unavailable_pv_prevents_start(self):
        self.at(0, pv_reachable="unavailable")
        result = self.at(3, pv_reachable="unavailable")
        self.assertEqual(result["zones"]["down"]["recommendation"], "hold")

    def test_both_zones_independent_without_solar(self):
        result = self.at(0, down_temp="23", up_temp="19")
        self.assertTrue(result["ufh"]["demand"])
        self.assertEqual(result["zones"]["up"]["recommendation"], "hold")

    def test_disabled_morning_never_starts(self):
        self.settings["morning_enabled"] = False
        self.at(0)
        result = self.at(3)
        self.assertEqual(result["zones"]["down"]["recommendation"], "hold")

    def test_sensor_failure_denies_start(self):
        self.at(0, down_temp="unavailable")
        result = self.at(3, down_temp="unavailable")
        self.assertEqual(result["zones"]["down"]["recommendation"], "hold")

    def test_solar_zone_start_after_power_headroom(self):
        noon = datetime(2026, 10, 9, 12, 0, tzinfo=TZ)
        for t in (noon, noon + timedelta(minutes=3)):
            result = evaluate(source(
                down_temp="21.8", up_temp="23", pv_reachable="on",
                battery_power="-1300", grid_power="-1500",
            ), self.settings, self.tracker, t)
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_start")
        self.assertEqual(result["zones"]["down"]["simulated_mode"], "solar")

    def test_financial_metrics_preserve_legacy_source(self):
        states = source()
        states[ENTITY_IDS["financial_week"]] = {"state": "7.25"}
        decision = evaluate(states, self.settings, self.tracker, START)
        self.assertEqual(decision["financial"]["financial_week"], 7.25)
        self.assertEqual(decision["financial"]["source"], "legacy_observed")

    def test_direct_beko_fault_bitmap_overrides_legacy_sensor(self):
        self.at(0)
        self.at(3)
        states = source(fault_down="0")
        states[ENTITY_IDS["ac_down"]]["attributes"] = {"tuya_fault_bitmap": 4}
        result = evaluate(states, self.settings, self.tracker,
                          START + timedelta(minutes=4))
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_stop")
        self.assertIn("hardware_fault", result["zones"]["down"]["reasons"])

    def test_missing_critical_telemetry_proposes_fail_safe_stop(self):
        self.at(0)
        self.at(3)
        result = self.at(4, down_temp="unavailable")
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_stop")
        self.assertIn("critical_telemetry_missing", result["zones"]["down"]["reasons"])

    def test_missing_pv_for_five_minutes_stops_after_minimum_on(self):
        self.at(0)
        self.at(3)
        self.at(10, pv_reachable="unavailable")
        result = self.at(34, pv_reachable="unavailable")
        self.assertEqual(result["zones"]["down"]["recommendation"], "would_stop")
        self.assertIn("sunset_recharge_forecast_adverse", result["zones"]["down"]["reasons"])


if __name__ == "__main__":
    unittest.main()
