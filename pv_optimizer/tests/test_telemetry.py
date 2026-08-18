import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from telemetry import InfluxTelemetry, _line_protocol


OPTIONS = {
    "influxdb_enabled": True,
    "influxdb_url": "http://influxdb:8086",
    "influxdb_database": "home_assistant",
    "influxdb_retention_policy": "one_year",
    "influxdb_measurement": "pv_optimizer_charge",
    "influxdb_username": "",
    "influxdb_password": "",
}


class TelemetryTests(unittest.TestCase):
    def test_line_protocol_contains_tags_fields_and_timestamp(self):
        line = _line_protocol(
            "pv_optimizer_charge",
            {"request": "on", "state": "charge grid"},
            {"voltage_l1": "249.3", "transitioned": True, "reason": "high voltage"},
            "2026-08-18T12:00:00+00:00",
        )
        self.assertIn("request=on", line)
        self.assertIn("state=charge\\ grid", line)
        self.assertIn("voltage_l1=249.3", line)
        self.assertIn('reason="high voltage"', line)

    def test_successful_write_keeps_recent_memory(self):
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        with patch("telemetry.urlopen", return_value=response) as mocked:
            store = InfluxTelemetry(OPTIONS)
            store.append({"timestamp": "2026-08-18T12:00:00+00:00", "request": "off", "state": "export_preferred", "pv_w": 3000})
            self.assertEqual(store.latest(1)[0]["request"], "off")
            self.assertEqual(store.last_error, "")
            self.assertIn("db=home_assistant", mocked.call_args.args[0].full_url)
            self.assertIn("rp=one_year", mocked.call_args.args[0].full_url)

    def test_write_failure_does_not_raise(self):
        with patch("telemetry.urlopen", side_effect=URLError("offline")):
            store = InfluxTelemetry(OPTIONS)
            store.append({"timestamp": "2026-08-18T12:00:00+00:00", "request": "off", "pv_w": 0})
            self.assertIn("InfluxDB connection failed", store.last_error)
            self.assertEqual(store.latest(1)[0]["request"], "off")

    def test_night_measurement_and_fields(self):
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        options = {**OPTIONS, "influxdb_night_measurement": "pv_optimizer_night_injection"}
        with patch("telemetry.urlopen", return_value=response) as mocked:
            store = InfluxTelemetry(options, measurement_option="influxdb_night_measurement", default_measurement="pv_optimizer_night_injection")
            store.append({
                "timestamp": "2026-08-18T20:00:00+00:00",
                "request": "export",
                "state": "exporting_shadow",
                "mode": "auto",
                "target_export_w": 1200,
                "stop_soc": 60,
                "blockers": [],
                "reason": "night surplus",
            })
            body = mocked.call_args.args[0].data.decode()
            self.assertTrue(body.startswith("pv_optimizer_night_injection,"))
            self.assertIn("target_export_w=1200.0", body)
            self.assertIn("stop_soc=60.0", body)


if __name__ == "__main__":
    unittest.main()
