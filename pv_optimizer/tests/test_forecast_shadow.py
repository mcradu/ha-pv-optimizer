import unittest
from datetime import datetime, timedelta, timezone
from app.forecast_shadow import compare_shadow, integrate
UTC = timezone.utc


def payload(now, watts=500, hours=49):
    hour = now.replace(minute=0, second=0, microsecond=0)
    return {
        "generated_at": now.isoformat(),
        "status": "ready",
        "backtest": {"daily_mape_pct": 10, "evaluated_days": 20},
        "points": [
            {"valid_hour_utc": (hour + timedelta(hours=i)).isoformat(),
             "p50_w": watts, "upper_w": watts + 200,
             "confidence": "high"}
            for i in range(hours)
        ],
    }


class ForecastShadowTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 10, 30, tzinfo=UTC)

    def test_fractional_sunset_integral(self):
        res = integrate(payload(self.now)["points"], self.now, self.now + timedelta(hours=2))
        self.assertAlmostEqual(res["expected_kwh"], 1.0, places=3)
        self.assertAlmostEqual(res["upper_kwh"], 1.4, places=3)

    def test_day_comparison_is_shadow_only(self):
        res = compare_shadow(payload(self.now), self.now, None,
                             self.now + timedelta(hours=4), False, 1.7, 800)
        self.assertFalse(res["used_for_control"])
        self.assertEqual(res["next_sunset"]["expected_kwh"], 2.0)
        self.assertEqual(res["next_sunset"]["delta_vs_legacy_kwh"], 0.3)
        self.assertIsNone(res["next_sunrise"])

    def test_night_compares_configured_static_load(self):
        res = compare_shadow(payload(self.now), self.now, self.now + timedelta(hours=3),
                             None, True, None, 800)
        self.assertEqual(res["next_sunrise"]["legacy_kwh"], 2.4)
        self.assertEqual(res["next_sunrise"]["expected_kwh"], 1.5)

    def test_stale_payload_is_rejected(self):
        old = payload(self.now - timedelta(hours=2))
        with self.assertRaisesRegex(ValueError, "Stale"):
            compare_shadow(old, self.now, None, self.now + timedelta(hours=2), False, 1, 800)

    def test_missing_target_hour_is_not_zero(self):
        altered = payload(self.now)
        altered["points"].pop(2)
        self.assertIsNone(integrate(altered["points"], self.now, self.now + timedelta(hours=4)))

    def test_upper_power_must_exceed_expected(self):
        altered = payload(self.now)
        altered["points"][0]["upper_w"] = 10
        with self.assertRaisesRegex(ValueError, "Upper forecast"):
            integrate(altered["points"], self.now, self.now + timedelta(hours=2))

    def test_low_quality_does_not_produce_control_grade_projection(self):
        altered = payload(self.now)
        altered["points"][0]["confidence"] = "low"
        with self.assertRaisesRegex(ValueError, "low-confidence"):
            compare_shadow(altered, self.now, None, self.now + timedelta(hours=2), False, 1, 800)

    def test_dst_fall_back_uses_distinct_utc_hours(self):
        utc_start = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        value = integrate(payload(utc_start)["points"], utc_start, utc_start + timedelta(hours=2))
        self.assertEqual(value["hours"], 2.0)


if __name__ == "__main__":
    unittest.main()
