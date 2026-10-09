from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.proxybench.benchmark import limit_failure
from core.proxybench.controller import CoreError
from core.proxybench.direct_benchmark import DirectBenchmark
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import RULES, TCP_RULES, current_rules, validate_rules
from core.proxybench.state import Store
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_recovery_pipeline import RecoveryManager


class FullCandidateBatchTests(unittest.TestCase):
    def settings(self, root, direct=False):
        return {"root": root, "state_dir": root / "state", "runtime_dir": root / "runtime",
                "rules_path": root / "rules.json", "geo_urls": [],
                "measurement_mode": "tcp_tls" if direct else "proxy",
                "rules": {**(TCP_RULES if direct else RULES), "quick_finish": 1, "batch_size": 1}}

    def test_all_twenty_thousand_reach_selected_engine_without_any_entry_admission_or_quota_cutoff(self):
        for method in ("proxy", "tcp", "tls"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                settings = self.settings(root, method != "proxy")
                if method == "tls":
                    settings["rules"]["tls_enabled"] = 1
                settings["fast_entry_screen"] = True  # Old settings cannot re-enable it.
                manager = RecoveryManager()
                pipeline = Pipeline(settings, manager=manager)
                candidates = [{**row, "entry_connected": False, "entry_latency_ms": 99999} for row in pool(20000)]
                pipeline.store.state = {"run_id": "full-pool", "phase": "scan", "pool": candidates, "results": {}}
                batches, observed = [], []
                pipeline.update = Mock()
                pipeline.events.append = Mock()
                pipeline.store.save_partial = Mock()
                def commit():
                    self.assertTrue(all(row["qualified"] for row in pipeline.store.state["results"].values()))
                pipeline.store.commit = commit
                def measured(batch, *arguments, **kwargs):
                    callback = arguments[-1]
                    batches.append(len(batch))
                    for row in batch:
                        observed.append(row["ip"])
                        # Enough early passes to trigger the removed quota shortcut,
                        # followed by failed measurements that must be removed.
                        qualified = len(observed) <= 600
                        callback({**row, "key": f"{row['ip']}:{row['port']}", "qualified": qualified,
                                  "jp_qualified": qualified, "proxy_probe_count": 3,
                                  "status": "Qualified" if qualified else "Rejected Latency"})
                with patch("socket.create_connection", side_effect=AssertionError("forbidden prefilter")), \
                     patch("core.proxybench.pipeline.Benchmark.batch", side_effect=measured), \
                     patch("core.proxybench.direct_benchmark.DirectBenchmark.batch", side_effect=measured):
                    pipeline.scan(pipeline.ordered_candidates(candidates), "results", {"default": object()})
                self.assertEqual(batches, [100] * 200)
                self.assertEqual(len(observed), 20000)
                self.assertEqual(len(set(observed)), 20000)
                self.assertEqual(pipeline.tested_count(), 20000)
                self.assertEqual(len(pipeline.store.state["results"]), 600)
                self.assertEqual(sum(pipeline.store.state["processed"]["results"].values()), 600)

    def test_failed_details_and_partial_cache_are_deleted_but_resume_skips_every_measured_address(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = self.settings(root)
            pipeline = Pipeline(settings, manager=RecoveryManager())
            pipeline.store.state = {"run_id": "durable", "phase": "scan", "pool": pool(301), "results": {}}
            seen = []
            def measured(batch, profiles, complete):
                for row in batch:
                    seen.append(row["ip"])
                    complete({**row, "key": f"{row['ip']}:{row['port']}", "qualified": False,
                              "probes": {"google": [{"success": False}]}, "status": "Rejected Loss"})
            with patch("core.proxybench.pipeline.Benchmark.batch", side_effect=measured):
                pipeline.scan(pool(301), "results", {})
            self.assertEqual(len(seen), 301)
            self.assertEqual(pipeline.store.state["results"], {})
            self.assertFalse((settings["state_dir"] / "partial-batch.jsonl").exists())
            view = json.loads(gzip.decompress((settings["state_dir"] / "benchmark-results.json.gz").read_bytes()))
            self.assertEqual(view, {})
            restored = Pipeline(settings, manager=RecoveryManager())
            restored.store.load()
            with patch("core.proxybench.pipeline.Benchmark.batch", side_effect=AssertionError("already measured")):
                restored.scan(pool(301), "results", {})
            self.assertEqual(restored.tested_count(), 301)

    def test_partial_journal_failure_is_not_reprobed_and_is_compacted_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = Pipeline(self.settings(root), manager=RecoveryManager())
            pipeline.store.state = {"run_id": "partial", "phase": "scan", "pool": pool(1), "results": {}}
            pipeline.store.commit()
            pipeline.store.save_partial({**pool(1)[0], "key": "104.16.0.1:443", "qualified": False, "status": "Rejected Loss"})
            pipeline.store = Store(pipeline.settings["state_dir"])
            pipeline.store.load()
            with patch("core.proxybench.pipeline.Benchmark.batch", side_effect=AssertionError("journal already completed")):
                pipeline.scan(pool(1), "results", {})
            self.assertEqual(pipeline.tested_count(), 1)
            self.assertEqual(pipeline.store.state["results"], {})

    def test_saved_preselection_options_are_retired_and_batch_size_is_fixed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for direct in (False, True):
                settings = self.settings(root, direct)
                saved = {"batch_size": 100, "quick_finish": 1}
                if not direct:
                    saved.update(max_entry_latency_ms=1, entry_timeout_seconds=.01, entry_concurrency=512)
                settings["rules_path"].write_text(json.dumps(saved), encoding="utf-8")
                rules = current_rules(settings)
                self.assertEqual(rules["batch_size"], 100)
                self.assertNotIn("quick_finish", rules)
                self.assertNotIn("max_entry_latency_ms", rules)
                self.assertNotIn("entry_concurrency", rules)

    def test_owned_core_retry_only_measures_unfinished_candidates_in_the_same_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = Pipeline(self.settings(root), manager=RecoveryManager())
            pipeline.store.state = {"run_id": "retry", "phase": "scan", "pool": pool(300), "results": {}}
            calls, seen = [], []
            def measured(batch, profiles, complete):
                calls.append(len(batch))
                for row in batch:
                    seen.append(row["ip"])
                    complete({**row, "key": f"{row['ip']}:{row['port']}", "qualified": False, "status": "Rejected Loss"})
                    if len(calls) == 1 and len(seen) == 17:
                        raise CoreError("fixture controller restart")
            with patch("core.proxybench.pipeline.Benchmark.batch", side_effect=measured):
                pipeline.scan(pool(300), "results", {})
            self.assertEqual(calls, [100, 83, 100, 100])
            self.assertEqual(len(seen), len(set(seen)))
            self.assertEqual(pipeline.tested_count(), 300)
            self.assertEqual(pipeline.store.state["results"], {})

    def test_failed_competition_is_deleted_and_revokes_stale_ordinary_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = Pipeline(self.settings(root), manager=RecoveryManager())
            key = "104.16.0.1:443"
            pipeline.store.state = {"results": {key: {**pool(1)[0], "key": key, "qualified": True}},
                                    "general_results": {key: {"key": key, "qualified": False, "probes": {"large": "discard"}}},
                                    "processed": {"results": {key: True}}}
            pipeline.compact_batch("general_results")
            self.assertEqual(pipeline.store.state["results"], {})
            self.assertEqual(pipeline.store.state["general_results"], {})
            self.assertFalse(pipeline.store.state["processed"]["results"][key])
            self.assertEqual(pipeline.tested_count(), 1)

    def test_proxy_quality_uses_only_real_proxy_measurements_even_with_old_failed_entry(self):
        row = {"entry_latency_ms": 9999, "entry_connected": False, "proxy_average_latency_ms": 200,
               "proxy_loss_percent": 0, "proxy_download_average_mbps": 10, "latency_jitter_ms": 0}
        rules = validate_rules({"max_proxy_average_latency_ms": 200, "max_entry_latency_ms": 1})
        self.assertEqual(limit_failure(row, rules), "")
        row["proxy_average_latency_ms"] = 200.01
        self.assertEqual(limit_failure(row, rules), "Rejected Latency")

    def test_three_direct_attempts_run_for_all_three_hundred_including_completely_failed_candidates(self):
        for tls in (0, 1):
            with self.subTest(tls=tls), tempfile.TemporaryDirectory() as folder:
                pipeline = Pipeline(self.settings(Path(folder), True), manager=RecoveryManager())
                tcp, tls_probe = AsyncMock(side_effect=TimeoutError()), AsyncMock(side_effect=TimeoutError())
                completed = []
                with patch("core.proxybench.direct_benchmark.tcp_probe", tcp), \
                     patch("core.proxybench.direct_benchmark.tls_probe", tls_probe), \
                     patch("core.proxybench.direct_benchmark.test_speed", side_effect=AssertionError("failed measured latency")):
                    DirectBenchmark({**TCP_RULES, "tls_enabled": tls}, pipeline.control).batch(pool(300), completed.append)
                self.assertEqual(len(completed), 300)
                self.assertEqual(tls_probe.await_count, 900 if tls else 0)
                self.assertEqual(tcp.await_count, 0 if tls else 900)
                self.assertTrue(all(len(row["tls_rounds_ms" if tls else "tcp_rounds_ms"]) == 3 for row in completed))
