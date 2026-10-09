from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.benchmark import Benchmark
from core.proxybench.controller import Controller, RoutingError
from core.proxybench.settings import RULES
from core.proxybench.state import Control, Stopped
from tests.proxybench.test_benchmark import FakeManager, pool


class PersistentProxyTests(unittest.TestCase):
    def controller(self):
        controller = Controller(1, "fixture", 2)
        controller.named_ports = {"PB-1": 3456}
        controller._connection_proof = Mock(return_value={"routing_proof": "connection-chain", "selected_proxy": "PB-1"})
        controller.delay = Mock(return_value={"success": True, "latency_ms": 150})
        controller.select = Mock()
        connection = Mock()
        connection.sock.getsockname.return_value = ("127.0.0.1", 1234)
        connection.getresponse.return_value = Mock(status=200)
        return controller, connection

    def test_one_warmup_then_five_timed_heads_share_one_named_proxy_connection(self):
        controller, connection = self.controller()
        rows = []
        clock = iter([0, .1, 1, 1.15, 2, 2.2, 3, 3.25, 4, 4.3])
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection) as constructor, \
             patch("core.proxybench.controller.time.perf_counter", side_effect=lambda: next(clock)):
            controller.site_samples("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: False)
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.args, ("127.0.0.1", 3456))
        connection.set_tunnel.assert_called_once_with("www.cloudflare.com", 443)
        connection.connect.assert_called_once()
        self.assertEqual(connection.request.call_count, 6)
        self.assertTrue(all(call.args[0] == "HEAD" for call in connection.request.call_args_list))
        self.assertTrue(all(call.kwargs["headers"]["User-Agent"] == "Go-http-client/1.1" for call in connection.request.call_args_list))
        self.assertEqual(len(rows), 5)
        for actual, expected in zip(rows, [100, 150, 200, 250, 300]):
            self.assertAlmostEqual(actual["latency_ms"], expected)
        self.assertTrue(all(r["routing_proof"] == "connection-chain" and r["connection_reused"] for r in rows))
        controller.select.assert_not_called()
        controller.delay.assert_not_called()
        connection.close.assert_called_once()

    def test_missing_candidate_listener_cannot_fall_back_to_shared_selector(self):
        controller, _ = self.controller()
        with self.assertRaises(RoutingError):
            controller.site_samples("missing", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=lambda: None, observed=lambda _: None, should_stop=lambda: False)
        controller.select.assert_not_called()

    def test_failed_route_proof_is_rejected_without_timing_direct_traffic(self):
        controller, connection = self.controller()
        controller._connection_proof.side_effect = RoutingError("DIRECT is forbidden")
        rows = []
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            controller.site_samples("PB-1", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: bool(rows))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["success"])
        connection.request.assert_not_called()
        controller.delay.assert_not_called()

    def test_unexpected_status_is_a_failure_with_no_latency(self):
        controller, connection = self.controller()
        connection.getresponse.return_value.status = 403
        controller.delay.return_value = {"success": False, "latency_ms": None}
        rows = []
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            controller.site_samples("PB-1", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: False)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(not r["success"] and r["latency_ms"] is None for r in rows))

    def test_closed_keepalive_uses_the_original_named_delay_api(self):
        controller, connection = self.controller()
        connection.getresponse.side_effect = lambda: (setattr(connection, "sock", None) or Mock(status=200))
        rows = []
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            controller.site_samples("PB-1", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: False)
        self.assertEqual(controller.delay.call_count, 5)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(call.args[0] == "PB-1" for call in controller.delay.call_args_list))

    def test_incompatible_warmup_switches_all_five_samples_to_original_core_with_same_status_rule(self):
        controller, connection = self.controller()
        connection.getresponse.return_value.status = 404
        rows = []
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            controller.site_samples("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: False)
        self.assertEqual(controller.delay.call_count, 5)
        self.assertEqual(connection.request.call_count, 1)
        self.assertTrue(all(call.args == ("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", 3) for call in controller.delay.call_args_list))
        self.assertTrue(all(r["success"] for r in rows))

    def test_warm_connection_failure_still_measures_remaining_allowed_attempts(self):
        controller, connection = self.controller()
        connection.connect.side_effect = TimeoutError()
        rows = []
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            controller.site_samples("PB-1", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=lambda: None, observed=rows.append, should_stop=lambda: False)
        self.assertEqual(len(rows), 5)
        self.assertFalse(rows[0]["success"])
        self.assertEqual(controller.delay.call_count, 4)

    def test_stopping_closes_the_connection_and_preserves_the_stop_signal(self):
        controller, connection = self.controller()
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection), self.assertRaises(Stopped):
            controller.site_samples("PB-1", "https://github.com/", "200-399", 3, 5,
                                    checkpoint=Mock(side_effect=Stopped()), observed=lambda _: None, should_stop=lambda: False)
        connection.close.assert_called_once()

    def batch(self, values, *, failure=False, count=1):
        manager = FakeManager()
        manager.controller.named_ports = {r["proxy_name"]: 123 for r in pool(count)}
        def samples(name, url, expected, timeout, attempts, *, checkpoint, observed, should_stop):
            for i in range(attempts):
                if should_stop():
                    return
                observed({"success": not failure, "latency_ms": None if failure else values[i],
                          "routing_proof": "connection-chain", "selected_proxy": name})
        manager.controller.site_samples = Mock(side_effect=samples)
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            rows = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 200}, Control(Path(directory)),
                             geo_urls=[], update=lambda **v: updates.append(v)).batch(pool(count), object())
        return rows, manager, updates

    def test_persistent_measurements_keep_five_samples_per_site_and_exact_trimmed_average(self):
        rows, manager, _ = self.batch([100, 150, 200, 250, 300])
        self.assertTrue(rows[0]["qualified"])
        self.assertEqual(rows[0]["proxy_average_latency_ms"], 200)
        self.assertEqual(rows[0]["proxy_probe_count"], 15)
        self.assertEqual(manager.controller.site_samples.call_count, 3)
        self.assertEqual(rows[0]["probe_method"], "named-proxy-persistent-head-v1")
        self.assertEqual(len(rows[0]["latency_targets"]), 3)

    def test_240_ms_cannot_qualify_under_200_ms_or_start_download(self):
        rows, manager, _ = self.batch([240] * 5)
        self.assertFalse(rows[0]["qualified"])
        self.assertEqual(rows[0]["status"], "Rejected Latency")
        self.assertFalse(manager.controller.speed_calls)

    def test_failed_candidates_end_early_without_serializing_every_bad_ip(self):
        rows, manager, updates = self.batch([100] * 5, failure=True, count=50)
        self.assertTrue(all(r["status"] == "Rejected Loss" and r["proxy_probe_count"] == 1 for r in rows))
        self.assertFalse(manager.controller.speed_calls)
        self.assertTrue(all(v.get("effective_concurrency", 24) == 24 for v in updates))
