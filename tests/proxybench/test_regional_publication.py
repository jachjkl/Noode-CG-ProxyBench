from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock, patch

from core.proxybench.benchmark import limit_failure, ranking_key
from core.proxybench.export import gate, publish
from core.proxybench.modes import mode_settings
from core.proxybench.pipeline import Pipeline
from core.proxybench.publication_policy import (
    PolicyChanged,
    current,
    editable,
    lock,
    preview,
    region_code,
    save,
    select,
    validate,
)
from core.proxybench.regional_pipeline import run
from core.proxybench.session_lifecycle import clear_transient
from core.proxybench.settings import current_rules, load_settings
from scripts.proxybench_channel import pack, unpack, validate_result_files
from tests.proxybench import test_desktop_cloud
from tests.proxybench.test_benchmark import pool
from tests.proxybench.test_dual_methods import records
from tests.proxybench.test_recovery_pipeline import RecoveryManager


def policy(total=100, regions=None, append=None, rounds=3):
    return {"kind": "regional-v1", "total": total, "regions": {"JP": 10, "HK": 20, "SG": 20} if regions is None else regions,
            "append": {} if append is None else append, "max_rounds": rounds}


def samples(counts, mode="proxy"):
    result = records(sum(counts.values()), 0, mode)
    index = 0
    for code, count in counts.items():
        for row in result[index:index + count]:
            row.update(geo_country=code, tested_at="2026-10-11T00:00:00Z", status="Qualified")
            row["tcp_average_latency_ms" if mode == "tcp_tls" else "proxy_average_latency_ms"] = 50 + index / 100
            if mode == "tcp_tls":
                row.update(tls_average_latency_ms=row["tcp_average_latency_ms"], tls_loss_percent=0, tls_jitter_ms=2,
                           download_measurement={"success": True})
            index += 1
    return result


class RegionalPolicyTests(unittest.TestCase):
    def settings(self, root, mode="proxy"):
        (root / "config.yaml").write_text("proxybench: {}", encoding="utf-8")
        return mode_settings(load_settings(root / "config.yaml"), mode)

    def test_total_includes_all_regions_and_keeps_best_per_country(self):
        rows = samples({"JP": 30, "HK": 40, "SG": 40, "DE": 350})
        for total in (100, 200, 300):
            chosen = select(rows, policy(total))
            self.assertEqual(len(chosen), total)
            self.assertEqual(Counter(r["geo_country"] for r in chosen), {"JP": 10, "HK": 20, "SG": 20, "DE": total - 50})
            self.assertEqual(chosen, sorted(chosen, key=ranking_key))
            self.assertTrue(gate(chosen, limits=policy(total)))
            self.assertEqual([r["ip"] for r in chosen if r["geo_country"] == "JP"], [r["ip"] for r in rows[:10]])

    def test_no_region_minimum_and_optional_append_uses_total(self):
        rows = samples({"DE": 130, "JP": 2})
        chosen = select(rows, policy(100, append={"JP": 10}))
        self.assertEqual(len(chosen), 100)
        self.assertEqual(sum(r["geo_country"] == "JP" for r in chosen), 2)
        self.assertTrue(gate(chosen, limits=policy(100, append={"JP": 10})))
        self.assertTrue(gate(select(rows[:130], policy(100, append={"JP": 10})), limits=policy(100, append={"JP": 10})))

    def test_zero_cap_custom_world_regions_aliases_and_duplicates(self):
        value = validate(policy(10, {"日本": 0, "香港": 2, "US": 3, "DE": 2, "FR2": 1, "英格兰": 1, "NL": 1, "BR": 1}))
        rows = samples({"JP": 20, "HK": 5, "US": 5, "DE": 5, "FR": 5, "GB": 5, "NL": 5, "BR": 5})
        selected = select([*rows, *rows], value)
        self.assertEqual(len(selected), 10)
        self.assertNotIn("JP", Counter(r["geo_country"] for r in selected))
        self.assertEqual(region_code("FR2"), "FR")
        self.assertEqual(region_code("英格兰"), "GB")
        self.assertEqual(region_code("UK"), "GB")
        for invalid in (policy(regions={"UK": 1, "GB": 2}), policy(regions={"DE": -1}), policy(rounds=0), policy(5, append={"JP": 6})):
            with self.assertRaises(ValueError):
                validate(invalid)

    def test_unconfigured_regions_have_no_preview_cap(self):
        self.assertEqual(preview(samples({"DE": 1200}), policy())["available"], 1200)

    def test_gate_rejects_overcap_unsorted_duplicate_roles_and_invalid_japan(self):
        value = policy(5, {"DE": 3, "JP": 2})
        chosen = select(samples({"DE": 4, "JP": 3}), value)
        self.assertTrue(gate(chosen, limits=value))
        for invalid in ([*chosen, chosen[0]], list(reversed(chosen)), [{**r, "publication_role": "append"} for r in chosen],
                        [{**r, "geo_verified": False} for r in chosen]):
            self.assertFalse(gate(invalid, limits=value))
        self.assertFalse(gate(select(samples({"DE": 5}), policy(5)), limits=value))
        self.assertFalse(gate(chosen[:-1], limits=value))
        self.assertTrue(gate(chosen[:-1], limits=value, allow_partial=True))

    def test_policy_persists_normal_cache_cleanup_and_modes_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            proxy = self.settings(Path(directory))
            direct = mode_settings(proxy, "tcp_tls")
            save(proxy, policy(200, {"JP": 10, "HK": 10, "SG": 20, "DE": 25}))
            save(direct, policy(300, {"JP": 7, "US": 30}))
            clear_transient(proxy)
            clear_transient(direct)
            self.assertEqual(current(proxy)["total"], 200)
            self.assertEqual(current(direct)["regions"], {"JP": 7, "US": 30})

    def test_only_actual_upload_lock_blocks_live_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            save(settings, policy())
            self.assertTrue(editable(settings))
            with lock(settings):
                self.assertFalse(editable(settings))
                with self.assertRaises(ValueError):
                    save(settings, policy(300))
            save(settings, policy(300))
            self.assertEqual(current(settings)["total"], 300)

    def test_upload_lock_is_visible_across_processes_without_snapshot_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(Path(directory))
            save(settings, policy())
            script = "from pathlib import Path;from core.proxybench.publication_policy import lock;import sys\nwith lock({'root':Path(sys.argv[1]),'measurement_mode':'proxy'}):\n print('locked',flush=True)\n sys.stdin.readline()"
            child = subprocess.Popen([sys.executable, "-X", "utf8", "-c", script, directory], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                self.assertFalse(editable(settings))
                with self.assertRaises(ValueError):
                    save(settings, policy(200))
                self.assertEqual(current(settings)["total"], 100)
            finally:
                child.communicate("release\n", timeout=5)
            self.assertTrue(editable(settings))

    def test_both_cloud_outputs_preserve_regional_limits_order_and_shared_direct_text(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, folder in (("proxy", "output"), ("tcp_tls", "output/Nodes-TCP")):
                local, cloud = Path(directory) / mode, Path(directory) / f"cloud-{mode}"
                value = policy(100, {"JP": 10, "HK": 10, "SG": 20, "US": 30})
                selected = select(samples({"JP": 25, "HK": 25, "SG": 25, "US": 80, "DE": 100}, mode), value)
                self.assertTrue(publish(local / folder, selected, {"publication_limits": value, "measurement_mode": mode})["published"])
                payload = pack(local, "result", mode)
                unpack(payload, hashlib.sha256(payload).hexdigest(), cloud, "result")
                self.assertEqual((local / folder / "nodes.txt").read_bytes(), (cloud / folder / "nodes.txt").read_bytes())
                if mode == "tcp_tls":
                    self.assertEqual((cloud / "output/Npdex-Tcp/Tls.txt").read_bytes(), (local / folder / "nodes.txt").read_bytes())
                import io
                import zipfile
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    files = {n: archive.read(n) for n in archive.namelist()}
                bad_health = json.loads(files[f"{folder}/health.json"])
                bad_health["publication_limits"]["regions"]["HK"] = 0
                files[f"{folder}/health.json"] = json.dumps(bad_health).encode()
                with self.assertRaises(ValueError):
                    validate_result_files(files)


class RegionalPipelineTests(unittest.TestCase):
    def pipeline(self, root, rows, value, mode="proxy"):
        settings = RegionalPolicyTests().settings(root, mode)
        save(settings, value)
        p = Pipeline(settings, manager=RecoveryManager())
        p.store.state = {"run_id": "fixture", "session_id": "fixture", "cycle": 1, "phase": "scan", "pool": pool(len(rows)), "results": {}, "sources": {}}
        lookup = {r["ip"]: r for r in rows}
        p.profiles = Mock(return_value={"default": object()})
        p.calls, p.fail = [], set()
        p.on_scan = lambda field: None
        def scan(candidates, field, profiles, *, fixed_rules=None):
            p.calls.append((field, [r["ip"] for r in candidates]))
            for candidate in candidates:
                row = {**lookup[candidate["ip"]], **candidate}
                row["qualified"] = not limit_failure(row, fixed_rules or current_rules(settings)) and not (field == "regional_results" and row["ip"] in p.fail)
                p.store.state.setdefault(field, {})[f"{row['ip']}:{row['port']}"] = row
            p.compact_batch(field)
            p.on_scan(field)
        p.scan = scan
        return p

    def test_all_20000_measured_before_competition_with_no_first_round_refetch_for_all_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode, tls in (("proxy", 0), ("tcp_tls", 0), ("tcp_tls", 1)):
                root = Path(directory) / f"{mode}-{tls}"
                root.mkdir()
                p = self.pipeline(root, samples({"DE": 20000}, mode), policy(300), mode)
                if mode == "tcp_tls":
                    p.settings["rules"]["tls_enabled"] = tls
                p.new_pool = Mock(side_effect=AssertionError("first pool already has enough"))
                result = run(p, object(), False, False)
                self.assertTrue(result["published"])
                self.assertEqual(len(p.calls[0][1]), 20000)
                self.assertEqual(len(p.calls[1][1]), 300)
                self.assertEqual(result["unique_final_count"], 300)
                p.new_pool.assert_not_called()

    def test_failed_competition_uses_local_backups_before_new_cloud_ips(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = samples({"DE": 120})
            p = self.pipeline(Path(directory), rows, policy(100))
            p.fail = {r["ip"] for r in rows[:15]}
            p.new_pool = Mock(side_effect=AssertionError("qualified backups suffice"))
            result = run(p, object(), False, False)
            self.assertTrue(result["published"])
            self.assertEqual([len(ips) for _, ips in p.calls], [120, 100, 15])
            self.assertEqual(result["unique_final_count"], 100)
            p.new_pool.assert_not_called()

    def test_caps_are_editable_during_retest_and_extra_qualified_candidates_are_retested(self):
        with tempfile.TemporaryDirectory() as directory:
            p = self.pipeline(Path(directory), samples({"JP": 50, "HK": 60, "DE": 150}), policy(100))
            changed = []
            def edit(field):
                if field == "regional_results" and not changed:
                    changed.append(True)
                    save(p.settings, policy(200, {"JP": 7, "HK": 10, "DE": 190}))
            p.on_scan = edit
            result = run(p, object(), True, False)
            # Only 167 qualified addresses survive these caps, so no false 200-entry publication.
            self.assertFalse(result["published"])
            self.assertEqual(result["unique_final_count"], 167)
            self.assertEqual(result["publication_limits"]["total"], 200)
            self.assertEqual(len({ip for field, ips in p.calls if field == "regional_results" for ip in ips}), 180)

    def test_ordinary_shortage_does_not_require_a_japanese_minimum_and_manual_is_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            p = self.pipeline(Path(directory), samples({"DE": 30, "JP": 20}), policy(100, {"JP": 10, "DE": 25}, {"JP": 10}))
            result = run(p, object(), True, True)
            self.assertTrue(result["published"])
            self.assertEqual(result["unique_final_count"], 35)

    def test_completed_checkpoint_reselection_does_not_fetch_or_retest_again_without_rule_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = self.pipeline(Path(directory), samples({"DE": 120}), policy(100))
            run(p, object(), True, False)
            calls = len(p.calls)
            save(p.settings, policy(80, {"DE": 80}))
            result = run(p, object(), True, False)
            self.assertTrue(result["published"])
            self.assertEqual(len(p.calls), calls)
            self.assertEqual(result["unique_final_count"], 80)


class RegionalControllerTests(unittest.TestCase):
    def controller(self, root, phase="scan", cycle=1):
        controller = test_desktop_cloud.DesktopCloudTests().controller(root, phase=phase)
        controller.settings["regional_publication"] = True
        controller.settings["max_cycles"] = 0
        controller.settings["rules"] = current_rules(controller.settings)
        from core.proxybench.state import Store
        store = Store(controller.settings["state_dir"])
        state = store.load()
        state["cycle"] = cycle
        store.commit()
        save(controller.settings, policy(100))
        return controller

    def test_default_round_limit_is_finite_even_with_old_unlimited_config(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller(Path(directory), phase="needs_more")
            c.fetch_handoff = Mock()
            c.local_select = Mock(return_value={"needs_more": True, "published": False})
            c.publish_pending = Mock(side_effect=AssertionError("no metadata upload between discovery rounds"))
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                self.assertFalse(c.run("continue")["published"])
            self.assertEqual(c.fetch_handoff.call_count, 2)
            c.publish_pending.assert_not_called()

    def test_continue_at_limit_allows_only_one_more_round(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller(Path(directory), phase="needs_more", cycle=3)
            c.fetch_handoff = Mock()
            c.local_select = Mock(return_value={"needs_more": True, "published": False})
            with patch("core.proxybench.desktop_cloud.ProxyProfile.load"), patch("core.proxybench.desktop_cloud.vpn_environment", return_value={}):
                c.run("continue")
            c.fetch_handoff.assert_called_once()

    def test_stale_publication_is_rejected_before_any_github_write(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller(Path(directory))
            c.settings["output_dir"] = c.root / "output"
            old = policy(100)
            publish(c.settings["output_dir"], select(samples({"DE": 100}), old), {"publication_limits": old})
            save(c.settings, policy(200))
            c.upload_pending = Mock()
            with self.assertRaises(PolicyChanged):
                c.publish_pending()
            c.upload_pending.assert_not_called()

    def test_policy_change_before_upload_reselects_without_fetching(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller(Path(directory))
            c.publish_pending = Mock(side_effect=[PolicyChanged("changed"), {"url": "https://example.test"}])
            c.fetch_handoff = Mock()
            c.local_select = Mock(return_value={"published": True, "unique_final_count": 200})
            result, confirmation = c.publish_current({"published": True})
            self.assertEqual(result["unique_final_count"], 200)
            self.assertIsNotNone(confirmation)
            c.fetch_handoff.assert_not_called()
            c.local_select.assert_called_once_with(publish_only=False)

    def test_network_failure_preserves_pending_archive_and_unlocks_settings(self):
        from core.proxybench.cloud import CloudError
        with tempfile.TemporaryDirectory() as directory:
            c = self.controller(Path(directory))
            c.settings["output_dir"] = c.root / "output"
            value = policy(100)
            publish(c.settings["output_dir"], select(samples({"DE": 100}), value), {"publication_limits": value})
            def fail(*args, **kwargs):
                self.assertFalse(editable(c.settings))
                with self.assertRaises(ValueError):
                    save(c.settings, policy(200))
                raise CloudError("fixture offline")
            c.command = fail
            with self.assertRaises(CloudError):
                c.publish_pending()
            self.assertTrue((c.pending_dir / "manifest.json").exists())
            self.assertTrue((c.pending_dir / "result.zip").exists())
            self.assertTrue(editable(c.settings))
            save(c.settings, policy(200))
