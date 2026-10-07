from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.proxybench.profile import ProfileError, ProxyProfile, import_link, save_import
from core.proxybench.state import RunLock, Store
from sources.common import merge
from sources.pool import build

UUID = "00000000-0000-4000-8000-000000000001"


class ProfileSourceStateTests(unittest.TestCase):
    def test_only_server_and_name_change_for_each_candidate(self):
        profile = ProxyProfile({"protocol": "vless", "port": 443, "uuid": UUID, "tls": True, "network": "ws",
                                "sni": "worker.example", "Host": "worker.example", "ws_path": "/auth-path"})
        first = profile.definition("104.16.1.1", "PB-1")
        second = profile.definition("104.16.1.2", "PB-2")
        first.pop("server")
        second.pop("server")
        first.pop("name")
        second.pop("name")
        self.assertEqual(first, second)
        self.assertEqual(first["ws-opts"]["path"], "/auth-path")
        self.assertNotIn(UUID, json.dumps(profile.summary()))

    def test_missing_or_invalid_profile_cannot_fallback(self):
        with self.assertRaisesRegex(ProfileError, "缺少可用代理协议配置"):
            ProxyProfile.load(Path("/definitely/missing/local.yaml"))
        with self.assertRaises(ProfileError):
            ProxyProfile({"type": "vless", "uuid": "invalid"})

    def test_import_link_keeps_real_protocol_parameters(self):
        value = import_link(f"vless://{UUID}@104.16.1.1:443?security=tls&type=ws&sni=worker.example&host=worker.example&path=%2Ftoken%3Dprivate&fp=chrome&alpn=http%2F1.1")
        self.assertEqual(value["ws-opts"]["path"], "/token=private")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proxy-profile.local.yaml"
            summary = save_import(f"vless://{UUID}@104.16.1.1:443?type=ws&sni=worker.example", path)
            self.assertNotIn(UUID, json.dumps(summary))
            self.assertIn(UUID, path.read_text())

    def test_full_fixed_sources_and_official_quota_and_invalid_jp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = {"root": root, "state_dir": root / "state", "official_sample_count": 100,
                        "sources": {"jp_supplemental": [{"name": "jp", "url": "https://feed.example/JP.txt"}]}}
            payloads = {"https://zip.cm.edu.kg/all.txt": "\n".join(f"104.16.{index // 254}.{index % 254 + 1}" for index in range(10003)).encode(),
                        "https://bestcf.pages.dev/lzj/all.txt": b"104.16.0.1#JP\n104.17.1.1",
                        "https://www.cloudflare.com/ips-v4/": b"104.16.0.0/13\n172.64.0.0/13",
                        "https://feed.example/JP.txt": b"104.17.1.1\n172.64.3.3\n8.8.8.8"}
            pool, report = build(settings, 443, seed="seed-a", downloader=payloads.__getitem__)
            self.assertEqual(report["fixed_sources"]["fixed-source-a"], 10003)
            self.assertEqual(report["cloudflare_official_count"], 100)
            official = [x for x in pool if "cloudflare-official" in x["source_names"]]
            self.assertTrue(any(x["ip"].startswith("104.") for x in official))
            self.assertTrue(any(x["ip"].startswith("172.") for x in official))
            self.assertEqual(report["jp_supplement_count"], 2)
            self.assertEqual(report["source_invalid"][0]["ip"], "8.8.8.8")
            shared = next(item for item in pool if item["ip"] == "104.17.1.1")
            self.assertEqual(set(shared["source_names"]), {"fixed-source-b", "jp"})
            self.assertTrue(shared["jp_hint"])
            again, _ = build(settings, 443, seed="seed-a", downloader=payloads.__getitem__)
            self.assertEqual([x["ip"] for x in again], [x["ip"] for x in pool])
            changed, _ = build(settings, 443, seed="seed-b", downloader=payloads.__getitem__)
            self.assertNotEqual([x["ip"] for x in changed], [x["ip"] for x in pool])

    def test_metadata_merge_and_ip_port_identity(self):
        records = [{"ip": "104.16.1.1", "port": 443, "source_names": [name], "source_types": ["cloudflare_edge_candidate"],
                    "source_priority": 0, "jp_hint": name == "jp", "first_seen": "a", "last_seen": "b"} for name in ("fixed", "jp")]
        self.assertEqual(len(merge(records)), 1)
        self.assertEqual(len(merge([*records, {**records[0], "port": 8443}])), 2)

    def test_checkpoint_transaction_and_partial_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root)
            store.state = {"run_id": "r1", "phase": "scan", "results": {}, "pool": []}
            store.commit()
            store.save_partial({"key": "104.16.1.1:443", "qualified": True})
            loaded = Store(root)
            self.assertEqual(loaded.load()["run_id"], "r1")
            self.assertIn("104.16.1.1:443", loaded.partial)
            old_manifest = (root / "batch-state.json").read_bytes()
            store.state["phase"] = "next"
            with patch("core.proxybench.state.atomic_write_json", side_effect=OSError):
                with self.assertRaises(OSError):
                    store.commit()
            self.assertEqual((root / "batch-state.json").read_bytes(), old_manifest)
            self.assertEqual(Store(root).load()["phase"], "scan")

    def test_concurrent_runs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with RunLock(Path(directory)):
                with self.assertRaises(ValueError):
                    with RunLock(Path(directory)):
                        pass
