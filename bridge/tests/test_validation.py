"""Offline tests for bridge CLI and event validation."""
import argparse
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BRIDGE_DIR)

import agent_floor_bridge
import floor_producer
import floor_worker


class ProducerPostTests(unittest.TestCase):
    def response(self, body):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = body.encode("utf-8")
        return response

    def test_post_accepts_bridge_confirmation(self):
        with patch.object(floor_producer.urllib.request, "urlopen",
                          return_value=self.response('{"ok": true}')):
            self.assertTrue(floor_producer.post("http://bridge", {"event": "log"}, quiet=True))

    def test_post_rejects_bridge_declared_failure(self):
        with patch.object(floor_producer.urllib.request, "urlopen",
                          return_value=self.response('{"ok": false, "error": "bad event"}')):
            self.assertFalse(floor_producer.post("http://bridge", {"event": "bad"}, quiet=True))

    def test_post_rejects_non_json_success_response(self):
        with patch.object(floor_producer.urllib.request, "urlopen",
                          return_value=self.response("not json")):
            self.assertFalse(floor_producer.post("http://bridge", {"event": "log"}, quiet=True))

    def test_post_reports_http_rejection_as_event_error(self):
        rejection = floor_producer.urllib.error.HTTPError(
            "http://bridge/event", 400, "Bad Request", {}, io.BytesIO(b'{"error":"bad event"}'))
        error_output = io.StringIO()
        with patch.object(floor_producer.urllib.request, "urlopen", side_effect=rejection):
            with redirect_stderr(error_output):
                self.assertFalse(floor_producer.post("http://bridge", {"event": "bad"}))
        self.assertIn("rejected the event", error_output.getvalue())
        self.assertNotIn("unreachable", error_output.getvalue())


class IntervalValidationTests(unittest.TestCase):
    def test_cli_interval_helpers_reject_nonpositive_values(self):
        for validator in (floor_producer.positive_float, floor_worker.positive_float):
            for value in ("0", "-1", "nan", "inf"):
                with self.subTest(validator=validator.__module__, value=value):
                    with self.assertRaises(argparse.ArgumentTypeError):
                        validator(value)

    def test_worker_rejects_negative_maximum(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            floor_worker.nonnegative_int("-1")

    def test_worker_serve_rejects_invalid_limits(self):
        for interval in (0, float("nan")):
            with self.subTest(interval=interval):
                with self.assertRaisesRegex(ValueError, "interval"):
                    floor_worker.serve("http://unused", interval=interval)
        with self.assertRaisesRegex(ValueError, "task count"):
            floor_worker.serve("http://unused", max_tasks=-1)

    def test_watch_rejects_missing_directory_and_invalid_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(dir=os.path.join(temp, "missing"), interval=1.5)
            with self.assertRaisesRegex(OSError, "does not exist"):
                floor_producer.watch(args)
            args.dir = temp
            for interval in (0, float("nan")):
                args.interval = interval
                with self.subTest(interval=interval):
                    with self.assertRaisesRegex(ValueError, "greater than zero"):
                        floor_producer.watch(args)


class ShiftValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), agent_floor_bridge.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()

    def setUp(self):
        with agent_floor_bridge.LOCK:
            agent_floor_bridge.STATE["agents"].clear()
            agent_floor_bridge.STATE["floor"]["log"].clear()

    def post_update(self, payload):
        request = Request(self.url + "/agent/update", data=json.dumps(payload).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_shift_requires_valid_hhmm_or_empty(self):
        for value in ("9:00", "24:00", "09:60", "09:00x"):
            with self.subTest(value=value):
                result = agent_floor_bridge.update_agent(
                    "ShiftTest", {"agent": "ShiftTest", "shiftFrom": value})
                self.assertFalse(result["ok"])
                self.assertEqual(agent_floor_bridge.STATE["agents"], {})

    def test_shift_accepts_valid_boundary_times(self):
        result = agent_floor_bridge.update_agent(
            "ShiftTest", {"agent": "ShiftTest", "shiftFrom": "00:00", "shiftTo": "23:59"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["shiftFrom"], "00:00")
        self.assertEqual(result["shiftTo"], "23:59")

    def test_invalid_shift_is_an_http_client_error(self):
        status, result = self.post_update({"agent": "ShiftTest", "shiftFrom": "25:00"})
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])
        self.assertIn("valid HH:MM", result["error"])

    def test_valid_shift_is_accepted_over_http(self):
        status, result = self.post_update(
            {"agent": "ShiftTest", "shiftFrom": "09:00", "shiftTo": "18:00"})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
