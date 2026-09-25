import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from datetime import date, datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from influx import InfluxError, InfluxWriter, point_to_line
from normalize import normalize_curve_payload
from portal import ReteleElectricePortal, parse_a4j_response, summarize_component_metadata
import run as run_module
from run import (
    PortalRateLimitError,
    backfill_start_for_pod,
    chunk_dates,
    data_freshness,
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

    def test_component_metadata_probe_discards_account_values(self):
        raw = {
            "descriptor": "markup://c:PED_Reading_Archive_Tab",
            "controller": {
                "descriptor": "apex://PED_ServizidiMisuraController/ACTION$PODDetails",
                "actionDefs": {
                    "GetArchive": {
                        "descriptor": "apex://PED_ServizidiMisuraController/ACTION$GetArchive"
                    }
                },
            },
            "accountData": {
                "pod": "RO00SECRET123456",
                "cnp": "1234567890123",
                "index": "98765.432",
            },
        }
        raw["controllerCode"] = (
            "function loadArchive(){"
            "event.setParams({methodName:'PED_csvReadArchiveEAP'});"
            "item.sParameterName='podId';"
            "callAsync('FindOutMeterReadingData');"
            "var pod='RO00SECRET123456';}"
        )
        summary = summarize_component_metadata(
            raw,
            include_literal_candidates=True,
        )
        serialized = json.dumps(summary)
        self.assertIn("PODDetails", summary["action_names"])
        self.assertIn("GetArchive", summary["action_names"])
        self.assertIn("accountData", summary["schema_keys"])
        self.assertIn("loadArchive", summary["identifier_signals"])
        self.assertIn("FindOutMeterReadingData", summary["identifier_signals"])
        self.assertTrue(
            any(
                "loadArchive" in context
                and "FindOutMeterReadingData" in context
                and "pod" in context
                for context in summary["identifier_contexts"]
            )
        )
        self.assertIn(
            "methodName=PED_csvReadArchiveEAP",
            summary["safe_relations"],
        )
        self.assertIn("sParameterName=podId", summary["safe_relations"])
        self.assertIn(
            "methodName~PED_csvReadArchiveEAP",
            summary["anchor_literal_candidates"],
        )
        self.assertIn(
            "sParameterName~podId",
            summary["anchor_literal_candidates"],
        )
        self.assertTrue(
            any(
                context.startswith("methodName:")
                and "PED_csvReadArchiveEAP" in context
                and "FindOutMeterReadingData" in context
                for context in summary["static_code_contexts"]
            )
        )
        self.assertNotIn("RO00SECRET123456", serialized)
        self.assertNotIn("1234567890123", serialized)
        self.assertNotIn("98765.432", serialized)

    def test_literal_candidates_disabled_for_instance_style_payload(self):
        raw = {
            "methodName": "PED_ReadArchive",
            "podId": "RO00SECRET123456",
        }
        summary = summarize_component_metadata(raw)
        self.assertEqual(summary["anchor_literal_candidates"], [])
        self.assertEqual(summary["static_code_contexts"], [])

    def test_reading_archive_probe_uses_component_controller_actions(self):
        portal = ReteleElectricePortal("user", "password")
        portal._aura_call = Mock(
            side_effect=[
                {
                    "descriptor": "markup://c:PED_Reading_Archive_Tab",
                    "controller": "apex://PED_ServizidiMisuraController/ACTION$ArchiveRows",
                },
                {
                    "descriptor": "markup://c:PED_Reading_Archive_Tab",
                    "controller": "apex://PED_ServizidiMisuraController/ACTION$PODDetails",
                    "sensitive": "RO00SECRET123456",
                },
                {
                    "descriptor": "markup://c:PED_CallWSAsyncEvent",
                    "methodName": "ReadArchiveService",
                },
                {
                    "descriptor": "markup://c:PED_CallbackWSAsyncEvent",
                    "attribute": "XML_Readings",
                },
                RuntimeError("dates event unavailable"),
                {
                    "descriptor": "markup://c:PED_Pagination",
                    "currentPage": 1,
                },
            ]
        )

        result = portal.probe_reading_archive_component()

        self.assertEqual(result["component"], "c:PED_Reading_Archive_Tab")
        self.assertEqual(
            result["calling_descriptor"], "markup://c:PED_Reading_Archive_Tab"
        )
        self.assertIn("ArchiveRows", result["definition"]["action_names"])
        self.assertIn("PODDetails", result["instance"]["action_names"])
        self.assertIn("methodName", result["related_definitions"]["c:PED_CallWSAsyncEvent"]["schema_keys"])
        self.assertIn("XML_Readings", result["related_definitions"]["c:PED_CallbackWSAsyncEvent"]["identifier_signals"])
        self.assertEqual(
            result["related_definitions"]["c:PED_Dates_event"]["error_type"],
            "RuntimeError",
        )
        self.assertIn("currentPage", result["related_definitions"]["c:PED_Pagination"]["schema_keys"])
        self.assertNotIn("RO00SECRET123456", json.dumps(result))

        calls = portal._aura_call.call_args_list
        self.assertEqual(
            calls[0].kwargs["descriptor"],
            "aura://ComponentController/ACTION$getComponentDef",
        )
        self.assertEqual(calls[0].kwargs["params"], {"name": "c:PED_Reading_Archive_Tab"})
        self.assertEqual(
            calls[1].kwargs["descriptor"],
            "aura://ComponentController/ACTION$getComponent",
        )
        self.assertEqual(
            calls[2].kwargs["params"],
            {"name": "c:PED_CallWSAsyncEvent"},
        )
        self.assertEqual(
            calls[3].kwargs["params"],
            {"name": "c:PED_CallbackWSAsyncEvent"},
        )
        self.assertEqual(
            calls[4].kwargs["params"],
            {"name": "c:PED_Dates_event"},
        )
        self.assertEqual(
            calls[5].kwargs["params"],
            {"name": "c:PED_Pagination"},
        )


class PortalDiscoveryTests(unittest.TestCase):
    def test_discovery_crawls_static_ped_components_and_catalogs_actions(self):
        portal = ReteleElectricePortal("user", "password")
        definitions = {
            "c:PED_Reading_Archive_Tab": {
                "descriptor": "markup://c:PED_Reading_Archive_Tab",
                "children": [
                    "markup://c:PED_Archive_Helper",
                    "markup://lightning:button",
                ],
                "controller": "apex://PED_ReadingArchiveController/ACTION$PODDetails",
                "code": (
                    "event.setParams({methodName:'PED_ReadArchive'});"
                    "var pod='RO00SECRET123456';"
                ),
            },
            "c:PED_Export_Curves_For_POD_Item": {
                "descriptor": "markup://c:PED_Export_Curves_For_POD_Item",
                "children": ["markup://c:PED_Archive_Helper"],
                "controller": "apex://PED_Valori_di_Energia_Ctrl/ACTION$PODDetails",
            },
            "c:PED_HomePage": {
                "descriptor": "markup://c:PED_HomePage",
                "controller": "apex://PED_Utility/ACTION$getPODs",
            },
            "c:PED_Archive_Helper": {
                "descriptor": "markup://c:PED_Archive_Helper",
                "controller": "apex://PED_ArchiveController/ACTION$ReadArchive",
                "code": "PED_ProxyCallWSAsync_Reading_VF",
            },
        }
        portal.get_component_definition = Mock(
            side_effect=lambda name: definitions[name]
        )
        portal.get_component_instance = Mock()
        portal._call_vf_ws_async = Mock()

        result = portal.discover_portal_api(max_components=20, max_depth=4)

        self.assertEqual(result["mode"], "static_metadata_only")
        self.assertFalse(result["business_actions_invoked"])
        self.assertFalse(result["component_instances_created"])
        self.assertFalse(result["load_curve_requests_invoked"])
        self.assertFalse(result["load_curve_budget_consumed"])
        self.assertEqual(result["components_attempted"], 4)
        self.assertEqual(result["components_successful"], 4)
        self.assertEqual(result["components_failed"], 0)
        self.assertIn("c:PED_Archive_Helper", result["components_discovered"])
        self.assertIn(
            "apex://PED_ArchiveController/ACTION$ReadArchive",
            result["apex_actions"],
        )
        self.assertIn("PED_ArchiveController", result["apex_controllers"])
        self.assertIn(
            "PED_ProxyCallWSAsync_Reading_VF",
            result["visualforce_candidates"],
        )
        self.assertNotIn("RO00SECRET123456", json.dumps(result))
        portal.get_component_instance.assert_not_called()
        portal._call_vf_ws_async.assert_not_called()

    def test_discovery_isolates_definition_errors(self):
        portal = ReteleElectricePortal("user", "password")

        def get_definition(name):
            if name == "c:PED_Export_Curves_For_POD_Item":
                raise RuntimeError("definition unavailable")
            return {"descriptor": f"markup://{name}"}

        portal.get_component_definition = Mock(side_effect=get_definition)

        result = portal.discover_portal_api(max_components=10, max_depth=0)

        self.assertEqual(result["components_attempted"], 3)
        self.assertEqual(result["components_failed"], 1)
        errors = [
            item for item in result["catalog"]
            if item["status"] == "error"
        ]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_type"], "RuntimeError")

    def test_discovery_enforces_component_limit(self):
        portal = ReteleElectricePortal("user", "password")
        portal.get_component_definition = Mock(
            return_value={"descriptor": "markup://c:PED_Test"}
        )

        result = portal.discover_portal_api(max_components=2, max_depth=5)

        self.assertEqual(result["components_attempted"], 2)
        self.assertTrue(result["limit_reached"])
        self.assertGreater(result["remaining_queue"], 0)



class PortalDiscoveryJobTests(unittest.TestCase):
    def setUp(self):
        run_module._set_discovery_runtime(
            state="idle",
            started_at=None,
            finished_at=None,
            error="",
            summary=None,
        )

    def test_background_job_persists_result_and_marks_complete(self):
        result = {
            "components_attempted": 4,
            "components_successful": 3,
            "components_failed": 1,
            "apex_actions": ["a", "b"],
            "apex_controllers": ["c"],
            "limit_reached": False,
            "catalog": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "portal_api_discovery.json"
            with patch.object(run_module, "DISCOVERY_PATH", target), patch.object(
                run_module, "discover_portal_api", return_value=result
            ):
                run_module.run_portal_discovery_job({"username": "u", "password": "p"})

            status = run_module.discovery_status()
            self.assertEqual(status["state"], "complete")
            self.assertEqual(status["summary"]["components_attempted"], 4)
            self.assertEqual(status["summary"]["apex_actions"], 2)
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved, result)

    def test_background_job_marks_failure_without_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "portal_api_discovery.json"
            with patch.object(run_module, "DISCOVERY_PATH", target), patch.object(
                run_module,
                "discover_portal_api",
                side_effect=RuntimeError("portal unavailable"),
            ):
                run_module.run_portal_discovery_job({"username": "u", "password": "p"})

            status = run_module.discovery_status()
            self.assertEqual(status["state"], "failed")
            self.assertIn("portal unavailable", status["error"])
            self.assertFalse(target.exists())



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
