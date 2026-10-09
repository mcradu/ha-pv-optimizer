import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))


class RuntimeTests(unittest.TestCase):
    def test_old_options_gain_new_default_entities(self):
        with tempfile.TemporaryDirectory() as directory:
            options = Path(directory) / "options.json"
            options.write_text(json.dumps({"entities": {"battery_soc": "sensor.custom_soc"}}))
            import run
            loaded = run.Runtime._load_json(options, run.DEFAULTS)
            self.assertEqual(loaded["entities"]["battery_soc"], "sensor.custom_soc")
            self.assertEqual(loaded["entities"]["grid_voltage_l1"], "sensor.ss_grid_l1_voltage")
            self.assertEqual(loaded["export_price_ron_per_kwh"], 0.11)

    def test_poll_without_supervisor_is_blocked_not_crashed(self):
        with tempfile.TemporaryDirectory() as directory:
            options = Path(directory) / "options.json"
            state = Path(directory) / "state.json"
            with patch.dict(os.environ, {}, clear=True):
                import run
                with patch.object(run, "OPTIONS_PATH", options), patch.object(run, "STATE_PATH", state):
                    runtime = run.Runtime()
                    runtime.poll()
                    self.assertEqual(runtime.status["decision"]["state"], "blocked")
                    self.assertEqual(runtime.status["decision"]["target_export_w"], 0)
                    self.assertTrue(runtime.status["errors"])
                    self.assertFalse(runtime.status["diagnostics"]["supervisor_token_present"])

    def test_legacy_hassio_token_is_supported(self):
        with patch.dict(os.environ, {"HASSIO_TOKEN": "test-token"}, clear=True):
            import ha_client
            client = ha_client.HomeAssistantClient()
            self.assertEqual(client.token, "test-token")
            self.assertEqual(client.token_source, "HASSIO_TOKEN")

    def test_night_events_are_deduplicated(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.state = {"logs": []}
        runtime.add_log = lambda message: runtime.state["logs"].append(message)
        runtime.save_state = lambda: None
        record = {
            "state": "exporting_shadow",
            "target_export_w": 1200,
            "stop_soc": 60,
            "blockers": [],
            "mode": "auto",
            "reason": "night surplus",
        }
        runtime._log_night_transition(record)
        runtime._log_night_transition(record)
        self.assertEqual(len(runtime.state["logs"]), 1)

    def test_energy_interface_is_published_to_home_assistant(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.options = {
            "sunset_target_soc": 100,
            "forecast_safety_kwh": 0.5,
            "export_price_ron_per_kwh": 0.11,
            "import_price_ron_per_kwh": 1.36463,
        }
        runtime.client = MagicMock()
        runtime._publish_energy_interface({
            "available_solar_headroom_kwh": 4.2,
            "projected_sunset_shortfall_kwh": 0,
            "battery_target_reachable": True,
        })
        self.assertEqual(runtime.client.set_state.call_count, 5)
        calls = {call.args[0]: call.args for call in runtime.client.set_state.call_args_list}
        self.assertEqual(calls["sensor.pv_optimizer_export_price"][1], 0.11)
        self.assertEqual(calls["sensor.pv_optimizer_import_price"][1], 1.36463)
        self.assertEqual(calls["sensor.pv_optimizer_available_solar_headroom"][1], 4.2)
        self.assertEqual(calls["sensor.pv_optimizer_projected_sunset_shortfall"][1], 0)
        self.assertEqual(calls["binary_sensor.pv_optimizer_battery_target_reachable"][1], "on")


    def test_heating_phase_uses_room_target_and_excludes_ac_from_baseline(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.options = {
            "baseline_window_minutes": 180,
            "baseline_min_samples": 1,
            "baseline_fallback_w": 450,
        }
        runtime.state = {}
        runtime.save_state = MagicMock()
        entities = {
            "ac_down": {"state": "off"},
            "ac_up": {"state": "off"},
            "ufh_active": {"state": "off"},
            "ground_floor_temperature": {"state": "21.5"},
            "ground_floor_morning_target": {"state": "22.5"},
            "ground_floor_solar_target": {"state": "23.0"},
            "ground_floor_warming_rate": {"state": "0.8"},
            "ground_floor_solar_active": {"state": "off"},
        }
        with patch.object(run.time, "time", return_value=100000):
            baseline, horizon, active = runtime._baseline_and_heating_horizon(entities, 420, 13)
        self.assertEqual((baseline, horizon, active), (420, 0, False))
        self.assertEqual(len(runtime.state["baseline_load_samples"]), 1)

        entities["ac_down"]["state"] = "heat"
        with patch.object(run.time, "time", return_value=100030):
            baseline, horizon, active = runtime._baseline_and_heating_horizon(entities, 1100, 13)
        self.assertEqual((baseline, horizon, active), (420, 1.25, True))
        self.assertEqual(len(runtime.state["baseline_load_samples"]), 1)

        entities["ac_down"]["state"] = "off"
        with patch.object(run.time, "time", return_value=100090):
            runtime._baseline_and_heating_horizon(entities, 1100, 13)
        self.assertEqual(len(runtime.state["baseline_load_samples"]), 1)

    def test_solar_mode_uses_solar_stop_temperature(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.options = {
            "baseline_window_minutes": 180,
            "baseline_min_samples": 2,
            "baseline_fallback_w": 450,
        }
        runtime.state = {}
        runtime.save_state = MagicMock()
        entities = {
            "ac_down": {"state": "heat"},
            "ac_up": {"state": "off"},
            "ufh_active": {"state": "off"},
            "ground_floor_temperature": {"state": "22.0"},
            "ground_floor_morning_target": {"state": "22.5"},
            "ground_floor_solar_target": {"state": "23.0"},
            "ground_floor_warming_rate": {"state": "0.5"},
            "ground_floor_solar_active": {"state": "on"},
        }
        with patch.object(run.time, "time", return_value=100000):
            baseline, horizon, active = runtime._baseline_and_heating_horizon(entities, 1200, 13)
        self.assertEqual((baseline, horizon, active), (450, 2.0, True))

    def test_default_baseline_window_is_full_day(self):
        import run
        self.assertEqual(run.DEFAULTS["baseline_window_minutes"], 1440)

    def test_legacy_180_minute_config_is_upgraded_at_runtime(self):
        import run
        with tempfile.TemporaryDirectory() as directory:
            options = Path(directory) / "options.json"
            state = Path(directory) / "state.json"
            options.write_text(json.dumps({
                "shadow_mode": True,
                "baseline_window_minutes": 180
            }))
            with patch.object(run, "OPTIONS_PATH", options), patch.object(run, "STATE_PATH", state):
                runtime = run.Runtime()
        self.assertEqual(runtime.options["baseline_window_minutes"], 1440)

    def test_24h_samples_not_limited_to_720_and_outside_day_excluded(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.options = {
            "baseline_window_minutes": 180,   # Old, persisted setting.
            "baseline_min_samples": 12,
            "baseline_fallback_w": 450,
            "poll_interval_seconds": 30,
        }
        now = 1000000
        # One sample every 30s across the last 24h, plus one older
        # sample that must be removed.
        samples = [
            [now - 86430, 9999],
            *[[now - 86370 + i * 30, 400 + (i // 120) * 3]
              for i in range(2878)]
        ]
        runtime.state = {"baseline_load_samples": samples}
        runtime.save_state = MagicMock()
        entities = {
            "ac_down": {"state": "heat"},
            "ac_up": {"state": "off"},
            "ufh_active": {"state": "off"},
            "ground_floor_temperature": {"state": "22.0"},
            "ground_floor_morning_target": {"state": "22.5"},
            "ground_floor_solar_target": {"state": "23.0"},
            "ground_floor_warming_rate": {"state": "0.8"},
            "ground_floor_solar_active": {"state": "off"},
        }
        with patch.object(run.time, "time", return_value=now):
            baseline, horizon, active = runtime._baseline_and_heating_horizon(
                entities, 1200, 12
            )
        self.assertTrue(active)
        self.assertGreater(len(runtime.state["baseline_load_samples"]), 2800)
        self.assertNotIn([now - 86430, 9999], runtime.state["baseline_load_samples"])
        self.assertEqual(runtime.state["baseline_covered_hours"], 24)
        self.assertGreater(runtime.state["baseline_oldest_sample_age_h"], 23)
        self.assertGreater(baseline, 400)
        self.assertLess(baseline, 500)

    def test_hour_balanced_average_not_biased_by_high_frequency_polling(self):
        import run
        runtime = object.__new__(run.Runtime)
        runtime.options = {
            "baseline_window_minutes": 1440,
            "baseline_min_samples": 12,
            "baseline_fallback_w": 450,
            "poll_interval_seconds": 5,
        }
        now = 1000000
        # 200 samples near now at 1000 W, 12 samples 13h ago
        # at 200 W. Arithmetic point average would be ~955 W;
        # equal-hour average is 600 W.
        samples = [
            *[[now - 2*i - 10, 1000] for i in range(200)],
            *[[now - 13*3600 - 30*i, 200] for i in range(12)],
        ]
        runtime.state = {"baseline_load_samples": samples}
        runtime.save_state = MagicMock()
        entities = {"ac_down": {"state": "heat"}, "ac_up": {"state": "off"},
                    "ufh_active": {"state": "off"},
                    "ground_floor_temperature": {"state": "22"},
                    "ground_floor_morning_target": {"state": "22.5"},
                    "ground_floor_warming_rate": {"state": "0.8"},
                    "ground_floor_solar_active": {"state": "off"}}
        with patch.object(run.time, "time", return_value=now):
            baseline, _, _ = runtime._baseline_and_heating_horizon(entities, 1300, 13)
        self.assertAlmostEqual(baseline, 600, places=0)
        self.assertEqual(runtime.state["baseline_covered_hours"], 2)


if __name__ == "__main__":
    unittest.main()
