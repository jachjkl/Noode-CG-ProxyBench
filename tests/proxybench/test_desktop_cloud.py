from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.cloud import CloudError
from core.proxybench.desktop_cloud import DesktopCloudController
from core.proxybench.state import Store
from core.proxybench.workflow import progress
from tests.proxybench import test_session_cloud


class DesktopCloudTests(unittest.TestCase):
    def controller(self, root, *, phase="scan"):
        settings = test_session_cloud.SessionCloudTests().settings(root)
        settings["profile"].parent.mkdir(parents=True)
        settings["profile"].touch()
        store = Store(settings["state_dir"])
        store.state = {"phase": phase, "cycle": 1, "session_id": "saved-session", "results": {"saved": {"qualified": True}}}
        store.commit()
        return DesktopCloudController(settings)

    def test_resume_measures_locally_even_when_all_github_calls_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller.command = Mock(side_effect=CloudError("unavailable"))
            controller.prepare_runner = Mock(side_effect=AssertionError("Runner must not be used"))
            controller.fetch_handoff = Mock(side_effect=AssertionError("saved handoff must be reused"))
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), \
                    patch("core.proxybench.desktop_cloud.vpn_environment", return_value={"client_detected": True}), \
                    patch("core.proxybench.desktop_cloud.Pipeline") as pipeline:
                pipeline.return_value.run.return_value = {"status": "stopped", "published": False}
                self.assertEqual(controller.run("resume")["status"], "stopped")
            pipeline.return_value.run.assert_called_once_with(resume=True, handoff=True)
            controller.command.assert_not_called()
            self.assertEqual(Store(controller.settings["state_dir"]).load()["results"], {"saved": {"qualified": True}})

    def test_start_uses_new_window_session_and_cloud_only_then_runs_local_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            (controller.settings["state_dir"] / "session.json").write_text(json.dumps({"session_id": "new-window"}))
            controller.fetch_handoff = Mock()
            controller.local_select = Mock(return_value={"status": "stopped"})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                controller.run()
            controller.fetch_handoff.assert_called_once_with("new-window", reuse=False)
            controller.local_select.assert_called_once()

    def test_continue_and_auto_replenishment_request_fresh_ips_in_same_session(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory), phase="needs_more")
            controller.fetch_handoff = Mock()
            controller.local_select = Mock(side_effect=[{"needs_more": True, "published": False}, {"published": True}])
            controller.publish_pending = Mock(return_value={"url": "https://example.test/publish"})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                self.assertTrue(controller.run("continue")["published"])
            self.assertEqual([call.args for call in controller.fetch_handoff.call_args_list], [("saved-session",)] * 2)
            self.assertTrue(all(call.kwargs == {"reuse": False} for call in controller.fetch_handoff.call_args_list))
            self.assertEqual(controller.publish_pending.call_count, 2)

    def test_failed_result_upload_retains_exact_pending_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller = self.controller(root)
            content = b"public result fixture"
            controller.command = Mock(side_effect=CloudError("network unavailable"))
            with patch("core.proxybench.desktop_cloud.pack", return_value=content), \
                    patch("core.proxybench.desktop_cloud.validate_result_files"), \
                    patch("zipfile.ZipFile"):
                with self.assertRaises(CloudError):
                    controller.upload_pending()
            pending = root / "runtime/pending-publish"
            self.assertEqual((pending / "result.zip").read_bytes(), content)
            self.assertEqual(json.loads((pending / "manifest.json").read_text())["sha256"], hashlib.sha256(content).hexdigest())
            self.assertFalse((pending / "public-upload.json").exists())

    def test_retry_reads_but_never_repeats_dispatch_post(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            with patch("core.proxybench.cloud.CloudController.command", side_effect=[CloudError("temporary"), {"ok": True}]) as command, \
                    patch("core.proxybench.desktop_cloud.time.sleep"):
                self.assertEqual(controller.command(["run", "view", "7"]), {"ok": True})
            self.assertEqual(command.call_count, 2)
            with patch("core.proxybench.cloud.CloudController.command", side_effect=CloudError("temporary")) as command:
                with self.assertRaises(CloudError):
                    controller.command(["workflow", "run", "proxybench.yml"])
            command.assert_called_once()

    def test_detached_live_phase_remains_current_when_publish_has_another_run_id(self):
        live = {"phase": "completed", "status": "completed", "session_id": "same", "workflow_run_id": "7"}
        cloud = {"status": "in_progress", "session_id": "same", "run_id": 8, "local_detached": True,
                 "jobs": [{"name": "云端发布最优IP", "status": "in_progress"}]}
        rows = progress(live, cloud, {"published": True})
        self.assertEqual([row["status"] for row in rows], ["completed"] * 4 + ["running"])

