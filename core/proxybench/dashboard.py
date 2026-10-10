from __future__ import annotations

import gzip
import json
import secrets
import statistics
import subprocess
import threading
import time

from core.io_utils import atomic_write_json

from .benchmark import limit_failure, ranking_key
from .events import EventLog
from .execution import cli_python
from .mihomo_manager import owned_core_running
from .modes import mode_settings
from .profile import ProxyProfile, discover_profiles, import_discovered, save_import
from .run_clock import RunClock
from .session_lifecycle import clear_shared, clear_transient, read_saved, save_measured, upgrade_direct_parallelism
from .settings import current_rules, load_settings, validate_rules
from .state import partial_results
from .workflow import progress


class BenchDashboard:
    def __init__(self, legacy_state, *, mode="proxy", session_id=None) -> None:
        self.legacy = legacy_state
        self.legacy.proxybench = self
        self.root = legacy_state.root
        self.app = self.root / "app" if (self.root / "app/config.yaml").exists() else self.root
        self.settings = mode_settings(load_settings(self.app / "config.yaml"), mode)
        self.direct = mode == "tcp_tls"
        self.events = EventLog(self.app, mode)
        if upgrade_direct_parallelism(self.settings):
            self.events.append("旧版默认并发已对齐原包：直连下载 20、TLS 100、TCP 超时 1 秒；延迟、丢包、抖动、速度和发布数量门槛保持原值")
        self.opened_at = time.monotonic()
        self.clock = RunClock(self.settings["state_dir"] / "run-timing.json")
        self.process = None
        self.lock = threading.RLock()
        self.log_handle = None
        self.file_cache = {}
        self.checkpoint_identity = None
        self.checkpoint_view = {}
        self.preserve_on_close = False
        self.explicit_stop = False
        self.recovery_pending = False
        self.cleaned_on_open = False
        self.lifecycle_path = self.app / "data" / f"{mode}-window.json"
        self.closing = False
        self.cloud_refresh_thread = None
        self.cloud_published = {"status": "Checking", "nodes": [], "total": 0, "general": 0, "japan": 0, "message": "正在读取 GitHub 已发布 IP"}
        prior = self.read_cached(self.settings["state_dir"] / "live.json", default={})
        prior_cloud = self.read_cached(self.settings["state_dir"] / "cloud-live.json", default={})
        if prior_cloud.get("status") == "Failed" and any(job.get("conclusion") == "cancelled" for job in prior_cloud.get("jobs", [])) and not owned_core_running(self.settings["runtime_dir"]):
            message = "上次云端执行器任务中断，断点已保留；可点击继续测试，按当前规则独立复测"
            prior = {**prior, "status": "Stopped", "stage": message, "speed_active": []}
            atomic_write_json(self.settings["state_dir"] / "live.json", prior)
            atomic_write_json(self.settings["state_dir"] / "cloud-live.json", {**prior_cloud, "status": "Stopped", "interrupted": True, "stage": message})
        marker = self.read_cached(self.lifecycle_path, default={})
        failed = prior.get("status") in {"Failed", "Validation Failed"} or prior_cloud.get("status") == "Failed" or prior_cloud.get("interrupted", False)
        normal = marker.get("last_exit") == "normal" or (not marker and prior.get("status") == "Stopped" and not failed)
        if normal and not owned_core_running(self.settings["runtime_dir"]):
            save_measured(self.settings)
            clear_transient(self.settings)
            self.file_cache.clear()
            self.clock = RunClock(self.settings["state_dir"] / "run-timing.json")
            self.cleaned_on_open = True
        else:
            self.recovery_pending = bool(failed or marker.get("last_exit") == "error" or marker.get("recovery_pending") or prior.get("status") in {"Running", "Paused"})
            self.preserve_on_close = self.recovery_pending
        atomic_write_json(self.lifecycle_path, {"last_exit": "open", "recovery_pending": self.recovery_pending})
        atomic_write_json(self.settings["state_dir"] / "session.json", {"session_id": session_id or secrets.token_hex(16)})

    def refresh_cloud(self) -> None:
        if self.closing:
            return
        if self.cloud_refresh_thread and self.cloud_refresh_thread.is_alive():
            return
        def fetch():
            from .cloud_nodes import read_published
            from .desktop_cloud import DesktopCloudController
            settings = dict(self.settings)
            target = (settings["repository"], settings["branch"])
            try:
                client = DesktopCloudController(settings)
                client.update = lambda **_: None  # Auxiliary reads must not overwrite the active workflow status.
                client.control.path = self.settings["state_dir"] / "cloud-read-control.json"
                client.control.path.unlink(missing_ok=True)
                report = read_published(client)
                with self.lock:
                    if target == (self.settings["repository"], self.settings["branch"]):
                        atomic_write_json(self.settings["state_dir"] / "cloud-published.json", report)
                        self.cloud_published = report
            except Exception:
                with self.lock:
                    if target == (self.settings["repository"], self.settings["branch"]):
                        self.cloud_published = {**self.cloud_published, "status": "Unavailable", "message": "云端读取暂时失败，可点击刷新；已缓存的发布顺序保持不变"}
            finally:
                if target != (self.settings["repository"], self.settings["branch"]):
                    self.cloud_refresh_thread = None
                    self.refresh_cloud()
        self.cloud_refresh_thread = threading.Thread(target=fetch, daemon=True)
        self.cloud_refresh_thread.start()

    def read_cached(self, path, *, compressed=False, default=None):
        if not path.exists():
            return default
        try:
            stat = path.stat()
        except FileNotFoundError:
            return default
        identity = (stat.st_mtime_ns, stat.st_size)
        cached = self.file_cache.get(path)
        if cached and cached[0] == identity:
            return cached[1]
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            return default
        value = json.loads(gzip.decompress(content) if compressed else content)
        self.file_cache[path] = (identity, value)
        return value

    def checkpoint_snapshot(self) -> dict:
        pointer = self.settings["state_dir"] / "batch-state.json"
        if not pointer.exists():
            self.checkpoint_identity = None
            self.checkpoint_view = {}
            return {}
        stat = pointer.stat()
        identity = (stat.st_mtime_ns, stat.st_size)
        if identity != self.checkpoint_identity:
            from .state import Store
            self.checkpoint_view = Store(self.settings["state_dir"]).load()
            self.checkpoint_identity = identity
        return self.checkpoint_view

    def rows(self, kind: str, page: int) -> dict:
        if page < 1:
            raise ValueError("页码必须大于零")
        settings = self.settings
        live = self.read_cached(settings["state_dir"] / "live.json", default={})
        cloud = self.read_cached(self.app / "data/handoff/proxybench-cloud-health.json", default={})
        same_pool = bool(live.get("sources", {}).get("seed") and live["sources"]["seed"] == cloud.get("seed") or
                         live.get("session_id") and live.get("session_id") == cloud.get("session_id"))
        measured = dict(self.read_cached(settings["state_dir"] / "benchmark-results.json.gz", compressed=True, default={})) if same_pool or not cloud else {}
        partial = self.read_cached(settings["state_dir"] / "partial-batch.json", default={})
        if partial.get("run_id") and partial.get("run_id") == live.get("run_id") and partial.get("phase") == live.get("phase"):
            measured.update(partial.get("results", {}))
        measured.update(partial_results(settings["state_dir"], live.get("run_id"), live.get("phase")))
        active_rows = live.get("candidates", []) if same_pool or not cloud or live.get("phase") == "validation" else []
        for row in active_rows:
            measured[f"{row['ip']}:{row['port']}"] = row
        saved_rules = current_rules(settings)
        if kind == "results" and not measured:
            measured = {f"{row['ip']}:{row['port']}": {**row, "qualified": False, "status": "Saved Result"} for row in read_saved(settings)}
        for key, row in measured.items():
            if row.get("qualified") and (failure := limit_failure(row, saved_rules)):
                measured[key] = {**row, "qualified": False, "status": failure}
        if kind == "competition-results":
            state = self.checkpoint_snapshot()
            rows = [*state.get("general_results", {}).values(), *state.get("jp_results", {}).values()]
            if live.get("phase") in {"general_retest", "jp_retest"}:
                staged = {f"{row['ip']}:{row['port']}": row for row in rows}
                staged.update({f"{row['ip']}:{row['port']}": row for row in active_rows})
                rows = list(staged.values())
        elif kind == "published-results":
            rows = self.read_cached(settings["output_dir"] / "nodes.json", default=[])
        elif kind == "live-results":
            active_keys = {f"{row['ip']}:{row['port']}" for row in active_rows}
            rows = [row for row in measured.values() if row.get("probes") or row.get("proxy_probe_count") or row.get("tcp_rounds_ms") or row.get("tls_rounds_ms")]
            rows.sort(key=lambda row: (f"{row['ip']}:{row['port']}" in active_keys, row.get("tested_at", "")), reverse=True)
        elif kind == "results":
            rows = [row for row in measured.values() if row.get("tested_at") and row.get("status") != "Rejected Entry"]
        elif kind == "qualified-results":
            rows = sorted((row for row in measured.values() if row.get("tested_at") and row.get("qualified") and row.get("status") == "Qualified"), key=ranking_key)
        else:
            cumulative = settings["state_dir"] / "candidate-pool.json.gz"
            if same_pool and cumulative.exists():
                rows = self.read_cached(cumulative, compressed=True)
            else:
                handoff = self.read_cached(self.app / "data/handoff/proxybench-pool.json.gz", compressed=True, default={})
                queued = self.read_cached(settings["state_dir"] / "cloud-candidate-queue.json.gz", compressed=True, default={})
                if queued and queued.get("report", {}).get("session_id") == handoff.get("report", {}).get("session_id"):
                    handoff = queued
                rows = handoff.get("pool", [])
        total = len(rows)
        pages = max(1, (total + 299) // 300)
        page = min(page, pages)
        visible = rows[(page - 1) * 300:page * 300]
        if kind == "live-results":
            visible = [dict(row) for row in visible]
            for row in visible:
                probes = [p for values in row.get("probes", {}).values() for p in values if not p.get("skipped")]
                row["completed_probe_count"] = len(probes)
                delays = [p["latency_ms"] for p in probes if p.get("success") and p.get("latency_ms") is not None]
                row["live_response_ms"] = statistics.fmean(delays) if delays else None
                if row.get("proxy_name") in live.get("speed_active", []):
                    row["status"] = "Speed Testing"
                if not row.get("tested_at") and live.get("status") in {"Stopped", "Paused", "Failed"}:
                    row["status"] = live["status"]
        if kind == "candidates":
            # Keep full candidate data on disk; send only this page and its actual measurements.
            processed = self.read_cached(settings["state_dir"] / "processed.json.gz", compressed=True, default={})
            visible = [{**row, **measured.get(f"{row['ip']}:{row['port']}", {}),
                        "status": measured.get(f"{row['ip']}:{row['port']}", {}).get("status", "已淘汰，详情已清理" if processed.get(f"{row['ip']}:{row['port']}") is False else "Queued")} for row in visible]
        return {"rows": visible, "total": total, "page": page, "pages": pages, "page_size": 300}

    def snapshot(self) -> dict:
        settings = self.settings
        path = settings["state_dir"] / "live.json"
        try:
            live = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            live = {"status": "正在刷新"}
        local_running = owned_core_running(settings["runtime_dir"])
        running = bool(self.process and self.process.poll() is None) or local_running
        live["local_process_active"] = local_running
        if not running and live.get("status") in {"Validation Failed", "Validation Required"} and "带宽" in live.get("stage", ""):
            # Older acceptance messages are history; they are not a prerequisite of this version.
            live.update(status="Ready", stage="准备就绪，点击开始优选")
        if "mihomo" not in live:
            version_path = settings["runtime_dir"] / "version.json"
            version = json.loads(version_path.read_text(encoding="utf-8")).get("version", "") if version_path.exists() else ""
            live["mihomo"] = {"version": version, "status": "Stopped", "mode": "rule", "loaded_proxies": 0, "controller_healthy": False}
        try:
            profile = ProxyProfile.load(settings["profile"]).summary()
        except ValueError:
            profile = {"configured": False}
        if self.direct:
            profile = {"configured": True, "protocol": "direct", "port": 443}
        health_path = settings["output_dir"] / "health.json"
        health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
        health["last_good_count"] = len(self.read_cached(settings["output_dir"] / "nodes.json", default=[]))
        cloud_path = settings["state_dir"] / "cloud-live.json"
        cloud = json.loads(cloud_path.read_text(encoding="utf-8")) if cloud_path.exists() else {}
        source_path = self.app / "data/handoff/proxybench-cloud-health.json"
        if source_path.exists() and not live.get("sources"):
            source_report = json.loads(source_path.read_text(encoding="utf-8"))
            live["sources"] = source_report
            live["candidate_total"] = source_report.get("unique_candidate_count", 0)
        queued = self.read_cached(settings["state_dir"] / "cloud-candidate-queue.json.gz", compressed=True, default={})
        if queued and queued.get("report", {}).get("session_id") == live.get("sources", {}).get("session_id"):
            live["candidate_total"] = max(live.get("candidate_total", 0), len(queued["pool"]))
        if self.process and self.process.poll() is not None and self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        saved_rules = current_rules(settings)
        cached_results = dict(self.read_cached(settings["state_dir"] / "benchmark-results.json.gz", compressed=True, default={}))
        partial = self.read_cached(settings["state_dir"] / "partial-batch.json", default={})
        if partial.get("run_id") == live.get("run_id") and partial.get("phase") == live.get("phase"):
            cached_results.update(partial.get("results", {}))
        cached_results.update(partial_results(settings["state_dir"], live.get("run_id"), live.get("phase")))
        if cached_results:
            live["qualified_count"] = sum(bool(row.get("qualified")) and not limit_failure(row, saved_rules) for row in cached_results.values())
        control = self.read_cached(settings["state_dir"] / "control.json", default={})
        with self.lock:
            timing = {**self.clock.snapshot(running, control.get("action") == "pause"),
                      "software_seconds": max(0.0, time.monotonic() - self.opened_at)}
        live = {key: value for key, value in live.items() if key != "candidates"}
        return {"live": live, "profile": profile, "rules": current_rules(settings), "published": health,
                "timing": timing,
                "running": running,
                "local_running": local_running,
                "actions_url": f"https://github.com/{self.legacy.repository}/actions",
                "cloud": cloud, "cloud_published": {key: value for key, value in self.cloud_published.items() if key != "nodes"}, "workflow": progress(live, cloud, health),
                "recovery_pending": self.recovery_pending,
                "can_resume": (settings["state_dir"] / "batch-state.json").exists()}

    def action(self, action: str, payload: dict) -> dict:
        with self.lock:
            settings = self.settings
            if action == "refresh-cloud-results":
                self.refresh_cloud()
                return {"requested": "refresh-cloud-results"}
            if action == "log-events":
                return {"rows": self.events.tail()}
            if action == "cloud-published-results":
                nodes = self.cloud_published.get("nodes", [])
                allowed = {"ip", "port", "rank", "lane", "qualified", "geo_country", "country", "entry_latency_ms", "proxy_average_latency_ms", "proxy_download_average_mbps",
                           "proxy_loss_percent", "latency_jitter_ms", "measurement_mode", "tcp_average_latency_ms", "tcp_loss_percent", "tcp_jitter_ms", "tls_average_latency_ms", "download_mbps", "city",
                           "tcp_rounds_ms", "tls_rounds_ms", "tls_enabled", "latency_probe", "latency_domain", "tls_loss_percent", "tls_jitter_ms", "rejection_reason", "google_rounds_ms", "cloudflare_rounds_ms", "github_rounds_ms",
                           "google_average_ms", "cloudflare_average_ms", "github_average_ms", "latency_method"}
                return {"rows": [{key: value for key, value in row.items() if key in allowed} for row in nodes], "total": len(nodes)}
            running = bool(self.process and self.process.poll() is None) or owned_core_running(settings["runtime_dir"])
            if action == "resume-testing":
                return self.action("resume-paused" if running else "resume", {})
            if action == "rules":
                rules = validate_rules({**current_rules(settings), **payload}, settings.get("measurement_mode", "proxy"))
                if self.direct and running and rules["tls_enabled"] != current_rules(settings)["tls_enabled"]:
                    raise ValueError("请先停止并保存，再切换 TCPing 或 TLS")
                atomic_write_json(settings["rules_path"], rules)
                self.events.append(f"规则已保存：常规发布前 {rules['publish_count']} 个，日本追加 {rules['jp_publish_count']} 个")
                return {"saved": True, "rules": rules, "effective": "已保存到本机，下一批生效；再次打开也使用这些规则" if running else "已保存到本机，立即生效；再次打开也使用这些规则"}
            if action in {"pause", "stop", "resume-paused"}:
                if action == "stop" and not self.closing:
                    self.explicit_stop = True
                    self.preserve_on_close = False
                    self.recovery_pending = False
                    save_measured(settings)
                    atomic_write_json(self.lifecycle_path, {"last_exit": "normal", "explicit_stop": True})
                path = settings["state_dir"] / "control.json"
                if action == "resume-paused":
                    path.unlink(missing_ok=True)
                    if running:
                        self.clock.start()
                else:
                    atomic_write_json(path, {"action": action})
                    if action == "pause":
                        self.clock.stop()
                self.events.append({"stop": "用户停止并保存：保存已测合格结果；正常关闭后下次全量获取，不续断点", "pause": "用户暂停了测试", "resume-paused": "用户继续测试"}[action])
                return {"requested": action}
            if action == "publish":
                pending = (self.app / "runtime" / ("pending-publish-tcp" if self.direct else "pending-publish") / "manifest.json").exists()
                if not running and not pending and not (settings["state_dir"] / "batch-state.json").exists() and not (settings["output_dir"] / "nodes.json").exists() and not read_saved(settings):
                    raise ValueError("没有可推送的已测结果，请先开始优选")
                atomic_write_json(settings["state_dir"] / "publish-request.json", {"requested": True})
                if running:
                    (settings["state_dir"] / "control.json").unlink(missing_ok=True)
                    self.clock.start()
                    return {"requested": "publish", "message": "手动推送已排队：当前批次结束后复测已有结果，再推送 GitHub"}
            if action == "discover":
                references = discover_profiles("jackoyu.dpdns.org")
                # One choice per immutable protocol parameter set; hide credentials and server values.
                seen = set()
                items = []
                for reference in references:
                    identity = (reference["path"], reference["port"], reference["protocol"], reference["network"], reference["matches_worker"])
                    if identity not in seen:
                        seen.add(identity)
                        items.append(reference)
                return {"profiles": items[:100]}
            if action in {"import", "import-existing"}:
                if running:
                    raise ValueError("测速运行中不能更换 Profile")
                if action == "import":
                    return save_import(str(payload.get("text", "")), settings["profile"])
                references = discover_profiles("jackoyu.dpdns.org")
                chosen = next((item for item in references if item["id"] == payload.get("id")), None)
                if chosen is None and payload.get("auto") is True:
                    chosen = next((item for item in references if item["matches_worker"] and item["port"] == 443), None)
                if chosen is None:
                    raise ValueError("未找到匹配配置，请导入现有节点链接")
                return import_discovered(chosen, settings["profile"])
            if action in {"start", "resume", "continue-fetch", "validate", "auto-start", "publish"}:
                if running:
                    raise ValueError("已有任务正在运行")
                if action in {"start", "auto-start", "resume", "continue-fetch"}:
                    self.preserve_on_close = False
                    (settings["state_dir"] / "publish-request.json").unlink(missing_ok=True)
                if action != "auto-start" and not self.direct:
                    ProxyProfile.load(settings["profile"])
                command = "validate-runtime" if action == "validate" else "auto-cloud"
                mode = {"continue-fetch": "continue", "resume": "resume", "publish": "publish"}.get(action)
                if action in {"start", "auto-start"} and self.recovery_pending:
                    mode = "resume"
                if action in {"start", "auto-start", "resume", "continue-fetch"}:
                    self.recovery_pending = False
                    self.explicit_stop = False
                atomic_write_json(self.lifecycle_path, {"last_exit": "running"})
                arguments = ["--mode", mode] if mode else []
                if command == "auto-cloud" and self.direct:
                    arguments.extend(["--measurement-mode", "tcp_tls"])
                atomic_write_json(settings["state_dir"] / "cloud-live.json", {"repository": self.legacy.repository,
                                  "mode": action,
                                  "status": "Preparing", "stage": "检查规则代理内核" if action == "validate" else "正在准备云端任务和规则代理"})
                log_path = self.root / "logs/proxybench.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self.log_handle = log_path.open("ab")
                env = dict(__import__("os").environ)
                env["PYTHONUTF8"] = "1"
                self.process = subprocess.Popen([cli_python(), "-X", "utf8", str(self.app / "main.py"), "--config", str(self.app / "config.yaml"), command, *arguments],
                                                cwd=self.app, stdout=self.log_handle, stderr=self.log_handle,
                                                env=env,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.legacy.process = self.process
                self.clock.start(reset=action in {"start", "auto-start"} and mode != "resume")
                return {"started": True, "action": action,
                        "message": "正在复测并推送已有合格结果；本次不获取新 IP" if action == "publish" else "任务已启动，获取与实测结果会自动更新"}
            if action == "cloud-start":
                return self.action("auto-start", {})
            if action in {"results", "live-results", "qualified-results", "candidates", "published-results", "competition-results"}:
                return self.rows(action, int(payload.get("page", int(payload.get("offset", 0)) // 300 + 1)))
            raise ValueError("未知操作")

    def request_close(self) -> None:
        live = self.read_cached(self.settings["state_dir"] / "live.json", default={})
        cloud = self.read_cached(self.settings["state_dir"] / "cloud-live.json", default={})
        if not self.explicit_stop:
            self.preserve_on_close |= live.get("status") == "Failed" or cloud.get("status") == "Failed" or cloud.get("interrupted", False)
        self.closing = True
        self.clock.stop()
        atomic_write_json(self.settings["state_dir"] / "cloud-read-control.json", {"action": "stop"})
        self.action("stop", {})

    def ready_to_close(self) -> bool:
        return not (self.process and self.process.poll() is None or owned_core_running(self.settings["runtime_dir"]) or
                    self.cloud_refresh_thread and self.cloud_refresh_thread.is_alive())

    def finish_close(self, normal: bool, *, clear_shared_cache=True) -> bool:
        """Delete only known transient files after the owned task releases its locks."""
        live = self.read_cached(self.settings["state_dir"] / "live.json", default={})
        cloud = self.read_cached(self.settings["state_dir"] / "cloud-live.json", default={})
        if not self.explicit_stop:
            self.preserve_on_close |= live.get("status") == "Failed" or cloud.get("status") == "Failed" or cloud.get("interrupted", False)
        if not self.ready_to_close():
            return False
        if not normal or self.preserve_on_close:
            atomic_write_json(self.lifecycle_path, {"last_exit": "error", "recovery_pending": True})
            return False
        save_measured(self.settings)
        atomic_write_json(self.lifecycle_path, {"last_exit": "normal"})
        clear_transient(self.settings)
        if clear_shared_cache:
            clear_shared(self.app)
        self.file_cache.clear()
        return True
