from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.build_delivery_bundle import assemble, build_inputs
from scripts.package_proxybench import package
from scripts.package_sources import public_source_files


class DeliveryBundleTests(unittest.TestCase):
    def write(self, root, name, data=b"fixture"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_extracted_source_without_git_can_rebuild_and_omits_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["main.py", "core/new-fix.py", "windows-controller/dashboard/proxybench.js", "output/README.md",
                         "runtime/runner/.credentials", "runtime/session-private/config.yaml", "config/proxy-profile.local.yaml",
                         "data/proxy-bench/results.json", "dist/previous.zip", ".env", "core/__pycache__/old.pyc"]:
                self.write(root, name)
            self.write(root, "output/nodes.txt", b"stale published data")
            with patch("scripts.package_sources.subprocess.check_output", side_effect=FileNotFoundError):
                names = public_source_files(root)
                with patch("scripts.package_proxybench.ROOT", root):
                    package(root / "dist/source.zip")
            self.assertIn("core/new-fix.py", names)
            self.assertNotIn("config/proxy-profile.local.yaml", names)
            self.assertNotIn("runtime/runner/.credentials", names)
            self.assertNotIn(".env", names)
            with zipfile.ZipFile(root / "dist/source.zip") as archive:
                self.assertEqual(archive.read("Noode-CG-ProxyBench/output/nodes.txt"), b"")
                self.assertIn("Noode-CG-ProxyBench/core/new-fix.py", archive.namelist())
                self.assertFalse(any(".local." in name or "/runtime/" in name or "/data/" in name for name in archive.namelist()))

    def test_combined_bundle_layout_and_file_digests_cover_local_and_cloud(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            windows = self.write(root, "dist/local.zip")
            installer = self.write(root, "dist/local.exe")
            source = self.write(root, "dist/cloud.zip")
            cache = self.write(root, "runtime/python-3.12.10-embed-amd64.zip")
            self.write(root, "scripts/windows/Rebuild-Bundle.ps1", b"# fixture rebuild script")
            destination = assemble(root / "dist/bundle.zip", windows=windows, installer=installer,
                                   source=source, inputs=[cache], personal=True, root=root)
            with zipfile.ZipFile(destination) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertTrue(manifest["contains_local_profile"])
                self.assertIn("本地测速/安装包/local.zip", archive.namelist())
                self.assertIn("云端部署/源码/cloud.zip", archive.namelist())
                self.assertIn("准备修复工作区.cmd", archive.namelist())
                self.assertIn("重新打包.cmd", archive.namelist())
                self.assertTrue(archive.read("维护与重新打包.ps1").startswith(b"\xef\xbb\xbf"))
                for record in manifest["files"]:
                    self.assertEqual(hashlib.sha256(archive.read(record["path"])).hexdigest(), record["sha256"])

    def test_build_cache_is_explicit_and_never_includes_runner_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["python-3.12.10-embed-amd64.zip", "gh-release.json", "mihomo/mihomo.exe", "mihomo/version.json",
                         "gh_2.102.0_windows_amd64.zip", "wheels/pyyaml-6.0.3.whl", "wheels/psutil-7.2.2.whl",
                         "runner/.credentials", "mihomo/owner.json", "mihomo/session-test/config.yaml"]:
                self.write(root, "runtime/" + name)
            inputs = build_inputs(root)
            self.assertEqual(len(inputs), 7)
            self.assertFalse(any(".credentials" in path.name or path.name == "config.yaml" for path in inputs))
            (root / "runtime/wheels/psutil-7.2.2.whl").unlink()
            with self.assertRaises(ValueError):
                build_inputs(root)


if __name__ == "__main__":
    unittest.main()
