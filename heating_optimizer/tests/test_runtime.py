import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
import run
from engine import DEFAULT_SETTINGS
from test_engine import source


class RuntimeTests(unittest.TestCase):
    def test_settings_validation_disallows_unsafe_timers(self):
        with self.assertRaises(ValueError):
            run.validate_settings({"min_on_seconds": 0})
        with self.assertRaises(ValueError):
            run.validate_settings({"min_off_seconds": 120})
        with self.assertRaises(ValueError):
            run.validate_settings({"morning_reserve_soc": 10})
        with self.assertRaises(ValueError):
            run.validate_settings({"solar_start_down_c": 24, "solar_stop_down_c": 23})
        self.assertEqual(run.validate_settings({})["min_on_seconds"], 1800)

    def test_addon_refuses_any_non_shadow_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "options.json").write_text('{"shadow_mode": false}')
            with self.assertRaisesRegex(RuntimeError, "requires shadow_mode"):
                run.Runtime(
                    options_path=path / "options.json",
                    settings_path=path / "settings.json",
                    state_path=path / "state.json",
                    client=MagicMock(),
                )

    def test_polls_and_saves_settings_and_shadow_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "options.json").write_text(
                json.dumps({"shadow_mode": True, "timezone": "Europe/Bucharest"})
            )
            client = MagicMock()
            client.all_states.return_value = source()
            app = run.Runtime(
                options_path=root / "options.json",
                settings_path=root / "settings.json",
                state_path=root / "state.json",
                client=client,
            )
            app.poll()
            self.assertEqual(app.get_status()["health"], "healthy")
            self.assertFalse(app.get_status()["control_enabled"])
            self.assertTrue((root / "state.json").exists())
            new = app.set_settings({"morning_target_c": 22.7})
            self.assertEqual(new["morning_target_c"], 22.7)
            self.assertEqual(
                json.loads((root / "settings.json").read_text())["morning_target_c"], 22.7
            )
            self.assertEqual(app.tracker, {})
            client.all_states.assert_called_once()

    def test_no_actuator_api_methods_exist(self):
        import ha_client
        client = ha_client.HomeAssistantClient(token="fake")
        self.assertFalse(hasattr(client, "call_service"))
        self.assertFalse(hasattr(client, "set_state"))

    def test_schedule_validator_rejects_partial_week(self):
        with self.assertRaisesRegex(ValueError, "seven weekdays"):
            run.validate_settings({"morning_schedule": {"monday": "06:00"}})
        with self.assertRaisesRegex(ValueError, "Invalid time"):
            bad = dict(DEFAULT_SETTINGS["morning_schedule"])
            bad["monday"] = "27:93"
            run.validate_settings({"morning_schedule": bad})

    def test_one_time_helper_import_includes_weekday_clock_and_zone_settings(self):
        states = {
            "input_boolean.heating_optimizer_ground_floor_ac_schedule_enabled": {"state": "on"},
            "input_number.heating_optimizer_ground_floor_morning_target": {"state": "22.6"},
            "input_number.heating_optimizer_upstairs_ac_solar_start_surplus": {"state": "1250"},
            "input_number.heating_optimizer_ground_floor_ac_solar_start_temperature": {"state": "22.0"},
        }
        for day in run.DAYS:
            states["input_datetime.heating_optimizer_morning_target_time_" + day] = {
                "state": "07:30:00"
            }
        imported = run.import_legacy_settings(states)
        self.assertTrue(imported["morning_enabled"])
        self.assertEqual(imported["morning_target_c"], 22.6)
        self.assertEqual(imported["solar_surplus_up_w"], 1250)
        self.assertEqual(imported["morning_schedule"]["monday"], "07:30")
        self.assertEqual(run.validate_settings(imported)["morning_target_c"], 22.6)

    def test_settings_form_fields_match_actual_config(self):
        import re
        from engine import DEFAULT_SETTINGS
        html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()
        fields = set(re.findall(r'name="([^"]+)"', html))
        self.assertTrue(fields)
        self.assertEqual(
            {name for name in fields if not name.startswith("schedule_")}
            - set(DEFAULT_SETTINGS),
            set(),
        )
        self.assertEqual(
            {name.removeprefix("schedule_") for name in fields if name.startswith("schedule_")},
            set(run.DAYS),
        )


if __name__ == "__main__":
    unittest.main()
