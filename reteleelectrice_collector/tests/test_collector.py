import json
import sys
import unittest
from unittest.mock import Mock, patch
from datetime import date, datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from influx import InfluxError, InfluxWriter, meter_index_to_line, point_to_line
from normalize import normalize_curve_payload
from portal import ReteleElectricePortal, parse_a4j_response
from run import (
    PortalRateLimitError,
    backfill_start_for_pod,
    chunk_dates,
    data_freshness,
    latest_meter_index,
    meter_indexes,
    latest_source_day,
    portal_request_status,
    reserve_portal_request,
    resolve_latest_timestamp,
    seconds_until_scheduled_sync,
    sync_window,
)


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

    def test_reading_archive_service_uses_dedicated_vf_page_and_identity(self):
        portal = ReteleElectricePortal("user", "password")
        portal._call_vf_ws_async = Mock(return_value={"result": "OK"})

        result = portal.get_reading_archive(
            "RO00TESTPOD123456",
            "PERSON-ID",
            "",
            date(2026, 8, 1),
            date(2026, 9, 28),
        )

        self.assertEqual(result, {"result": "OK"})
        portal._call_vf_ws_async.assert_called_once_with(
            "RetriveSingleSelf",
            [
                "",
                "",
                "PERSON-ID",
                "RO00TESTPOD123456",
                "01/08/2026 00:00:00",
                "28/09/2026 23:59:59",
            ],
            vf_page_name="PED_ProxyCallWSAsynSingleSelf_VF",
        )

    def test_a4j_parser_accepts_cdata_json(self):
        page = '<partial-response><![CDATA[{"result":"OK","XML_Readings":[]}]]></partial-response>'
        self.assertEqual(
            parse_a4j_response(page),
            {"result": "OK", "XML_Readings": []},
        )

    def test_meter_indexes_returns_sorted_history_and_prefers_real_reading(self):
        payload = {
            "XML_Readings": [
                {
                    "typeOfReading": "estimated",
                    "SerialNumber": "TEST-METER",
                    "meter": [
                        {"Value": "12000", "typeofenergy_measured": "EA"},
                        {"Value": "6000", "typeofenergy_measured": "EAP"},
                    ],
                    "measureDate": "01.09.2026",
                    "constanta": "1",
                },
                {
                    "typeOfReading": "real",
                    "SerialNumber": "TEST-METER",
                    "meter": [
                        {"Value": "12001", "typeofenergy_measured": "EA"},
                        {"Value": "6001", "typeofenergy_measured": "EAP"},
                    ],
                    "measureDate": "01.09.2026",
                    "constanta": "1",
                },
                {
                    "typeOfReading": "real",
                    "SerialNumber": "TEST-METER",
                    "meter": [
                        {"Value": "12050", "typeofenergy_measured": "EA"},
                        {"Value": "6300", "typeofenergy_measured": "EAP"},
                    ],
                    "measureDate": "16.09.2026",
                    "constanta": "1",
                },
            ]
        }

        readings = meter_indexes(
            payload,
            "RO00TESTPOD123456",
            "Europe/Bucharest",
        )

        self.assertEqual([item["measure_date"] for item in readings], ["01.09.2026", "16.09.2026"])
        self.assertEqual(readings[0]["reading_type"], "real")
        self.assertEqual(readings[0]["import_index_kwh"], 12001.0)
        self.assertEqual(readings[0]["export_index_kwh"], 6001.0)

    def test_latest_meter_index_maps_ea_to_import_and_eap_to_export(self):
        payload = {
            "XML_Readings": [
                {
                    "typeOfReading": "real",
                    "SerialNumber": "TEST-METER",
                    "meter": [
                        {"Value": "12345", "typeofenergy_measured": "EA"},
                        {"Value": "6789", "typeofenergy_measured": "EAP"},
                    ],
                    "measureDate": "16.09.2026",
                    "constanta": "1",
                },
                {
                    "typeOfReading": "real",
                    "SerialNumber": "TEST-METER",
                    "meter": [
                        {"Value": "12300", "typeofenergy_measured": "EA"},
                        {"Value": "6500", "typeofenergy_measured": "EAP"},
                    ],
                    "measureDate": "01.09.2026",
                    "constanta": "1",
                },
            ]
        }

        reading = latest_meter_index(
            payload,
            "RO00TESTPOD123456",
            "Europe/Bucharest",
        )

        self.assertIsNotNone(reading)
        self.assertEqual(reading["measure_date"], "16.09.2026")
        self.assertEqual(reading["reading_type"], "real")
        self.assertEqual(reading["meter_serial"], "TEST-METER")
        self.assertAlmostEqual(reading["import_index_kwh"], 12345.0)
        self.assertAlmostEqual(reading["export_index_kwh"], 6789.0)

class SchedulingTests(unittest.TestCase):
    def test_backfill_ends_yesterday(self):
        options = {"backfill_days": 365, "rolling_days": 7}
        start, end, mode = sync_window(options, {}, date(2026, 8, 28))
        self.assertEqual(end, date(2026, 8, 27))
        self.assertEqual(start, date(2025, 8, 28))
        self.assertEqual(mode, "backfill")

    def test_rolling_window_ends_yesterday(self):
        options = {
            "backfill_days": 365,
            "rolling_days": 7,
            "timezone": "Europe/Bucharest",
            "interval_timestamp": "start",
        }
        start, end, mode = sync_window(
            options, {"backfill_complete": True}, date(2026, 8, 28)
        )
        self.assertEqual((start, end), (date(2026, 8, 21), date(2026, 8, 27)))
        self.assertEqual(mode, "rolling")

    def test_rolling_window_catches_up_from_latest_persisted_day(self):
        options = {
            "backfill_days": 365,
            "rolling_days": 7,
            "timezone": "Europe/Bucharest",
            "interval_timestamp": "start",
        }
        state = {
            "backfill_complete": True,
            "latest_data_timestamp": "2026-09-14T20:45:00+00:00",
        }
        start, end, mode = sync_window(options, state, date(2026, 9, 24))
        self.assertEqual((start, end), (date(2026, 9, 15), date(2026, 9, 23)))
        self.assertEqual(mode, "catchup")

    def test_interval_end_timestamp_maps_to_previous_source_day(self):
        state = {"latest_data_timestamp": "2026-09-15T21:00:00+00:00"}
        self.assertEqual(
            latest_source_day(state, "Europe/Bucharest", "end"),
            date(2026, 9, 15),
        )

    def test_portal_chunks_are_at_most_31_days(self):
        chunks = list(chunk_dates(date(2026, 1, 1), date(2026, 3, 10)))
        self.assertEqual(chunks[0], (date(2026, 1, 1), date(2026, 1, 31)))
        self.assertTrue(all((end - start).days + 1 <= 31 for start, end in chunks))
        self.assertEqual(chunks[-1][1], date(2026, 3, 10))

    def test_request_budget_is_sliding_24_hours(self):
        now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
        state = {
            "portal_request_history": [
                "2026-09-23T07:59:59+00:00",
                "2026-09-23T08:00:01+00:00",
                "2026-09-24T07:00:00+00:00",
            ]
        }
        status = portal_request_status(state, 8, now=now)
        self.assertEqual(status["portal_requests_24h"], 2)
        self.assertEqual(status["portal_requests_remaining"], 6)

    def test_request_budget_stops_before_ninth_reserved_call(self):
        now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
        state = {
            "portal_request_history": [
                f"2026-09-24T0{hour}:00:00+00:00" for hour in range(8)
            ]
        }
        with patch("run.save_state"):
            with self.assertRaises(PortalRateLimitError):
                reserve_portal_request(state, 8, now=now)

    def test_restart_guard_waits_until_24h_interval_is_due(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        state = {"last_sync_attempt": "2026-09-24T06:00:00+00:00"}
        self.assertEqual(
            seconds_until_scheduled_sync(state, 1440, now=now),
            18 * 3600,
        )

    def test_backfill_cursor_resumes_after_last_completed_chunk(self):
        state = {
            "backfill_cursor_by_pod": {
                "RO00TESTPOD123456": "2026-02-01",
            }
        }
        self.assertEqual(
            backfill_start_for_pod(
                state,
                "RO00TESTPOD123456",
                date(2026, 1, 1),
                date(2026, 12, 31),
            ),
            date(2026, 2, 1),
        )

    def test_data_freshness_uses_configured_threshold(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        fresh = data_freshness("2026-09-14T23:45:00+00:00", 5, now=now)
        stale = data_freshness("2026-09-11T23:45:00+00:00", 5, now=now)
        self.assertTrue(fresh["data_fresh"])
        self.assertFalse(stale["data_fresh"])
        self.assertEqual(fresh["data_age_days"], 2.51)


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


class InfluxTests(unittest.TestCase):
    def test_meter_index_line_persists_validated_registers(self):
        reading = {
            "pod": "RO00TESTPOD123456",
            "timestamp": 1789506000,
            "measure_date": "16.09.2026",
            "reading_type": "real",
            "meter_serial": "TEST-METER",
            "constant": "1",
            "import_index_kwh": 12345.0,
            "export_index_kwh": 6789.0,
        }

        line = meter_index_to_line("reteleelectrice_meter_index", reading)

        self.assertIn("pod=RO00TESTPOD123456,source=reteleelectrice", line)
        self.assertIn("import_index_kwh=12345.0", line)
        self.assertIn("export_index_kwh=6789.0", line)
        self.assertIn('measure_date="16.09.2026"', line)
        self.assertIn('reading_type="real"', line)

    def test_meter_index_batch_write_sends_multiple_lines(self):
        writer = InfluxWriter(
            "http://influx.example:8086",
            "home_assistant",
            "one_year",
            "reteleelectrice_meter_15m",
        )
        response = Mock()
        response.status_code = 204
        writer.session.post = Mock(return_value=response)

        readings = [
            {
                "pod": "RO00TESTPOD123456",
                "timestamp": 1788210000,
                "measure_date": "01.09.2026",
                "reading_type": "real",
                "meter_serial": "TEST-METER",
                "constant": "1",
                "import_index_kwh": 12001.0,
                "export_index_kwh": 6001.0,
            },
            {
                "pod": "RO00TESTPOD123456",
                "timestamp": 1789506000,
                "measure_date": "16.09.2026",
                "reading_type": "real",
                "meter_serial": "TEST-METER",
                "constant": "1",
                "import_index_kwh": 12050.0,
                "export_index_kwh": 6300.0,
            },
        ]

        written = writer.write_meter_indexes(readings, "reteleelectrice_meter_index")

        self.assertEqual(written, 2)
        body = writer.session.post.call_args.kwargs["data"].decode("utf-8")
        self.assertEqual(len(body.splitlines()), 2)
        self.assertIn('measure_date="01.09.2026"', body)
        self.assertIn('measure_date="16.09.2026"', body)

    def test_latest_timestamp_queries_target_measurement(self):
        writer = InfluxWriter(
            "http://influx.example:8086",
            "home_assistant",
            "one_year",
            "reteleelectrice_meter_15m",
        )
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "results": [
                {
                    "series": [
                        {
                            "columns": ["time", "last"],
                            "values": [[1789429500, 96]],
                        }
                    ]
                }
            ]
        }
        writer.session.get = Mock(return_value=response)

        latest = writer.latest_timestamp()

        self.assertEqual(latest, datetime.fromtimestamp(1789429500, tz=timezone.utc))
        params = writer.session.get.call_args.kwargs["params"]
        self.assertEqual(params["db"], "home_assistant")
        self.assertEqual(
            params["q"],
            'SELECT LAST("slot") FROM "one_year"."reteleelectrice_meter_15m"',
        )

    def test_successful_write_uses_acknowledged_timestamp_without_readback(self):
        writer = Mock()

        latest, source, query_error = resolve_latest_timestamp(writer, 1789418700)

        self.assertEqual(latest, datetime.fromtimestamp(1789418700, tz=timezone.utc))
        self.assertEqual(source, "write_acknowledgement")
        self.assertEqual(query_error, "")
        writer.latest_timestamp.assert_not_called()

    def test_no_accepted_write_uses_readback_when_available(self):
        writer = Mock()
        expected = datetime(2026, 9, 21, 20, 45, tzinfo=timezone.utc)
        writer.latest_timestamp.return_value = expected

        latest, source, query_error = resolve_latest_timestamp(writer, None)

        self.assertEqual(latest, expected)
        self.assertEqual(source, "influx_query")
        self.assertEqual(query_error, "")

    def test_query_failure_without_accepted_write_is_fatal(self):
        writer = Mock()
        writer.latest_timestamp.side_effect = InfluxError("query failed")

        with self.assertRaises(InfluxError):
            resolve_latest_timestamp(writer, None)


if __name__ == "__main__":
    unittest.main()
