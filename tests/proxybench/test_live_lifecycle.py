from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from core.proxybench.cloud import CloudController, CloudError
from core.proxybench.pipeline import Pipeline
from core.proxybench.profile import ProfileChanged, ProxyProfile, refresh_existing
from core.proxybench.settings import RULES
from core.proxybench.state import Store
from core.proxybench.workflow import progress
from tests.proxybench import test_dashboard_pages, test_recovery_pipeline
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_profile_sources_state import UUID


class LiveLifecycleTests(unittest.TestCase):
    def dashboard(self, root):
        return test_dashboard_pages.DashboardPageTests().controller(root)

    def write(self, path, payload):
        test_dashboard_pages.DashboardPageTests().write(path, payload)

    def test_dispatch_finds_its_exact_request_despite_server_clock_and_other_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = CloudController({"root": root, "state_dir": root})
            def command(args, **kwargs):
                if args[:2] == ["workflow", "run"]:
                    request = next(value for value in args if value.startswith("dispatch_id="))
                    controller.request_for_test = request.split("=", 1)[1]
                    return ""
                return [{"databaseId": 99, "createdAt": "2099-01-01T00:00:00Z", "event": "workflow_dispatch", "displayTitle": "another request"},
                        {"databaseId": 7, "createdAt": "2000-01-01T00:00:00Z", "event": "workflow_dispatch", "displayTitle": controller.request_for_test}]
            controller.command = command
            controller.dispatch("session", False)
            self.assertEqual(controller.run_id, 7)

    def test_monitor_retries_temporary_api_failure_without_aborting_owned_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = CloudController({"root": root, "state_dir": root})
            controller.run_id = 7
            controller.runner = Mock()
            controller.command = Mock(side_effect=[CloudError("temporary"), {"status": "completed", "url": "https://example.test/7", "jobs": []}])
            with patch("core.proxybench.cloud.time.sleep"):
                self.assertEqual(controller.watch()["status"], "completed")
            controller.runner.terminate.assert_not_called()

    def test_live_local_child_advances_flow_even_after_monitor_loses_run_identity(self):
        rows = progress({"local_process_active": True, "workflow_run_id": "7", "phase": "scan", "status": "Running"},
                        {"status": "Failed", "stage": "未找到新云端任务"}, {})
        self.assertEqual([row["status"] for row in rows], ["completed", "completed", "running", "pending", "pending"])

    def test_live_results_include_inflight_and_partial_records_but_not_entry_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.dashboard(root)
            nodes = pool(4)
            active = {**nodes[0], "status": "Round 1", "probes": {"google": [{"success": True, "latency_ms": 87}]}}
            complete = {**nodes[1], "tested_at": "2026-10-08", "status": "Qualified", "probes": {"google": []}}
            partial = {**nodes[2], "tested_at": "2026-10-08", "status": "Qualified", "probes": {"google": []}}
            self.write(root / "data/proxy-bench/live.json", {"run_id": "current", "phase": "scan", "candidates": [active]})
            self.write(root / "data/proxy-bench/benchmark-results.json.gz", {"done": complete, "bad": {**nodes[3], "status": "Rejected Entry"}})
            self.write(root / "data/proxy-bench/partial-batch.json", {"run_id": "current", "phase": "scan", "results": {"partial": partial}})
            page = controller.rows("live-results", 1)
            self.assertEqual(page["total"], 3)
            self.assertEqual(page["rows"][0]["ip"], active["ip"])
            self.assertEqual(page["rows"][0]["live_response_ms"], 87)
            self.assertEqual(page["rows"][0]["completed_probe_count"], 1)

    def test_candidates_and_live_results_keep_independent_300_row_paging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.dashboard(root)
            nodes = pool(901)
            self.write(root / "data/handoff/proxybench-pool.json.gz", {"pool": nodes})
            self.write(root / "data/proxy-bench/benchmark-results.json.gz", {str(i): {**row, "status": "Qualified", "probes": {"google": []}} for i, row in enumerate(nodes[:650])})
            self.assertEqual(len(controller.rows("candidates", 1)["rows"]), 300)
            self.assertEqual(len(controller.rows("live-results", 2)["rows"]), 300)
            self.assertEqual(len(controller.rows("live-results", 3)["rows"]), 50)
            self.assertEqual(controller.rows("candidates", 1)["rows"][0]["ip"], nodes[0]["ip"])

    def test_normal_close_clears_transient_pool_and_checkpoint_but_keeps_profile_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.dashboard(root)
            self.write(root / "data/proxy-bench/live.json", {"status": "Ready"})
            self.write(root / "data/proxy-bench/batch-state.json", {"saved": True})
            self.write(root / "data/handoff/proxybench-pool.json.gz", {"pool": pool(1)})
            self.write(root / "output/nodes.json", [{"ip": "104.16.0.1"}])
            profile = root / "config/proxy-profile.local.yaml"
            profile.parent.mkdir()
            profile.write_text("local profile", encoding="utf-8")
            controller.request_close()
            self.assertTrue(controller.finish_close(normal=True))
            self.assertFalse((root / "data/proxy-bench/batch-state.json").exists())
            self.assertFalse((root / "data/handoff/proxybench-pool.json.gz").exists())
            self.assertTrue(profile.exists())
            self.assertTrue((root / "output/nodes.json").exists())

    def test_failed_or_unexpected_close_preserves_checkpoint(self):
        for normal, failed in ((True, True), (False, False)):
            with self.subTest(normal=normal), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                controller = self.dashboard(root)
                saved = root / "data/proxy-bench/batch-state.json"
                self.write(saved, {"saved": True})
                self.write(root / "data/proxy-bench/cloud-live.json", {"status": "Failed" if failed else "Ready"})
                controller.request_close()
                self.assertFalse(controller.finish_close(normal=normal))
                self.assertTrue(saved.exists())

    def test_closing_after_runner_interruption_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.dashboard(root)
            saved = root / "data/proxy-bench/batch-state.json"
            self.write(saved, {"saved": True})
            self.write(root / "data/proxy-bench/cloud-live.json", {"status": "Stopped", "interrupted": True})
            controller.request_close()
            self.assertFalse(controller.finish_close(normal=True))
            self.assertTrue(saved.exists())

    def test_opening_old_cancelled_workflow_clears_stale_running_without_erasing_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root / "data/proxy-bench/batch-state.json", {"saved": True})
            self.write(root / "data/proxy-bench/live.json", {"status": "Running", "qualified_count": 111})
            self.write(root / "data/proxy-bench/cloud-live.json", {"status": "Failed", "jobs": [{"conclusion": "cancelled"}]})
            controller = self.dashboard(root)
            live = controller.read_cached(root / "data/proxy-bench/live.json")
            self.assertEqual(live["status"], "Stopped")
            self.assertEqual(live["qualified_count"], 111)
            self.assertTrue((root / "data/proxy-bench/batch-state.json").exists())
            self.assertTrue(controller.preserve_on_close)

    def test_auto_profile_refresh_syncs_changed_authentication_without_reporting_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "proxy.local.yaml"
            current = {"type": "vless", "uuid": UUID, "port": 443, "servername": "worker.example.test"}
            profile.write_text(yaml.safe_dump(current), encoding="utf-8")
            updated_uuid = "00000000-0000-4000-8000-000000000002"
            client = root / "client.yaml"
            client.write_text(yaml.safe_dump({"proxies": [{**current, "uuid": updated_uuid, "server": "104.16.0.1"}]}), encoding="utf-8")
            with patch("core.proxybench.profile.discover_profiles", return_value=[{"path": str(client), "index": 0, "matches_worker": True}]):
                result = refresh_existing(profile)
            self.assertTrue(result["changed"])
            self.assertEqual(ProxyProfile.load(profile)._proxy["uuid"], updated_uuid)
            self.assertNotIn(updated_uuid, json.dumps(result))

    def test_changed_profile_archives_old_measurements_and_retests_saved_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "proxy.local.yaml"
            profile_path.write_text(yaml.safe_dump({"type": "vless", "uuid": UUID, "port": 2053}), encoding="utf-8")
            profile = ProxyProfile.load(profile_path)
            settings = {"root": root, "profile": profile_path, "state_dir": root / "state", "runtime_dir": root / "runtime",
                        "rules_path": root / "rules.json", "rules": {**RULES, "round_cooldown_seconds": 0}, "output_dir": root / "output",
                        "auto_update": False, "auto_refresh_profile": True, "profile_refresh_seconds": 30, "geo_urls": [], "max_cycles": 1}
            store = Store(settings["state_dir"])
            store.state = {"run_id": "previous", "phase": "scan", "cycle": 1, "session_id": "same-session", "sources": {},
                           "profile_fingerprint": "old-profile", "pool": pool(1), "results": {"old": {"qualified": True}}}
            store.commit()
            manager = test_recovery_pipeline.RecoveryManager()
            manager.ensure = Mock()
            manager.controller.delay = lambda *_: {"success": True, "latency_ms": 50}
            pipeline = Pipeline(settings, manager=manager)
            with patch("core.proxybench.pipeline.refresh_existing", return_value={"changed": False}):
                pipeline.run(resume=True)
            self.assertEqual(pipeline.store.state["profile_fingerprint"], profile.fingerprint)
            self.assertEqual(pipeline.store.state["session_id"], "same-session")
            self.assertEqual(pipeline.store.state["pool"][0]["port"], 2053)
            self.assertNotIn("old", pipeline.store.state["results"])
            self.assertTrue(list(settings["state_dir"].glob("previous-profile-*-results.json.gz")))

    def test_hot_profile_change_restarts_with_resume_instead_of_reporting_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = test_recovery_pipeline.RecoveryManager()
            pipeline = Pipeline({"state_dir": root, "auto_refresh_profile": True, "profile": root / "proxy.local.yaml"}, manager=manager)
            pipeline._run = Mock(side_effect=[ProfileChanged(), {"status": "resumed"}])
            with patch("core.proxybench.pipeline.refresh_existing", return_value={"changed": False}):
                self.assertEqual(pipeline.run()["status"], "resumed")
            self.assertEqual([call.args for call in pipeline._run.call_args_list], [(False, False, False), (True, False, False)])
