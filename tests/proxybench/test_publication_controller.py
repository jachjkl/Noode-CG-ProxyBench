from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.proxybench.controller import Controller, RoutingError
from core.proxybench.export import gate, nodes_text, publish
from scripts.proxybench_channel import pack, unpack


def winners():
    return [{"ip": f"104.16.1.{index + 1}", "port": 443, "qualified": True,
             "lane": "general" if index < 100 else "jp_append", "geo_country": "JP",
             "geo_verified": True, "geo_conflict": False, "source_names": ["fixed"],
             "google_rounds_ms": [80, 81, 82], "cloudflare_rounds_ms": [90, 91, 92],
             "github_rounds_ms": [100, 101, 102], "round_averages_ms": [90, 91, 92],
             "proxy_average_latency_ms": 91, "proxy_loss_percent": 0, "download_rounds_mbps": [24, 25, 26],
             "proxy_download_average_mbps": 25, "proxy_download_average_mbytes": 25 / 8,
             "google_average_ms": 81, "cloudflare_average_ms": 91, "github_average_ms": 101,
             "stability_score": 80, "tested_at": "2026-10-07T00:00:00Z",
             "uuid": "should-never-be-published", "password": "never-publish-password"} for index in range(110)]


class PublicationControllerTests(unittest.TestCase):
    def test_requested_address_format_and_capital_country_code(self):
        self.assertEqual(nodes_text([{"ip": "82.139.242.5", "port": 443, "geo_country": "de"}]),
                         "82.139.242.5:443#DE\n")

    def test_complete_local_results_keep_exact_text_and_order_after_cloud_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            local, cloud = Path(directory) / "local", Path(directory) / "cloud"
            records = winners()
            records[0].update(ip="82.139.242.5", geo_country="DE")
            publish(local / "output", records, {})
            content = pack(local, "result")
            unpack(content, hashlib.sha256(content).hexdigest(), cloud, "result")
            lines = (cloud / "output/nodes.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "82.139.242.5:443#DE")
            self.assertEqual(len(lines), 110)
            self.assertTrue(all(line.endswith("#JP") for line in lines[-10:]))
            self.assertEqual((local / "output/nodes.txt").read_bytes(), (cloud / "output/nodes.txt").read_bytes())

    def test_missing_text_cannot_be_packed_as_a_completed_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(root / "output", winners(), {})
            (root / "output/nodes.txt").unlink()
            with self.assertRaises(ValueError):
                pack(root, "result")

    def test_cloud_rejects_missing_or_inconsistent_text_before_overwriting_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            local, cloud = Path(directory) / "local", Path(directory) / "cloud"
            publish(local / "output", winners(), {})
            publish(cloud / "output", winners(), {})
            before = (cloud / "output/nodes.txt").read_bytes()
            good = pack(local, "result")
            for replacement in (None, b"82.139.242.5:443#DE\n"):
                stream = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(good)) as source, zipfile.ZipFile(stream, "w") as target:
                    for name in source.namelist():
                        if name == "output/nodes.txt":
                            if replacement is not None:
                                target.writestr(name, replacement)
                        else:
                            target.writestr(name, source.read(name))
                content = stream.getvalue()
                with self.assertRaises(ValueError):
                    unpack(content, hashlib.sha256(content).hexdigest(), cloud, "result")
                self.assertEqual((cloud / "output/nodes.txt").read_bytes(), before)

    def test_exact_110_order_unique_jp_gate(self):
        records = winners()
        self.assertTrue(gate(records))
        self.assertFalse(gate(records[:109]))
        duplicate = [*records[:109], {**records[109], "ip": records[0]["ip"]}]
        self.assertFalse(gate(duplicate))
        records[-1]["geo_conflict"] = True
        self.assertFalse(gate(records))

    def test_failed_publish_preserves_last_good_and_secrets_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(publish(root, winners(), {})["published"])
            before = {name: (root / name).read_bytes() for name in ("nodes.txt", "nodes.json", "nodes.csv", "api.json", "ip.zip")}
            self.assertFalse(publish(root, winners()[:20], {"status": "needs_more"})["published"])
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
                self.assertNotIn(b"should-never-be-published", content)
                self.assertNotIn(b"never-publish-password", content)
            nodes = json.loads((root / "nodes.json").read_text(encoding="utf-8"))
            self.assertEqual([x["rank"] for x in nodes], list(range(1, 111)))

    def test_bad_cloud_payload_does_not_write_any_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as package:
                package.writestr("output/health.json", '{"published":false}')
                package.writestr("../config/proxy-profile.local.yaml", "sensitive")
            content = stream.getvalue()
            with self.assertRaises(ValueError):
                unpack(content, hashlib.sha256(content).hexdigest(), root, "result")
            self.assertEqual(list(root.iterdir()), [])

    def test_partial_result_channel_cannot_overwrite_subscription(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "health.json").write_text('{"published":false,"needs_more":true}', encoding="utf-8")
            (output / "nodes.txt").write_text("old-last-good", encoding="utf-8")
            content = pack(root, "result")
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                self.assertEqual(package.namelist(), ["output/health.json"])

    def test_direct_or_wrong_candidate_chain_is_invalid(self):
        controller = Controller(1, "not-a-real-secret", 2)
        for chains in (["DIRECT"], ["PB-2", "BENCHMARK-PROXY"]):
            controller.call = lambda _: {"connections": [{"metadata": {"sourcePort": "123"}, "chains": chains, "rule": "InName"}]}
            with self.assertRaises(RoutingError):
                controller._connection_proof("PB-1", 123)

    def test_selected_proxy_is_verified_after_change(self):
        controller = Controller(1, "not-a-real-secret", 2)
        controller.call = lambda *args, **kwargs: {"now": "PB-2"}
        with self.assertRaises(RoutingError):
            controller.select("PB-1")
