from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.io_utils import atomic_write_json
from core.proxybench.desktop_cloud import DesktopCloudController
from core.proxybench.export import gate, publish
from core.proxybench.pipeline import Pipeline
from core.proxybench.profile import ProxyProfile
from core.proxybench.run_clock import RunClock
from core.proxybench.settings import RULES, current_rules, load_settings
from scripts.proxybench_channel import pack, unpack
from tests.proxybench import test_dashboard_pages, test_session_cloud
from tests.proxybench.test_benchmark import FakeManager, pool
from tests.proxybench.test_profile_sources_state import UUID
from tests.proxybench.test_publication_controller import winners


class ManualPublishTimerTests(unittest.TestCase):
    def test_policy_upgrade_keeps_old_qualified_ips_as_candidates_for_fresh_manual_retest(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = test_session_cloud.SessionCloudTests().settings(Path(directory))
            settings.update(auto_update=False, geo_urls=[], auto_refresh_profile=False)
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].write_text(f'proxy:\n  type: vless\n  port: 443\n  uuid: {UUID}\n', encoding="utf-8")
            manager = FakeManager()
            manager.version = "fixture"
            manager.ensure = Mock()
            manager.stop = Mock()
            manager.health = lambda: {"status": "Stopped"}
            manager.controller.delay = lambda *args: manager.controller.calls.append(args) or {"success": True, "latency_ms": 90}
            node = pool(3)[0]
            pipeline = Pipeline(settings, manager=manager)
            pipeline.store.state = {"run_id": "old", "session_id": "old", "cycle": 1, "phase": "scan", "sources": {}, "pool": pool(3),
                                    "profile_fingerprint": ProxyProfile.load(settings["profile"]).fingerprint,
                                    "measurement_policy": "entry-proxy-v7-trace",
                                    "results": {"104.16.0.1:443": {**node, "qualified": True, "proxy_average_latency_ms": 90}}}
            pipeline.store.commit()
            pipeline.new_pool = Mock(side_effect=AssertionError("manual policy migration must not acquire or scan new IPs"))
            result = pipeline.run(resume=True, publish_only=True)
            self.assertTrue(result["published"])
            self.assertEqual(result["unique_final_count"], 1)
            self.assertEqual({ip for batch in manager.loads for ip in batch}, {"PB-COMP-000001"})
            self.assertEqual(len(manager.controller.calls), 15)
            self.assertTrue(list(settings["state_dir"].glob("previous-policy-*-results.json.gz")))

    def test_elapsed_pauses_resumes_survives_reopen_without_counting_downtime_and_resets(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100.0]
            path = Path(directory) / "timing.json"
            timer = RunClock(path, lambda: now[0])
            timer.start(reset=True)
            now[0] += 65
            self.assertEqual(timer.snapshot(True, False)["elapsed_seconds"], 65)
            timer.snapshot(True, True)
            now[0] += 300
            self.assertEqual(timer.seconds(), 65)
            timer.start()
            now[0] += 5
            timer.snapshot(False, False)
            now[0] += 86400
            reopened = RunClock(path, lambda: now[0])
            self.assertEqual(reopened.seconds(), 70)
            reopened.start()
            now[0] += 2
            self.assertEqual(reopened.seconds(), 72)
            reopened.start(reset=True)
            self.assertEqual(reopened.seconds(), 0)

    def test_new_install_defaults_match_the_owners_current_saved_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
            actual = current_rules(load_settings(root / "config.yaml"))
            self.assertEqual(actual, RULES)
            self.assertEqual((actual["max_entry_latency_ms"], actual["max_proxy_average_latency_ms"], actual["min_proxy_speed_mbps"], actual["round_count"]), (300, 300, 3.01, 5))

    def test_stop_saves_without_queuing_publication_or_starting_a_process(self):
        with tempfile.TemporaryDirectory() as directory:
            dashboard = test_dashboard_pages.DashboardPageTests().controller(Path(directory))
            with patch("core.proxybench.dashboard.subprocess.Popen") as spawn:
                dashboard.action("stop", {})
            spawn.assert_not_called()
            self.assertTrue(dashboard.preserve_on_close)
            self.assertFalse((dashboard.settings["state_dir"] / "publish-request.json").exists())
            self.assertEqual(json.loads((dashboard.settings["state_dir"] / "control.json").read_text())["action"], "stop")

    def test_active_manual_publication_is_queued_idempotently_and_unpauses_without_duplicate_children(self):
        with tempfile.TemporaryDirectory() as directory:
            dashboard = test_dashboard_pages.DashboardPageTests().controller(Path(directory))
            dashboard.process = Mock()
            dashboard.process.poll.return_value = None
            dashboard.action("pause", {})
            with patch("core.proxybench.dashboard.subprocess.Popen") as spawn:
                for _ in range(2):
                    self.assertEqual(dashboard.action("publish", {})["requested"], "publish")
            spawn.assert_not_called()
            self.assertFalse((dashboard.settings["state_dir"] / "control.json").exists())
            self.assertTrue(json.loads((dashboard.settings["state_dir"] / "publish-request.json").read_text())["requested"])

    def test_idle_manual_publication_starts_the_publish_mode_and_empty_results_report_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            dashboard = test_dashboard_pages.DashboardPageTests().controller(Path(directory))
            with self.assertRaisesRegex(ValueError, "没有可推送"):
                dashboard.action("publish", {})
            atomic_write_json(dashboard.settings["state_dir"] / "batch-state.json", {})
            with patch("core.proxybench.dashboard.ProxyProfile.load"), patch("core.proxybench.dashboard.subprocess.Popen") as spawn:
                self.assertTrue(dashboard.action("publish", {})["started"])
            self.assertEqual(spawn.call_args.args[0][-2:], ["--mode", "publish"])
            dashboard.log_handle.close()

    def test_scan_finishes_current_batch_then_leaves_unmeasured_candidates_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = {"state_dir": root, "rules_path": root / "rules.json", "rules": {**RULES, "batch_size": 1, "round_cooldown_seconds": 0}, "geo_urls": []}
            manager = FakeManager()
            manager.health = lambda: {"status": "Stopped"}
            pipeline = Pipeline(settings, manager=manager)
            pipeline.store.state = {"run_id": "run", "phase": "scan", "pool": pool(3), "results": {}}
            original = pipeline.store.commit
            def queue_after_batch():
                original()
                atomic_write_json(root / "publish-request.json", {"requested": True})
            pipeline.store.commit = queue_after_batch
            pipeline.scan(pool(3), "results", {"default": object()})
            self.assertEqual(len(pipeline.store.state["results"]), 1)
            self.assertEqual(len(pipeline.store.state["pool"]), 3)

    def test_manual_partial_results_cross_cloud_channel_but_automatic_partial_output_cannot(self):
        records = [*winners()[:3], *winners()[100:102]]
        self.assertFalse(gate(records))
        self.assertTrue(gate(records, allow_partial=True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(publish(root / "automatic", records, {})["published"])
            result = publish(root / "local/output", records, {"manual_publication": True})
            self.assertTrue(result["published"])
            self.assertFalse(result["quota_complete"])
            content = pack(root / "local", "result")
            unpack(content, hashlib.sha256(content).hexdigest(), root / "cloud", "result")
            self.assertEqual(len((root / "cloud/output/nodes.txt").read_text().splitlines()), 5)
            self.assertEqual(json.loads((root / "cloud/output/api.json").read_text())["count"], 5)
        records[-1]["geo_verified"] = False
        self.assertFalse(gate(records, allow_partial=True))

    def test_publish_mode_retests_saved_partial_results_and_never_fetches_or_scans_unmeasured_ips(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = test_session_cloud.SessionCloudTests().settings(Path(directory))
            settings.update(auto_update=False, geo_urls=["https://geo.example.test"], auto_refresh_profile=False)
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].write_text(f'proxy:\n  type: vless\n  port: 443\n  uuid: {UUID}\n', encoding="utf-8")
            profile = ProxyProfile.load(settings["profile"])
            manager = FakeManager()
            manager.version = "fixture"
            manager.health = lambda: {"status": "Stopped"}
            manager.ensure = Mock()
            manager.stop = Mock()
            manager.controller.delay = lambda *_: {"success": True, "latency_ms": 90}
            pipeline = Pipeline(settings, manager=manager)
            nodes = pool(4)
            pipeline.store.state = {"phase": "scan", "cycle": 1, "session_id": "saved", "run_id": "saved",
                                    "profile_fingerprint": profile.fingerprint, "sources": {}, "pool": nodes,
                                    "measurement_policy": "entry-proxy-v9-verified-trace-get",
                                    "results": {"104.16.0.1:443": {**nodes[0], "qualified": True, "proxy_average_latency_ms": 90}}}
            pipeline.store.commit()
            pipeline.store.save_partial({**nodes[1], "key": "104.16.0.2:443", "qualified": True, "proxy_average_latency_ms": 95})
            pipeline.new_pool = Mock(side_effect=AssertionError("manual publication must not fetch"))
            result = pipeline.run(resume=True, publish_only=True)
            self.assertTrue(result["published"])
            self.assertEqual(result["unique_final_count"], 2)
            self.assertEqual(pipeline.store.state["phase"], "scan")
            self.assertEqual({name for group in manager.loads for name in group}, {"PB-COMP-000001", "PB-COMP-000002"})
            records = json.loads((settings["output_dir"] / "nodes.json").read_text(encoding="utf-8"))
            self.assertTrue(all(len(row[site + "_rounds_ms"]) == 5 for row in records for site in ("google", "cloudflare", "github")))
            manager.stop.assert_called()

    def test_controller_manual_publication_never_calls_cloud_discovery_and_confirms_push(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = test_session_cloud.SessionCloudTests().settings(Path(directory))
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            controller = DesktopCloudController(settings)
            controller.fetch_handoff = Mock(side_effect=AssertionError("must not discover new IPs"))
            controller.local_select = Mock(return_value={"published": True, "manual_publication": True, "general_final_count": 7, "jp_final_count": 2})
            controller.publish_pending = Mock(return_value={"url": "https://example.test/publish"})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                result = controller.run("publish")
            controller.local_select.assert_called_once_with(publish_only=True)
            self.assertTrue(result["cloud_confirmed"])
            self.assertEqual(controller.live["status"], "Completed")

    def test_cloud_request_before_discovery_switches_to_existing_results(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = test_session_cloud.SessionCloudTests().settings(Path(directory))
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            atomic_write_json(settings["state_dir"] / "publish-request.json", {"requested": True})
            controller = DesktopCloudController(settings)
            controller.fetch_handoff = Mock(side_effect=AssertionError("do not fetch after manual request"))
            controller.local_select = Mock(return_value={"published": False, "manual_publication": True})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                self.assertFalse(controller.run()["published"])
            controller.local_select.assert_called_once_with(publish_only=True)

    def test_pending_retry_uses_archived_health_even_when_local_health_has_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = test_session_cloud.SessionCloudTests().settings(root)
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            publish(root / "output", winners(), {})
            archive = pack(root, "result")
            pending = root / "runtime/pending-publish"
            pending.mkdir(parents=True)
            (pending / "result.zip").write_bytes(archive)
            atomic_write_json(pending / "manifest.json", {"sha256": hashlib.sha256(archive).hexdigest()})
            atomic_write_json(root / "output/health.json", {"published": False})
            controller = DesktopCloudController(settings)
            controller.local_select = Mock(side_effect=AssertionError("completed pending payload needs no new measurements"))
            controller.publish_pending = Mock(return_value={"url": "https://example.test/confirmed"})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                self.assertTrue(controller.run("publish")["published"])
            controller.publish_pending.assert_called_once()

    def test_manual_network_failure_reports_failure_and_keeps_publication_request(self):
        from core.proxybench.cloud import CloudError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = test_session_cloud.SessionCloudTests().settings(root)
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            request = settings["state_dir"] / "publish-request.json"
            atomic_write_json(request, {"requested": True})
            controller = DesktopCloudController(settings)
            controller.local_select = Mock(return_value={"published": True, "manual_publication": True, "general_final_count": 2, "jp_final_count": 0})
            controller.publish_pending = Mock(side_effect=CloudError("temporary"))
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                with self.assertRaises(CloudError):
                    controller.run("publish")
            self.assertTrue(request.exists())
            self.assertEqual(controller.live["status"], "Failed")
