from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.controller import Controller, CoreError
from core.proxybench.direct_benchmark import DirectManager
from core.proxybench.mihomo_manager import MihomoManager
from core.proxybench.modes import mode_settings
from core.proxybench.pipeline import Pipeline
from core.proxybench.settings import load_settings
from tests.proxybench.test_benchmark import pool


class CoreVersionHistoryTests(unittest.TestCase):
    def release(self, tag, binary):
        if os.name == "nt":
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as package:
                package.writestr("mihomo.exe", binary)
            content = stream.getvalue()
            name = f"mihomo-windows-amd64-compatible-{tag}.zip"
        else:
            content = gzip.compress(binary)
            name = f"mihomo-linux-amd64-{tag}.gz"
        return {"tag_name": tag, "assets": [{"name": name, "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                                             "browser_download_url": f"https://github.com/MetaCubeX/mihomo/releases/download/{tag}/{name}"}]}, content

    def seed(self, root):
        manager = MihomoManager(root)
        manager.binary.write_bytes(b"core-one")
        (root / "version.json").write_text(json.dumps({"version": "v1.0.0"}), encoding="utf-8")
        manager.read_version = Mock(return_value="Mihomo v1.0.0")
        return manager

    def test_verified_updates_keep_exactly_current_and_previous_and_rollback_is_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.seed(root)
            for tag, binary in (("v2.0.0", b"core-two"), ("v3.0.0", b"core-three")):
                release, archive = self.release(tag, binary)
                with patch("core.proxybench.mihomo_manager.platform.machine", return_value="AMD64"), \
                     patch("core.proxybench.mihomo_manager.download", side_effect=[json.dumps(release).encode(), archive]), \
                     patch.object(manager, "start", side_effect=AssertionError("update review must not start a direct-mode proxy")):
                    manager.ensure(True, validate_start=False)
            self.assertEqual(manager.version_catalog()["versions"], ["v3.0.0", "v2.0.0"])
            self.assertEqual((root / "mihomo.previous").read_bytes(), b"core-two")
            self.assertFalse((root / "mihomo.backup").exists())
            manager.choose_version("v2.0.0")
            self.assertEqual(manager.binary.read_bytes(), b"core-two")
            self.assertEqual(manager.version_catalog()["versions"], ["v2.0.0", "v3.0.0"])
            manager.choose_version("v3.0.0")
            self.assertEqual(manager.binary.read_bytes(), b"core-three")

    def test_manual_rollback_checks_new_releases_but_preserves_selected_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.seed(root)
            manager.choose_version("v1.0.0")
            release, _ = self.release("v2.0.0", b"new")
            with patch("core.proxybench.mihomo_manager.download", return_value=json.dumps(release).encode()) as fetch:
                manager.ensure(True, validate_start=False)
            fetch.assert_called_once()
            self.assertEqual(manager.binary.read_bytes(), b"core-one")
            self.assertEqual(manager.version_catalog()["latest"], "v2.0.0")

    def test_direct_task_still_checks_updates_without_loading_any_proxy_or_route(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
            pipeline = Pipeline(mode_settings(load_settings(root / "config.yaml"), "tcp_tls"))
            self.assertIsInstance(pipeline.manager, DirectManager)
            with patch.object(pipeline.manager.updater, "ensure") as ensure:
                pipeline.manager.ensure(False)
            ensure.assert_called_once_with(True, validate_start=False)

    def test_tampered_previous_binary_and_switch_while_active_never_replace_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.seed(root)
            (root / "mihomo.previous").write_bytes(b"tampered")
            (root / "previous-version.json").write_text(json.dumps({"version": "v0.9.0", "binary_sha256": "wrong"}))
            with self.assertRaises(CoreError):
                manager.choose_version("v0.9.0")
            self.assertEqual(manager.binary.read_bytes(), b"core-one")
            manager.benchmark_active = True
            with self.assertRaises(CoreError):
                manager.choose_version("v1.0.0")

    def test_failed_rollback_validation_restores_both_binary_slots_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = self.seed(root)
            previous = b"broken-old"
            (root / "mihomo.previous").write_bytes(previous)
            (root / "previous-version.json").write_text(json.dumps({"version": "v0.9.0", "binary_sha256": hashlib.sha256(previous).hexdigest()}))
            manager.read_version.side_effect = CoreError("invalid version")
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            with self.assertRaises(CoreError):
                manager.choose_version("v0.9.0")
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_three_hundred_independent_rule_inbounds_and_batch_cleanup_only_touch_owned_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = MihomoManager(Path(directory))
            manager.controller = Controller(1234, "fixture", 2345)
            profile = Mock()
            profile.definition.side_effect = lambda ip, name: {"name": name, "type": "http", "server": ip, "port": 443}
            config = manager.config(pool(300), profile)
            self.assertEqual(len(config["proxies"]), 300)
            self.assertEqual(len(config["listeners"]), 301)
            self.assertEqual(len({row["port"] for row in config["listeners"]}), 301)
            self.assertIn("IN-NAME,proxybench-node-299,PB-000300", config["rules"])
            manager.process = Mock()
            manager.process.poll.return_value = None
            manager.controller.call = Mock()
            manager.loaded = 300
            manager.clear_batch()
            self.assertEqual(manager.loaded, 0)
            self.assertEqual(manager.controller.named_ports, {})
            manager.controller.call.assert_any_call("/connections", "DELETE")
            payload = manager.controller.call.call_args.args[2]["payload"]
            self.assertIn("proxies: []", payload)

