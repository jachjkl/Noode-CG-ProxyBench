from __future__ import annotations

import io
import ipaddress
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.controller import Controller, RequestError, RoutingError
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import RULES, current_rules, validate_rules
from tests.proxybench.test_benchmark import FakeManager, pool


class LegacySpeedTests(unittest.TestCase):
    def measure(self, body, *, status=200, proof=None, read=None):
        controller = Controller(1, "fixture-secret", 9876)
        controller.select = Mock()
        controller._connection_proof = Mock(return_value=proof or {"selected_proxy": "PB-1", "routing_proof": "connection-chain"})
        if isinstance(proof, Exception):
            controller._connection_proof.side_effect = proof
        connection = Mock()
        connection.sock.getsockname.return_value = ("127.0.0.1", 1234)
        response = Mock(status=status)
        response.read.side_effect = read or io.BytesIO(body).read
        connection.getresponse.return_value = response
        clock = iter([10, 10.1, 10.2, 10.3, 10.4])
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection) as constructor, \
                patch("core.proxybench.controller.time.perf_counter", side_effect=lambda: next(clock)):
            result = controller.legacy_speed("PB-1", "https://speed.cloudflare.com/__down?bytes=1000",
                                             wanted_bytes=1000, timeout=8)
        return result, controller, connection, constructor

    def test_speed_uses_local_proxy_connect_with_original_host_and_body_timing(self):
        result, controller, connection, constructor = self.measure(b"x" * 1000)
        constructor.assert_called_once()
        self.assertEqual(constructor.call_args.args, ("127.0.0.1", 9876))
        connection.set_tunnel.assert_called_once_with("speed.cloudflare.com", 443)
        controller.select.assert_called_once_with("PB-1")
        controller._connection_proof.assert_called_once_with("PB-1", 1234, timeout=1.0)
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Host"], "speed.cloudflare.com")
        self.assertEqual(headers["Connection"], "close")
        self.assertEqual(headers["Accept"], "application/octet-stream")
        self.assertEqual(result["method"], "legacy-proxy-speed")
        self.assertAlmostEqual(result["speed_mbps"], .04)
        connection.close.assert_called_once()

    def test_original_95_percent_eof_is_accepted(self):
        result, *_ = self.measure(b"x" * 950)
        self.assertEqual(result["received_bytes"], 950)
        self.assertEqual(result["completion_ratio"], .95)

    def test_incomplete_body_preserves_received_bytes_and_proxy_proof(self):
        with self.assertRaises(RequestError) as caught:
            self.measure(b"x" * 949)
        self.assertEqual(caught.exception.received, 949)
        self.assertEqual(caught.exception.proof["selected_proxy"], "PB-1")

    def test_timeout_cannot_pass_even_after_95_percent(self):
        with self.assertRaises(RequestError) as caught:
            self.measure(b"", read=[b"x" * 960, TimeoutError()])
        self.assertEqual(caught.exception.received, 960)
        self.assertEqual(caught.exception.cause, "TimeoutError")

    def test_missing_named_proxy_proof_rejects_before_speed_request(self):
        with self.assertRaises(RequestError) as caught:
            self.measure(b"x" * 1000, proof=RoutingError("missing route"))
        self.assertEqual(caught.exception.stage, "Routing Verification")

    def test_non_200_response_is_rejected(self):
        with self.assertRaises(RequestError):
            self.measure(b"x" * 1000, status=302)

    def test_saved_former_preset_is_authoritative_without_silent_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"min_proxy_speed_mbps": 16, "download_attempts": 3,
                                        "download_bytes": 2097152, "download_timeout_seconds": 15,
                                        "max_proxy_average_latency_ms": 750}))
            rules = current_rules({"rules_path": path, "rules": RULES})
        self.assertEqual(rules["download_bytes"], 2097152)
        self.assertEqual(rules["download_attempts"], 3)
        self.assertEqual(rules["min_proxy_speed_mbps"], 16)
        self.assertEqual(rules["max_proxy_average_latency_ms"], 750)

    def test_custom_speed_threshold_survives_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps({"min_proxy_speed_mbps": 12}))
            self.assertEqual(current_rules({"rules_path": path, "rules": RULES})["min_proxy_speed_mbps"], 12)

    def test_completion_threshold_cannot_be_lower_than_original(self):
        with self.assertRaises(ValueError):
            validate_rules({"minimum_completion_ratio": .94})

    def test_runtime_check_loads_100_without_any_speed_acceptance_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profile.local.yaml"
            profile.write_text("proxy:\n  type: http\n  port: 443\n")
            manager = FakeManager()
            manager.ensure = Mock()
            manager.stop = Mock()
            manager.health = Mock(return_value={"status": "Stopped"})
            manager.version = "fixture"
            manager.controller.delay = Mock(return_value={"success": False})
            manager.controller.legacy_speed = Mock(side_effect=AssertionError("separate speed gate forbidden"))
            settings = {"profile": profile, "auto_update": False, "runtime_dir": root / "runtime",
                        "state_dir": root / "state", "rules_path": root / "rules.json", "rules": RULES}
            with patch("sources.cloudflare_official.collect", return_value=(pool(100), [ipaddress.ip_network("104.16.0.0/13")])):
                report = Pipeline(settings, manager=manager).validate_runtime()
            self.assertTrue(report["runtime_ready"])
            self.assertFalse(report["speed_acceptance_gate"])
            self.assertEqual([len(names) for names in manager.loads], [1, 10, 100])
            manager.controller.legacy_speed.assert_not_called()
            manager.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
