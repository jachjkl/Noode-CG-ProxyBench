from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.cloud import CloudController
from core.proxybench.cloud_network import cloud_environment
from core.proxybench.state import Store
from core.proxybench.workflow import progress
from tests.proxybench import test_session_cloud


class CloudConnectionTests(unittest.TestCase):
    def test_existing_windows_proxy_is_passed_to_runner_without_mutating_environment(self):
        original = {"PATH": "original", "NO_PROXY": "example.test"}
        with patch("core.proxybench.cloud_network.windows_proxy", return_value="http://127.0.0.1:7890"), \
                patch("core.proxybench.cloud_network.socket.create_connection"):
            env = cloud_environment(original)
        self.assertEqual(original, {"PATH": "original", "NO_PROXY": "example.test"})
        self.assertEqual(env["https_proxy"], "http://127.0.0.1:7890")
        self.assertEqual(env["HTTPS_PROXY"], env["https_proxy"])
        self.assertEqual(env["no_proxy"], "example.test,localhost,127.0.0.1,::1")

    def test_explicit_proxy_is_kept_and_dead_or_nonlocal_automatic_proxy_is_not_used(self):
        with patch("core.proxybench.cloud_network.windows_proxy") as windows:
            env = cloud_environment({"HTTPS_PROXY": "http://owner.example:8080"})
        windows.assert_not_called()
        self.assertEqual(env["https_proxy"], "http://owner.example:8080")
        for proxy in ("http://127.0.0.1:7890", "http://remote.example:7890", "socks5://127.0.0.1:7890"):
            with self.subTest(proxy=proxy), patch("core.proxybench.cloud_network.windows_proxy", return_value=proxy), \
                    patch("core.proxybench.cloud_network.socket.create_connection", side_effect=OSError):
                self.assertNotIn("https_proxy", cloud_environment({}))

    def test_runner_renewal_abandonment_is_detected_only_in_this_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = CloudController({"root": root, "state_dir": root})
            log = controller.runner_root / "_diag/Runner_current.log"
            log.parent.mkdir(parents=True)
            job = "00000000-0000-0000-0000-000000000001"
            evidence = (f"Catch exception during renew runner job {job}.\n"
                        f"finish job request for job {job} with result: Abandoned\n")
            log.write_text(evidence, encoding="utf-8")
            self.assertTrue(controller.runner_lost_connection())
            controller.diag_offsets = {log: log.stat().st_size}
            with log.open("a", encoding="utf-8") as handle:
                handle.write("Job cancellation request received\n")
            self.assertFalse(controller.runner_lost_connection())

    def controller(self, root):
        settings = test_session_cloud.SessionCloudTests().settings(root)
        settings["profile"].parent.mkdir(parents=True)
        settings["profile"].touch()
        settings["output_dir"].mkdir()
        (settings["output_dir"] / "health.json").write_text(json.dumps({"published": True}))
        store = Store(settings["state_dir"])
        store.state = {"phase": "scan", "cycle": 1, "session_id": "same-session", "results": {"saved": {"qualified": True}}}
        store.commit()
        (settings["state_dir"] / "live.json").write_text(json.dumps({"status": "Running", "phase": "scan", "qualified_count": 111,
                                                                     "workflow_run_id": "7", "speed_active": ["PB-1"]}))
        controller = CloudController(settings)
        controller.prepare_runner = Mock()
        controller.dispatch = Mock()
        controller.wait_local_exit = Mock()
        return controller

    def test_cancelled_runner_network_job_resumes_same_handoff_and_preserves_results(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller.runner_lost_connection = Mock(return_value=True)
            controller.watch = Mock(side_effect=[{"conclusion": "cancelled", "url": "https://example.test/7"},
                                                 {"conclusion": "success", "url": "https://example.test/8"}])
            with patch("core.proxybench.cloud.ProxyProfile.load"), patch("core.proxybench.cloud.time.sleep"):
                self.assertTrue(controller.run("resume")["published"])
            self.assertEqual([call.args for call in controller.dispatch.call_args_list], [("same-session", True)] * 2)
            self.assertEqual(Store(controller.settings["state_dir"]).load()["results"], {"saved": {"qualified": True}})
            live = json.loads((controller.settings["state_dir"] / "live.json").read_text())
            self.assertEqual(live["qualified_count"], 111)
            self.assertFalse(live["speed_active"])

    def test_owner_cancel_is_not_restarted_and_live_steps_show_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller.runner_lost_connection = Mock(return_value=False)
            controller.watch = Mock(return_value={"conclusion": "cancelled", "url": "https://example.test/7"})
            with patch("core.proxybench.cloud.ProxyProfile.load"):
                self.assertEqual(controller.run("resume")["reason"], "cancelled")
            controller.dispatch.assert_called_once()
            cloud = json.loads((controller.settings["state_dir"] / "cloud-live.json").read_text())
            live = json.loads((controller.settings["state_dir"] / "live.json").read_text())
            self.assertEqual(live["status"], "Stopped")
            self.assertTrue(cloud["interrupted"])
            rows = progress(live, {**cloud, "run_id": 7}, {})
            self.assertEqual([row["status"] for row in rows], ["completed", "completed", "paused", "pending", "pending"])
            self.assertIn("取消", rows[2]["detail"])

    def test_repeated_connection_loss_has_bounded_recovery_and_retains_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller.runner_lost_connection = Mock(return_value=True)
            controller.watch = Mock(return_value={"conclusion": "cancelled", "url": "https://example.test/7"})
            with patch("core.proxybench.cloud.ProxyProfile.load"), patch("core.proxybench.cloud.time.sleep"):
                result = controller.run("resume")
            self.assertEqual(result["reason"], "runner_connection_lost")
            self.assertEqual(controller.dispatch.call_count, 4)
            self.assertTrue((controller.settings["state_dir"] / "batch-state.json").exists())
