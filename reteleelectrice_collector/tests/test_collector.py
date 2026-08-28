import json
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from influx import point_to_line
from normalize import normalize_curve_payload
from portal import ReteleElectricePortal, parse_a4j_response
from run import chunk_dates, sync_window


class ParserTests(unittest.TestCase):
    def test_parse_async_response(self):
        payload = {
            "result": "OK",
            "POD": "RO00TESTPOD123456",
            "ListData": [
                {
                    "Value": ["0,100", "0,200"],
                    "ReadingType": "WI",
                    "Frequency": "15",
                    "DateT": "2026-08-10",
                }
            ],
        }
        page = (
            '<html><body><span id="j_id0:j_id2:asyncResponse">'
            + json.dumps(payload)
            + "</span></body></html>"
        )
        self.assertEqual(parse_a4j_response(page), payload)

    def test_extract_pods_recursively(self):
        value = {"items": [{"PodName": "RO00TESTPOD123456"}, {"other": "ignore"}]}
        self.assertEqual(
            ReteleElectricePortal._extract_pod_values(value), {"RO00TESTPOD123456"}
        )


class SchedulingTests(unittest.TestCase):
    def test_backfill_ends_yesterday(self):
        options = {"backfill_days": 365, "rolling_days": 7}
        start, end, mode = sync_window(options, {}, date(2026, 8, 28))
        self.assertEqual(end, date(2026, 8, 27))
        self.assertEqual(start, date(2025, 8, 28))
        self.assertEqual(mode, "backfill")

    def test_rolling_window_ends_yesterday(self):
        options = {"backfill_days": 365, "rolling_days": 7}
        start, end, mode = sync_window(
            options, {"backfill_complete": True}, date(2026, 8, 28)
        )
        self.assertEqual((start, end), (date(2026, 8, 21), date(2026, 8, 27)))
        self.assertEqual(mode, "rolling")

    def test_portal_chunks_are_at_most_31_days(self):
        chunks = list(chunk_dates(date(2026, 1, 1), date(2026, 3, 10)))
        self.assertEqual(chunks[0], (date(2026, 1, 1), date(2026, 1, 31)))
        self.assertTrue(all((end - start).days + 1 <= 31 for start, end in chunks))
        self.assertEqual(chunks[-1][1], date(2026, 3, 10))


class NormalizationTests(unittest.TestCase):
    def payload(self):
        return {
            "result": "OK",
            "POD": "RO00TESTPOD123456",
            "ListData": [
                {
                    "Value": ["0,100", "0,200"],
                    "ReadingType": "WI",
                    "Frequency": "15",
                    "DateT": "2026-08-10",
                },
                {
                    "Value": ["0,300", "0,400"],
                    "ReadingType": "WE",
                    "Frequency": "15",
                    "DateT": "2026-08-10",
                },
            ],
        }

    def test_active_curves_merge_per_timestamp(self):
        points = normalize_curve_payload(self.payload())
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[0]["import_kwh"], 0.1)
        self.assertAlmostEqual(points[0]["export_kwh"], 0.3)
        self.assertAlmostEqual(points[0]["import_avg_kw"], 0.4)
        self.assertAlmostEqual(points[0]["export_avg_kw"], 1.2)
        expected = int(datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc).timestamp())
        self.assertEqual(points[0]["timestamp"], expected)

    def test_end_timestamp_adds_one_interval(self):
        start = normalize_curve_payload(self.payload(), interval_timestamp="start")[0]["timestamp"]
        end = normalize_curve_payload(self.payload(), interval_timestamp="end")[0]["timestamp"]
        self.assertEqual(end - start, 900)

    def test_influx_line(self):
        point = normalize_curve_payload(self.payload())[0]
        line = point_to_line("reteleelectrice_meter_15m", point)
        self.assertIn("source=reteleelectrice", line)
        self.assertIn("import_kwh=0.1", line)
        self.assertIn("export_kwh=0.3", line)
        self.assertTrue(line.endswith(str(point["timestamp"])))


if __name__ == "__main__":
    unittest.main()
