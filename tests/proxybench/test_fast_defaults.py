from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.proxybench.modes import mode_settings
from core.proxybench.session_lifecycle import upgrade_fast_defaults
from core.proxybench.settings import current_rules, load_settings


class FastDefaultsTests(unittest.TestCase):
    def test_former_defaults_migrate_once_and_custom_rules_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
            for mode in ("proxy", "tcp_tls"):
                settings = mode_settings(load_settings(root / "config.yaml"), mode)
                settings["rules_path"].parent.mkdir(exist_ok=True)
                old = {**current_rules(settings), "download_timeout_seconds": 8, "maximum_download_seconds": 7}
                old.update({"tls_timeout_seconds": 4} if mode == "tcp_tls" else {"request_timeout_seconds": 3, "delay_concurrency": 60, "speed_concurrency": 4})
                settings["rules_path"].write_text(json.dumps(old), encoding="utf-8")
                changed = upgrade_fast_defaults(settings)
                self.assertEqual(changed["download_timeout_seconds"], 5)
                self.assertEqual(current_rules(settings)["maximum_download_seconds"], 5)
                self.assertEqual(upgrade_fast_defaults(settings), {})
                for key in old:
                    if key not in changed:
                        self.assertEqual(current_rules(settings)[key], old[key])

    def test_custom_timeouts_and_saved_quality_thresholds_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
            settings = load_settings(root / "config.yaml")
            settings["rules_path"].parent.mkdir()
            customized = {**current_rules(settings), "download_timeout_seconds": 12, "request_timeout_seconds": 1.1,
                          "max_proxy_average_latency_ms": 200, "min_proxy_speed_mbps": 16, "speed_concurrency": 2, "delay_concurrency": 30}
            settings["rules_path"].write_text(json.dumps(customized), encoding="utf-8")
            self.assertEqual(upgrade_fast_defaults(settings), {})
            self.assertEqual(current_rules(settings), customized)
