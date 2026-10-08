from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.proxybench.benchmark import Benchmark
from core.proxybench.settings import RULES, current_rules
from core.proxybench.state import Control
from tests.proxybench import test_dashboard_pages
from tests.proxybench.test_benchmark import FakeManager, pool


class SavedRulesTests(unittest.TestCase):
    def test_saved_200_ms_and_every_timeout_concurrency_value_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            saved = {**RULES, "max_proxy_average_latency_ms": 200, "request_timeout_seconds": 5,
                     "delay_concurrency": 20, "speed_concurrency": 1, "max_entry_latency_ms": 200}
            path.write_text(json.dumps(saved))
            for _ in range(3):
                self.assertEqual(current_rules({"rules_path": path, "rules": RULES}), saved)

    def test_200_ms_boundary_passes_but_240_ms_average_never_reaches_speed_test(self):
        for latency, passes in ((200, True), (240, False)):
            with self.subTest(latency=latency), tempfile.TemporaryDirectory() as directory:
                manager = FakeManager()
                manager.controller.delay = lambda *_: {"success": True, "latency_ms": latency}
                results = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 200, "round_cooldown_seconds": 0},
                                    Control(Path(directory)), geo_urls=[]).batch(pool(1), object())
                self.assertEqual(results[0]["qualified"], passes)
                self.assertEqual(bool(manager.controller.speed_calls), passes)

    def test_240_ms_entry_cannot_qualify_even_when_unified_response_is_fast(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager()
            candidates = [{**pool(1)[0], "entry_latency_ms": 240}]
            results = Benchmark(manager, {**RULES, "max_entry_latency_ms": 200, "round_cooldown_seconds": 0},
                                Control(Path(directory)), geo_urls=[]).batch(candidates, object())
            self.assertFalse(results[0]["qualified"])
            self.assertFalse(results[0]["entry_passed"])
            self.assertFalse(manager.controller.speed_calls)

    def test_save_close_reopen_keeps_every_rule_and_hidden_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = test_dashboard_pages.DashboardPageTests()
            controller = helper.controller(root)
            original = {**RULES, "max_proxy_average_latency_ms": 200, "entry_concurrency": 128, "minimum_completion_ratio": 1}
            controller.action("rules", original)
            # A partial edit must not silently reset other previously saved choices.
            controller.action("rules", {"min_proxy_speed_mbps": 4})
            controller.request_close()
            self.assertTrue(controller.finish_close(normal=True))
            reopened = helper.controller(root)
            self.assertEqual(reopened.snapshot()["rules"], {**original, "min_proxy_speed_mbps": 4})

    def test_cached_240_ms_pass_is_revoked_in_live_table_and_count_under_200_ms_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = test_dashboard_pages.DashboardPageTests()
            controller = helper.controller(root)
            record = {**pool(1)[0], "qualified": True, "status": "Qualified", "tested_at": "2026-10-08",
                      "entry_latency_ms": 50, "proxy_average_latency_ms": 240, "proxy_probe_count": 9}
            state_dir = root / "data/proxy-bench"
            helper.write(state_dir / "benchmark-results.json.gz", {"saved": record})
            helper.write(state_dir / "live.json", {"run_id": "old", "phase": "scan", "qualified_count": 1})
            controller.action("rules", {"max_proxy_average_latency_ms": 200})
            row = controller.rows("live-results", 1)["rows"][0]
            self.assertFalse(row["qualified"])
            self.assertEqual(row["status"], "Rejected Latency")
            self.assertEqual(controller.snapshot()["live"]["qualified_count"], 0)
