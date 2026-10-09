from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.benchmark import Benchmark
from core.proxybench.controller import Controller
from core.proxybench.mihomo_manager import MihomoManager
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import RULES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import FakeManager, pool


class FastSelectionTests(unittest.TestCase):
    def test_failed_candidate_only_gets_one_actual_probe_while_other_nodes_finish_nine(self):
        manager = FakeManager()
        original = manager.controller.delay
        def delay(name, *arguments):
            if name == "PB-000001":
                manager.controller.calls.append((name, arguments[0], arguments[1]))
                return {"success": False, "latency_ms": None}
            return original(name, *arguments)
        manager.controller.delay = delay
        with tempfile.TemporaryDirectory() as directory:
            rows = Benchmark(manager, {**RULES, "round_cooldown_seconds": 0}, Control(Path(directory)), geo_urls=[]).batch(pool(10), object())
        self.assertEqual(len(manager.controller.calls), 136)
        self.assertEqual(rows[0]["proxy_probe_count"], 1)
        self.assertFalse(rows[0]["qualified"])
        self.assertTrue(all(row["qualified"] and row["proxy_probe_count"] == 15 for row in rows[1:]))

    def test_good_entry_is_not_rejected_for_realistic_worker_end_to_end_response(self):
        manager = FakeManager()
        manager.controller.delay = lambda *_: {"success": True, "latency_ms": 900}
        candidates = [{**pool(1)[0], "entry_latency_ms": 80, "entry_connected": True}]
        with tempfile.TemporaryDirectory() as directory:
            row = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 1500, "round_cooldown_seconds": 0}, Control(Path(directory)), geo_urls=[]).batch(candidates, object())[0]
        self.assertTrue(row["qualified"])
        self.assertEqual(row["entry_latency_ms"], 80)
        self.assertEqual(row["proxy_average_latency_ms"], 900)

    def test_dedicated_speed_ports_never_change_shared_proxy_selector(self):
        controller = Controller(1, "fixture", 2)
        controller.named_ports = {"PB-A": 11001, "PB-B": 11002}
        controller.select = Mock(side_effect=AssertionError("shared selector race"))
        self.assertEqual(controller.request_port("PB-A"), 11001)
        self.assertEqual(controller.request_port("PB-B"), 11002)
        controller.select.assert_not_called()

    def test_one_core_has_distinct_loopback_listeners_and_per_candidate_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = MihomoManager(Path(directory))
            manager.controller = Controller(1234, "fixture", 2345)
            profile = Mock()
            profile.definition.side_effect = lambda ip, name: {"type": "http", "server": ip, "name": name, "port": 443}
            config = manager.config(pool(100), profile)
        self.assertEqual(len(config["proxies"]), 100)
        self.assertEqual(len(config["listeners"]), 101)
        self.assertEqual(len({listener["port"] for listener in config["listeners"]}), 101)
        self.assertTrue(all(listener["listen"] == "127.0.0.1" for listener in config["listeners"]))
        self.assertIn("IN-NAME,proxybench-node-99,PB-000100", config["rules"])
        self.assertTrue(config["unified-delay"])

    def test_ordering_never_probes_or_drops_any_candidate_even_with_legacy_screen_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = FakeManager()
            settings = {"state_dir": root, "rules_path": root / "rules.json", "rules": RULES, "fast_entry_screen": True}
            pipeline = Pipeline(settings, manager=manager)
            candidates = [{**row, "entry_connected": False, "entry_latency_ms": 9999} for row in pool(300)]
            with patch("socket.create_connection", side_effect=AssertionError("no admission probe")):
                ordered = pipeline.ordered_candidates(candidates)
            self.assertEqual({row["ip"] for row in ordered}, {row["ip"] for row in candidates})
            self.assertEqual(len(ordered), 300)

    def test_control_does_not_flush_large_dashboard_snapshot_for_every_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            update = Mock()
            control = Control(Path(directory), update)
            for _ in range(1000):
                control.checkpoint()
            update.assert_called_once_with(status="Running")


if __name__ == "__main__":
    unittest.main()
