from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.proxybench.benchmark import Benchmark, calculate
from core.proxybench.settings import RULES, SITES, current_rules, validate_rules
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import FakeManager, pool


class TrimmedLatencyTests(unittest.TestCase):
    def record(self, values):
        return {"probes": {site: [{"success": True, "latency_ms": number} for number in sample]
                           for (site, _, _), sample in zip(SITES, values)}}

    def test_each_site_drops_one_low_and_high_then_three_means_are_averaged(self):
        record = self.record(([1000, 90, 10, 110, 100], [20, 80, 90, 100, 2000], [30, 70, 80, 90, 3000]))
        calculate(record, {**RULES, "max_proxy_jitter_ms": 10000})
        self.assertEqual(record["google_retained_ms"], [90, 100, 110])
        self.assertEqual(record["google_discarded_ms"], [10, 1000])
        self.assertEqual([record[f"{site}_average_ms"] for site, _, _ in SITES], [100, 90, 80])
        self.assertEqual(record["proxy_average_latency_ms"], 90)
        self.assertTrue(record["latency_passed"])

    def test_repeated_extremes_drop_only_one_observation_each(self):
        record = self.record(([10, 10, 10, 10, 1000],) * 3)
        calculate(record, RULES)
        self.assertEqual(record["google_retained_ms"], [10, 10, 10])
        self.assertEqual(record["proxy_average_latency_ms"], 10)

    def test_six_probes_keep_four_middle_values(self):
        record = self.record(([1, 10, 20, 30, 40, 500],) * 3)
        calculate(record, {**RULES, "round_count": 6})
        self.assertEqual(record["google_retained_ms"], [10, 20, 30, 40])
        self.assertEqual(record["proxy_average_latency_ms"], 25)

    def test_discarding_timeout_from_latency_does_not_discard_request_failure(self):
        record = self.record(([10, 80, 90, 100, 110],) * 3)
        record["probes"]["github"][-1] = {"success": False, "latency_ms": None}
        calculate(record, RULES)
        self.assertGreater(record["proxy_loss_percent"], 0)
        self.assertFalse(record["latency_passed"])

    def test_fewer_than_five_probes_cannot_be_saved_or_executed(self):
        with self.assertRaises(ValueError):
            validate_rules({"round_count": 4})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                Benchmark(FakeManager(), {**RULES, "round_count": 4}, Control(Path(directory)), geo_urls=[])

    def test_legacy_three_probe_settings_upgrade_only_count_to_new_minimum(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = {"rules": {**RULES, "round_count": 3, "max_proxy_average_latency_ms": 1500}, "rules_path": Path(directory) / "absent.json"}
            rules = current_rules(settings)
        self.assertEqual(rules["round_count"], 5)
        self.assertEqual(rules["max_proxy_average_latency_ms"], 1500)

    def test_trimmed_240_ms_composite_still_cannot_qualify_under_200_ms_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager()
            values = iter([1, 1, 1, 230, 230, 230, 240, 240, 240, 250, 250, 250, 1000, 1000, 1000])
            manager.controller.delay = lambda *_: {"success": True, "latency_ms": next(values)}
            record = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 200, "round_cooldown_seconds": 0, "delay_concurrency": 1},
                               Control(Path(directory)), geo_urls=[]).batch(pool(1), object())[0]
        self.assertEqual(record["proxy_average_latency_ms"], 240)
        self.assertFalse(record["qualified"])
        self.assertFalse(manager.controller.speed_calls)
