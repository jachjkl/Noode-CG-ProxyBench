from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import RULES, TCP_RULES
from core.proxybench.state import Store
from tests.proxybench import test_dashboard_pages
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_recovery_pipeline import RecoveryManager


class BatchProgressTests(unittest.TestCase):
    def test_each_hundred_has_its_own_progress_then_cleanup_resets_before_next_batch(self):
        for direct in (False, True):
            with self.subTest(direct=direct), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                settings = {"root": root, "state_dir": root / "state", "runtime_dir": root / "runtime", "rules_path": root / "rules.json",
                            "measurement_mode": "tcp_tls" if direct else "proxy", "rules": TCP_RULES if direct else RULES, "geo_urls": []}
                pipeline = Pipeline(settings, manager=RecoveryManager())
                pipeline.store.state = {"run_id": "visual", "phase": "scan", "pool": pool(201), "results": {}}
                pipeline.events.append = lambda *args, **kwargs: None
                frames = []
                update = pipeline.update
                def capture(**values):
                    update(**values)
                    frames.append(copy.deepcopy(pipeline.status))
                pipeline.update = capture
                def measure(batch, *args, **kwargs):
                    complete = args[-1]
                    for index, row in enumerate(batch):
                        complete({**row, "key": f"{row['ip']}:{row['port']}", "qualified": index % 2 == 0,
                                  "tested_at": "2026-10-09", "status": "Qualified" if index % 2 == 0 else "Rejected Loss"})
                with patch("core.proxybench.pipeline.Benchmark.batch", side_effect=measure), \
                     patch("core.proxybench.direct_benchmark.DirectBenchmark.batch", side_effect=measure):
                    pipeline.scan(pool(201), "results", {})
                cleaning = [frame for frame in frames if frame.get("stage") == "清理本批缓存"]
                self.assertEqual([frame["batch_done"] for frame in cleaning], [100, 100, 1])
                self.assertEqual([frame["batch_passed"] for frame in cleaning], [50, 50, 1])
                reset = [frame for frame in frames if frame.get("batch_visual_phase") == "reset"]
                self.assertEqual(len(reset), 3)
                self.assertTrue(all(frame["batch_nodes"] == [] and frame["batch_done"] == 0 and frame["batch_input_count"] == 0 for frame in reset))
                self.assertEqual(pipeline.tested_count(), 201)

    def test_competition_polls_reuse_unchanged_checkpoint_and_invalidate_after_next_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dashboard = test_dashboard_pages.DashboardPageTests().controller(root)
            store = Store(dashboard.settings["state_dir"])
            store.state = {"run_id": "cached", "phase": "scan", "pool": pool(1), "results": {}}
            store.commit()
            with patch("core.proxybench.state.Store.load", wraps=Store.load, autospec=True) as load:
                # A concrete wrapper preserves production hash checks while counting loads.
                load.side_effect = lambda instance: original(instance)
                first = dashboard.checkpoint_snapshot()
                second = dashboard.checkpoint_snapshot()
                self.assertIs(first, second)
                self.assertEqual(load.call_count, 1)
                store.state["phase"] = "general_retest"
                store.commit()
                self.assertEqual(dashboard.checkpoint_snapshot()["phase"], "general_retest")
                self.assertEqual(load.call_count, 2)


original = Store.load
