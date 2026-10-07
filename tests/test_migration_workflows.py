from __future__ import annotations

import unittest
from pathlib import Path


class MigrationWorkflowTests(unittest.TestCase):
    def test_original_baseline_is_archived_and_dispatch_is_disabled(self):
        root = Path(__file__).parents[1]
        archived = (root / "docs/legacy/update.yml").read_text(encoding="utf-8")
        current = (root / ".github/workflows/update.yml").read_text(encoding="utf-8")
        self.assertIn("cloud-publish:", archived)
        self.assertNotIn("git push", current)
        self.assertNotIn("self-hosted", current)
        self.assertIn("proxybench.yml", current)
