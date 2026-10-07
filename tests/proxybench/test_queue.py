from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.proxybench.pipeline import Pipeline
from core.proxybench.profile import ProxyProfile
from core.proxybench.queue import accumulate
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_profile_sources_state import UUID


class CandidateQueueTests(unittest.TestCase):
    def test_first_full_pool_survives_validation_failure_and_next_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = {"root": root, "state_dir": root / "state"}
            path = root / "data/handoff/proxybench-pool.json.gz"
            path.parent.mkdir(parents=True)
            first = [{**x, "source_types": ["cloudflare_edge_candidate"], "source_priority": 0,
                      "jp_hint": False, "first_seen": "2026", "last_seen": "2026"} for x in pool(301)]
            report = {"session_id": "window", "seed": "first", "cycle": 1}
            path.write_bytes(gzip.compress(json.dumps({"pool": first, "report": report}).encode()))
            self.assertEqual(accumulate(settings)["queued_candidate_count"], 301)
            self.assertEqual(accumulate(settings)["queued_candidate_count"], 301)
            second = [{**first[0], "ip": "104.17.2.1"}]
            path.write_bytes(gzip.compress(json.dumps({"pool": second, "report": {**report, "seed": "second", "cycle": 2}}).encode()))
            self.assertEqual(accumulate(settings)["queued_candidate_count"], 302)
            pipeline = Pipeline({**settings, "runtime_dir": root / "runtime"}, manager=Mock())
            profile = ProxyProfile({"type": "vless", "port": 443, "uuid": UUID})
            candidates, _ = pipeline.new_pool(profile, True)
            self.assertEqual({x["ip"] for x in candidates}, {x["ip"] for x in [*first, *second]})
            path.write_bytes(gzip.compress(json.dumps({"pool": second, "report": {**report, "session_id": "new-window"}}).encode()))
            self.assertEqual(accumulate(settings)["queued_candidate_count"], 1)
