from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from core.proxybench.benchmark import Benchmark, calculate, ranking_key
from core.proxybench.settings import RULES, SITES, validate_rules
from core.proxybench.state import Control


class FakeController:
    def __init__(self):
        self.calls = []
        self.speed_calls = []
        self.lock = threading.Lock()

    def delay(self, name, url, expected, timeout):
        with self.lock:
            self.calls.append((name, url, expected))
        latency = 10 + int(name.split("-")[1])
        return {"success": True, "latency_ms": latency, "selected_proxy": name,
                "routing_proof": "specified-proxy-controller-api", "destination": url}

    def request(self, name, url, **kwargs):
        if "__down" in url:
            return {"success": True, "speed_mbps": 24.0, "received_bytes": kwargs["wanted_bytes"],
                    "routing_proof": "connection-chain", "selected_proxy": name, "body": b""}
        return {"success": True, "body": b'{"country_code":"JP"}', "routing_proof": "connection-chain"}

    def legacy_speed(self, name, url, **kwargs):
        self.speed_calls.append((name, url, kwargs))
        return {"success": True, "speed_mbps": 24.0, "received_bytes": kwargs["wanted_bytes"],
                "routing_proof": "connection-chain", "selected_proxy": name}


class FakeManager:
    def __init__(self):
        self.controller = FakeController()
        self.loads = []

    def load_batch(self, candidates, profile):
        self.loads.append([item["proxy_name"] for item in candidates])


def pool(count):
    return [{"ip": f"104.16.{index // 254}.{index % 254 + 1}", "port": 443,
             "proxy_name": f"PB-{index + 1:06d}", "source_names": ["unit-fixture"]} for index in range(count)]


class BenchmarkTests(unittest.TestCase):
    def test_batch100_independent_three_site_requests_before_download(self):
        manager = FakeManager()
        rules = {**RULES, "round_cooldown_seconds": 0}
        with tempfile.TemporaryDirectory() as directory:
            results = Benchmark(manager, rules, Control(Path(directory)), geo_urls=["https://ipwho.is/"]).batch(pool(100), object())
        self.assertEqual(len(manager.loads), 1)
        self.assertEqual(len(results), 100)
        self.assertEqual(len(manager.controller.calls), 300)
        self.assertEqual(len({row["proxy_average_latency_ms"] for row in results}), 100)
        for name in manager.loads[0]:
            calls = [call for call in manager.controller.calls if call[0] == name]
            self.assertEqual(len(calls), 3)
            self.assertEqual({call[1] for call in calls}, {site[1] for site in SITES})
        self.assertTrue(all(row["qualified"] and row["jp_qualified"] for row in results))
        self.assertTrue(all(len(row["download_rounds_mbps"]) == 1 for row in results))
        self.assertEqual(len(manager.controller.speed_calls), 100)
        self.assertTrue(all(call[2]["wanted_bytes"] == 524288 and call[2]["maximum_download_seconds"] == 7
                            and call[2]["minimum_completion_ratio"] == .95 for call in manager.controller.speed_calls))
        self.assertEqual(results[0]["proxy_download_average_mbytes"], 3.0)

    def test_one_failed_probe_is_loss_and_no_download(self):
        manager = FakeManager()
        original = manager.controller.delay
        def failing(name, url, expected, timeout):
            if len(manager.controller.calls) == 0:
                manager.controller.calls.append((name, url, expected))
                return {"success": False, "latency_ms": None}
            return original(name, url, expected, timeout)
        manager.controller.delay = failing
        with tempfile.TemporaryDirectory() as directory:
            results = Benchmark(manager, {**RULES, "round_cooldown_seconds": 0}, Control(Path(directory)), geo_urls=[]).batch(pool(1), object())
        self.assertEqual(results[0]["proxy_loss_percent"], 100/3)
        self.assertEqual(results[0]["proxy_probe_count"], 3)
        self.assertEqual(results[0]["status"], "Rejected Loss")
        self.assertEqual(results[0]["download_rounds_mbps"], [])

    def test_geo_conflict_does_not_qualify_japan(self):
        manager = FakeManager()
        manager.controller.request = lambda name, url, **kwargs: {"body": b'{"country":"JP"}' if url.endswith("a/") else b'{"country":"US"}', "routing_proof": "connection-chain"}
        with tempfile.TemporaryDirectory() as directory:
            result = Benchmark(manager, RULES, Control(Path(directory)), geo_urls=["https://a/", "https://b/"]).geo("PB-1")
        self.assertTrue(result["geo_conflict"])
        self.assertFalse(result["jp_qualified"])

    def test_single_speed_failure_does_not_block_other_candidates(self):
        manager = FakeManager()
        original = manager.controller.legacy_speed
        def speed(name, url, **kwargs):
            if name == "PB-000001":
                raise TimeoutError()
            return original(name, url, **kwargs)
        manager.controller.legacy_speed = speed
        with tempfile.TemporaryDirectory() as directory:
            results = Benchmark(manager, {**RULES, "round_cooldown_seconds": 0}, Control(Path(directory)), geo_urls=[]).batch(pool(2), object())
        self.assertFalse(results[0]["qualified"])
        self.assertEqual(results[0]["status"], "Rejected Speed")
        self.assertTrue(results[1]["qualified"])

    def test_latency_precedes_download_in_ranking(self):
        fast_latency = {"ip": "104.16.1.1", "port": 443, "proxy_loss_percent": 0, "site_success_count": 9,
                        "proxy_average_latency_ms": 80, "latency_jitter_ms": 3, "proxy_download_average_mbps": 120}
        fast_speed = {**fast_latency, "ip": "104.16.1.2", "proxy_average_latency_ms": 190, "proxy_download_average_mbps": 160}
        self.assertEqual(sorted([fast_speed, fast_latency], key=ranking_key)[0], fast_latency)

    def test_exact_averages(self):
        result = {"probes": {site: [{"success": True, "latency_ms": value}] for (site, _, _), value in zip(SITES, (90, 105, 120))}}
        calculate(result, RULES)
        self.assertEqual(result["round_averages_ms"], [105])
        self.assertEqual(result["proxy_average_latency_ms"], 105)

    def test_rules_reject_nan_unknown_and_unsafe_concurrency(self):
        for invalid in ({"max_proxy_loss_percent": float("nan")}, {"batch_size": 301}, {"speed_concurrency": 9}, {"site_url": "https://x"}):
            with self.assertRaises(ValueError):
                validate_rules(invalid)


if __name__ == "__main__":
    unittest.main()
