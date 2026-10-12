from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from core.io_utils import atomic_write_bytes, atomic_write_json
from core.proxybench.cloud import CloudController, CloudError
from core.proxybench.cloud_network import cloud_environment, network_settings, save_network
from core.proxybench.dashboard import BenchDashboard
from core.proxybench.desktop_cloud import DesktopCloudController
from core.proxybench.github_destination import check_destination, destination
from core.proxybench.github_login import start
from core.proxybench.handoff import validate
from core.proxybench.multi_dashboard import MultiModeDashboard
from core.proxybench.pipeline import prepare
from core.proxybench.session_lifecycle import clear_shared
from sources.pool import build
from tests.proxybench import test_session_cloud


class FullCloudDeliveryTests(unittest.TestCase):
    def settings(self, root):
        return test_session_cloud.SessionCloudTests().settings(root)

    def feeds(self):
        return {"https://zip.cm.edu.kg/all.txt": b"104.16.1.1\n104.17.1.1",
                "https://bestcf.pages.dev/lzj/all.txt": b"104.17.1.1\n104.17.1.2",
                "https://www.cloudflare.com/ips-v4/": b"104.16.0.0/13\n172.64.0.0/13"}

    def builder(self, settings, port, excluded, *, include_fixed):
        return build(settings, port, excluded, downloader=self.feeds().__getitem__, include_fixed=include_fixed)

    def payload(self, root):
        return json.loads(gzip.decompress((root / "data/handoff/proxybench-pool.json.gz").read_bytes()))

    def test_committed_initial_request_retries_exact_bytes_and_five_rounds_remain_disjoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self.settings(root)
            with patch("core.proxybench.pipeline.build", side_effect=self.builder) as builder:
                first = prepare(settings, session_id="window", fetch_id="initial", initial_full=True)
                path = root / "data/handoff/proxybench-pool.json.gz"
                saved = path.read_bytes()
                self.assertEqual(prepare(settings, session_id="window", fetch_id="initial", initial_full=True), first)
                self.assertEqual(path.read_bytes(), saved)
                self.assertEqual(builder.call_count, 1)
                seen = set()
                for index in range(5):
                    if index:
                        prepare(settings, session_id="window", fetch_id=f"round-{index}")
                    payload = self.payload(root)
                    validate(payload, session_id="window", fetch_id="initial" if index == 0 else f"round-{index}", initial_full=index == 0)
                    ips = {row["ip"] for row in payload["pool"]}
                    self.assertFalse(ips & seen)
                    seen.update(ips)
                    self.assertEqual(payload["report"]["first_round_sources"], first["fixed_sources"])
                self.assertEqual(len(seen), 50003)
                self.assertEqual([call.kwargs["include_fixed"] for call in builder.call_args_list], [True, False, False, False, False])
                prepare(settings, session_id="next-window", fetch_id="new", initial_full=True)
                self.assertTrue(builder.call_args.kwargs["include_fixed"])

    def test_old_failed_cloud_commit_without_delivered_pool_can_recover_full_initial_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("core.proxybench.pipeline.build", side_effect=self.builder):
                prepare(self.settings(root), session_id="legacy")
                prepare(self.settings(root), session_id="legacy")
                result = prepare(self.settings(root), session_id="legacy", fetch_id="fixed", initial_full=True)
            self.assertEqual(result["cycle"], 1)
            self.assertTrue(result["fixed_fetched_this_round"])
            validate(self.payload(root), session_id="legacy", fetch_id="fixed", initial_full=True)

    def test_incomplete_source_or_1000_official_candidates_cannot_enter_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("core.proxybench.pipeline.build", side_effect=self.builder):
                prepare(self.settings(root), session_id="window", fetch_id="request", initial_full=True)
            payload = self.payload(root)
            for kind in ("fixed", "official", "request"):
                damaged = json.loads(json.dumps(payload))
                if kind == "fixed":
                    damaged["report"]["fixed_sources"]["fixed-source-a"] += 1
                elif kind == "official":
                    damaged["report"]["cloudflare_official_count"] = 1000
                else:
                    damaged["report"]["fetch_id"] = "another"
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    validate(damaged, session_id="window", fetch_id="request", initial_full=True)

    def test_desktop_cloud_never_uses_limited_job_output_channel_and_has_full_artifact(self):
        workflow = yaml.safe_load(Path(".github/workflows/proxybench.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["cloud-prepare"]["steps"]
        encode = next(step for step in steps if step.get("id") == "encode")
        self.assertEqual(encode["if"], "inputs.prepare_only != true")
        artifact = next(step for step in steps if step.get("name") == "Save trusted mirror download metadata")
        self.assertEqual(artifact["with"]["if-no-files-found"], "error")
        metadata = next(step for step in steps if step.get("name") == "Prepare trusted mirror download metadata")
        self.assertIn("shutil.copyfile('data/handoff/proxybench-pool.json.gz'", metadata["run"])

    def test_failed_delivery_keeps_request_and_official_artifact_recovers_identical_full_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self.settings(root)
            controller = DesktopCloudController(settings)
            controller.dispatch_named = Mock()
            controller.watch = Mock(return_value={"conclusion": "failure"})
            with self.assertRaises(CloudError):
                controller.fetch_handoff("window", False)
            marker = root / "data/pending-cloud-fetch.json"
            pending = json.loads(marker.read_text())
            self.assertTrue(pending["initial_full"])
            with patch("core.proxybench.pipeline.build", side_effect=self.builder):
                prepare(settings, session_id="window", fetch_id=pending["fetch_id"], initial_full=True)
            content = (root / "data/handoff/proxybench-pool.json.gz").read_bytes()
            (root / "data/handoff/proxybench-pool.json.gz").unlink()
            controller.run_id = 7
            directories = []
            def official_artifact(args, **kwargs):
                dest = Path(args[args.index("--dir") + 1])
                self.assertFalse((dest / "handoff.json").exists(), "official CLI refuses to overwrite previous downloads")
                directories.append(dest)
                atomic_write_json(dest / "handoff.json", {"repository": controller.repository, "ref": "a" * 40, "session_id": "window", "sha256": hashlib.sha256(content).hexdigest()})
                atomic_write_bytes(dest / "proxybench-pool.json.gz", content)
            controller.command = Mock(side_effect=official_artifact)
            controller.watch.return_value = {"conclusion": "success"}
            with patch("core.proxybench.desktop_cloud.download", side_effect=RuntimeError("mirrors unavailable")):
                controller.fetch_handoff("window", False)
            requests = controller.dispatch_named.call_args_list
            self.assertEqual(requests[0].args, requests[1].args)
            self.assertEqual(len(self.payload(root)["pool"]), 10003)
            self.assertFalse(marker.exists())
            self.assertEqual((root / "data/handoff/proxybench-pool.json.gz").read_bytes(), content)
            atomic_write_json(marker, pending)
            with patch("core.proxybench.desktop_cloud.download", side_effect=RuntimeError("mirrors unavailable")):
                controller.fetch_handoff("window", False)
            self.assertNotEqual(directories[0], directories[1])
            self.assertTrue(all(not directory.exists() for directory in directories))
            self.assertFalse(marker.exists())

    def test_dispatch_with_same_fetch_id_finds_existing_success_without_extra_post(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = DesktopCloudController(self.settings(Path(directory)))
            controller.command = Mock(return_value=[{"databaseId": 8, "displayTitle": "window request", "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}])
            controller.dispatch_named("proxybench.yml", {"fetch_id": "request"})
            self.assertEqual(controller.run_id, 8)
            self.assertEqual(controller.command.call_count, 1)
            self.assertEqual(controller.command.call_args.args[0][:2], ["run", "list"])

    def ui(self, root):
        (root / "config.yaml").write_bytes(Path("config.yaml").read_bytes())
        return MultiModeDashboard(SimpleNamespace(root=root, repository="jachjkl/Noode-CG-ProxyBench"))

    def test_cloud_failure_before_any_test_retains_session_and_pending_request_on_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ui = self.ui(root)
            child = ui.controllers["proxy"]
            old = json.loads((child.settings["state_dir"] / "session.json").read_text())["session_id"]
            atomic_write_json(child.settings["state_dir"] / "cloud-live.json", {"status": "Failed"})
            atomic_write_json(root / "data/pending-cloud-fetch.json", {"session_id": old, "fetch_id": "pending", "initial_full": True})
            ui.request_close()
            self.assertFalse(ui.finish_close(True))
            reopened = self.ui(root)
            self.assertTrue(reopened.controllers["proxy"].recovery_pending)
            for other in reopened.controllers.values():
                self.assertEqual(json.loads((other.settings["state_dir"] / "session.json").read_text())["session_id"], old)
            self.assertEqual(json.loads((root / "data/pending-cloud-fetch.json").read_text())["fetch_id"], "pending")

    def test_normal_paused_stopped_or_published_window_reopens_without_checkpoint(self):
        for status in ("Paused", "Stopped", "Completed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ui = self.ui(root)
                child = ui.controllers["proxy"]
                old = json.loads((child.settings["state_dir"] / "session.json").read_text())["session_id"]
                atomic_write_json(child.settings["state_dir"] / "live.json", {"status": status})
                atomic_write_json(root / "data/pending-cloud-fetch.json", {"session_id": old})
                ui.request_close()
                self.assertTrue(ui.finish_close(True))
                reopened = self.ui(root)
                self.assertFalse(reopened.controllers["proxy"].recovery_pending)
                self.assertNotEqual(json.loads((reopened.controllers["proxy"].settings["state_dir"] / "session.json").read_text())["session_id"], old)
                self.assertFalse((root / "data/pending-cloud-fetch.json").exists())

    def test_unexpected_close_retains_fetch_session_even_without_live_measurement_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ui = self.ui(root)
            child = ui.controllers["proxy"]
            session = json.loads((child.settings["state_dir"] / "session.json").read_text())["session_id"]
            atomic_write_json(child.lifecycle_path, {"last_exit": "error", "recovery_pending": True})
            reopened = BenchDashboard(SimpleNamespace(root=root, repository=child.settings["repository"]), session_id="new-window")
            self.assertEqual(json.loads((reopened.settings["state_dir"] / "session.json").read_text())["session_id"], session)

    def test_proxy_opt_in_is_saved_and_default_never_adopts_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(network_settings(root)["enabled"])
            base = {"HTTPS_PROXY": "http://127.0.0.1:9999"}
            self.assertNotIn("HTTPS_PROXY", cloud_environment(base, root=root))
            save_network(root, {"enabled": True, "proxy_url": "http://127.0.0.1:7890"})
            self.assertEqual(cloud_environment(base, root=root)["HTTPS_PROXY"], "http://127.0.0.1:7890")
            clear_shared(root)
            self.assertTrue(network_settings(root)["enabled"])
            save_network(root, {"enabled": False, "proxy_url": "http://127.0.0.1:7890"})
            self.assertNotIn("HTTPS_PROXY", cloud_environment(base, root=root))
            for url in ("http://remote.example:7890", "http://secret@localhost:7890", "socks5://127.0.0.1:7890", "http://127.0.0.1:7890/token"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    save_network(root, {"enabled": True, "proxy_url": url})

    def test_network_failure_is_not_misreported_as_expired_authorization(self):
        client = Mock()
        client.command.side_effect = CloudError("GitHub 官方连接超时", category="network")
        events = []
        with self.assertRaisesRegex(ValueError, "连接超时"):
            check_destination(client, destination("owner/repo"), events.append)
        self.assertNotIn("尚未登录", events[-1]["detail"])

    def test_command_classifies_network_and_authentication_without_logging_raw_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            client = CloudController(self.settings(Path(directory)))
            client.gh = "gh"
            for error, category in (("dial tcp: connection refused secret", "network"), ("HTTP 401 Bad credentials secret", "auth")):
                with patch("core.proxybench.cloud.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr=error)):
                    with self.assertRaises(CloudError) as raised:
                        client.command(["api", "user"])
                    self.assertEqual(raised.exception.category, category)
                    self.assertNotIn("secret", str(raised.exception))
            with patch("core.proxybench.cloud.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 8)):
                with self.assertRaises(CloudError) as raised:
                    client.command(["api", "user"])
                self.assertEqual(raised.exception.category, "network")

    def test_login_extracts_code_in_hidden_process_without_recording_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = SimpleNamespace(root=root, gh="gh")
            process = SimpleNamespace(stdout=io.StringIO("secret token must not persist\n! One-time code (ABCD-EFGH) copied to clipboard\n"))
            ready = threading.Event()
            found = []
            def on_code(proc, code, copied):
                found.append((code, copied))
                ready.set()
            with patch("core.proxybench.github_login.subprocess.Popen", return_value=process) as popen, patch.dict("os.environ", {"GH_TOKEN": "test-token"}):
                self.assertIs(start(client, on_code), process)
                self.assertTrue(ready.wait(2))
            self.assertEqual(found, [("ABCD-EFGH", True)])
            options = popen.call_args.kwargs
            self.assertNotIn("GH_TOKEN", options["env"])
            self.assertEqual(options["stdin"], subprocess.DEVNULL)
            self.assertIn("--clipboard", popen.call_args.args[0])
            self.assertEqual(list(root.rglob("*")), [])

    def test_refresh_code_discards_old_callbacks_and_never_reuses_previous_code(self):
        with tempfile.TemporaryDirectory() as directory:
            ui = self.ui(Path(directory))
            callbacks = []
            processes = []
            def login(client, callback):
                process = Mock()
                process.poll.return_value = None
                callbacks.append(callback)
                processes.append(process)
                return process
            with patch("core.proxybench.github_login.start", side_effect=login):
                ui.login_github()
                callbacks[0](processes[0], "AAAA-BBBB", True)
                self.assertEqual(ui.github_status["device"]["code"], "AAAA-BBBB")
                ui.action("refresh-github-code", {})
                self.assertEqual(ui.github_status["device"]["code"], "")
                callbacks[0](processes[0], "AAAA-BBBB", True)
                self.assertEqual(ui.github_status["device"]["code"], "")
                callbacks[1](processes[1], "CCCC-DDDD", True)
                self.assertEqual(ui.github_status["device"]["code"], "CCCC-DDDD")
                processes[0].terminate.assert_called_once()
                ui.action("cancel-github-login", {})
                callbacks[1](processes[1], "CCCC-DDDD", True)
                self.assertNotIn("device", ui.github_status)

    def test_official_expired_response_refreshes_code_without_reusing_or_persisting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            ui = self.ui(Path(directory))
            ui.github_status = {"status": "Authenticating", "steps": [{"id": "account"}], "device": {"code": "AAAA-BBBB"}}
            ui.github_login_process = SimpleNamespace(poll=lambda: 1, returncode=1, device_expired=True)
            def renew():
                self.assertNotIn("device", ui.github_status)
                ui.github_status = {"status": "Authenticating", "device": {"code": ""}}
            with patch.object(ui, "login_github", side_effect=renew) as login:
                ui.snapshot()
                login.assert_called_once()
            self.assertEqual(ui.github_status["device"]["code"], "")
