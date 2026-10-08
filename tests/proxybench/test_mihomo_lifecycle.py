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

from core.proxybench.controller import CoreError
from core.proxybench.mihomo_manager import MihomoManager


class MihomoLifecycleTests(unittest.TestCase):
    def test_release_mirror_digest_failure_falls_back_to_valid_mirror(self):
        from core.proxybench.mihomo_manager import release_download
        expected = hashlib.sha256(b"valid core").hexdigest()
        with patch("core.proxybench.mihomo_manager.download", side_effect=[b"wrong core", OSError(), b"valid core"]) as fetch:
            self.assertEqual(release_download("https://github.com/example/core.zip", expected), b"valid core")
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(fetch.call_args_list[0].args[0].startswith("https://ghfast.top/"))

    def test_update_is_forbidden_while_benchmark_active(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = MihomoManager(Path(directory))
            manager.benchmark_active = True
            with patch("core.proxybench.mihomo_manager.download") as download:
                with self.assertRaises(CoreError):
                    manager.ensure()
                download.assert_not_called()

    def test_failed_new_core_health_rolls_back_old_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = MihomoManager(Path(directory))
            manager.binary.write_bytes(b"old-core")
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as package:
                package.writestr("mihomo.exe", b"new-core")
            content = stream.getvalue() if os.name == "nt" else gzip.compress(b"new-core")
            asset_name = "mihomo-windows-amd64-compatible-v9.0.0.zip" if os.name == "nt" else "mihomo-linux-amd64-v9.0.0.gz"
            release = {"tag_name": "v9.0.0", "draft": False, "prerelease": False,
                       "assets": [{"name": asset_name, "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                                   "browser_download_url": "https://github.com/MetaCubeX/mihomo/releases/download/v9.0.0/core.zip"}]}
            with patch("core.proxybench.mihomo_manager.platform.machine", return_value="AMD64"), \
                 patch("core.proxybench.mihomo_manager.download", side_effect=[json.dumps(release).encode(), content]), \
                 patch.object(manager, "read_version", return_value="old-version"), patch.object(manager, "start", side_effect=CoreError("health failed")) as start:
                manager.ensure()
                start.assert_called_once()
            self.assertEqual(manager.binary.read_bytes(), b"old-core")
            self.assertEqual(manager.version, "old-version")

    def test_core_process_alive_does_not_imply_controller_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = MihomoManager(Path(directory))
            manager.process = Mock()
            manager.process.poll.return_value = None
            manager.controller = Mock()
            manager.controller.call.side_effect = CoreError("failed")
            self.assertFalse(manager.health()["controller_healthy"])
            self.assertEqual(manager.health()["status"], "Failed")

    def test_orphan_with_wrong_executable_is_never_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = MihomoManager(root)
            work = root / "session-test"
            work.mkdir()
            manager.owner_path.write_text(json.dumps({"pid": 1, "created": 1, "work": str(work)}))
            process = Mock()
            process.exe.return_value = str(root / "another-user-core.exe")
            with patch("core.proxybench.mihomo_manager.psutil.Process", return_value=process):
                with self.assertRaises(CoreError):
                    manager.cleanup_orphan()
            process.terminate.assert_not_called()
            process.kill.assert_not_called()
