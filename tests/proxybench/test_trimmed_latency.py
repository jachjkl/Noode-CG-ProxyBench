from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.proxybench.benchmark import Benchmark, calculate, limit_failure
from core.proxybench.settings import RULES, SITES, current_rules, validate_rules
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import FakeManager, pool


class OneRoundLatencyTests(unittest.TestCase):
    def record(self, values):
        return {"probes": {site: [{"success": value is not None, "latency_ms": value}]
                           for (site, _, _), value in zip(SITES, values)}}

    def test_three_site_values_are_averaged_without_discarding_any_extreme(self):
        record = self.record([100, 200, 300])
        calculate(record, RULES)
        self.assertEqual(record["proxy_average_latency_ms"], 200)
        self.assertEqual(record["google_retained_ms"], [100])
        self.assertEqual(record["google_discarded_ms"], [])
        self.assertEqual(record["site_success_count"], 3)
        self.assertEqual(record["latency_method"], "one-round-three-site-mean-v2")
        self.assertTrue(record["latency_passed"])

    def test_single_slow_site_is_never_trimmed_away_to_fake_a_pass(self):
        record = self.record([10, 10, 1000])
        calculate(record, {**RULES, "max_proxy_average_latency_ms": 200})
        self.assertEqual(record["proxy_average_latency_ms"], 340)
        self.assertFalse(record["latency_passed"])

    def test_duplicate_or_missing_site_observations_are_rejected(self):
        for values in ([], [{"success": True, "latency_ms": 10}] * 2):
            record = self.record([100, 100, 100])
            record["probes"]["github"] = values
            with self.assertRaises(ValueError):
                calculate(record, RULES)

    def test_timeout_is_failure_and_never_averaged_as_zero(self):
        record = self.record([10, 20, None])
        calculate(record, RULES)
        self.assertEqual(record["proxy_loss_percent"], 100/3)
        self.assertGreater(record["proxy_average_latency_ms"], RULES["request_timeout_seconds"] * 1000 / 3)
        self.assertFalse(record["latency_passed"])

    def test_legacy_round_counts_are_normalized_to_exactly_one(self):
        for old in (1, 3, 4, 5, 6, 10):
            self.assertEqual(validate_rules({"round_count": old})["round_count"], 1)
        with self.assertRaises(ValueError):
            validate_rules({"round_count": 0})

    def test_saved_latency_rule_is_kept_while_only_batch_and_round_counts_change(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = {"rules": {**RULES, "round_count": 5, "batch_size": 300, "max_proxy_average_latency_ms": 1500}, "rules_path": Path(directory) / "absent.json"}
            rules = current_rules(settings)
        self.assertEqual(rules["round_count"], 1)
        self.assertEqual(rules["batch_size"], 100)
        self.assertEqual(rules["max_proxy_average_latency_ms"], 1500)

    def test_240_ms_mean_fails_under_saved_200_ms_and_each_site_is_called_once(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = FakeManager()
            values = iter([230, 240, 250])
            calls = []
            def delay(*args):
                calls.append(args)
                return {"success": True, "latency_ms": next(values)}
            manager.controller.delay = delay
            record = Benchmark(manager, {**RULES, "max_proxy_average_latency_ms": 200}, Control(Path(directory)), geo_urls=[]).batch(pool(1), object())[0]
        self.assertEqual(len(calls), 3)
        self.assertEqual(record["proxy_average_latency_ms"], 240)
        self.assertFalse(record["qualified"])
        self.assertFalse(manager.controller.speed_calls)

    def test_old_five_round_cached_pass_requires_fresh_one_round_measurement(self):
        self.assertEqual(limit_failure({"rules": {"round_count": 5}, "qualified": True}, RULES), "Retest Required")
