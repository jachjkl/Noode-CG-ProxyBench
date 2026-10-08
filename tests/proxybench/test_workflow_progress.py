from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.proxybench.cloud import CloudController
from core.proxybench.workflow import progress


class WorkflowProgressTests(unittest.TestCase):
    def test_new_start_does_not_show_previous_published_run_as_complete(self):
        rows = progress({"phase": "completed", "workflow_run_id": "old"},
                        {"status": "Preparing", "mode": "start"}, {"published": True})
        self.assertEqual([row["status"] for row in rows], ["running", "pending", "pending", "pending", "pending"])

    def test_download_only_starts_after_actual_cloud_success(self):
        cloud = {"run_id": 123, "jobs": [{"name": "云端自动获取候选IP", "conclusion": "success"},
                 {"name": "本地真实代理测速", "status": "in_progress", "steps": [
                     {"name": "Decode digest-verified cloud candidate handoff", "status": "in_progress"}]}]}
        self.assertEqual([row["status"] for row in progress({}, cloud, {})],
                         ["completed", "running", "pending", "pending", "pending"])

    def test_retest_and_pause_use_current_run_instead_of_stale_local_phase(self):
        cloud = {"run_id": 123, "jobs": [{"name": "云端自动获取候选IP", "conclusion": "success"}]}
        live = {"workflow_run_id": "123", "phase": "general_retest", "status": "Paused"}
        rows = progress(live, cloud, {})
        self.assertEqual([row["status"] for row in rows], ["completed", "completed", "completed", "paused", "pending"])
        self.assertEqual(progress({**live, "workflow_run_id": "old"}, cloud, {})[3]["status"], "pending")

    def test_local_publication_waits_for_successful_github_push(self):
        live = {"workflow_run_id": "123", "phase": "completed"}
        cloud = {"run_id": 123, "jobs": [{"name": "云端发布最优IP", "status": "in_progress"}]}
        self.assertEqual(progress(live, cloud, {"published": True})[-1]["status"], "running")
        cloud["jobs"][0].update(status="completed", conclusion="success")
        self.assertTrue(all(row["status"] == "completed" for row in progress(live, cloud, {"published": True})))

    def test_shortfall_is_waiting_and_failure_is_visible(self):
        rows = progress({"workflow_run_id": "123", "phase": "needs_more"},
                        {"run_id": 123, "status": "completed"}, {"needs_more": True, "published": False})
        self.assertEqual(rows[-1]["status"], "waiting")
        self.assertEqual(progress({}, {"status": "Failed"}, {})[0]["status"], "failed")

    def test_cloud_terminal_update_keeps_job_proof_and_next_dispatch_clears_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = CloudController({"root": root, "state_dir": root})
            jobs = [{"name": "云端发布最优IP", "conclusion": "success"}]
            controller.update(status="in_progress", run_id=123, jobs=jobs)
            controller.update(status="Completed")
            path = root / "cloud-live.json"
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["jobs"], jobs)
            controller.update(status="Dispatching")
            self.assertNotIn("jobs", json.loads(path.read_text(encoding="utf-8")))
            self.assertNotIn("run_id", json.loads(path.read_text(encoding="utf-8")))
