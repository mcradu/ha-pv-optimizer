import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
