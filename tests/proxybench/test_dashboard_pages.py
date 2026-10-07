from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.proxybench.dashboard import BenchDashboard
from tests.proxybench.test_benchmark import pool


class DashboardPageTests(unittest.TestCase):
    def controller(self, root):
        (root / "config.yaml").write_text("proxybench:\n  max_cycles: 0\n", encoding="utf-8")
        return BenchDashboard(SimpleNamespace(root=root, repository="jachjkl/Noode-CG-ProxyBench"))

    def write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload).encode()
        path.write_bytes(gzip.compress(content) if path.suffix == ".gz" else content)

    def test_901_ips_are_paged_300_each_with_one_ip_on_last_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.controller(root)
            self.write(root / "data/handoff/proxybench-pool.json.gz", {"pool": pool(901)})
            first = controller.action("candidates", {"page": 1})
            second = controller.action("candidates", {"page": 2})
            last = controller.action("candidates", {"page": 999})
            self.assertEqual((first["total"], first["pages"], len(first["rows"])), (901, 4, 300))
            self.assertFalse({x["ip"] for x in first["rows"]} & {x["ip"] for x in second["rows"]})
            self.assertEqual((last["page"], len(last["rows"])), (4, 1))
            with self.assertRaises(ValueError):
                controller.action("candidates", {"page": 0})

    def test_obsolete_bandwidth_gate_does_not_block_ready_screen_after_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.controller(root)
            self.write(root / "data/proxy-bench/live.json", {"status": "Validation Failed",
                       "phase": "validation", "stage": "真实带宽测速失败，未启动大池优选", "candidate_total": 21538})
            snapshot = controller.snapshot()
            self.assertEqual(snapshot["live"]["status"], "Ready")
            self.assertEqual(snapshot["live"]["candidate_total"], 21538)
            self.assertFalse(snapshot["running"])
            self.assertNotIn("带宽", snapshot["live"]["stage"])

    def test_paged_candidates_include_actual_saved_measurements_and_new_batch_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.controller(root)
            candidates = pool(901)
            self.write(root / "data/handoff/proxybench-cloud-health.json", {"seed": "current"})
            self.write(root / "data/proxy-bench/live.json", {"sources": {"seed": "current"}})
            self.write(root / "data/proxy-bench/candidate-pool.json.gz", candidates)
            row = {**candidates[300], "status": "Qualified", "tested_at": "2026-10-07", "proxy_download_average_mbps": 22}
            key = f"{row['ip']}:{row['port']}"
            results_path = root / "data/proxy-bench/benchmark-results.json.gz"
            self.write(results_path, {key: row})
            self.assertEqual(controller.rows("candidates", 2)["rows"][0]["proxy_download_average_mbps"], 22)
            self.write(results_path, {key: {**row, "proxy_download_average_mbps": 24}})
            self.assertEqual(controller.rows("candidates", 2)["rows"][0]["proxy_download_average_mbps"], 24)
            self.assertEqual(controller.rows("results", 1)["total"], 1)

    def test_new_cloud_pool_does_not_display_old_results_as_new_measurements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.controller(root)
            row = {**pool(1)[0], "status": "Qualified", "tested_at": "2026-10-07", "proxy_download_average_mbps": 22}
            self.write(root / "data/handoff/proxybench-cloud-health.json", {"seed": "new"})
            self.write(root / "data/handoff/proxybench-pool.json.gz", {"pool": pool(1)})
            self.write(root / "data/proxy-bench/live.json", {"sources": {"seed": "old"}, "candidates": [row]})
            self.write(root / "data/proxy-bench/benchmark-results.json.gz", {"one": row})
            visible = controller.rows("candidates", 1)["rows"][0]
            self.assertEqual(visible["status"], "Queued")
            self.assertNotIn("proxy_download_average_mbps", visible)
