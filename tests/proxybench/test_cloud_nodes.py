from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.cloud import CloudError
from core.proxybench.cloud_nodes import read_published
from core.proxybench.export import publish
from tests.proxybench import test_dashboard_pages, test_publication_controller


class CloudNodesTests(unittest.TestCase):
    def test_failed_replenishment_keeps_the_last_confirmed_partial_publication_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [*test_publication_controller.winners()[:3], *test_publication_controller.winners()[100:102]]
            publish(root / "output", records, {"manual_publication": True})
            for _ in range(2):
                publish(root / "output", [], {"status": "needs_more", "publication_limits": {"general": 300, "japan": 10}})
            content = (root / "output/nodes.json").read_bytes()
            health = (root / "output/health.json").read_bytes()
            client = Mock(settings={"state_dir": root})
            client.command.side_effect = ["a" * 40, {"content": base64.b64encode(content).decode()}, {"content": base64.b64encode(health).decode()}]
            with patch("core.proxybench.cloud_nodes.download", side_effect=lambda dest, *a, **k: dest.write_bytes(content)):
                result = read_published(client)
            self.assertEqual((result["total"], result["general"], result["japan"]), (5, 3, 2))

    def test_large_cloud_file_uses_trusted_git_blob_when_contents_api_has_no_inline_base64(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(root / "output", test_publication_controller.winners(), {})
            content = (root / "output/nodes.json").read_bytes()
            client = Mock(settings={"state_dir": root})
            client.command.side_effect = ["a" * 40, {"encoding": "none", "content": "", "sha": "b" * 40},
                                          {"encoding": "base64", "content": base64.b64encode(content).decode()}]
            with patch("core.proxybench.cloud_nodes.download", side_effect=lambda dest, *a, **k: dest.write_bytes(content)):
                result = read_published(client)
            self.assertEqual(result["total"], 110)
            self.assertEqual(client.command.call_args.args[0][-1], "repos/jachjkl/Noode-CG-ProxyBench/git/blobs/" + "b" * 40)

    def test_large_file_does_not_follow_an_invalid_blob_reference(self):
        client = Mock(settings={})
        client.command.side_effect = ["a" * 40, {"encoding": "none", "content": "", "sha": "../private"}]
        with self.assertRaises(CloudError):
            read_published(client)
        self.assertEqual(client.command.call_count, 2)

    def test_cloud_original_order_and_rank_are_preserved_in_read_only_panel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            publish(root / "output", test_publication_controller.winners(), {})
            content = (root / "output/nodes.json").read_bytes()
            client = Mock(settings={"state_dir": root})
            client.command.side_effect = ["a" * 40, {"content": base64.b64encode(content).decode()}]
            def mirrored(destination, expected, urls, **kwargs):
                destination.write_bytes(content)
            with patch("core.proxybench.cloud_nodes.download", side_effect=mirrored):
                report = read_published(client)
            self.assertEqual((report["total"], report["general"], report["japan"]), (110, 100, 10))
            self.assertEqual([row["rank"] for row in report["nodes"]], list(range(1, 111)))
            controller = test_dashboard_pages.DashboardPageTests().controller(root)
            controller.cloud_published = report
            rows = controller.action("cloud-published-results", {})["rows"]
            self.assertEqual([row["ip"] for row in rows], [row["ip"] for row in report["nodes"]])
            self.assertEqual(rows[100]["lane"], "jp_append")
            self.assertFalse(any("uuid" in row or "password" in row for row in rows))

    def test_empty_cloud_placeholder_displays_zero_without_invented_nodes(self):
        client = Mock(settings={})
        client.command.side_effect = ["a" * 40, CloudError("missing nodes.json"), {"size": 0}]
        report = read_published(client)
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["nodes"], [])

    def test_manual_partial_cloud_list_displays_actual_counts_and_requires_manual_health(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [*test_publication_controller.winners()[:3], *test_publication_controller.winners()[100:102]]
            publish(root / "output", records, {"manual_publication": True})
            content = (root / "output/nodes.json").read_bytes()
            health = (root / "output/health.json").read_bytes()
            client = Mock(settings={"state_dir": root})
            client.command.side_effect = ["a" * 40, {"content": base64.b64encode(content).decode()}, {"content": base64.b64encode(health).decode()}]
            with patch("core.proxybench.cloud_nodes.download", side_effect=lambda dest, *_args, **_kwargs: dest.write_bytes(content)):
                result = read_published(client)
            self.assertEqual((result["total"], result["general"], result["japan"]), (5, 3, 2))
            client.command.side_effect = ["a" * 40, {"content": base64.b64encode(content).decode()}, {"content": base64.b64encode(b'{"published":true}').decode()}]
            with patch("core.proxybench.cloud_nodes.download", side_effect=lambda dest, *_args, **_kwargs: dest.write_bytes(content)):
                with self.assertRaises(CloudError):
                    read_published(client)
