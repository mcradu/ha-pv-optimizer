import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from telemetry import TelemetryStore


class TelemetryTests(unittest.TestCase):
    def test_persists_and_reloads_recent_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            store = TelemetryStore(path, recent_limit=2)
            store.append({"timestamp": "one", "request": "off"})
            store.append({"timestamp": "two", "request": "on"})
            reloaded = TelemetryStore(path, recent_limit=2)
            self.assertEqual(reloaded.latest(), [
                {"timestamp": "one", "request": "off"},
                {"timestamp": "two", "request": "on"},
            ])


if __name__ == "__main__":
    unittest.main()
