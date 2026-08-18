import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from discovery import control_candidates


class DiscoveryTests(unittest.TestCase):
    def test_finds_relevant_writable_entities_and_safe_attributes(self):
        states = [
            {"entity_id": "select.ss_energy_pattern", "state": "Battery First", "attributes": {"friendly_name": "SS Energy Pattern", "options": ["Battery First", "Selling First"], "hidden": "not-returned"}},
            {"entity_id": "switch.ss_grid_charge_enabled", "state": "off", "attributes": {"friendly_name": "SS Grid Charge Enabled"}},
            {"entity_id": "sensor.ss_battery_soc", "state": "80", "attributes": {}},
            {"entity_id": "switch.unrelated_charge", "state": "off", "attributes": {}},
        ]
        result = control_candidates(states)
        self.assertEqual([item["entity_id"] for item in result], ["select.ss_energy_pattern", "switch.ss_grid_charge_enabled"])
        self.assertEqual(result[0]["attributes"]["options"], ["Battery First", "Selling First"])
        self.assertNotIn("hidden", result[0]["attributes"])


if __name__ == "__main__":
    unittest.main()
