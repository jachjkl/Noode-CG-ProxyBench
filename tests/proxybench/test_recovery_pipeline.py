from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.proxybench.pipeline import Pipeline
from core.proxybench.profile import ProxyProfile
from core.proxybench.settings import RULES
from tests.proxybench.test_benchmark import FakeManager, pool


class RecoveryManager(FakeManager):
    version = "fixture-version"
    benchmark_active = False

    def health(self):
        return {"status": "Stopped", "version": self.version, "loaded_proxies": 0}

    def stop(self):
        pass


class RecoveryPipelineTests(unittest.TestCase):
    def settings(self, root):
        return {"root": root, "state_dir": root / "state", "runtime_dir": root / "runtime", "rules_path": root / "rules.json",
                "rules": {**RULES, "round_cooldown_seconds": 0}, "geo_urls": []}

    def test_resume_partial_batch_does_not_retest_completed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = RecoveryManager()
            pipeline = Pipeline(self.settings(root), manager=manager)
            pipeline.store.state = {"run_id": "one", "phase": "scan", "pool": pool(10), "results": {}}
            pipeline.store.commit()
            pipeline.store.save_partial({"ip": "104.16.0.1", "port": 443, "key": "104.16.0.1:443", "qualified": False})
            pipeline.store.load()
            pipeline.scan(pool(10), "results", {"default": object()})
            self.assertEqual(len(pipeline.store.state["results"]), 10)
            self.assertNotIn("PB-000001", {name for name, _, _ in manager.controller.calls})
            self.assertEqual(len(manager.controller.calls), 81)

    def test_rule_edits_are_used_in_next_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self.settings(root)
            settings["rules"]["batch_size"] = 1
            pipeline = Pipeline(settings, manager=RecoveryManager())
            pipeline.store.state = {"run_id": "two", "phase": "scan", "pool": pool(2), "results": {}}
            original_commit = pipeline.store.commit
            calls = []
            def edit_after_batch():
                original_commit()
                calls.append(1)
                settings["rules_path"].write_text(json.dumps({"max_proxy_average_latency_ms": 1}), encoding="utf-8")
            pipeline.store.commit = edit_after_batch
            pipeline.scan(pool(2), "results", {"default": object()})
            results = list(pipeline.store.state["results"].values())
            self.assertTrue(results[0]["qualified"])
            self.assertFalse(results[1]["qualified"])
            self.assertEqual(results[1]["status"], "Rejected Latency")

    def test_missing_profile_fails_before_core_or_source_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self.settings(root)
            settings["profile"] = root / "missing.local.yaml"
            with patch.object(ProxyProfile, "load", side_effect=ValueError("missing")), patch("core.proxybench.pipeline.build") as source:
                with self.assertRaises(ValueError):
                    Pipeline(settings, manager=RecoveryManager()).run()
                source.assert_not_called()
