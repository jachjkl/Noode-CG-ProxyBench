from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.benchmark import Benchmark
from core.proxybench.controller import Controller, RoutingError
from core.proxybench.settings import RULES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import FakeManager, pool


class SingleSiteProxyTests(unittest.TestCase):
    def controller(self):
        controller = Controller(1, "fixture", 2)
        controller.named_ports = {"PB-1": 3456}
        controller._connection_proof = Mock(return_value={"routing_proof": "connection-chain", "selected_proxy": "PB-1"})
        controller.delay = Mock(side_effect=AssertionError("no warmup or fallback request"))
        controller.select = Mock()
        connection = Mock()
        connection.sock.getsockname.return_value = ("127.0.0.1", 1234)
        connection.getresponse.return_value = Mock(status=200)
        connection.getresponse.return_value.read.return_value = b"colo=SJC\nip=192.0.2.1\n"
        return controller, connection

    def test_one_named_proxy_head_without_warmup_repeat_or_shared_selector(self):
        controller, connection = self.controller()
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://github.com/", "200-399", 3)
        self.assertTrue(result["success"])
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[0], "HEAD")
        self.assertEqual(connection.request.call_args.kwargs["headers"]["User-Agent"], "Go-http-client/1.1")
        controller.select.assert_not_called()
        controller.delay.assert_not_called()
        connection.close.assert_called_once()

    def test_missing_listener_cannot_fall_back_to_shared_proxy(self):
        controller, _ = self.controller()
        with self.assertRaises(RoutingError):
            controller.site_probe("missing", "https://github.com/", "200-399", 3)
        controller.select.assert_not_called()

    def test_invalid_route_fails_before_any_http_request(self):
        controller, connection = self.controller()
        controller._connection_proof.side_effect = RoutingError("DIRECT forbidden")
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://github.com/", "200-399", 3)
        self.assertFalse(result["success"])
        connection.request.assert_not_called()

    def test_bad_http_status_is_not_a_successful_latency(self):
        controller, connection = self.controller()
        connection.getresponse.return_value.status = 403
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://github.com/", "200-399", 3)
        self.assertFalse(result["success"])
        self.assertIsNone(result["latency_ms"])
        self.assertEqual(connection.request.call_count, 1)

    def test_cloudflare_uses_one_get_with_real_trace_evidence(self):
        controller, connection = self.controller()
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", 3)
        self.assertTrue(result["success"])
        self.assertEqual(connection.request.call_args.args[0], "GET")
        self.assertEqual(connection.request.call_count, 1)

    def test_a_200_html_page_is_not_a_cloudflare_trace(self):
        controller, connection = self.controller()
        connection.getresponse.return_value.read.return_value = b"<html>not a trace</html>"
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", 3)
        self.assertFalse(result["success"])

    def test_production_calls_each_selected_site_once_and_retains_saved_threshold(self):
        for latency, qualifies in [(200, True), (240, False)]:
            with self.subTest(latency=latency), tempfile.TemporaryDirectory() as directory:
                manager = FakeManager()
                manager.controller.site_probe = Mock(return_value={"success": True, "latency_ms": latency})
                rows = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 200}, Control(Path(directory)), geo_urls=[]).batch(pool(10), object())
                self.assertEqual(manager.controller.site_probe.call_count, 30)
                self.assertTrue(all(row["proxy_probe_count"] == 3 and row["qualified"] == qualifies for row in rows))
                self.assertEqual(bool(manager.controller.speed_calls), qualifies)

    def test_all_failed_candidates_still_attempt_three_sites_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager()
            manager.controller.site_probe = Mock(return_value={"success": False, "latency_ms": None})
            rows = Benchmark(manager, RULES, Control(Path(directory)), geo_urls=[]).batch(pool(100), object())
        self.assertEqual(manager.controller.site_probe.call_count, 300)
        self.assertTrue(all(not row["qualified"] and row["proxy_probe_count"] == 3 for row in rows))
        self.assertFalse(manager.controller.speed_calls)
