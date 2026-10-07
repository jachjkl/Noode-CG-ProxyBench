from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.cloud import CloudController
from core.proxybench.pipeline import Pipeline, prepare
from core.proxybench.profile import ProxyProfile
from core.proxybench.settings import RULES
from core.proxybench.state import Store
from sources.pool import build
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_profile_sources_state import UUID


class SessionCloudTests(unittest.TestCase):
    def settings(self, root):
        return {"root": root, "state_dir": root / "state", "runtime_dir": root / "runtime/mihomo",
                "output_dir": root / "output", "rules_path": root / "rules.json", "rules": RULES,
                "profile": root / "config/proxy-profile.local.yaml", "max_cycles": 3, "sources": {},
                "official_sample_count": 10000}

    def test_three_real_pool_builds_fetch_fixed_once_and_never_repeat_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            feeds = {"https://zip.cm.edu.kg/all.txt": b"104.16.1.1\n104.17.1.1",
                     "https://bestcf.pages.dev/lzj/all.txt": b"104.17.1.1\n104.17.1.2",
                     "https://www.cloudflare.com/ips-v4/": b"104.16.0.0/13\n172.64.0.0/13"}
            fetch = Mock(side_effect=feeds.__getitem__)
            seen = set()
            for index in range(3):
                candidates, report = build(settings, 443, seen, seed=f"round-{index}", downloader=fetch, include_fixed=index == 0)
                ips = {item["ip"] for item in candidates}
                self.assertFalse(ips & seen)
                self.assertEqual(report["cloudflare_official_count"], 10000)
                seen.update(ips)
            urls = [call.args[0] for call in fetch.call_args_list]
            self.assertEqual(urls.count("https://zip.cm.edu.kg/all.txt"), 1)
            self.assertEqual(urls.count("https://bestcf.pages.dev/lzj/all.txt"), 1)
            self.assertEqual(len(seen), 30003)

    def test_cloud_history_excludes_unattempted_ips_and_reuses_exact_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            seen_arguments = []
            def builder(settings, port, excluded, *, include_fixed):
                seen_arguments.append((set(excluded), include_fixed))
                ip = f"104.16.1.{len(seen_arguments)}"
                return [{**pool(1)[0], "ip": ip}], {"seed": str(len(seen_arguments))}
            with patch("core.proxybench.pipeline.build", side_effect=builder):
                first = prepare(settings, session_id="session-one")
                handoff = settings["root"] / "data/handoff/proxybench-pool.json.gz"
                content = handoff.read_bytes()
                self.assertEqual(prepare(settings, session_id="session-one", reuse=True), first)
                self.assertEqual(handoff.read_bytes(), content)
                prepare(settings, session_id="session-one")
                prepare(settings, session_id="session-one")
                prepare(settings, session_id="session-two")
            self.assertEqual(seen_arguments, [(set(), True), ({"104.16.1.1"}, False),
                                              ({"104.16.1.1", "104.16.1.2"}, False), (set(), True)])
            history = json.loads(gzip.decompress(handoff.with_name("proxybench-session-history.json.gz").read_bytes()))
            self.assertEqual(history["session_id"], "session-two")
            self.assertEqual(history["cycle"], 1)

    def test_fixed_and_optional_sources_cannot_reintroduce_excluded_ips(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            settings["official_sample_count"] = 10
            settings["sources"] = {"jp_supplemental": [{"name": "jp", "url": "https://example.test/jp"}]}
            feeds = {"https://www.cloudflare.com/ips-v4/": b"104.16.0.0/13",
                     "https://example.test/jp": b"104.16.1.1\n104.16.1.2"}
            candidates, _ = build(settings, 443, {"104.16.1.1"}, downloader=feeds.__getitem__, include_fixed=False)
            self.assertNotIn("104.16.1.1", {x["ip"] for x in candidates})
            self.assertIn("104.16.1.2", {x["ip"] for x in candidates})

    def test_incumbent_ordinary100_compete_outside_fresh_top200_and_jp_stays_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = Pipeline(self.settings(Path(directory)), manager=Mock())
            profile = ProxyProfile({"type": "vless", "port": 443, "uuid": UUID})
            pipeline.incumbents = [{"ip": f"104.17.1.{i + 1}", "port": 443, "lane": "general" if i < 100 else "jp_append"}
                                   for i in range(110)]
            general = pipeline.incumbent_candidates(profile, "general")
            jp = pipeline.incumbent_candidates(profile, "jp_append")
            candidates = pipeline.competition_candidates(pool(200), general)
            self.assertEqual(len(candidates), 300)
            self.assertTrue({x["ip"] for x in general} <= {x["ip"] for x in candidates})
            self.assertFalse({x["ip"] for x in jp} & {x["ip"] for x in candidates})
            self.assertEqual(len(jp), 10)

    def test_application_runner_stays_alive_through_all_three_auto_rounds(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            controller = CloudController(settings)
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            settings["output_dir"].mkdir()
            (settings["output_dir"] / "health.json").write_text(json.dumps({"published": False, "needs_more": True}))
            controller.prepare_runner = Mock()
            controller.dispatch = Mock()
            controller.watch = Mock(return_value={"status": "completed", "conclusion": "success", "url": "https://example.test/run"})
            controller.runner = Mock()
            controller.runner.poll.return_value = None
            with patch("core.proxybench.cloud.ProxyProfile.load"):
                self.assertEqual(controller.run()["status"], "needs_more")
            self.assertEqual(controller.dispatch.call_count, 3)
            self.assertEqual(len({x.args[0] for x in controller.dispatch.call_args_list}), 1)
            controller.runner.terminate.assert_called_once()

    def test_reopen_unfinished_cycle_reuses_cloud_handoff_then_replenishes(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            store = Store(settings["state_dir"])
            store.state = {"phase": "scan", "cycle": 2, "session_id": "old-session"}
            store.commit()
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            settings["output_dir"].mkdir()
            (settings["output_dir"] / "health.json").write_text(json.dumps({"needs_more": True}))
            controller = CloudController(settings)
            controller.prepare_runner = Mock()
            controller.dispatch = Mock()
            controller.watch = Mock(return_value={"conclusion": "success", "url": "https://example.test/run"})
            with patch("core.proxybench.cloud.ProxyProfile.load"):
                controller.run()
            self.assertEqual([x.args for x in controller.dispatch.call_args_list], [("old-session", True), ("old-session", False)])

    def test_manual_continue_after_completed_round_dispatches_fresh_same_session(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            store = Store(settings["state_dir"])
            store.state = {"phase": "completed", "cycle": 3, "session_id": "old-session"}
            store.commit()
            settings["profile"].parent.mkdir(parents=True)
            settings["profile"].touch()
            settings["output_dir"].mkdir()
            (settings["output_dir"] / "health.json").write_text(json.dumps({"published": True}))
            controller = CloudController(settings)
            controller.prepare_runner = Mock()
            controller.dispatch = Mock()
            controller.watch = Mock(return_value={"conclusion": "success", "url": "https://example.test/run"})
            with patch("core.proxybench.cloud.ProxyProfile.load"):
                controller.run("continue")
            controller.dispatch.assert_called_once_with("old-session", False)
