from __future__ import annotations

import gzip
import json
import secrets
import subprocess
import threading

from core.io_utils import atomic_write_json

from .execution import cli_python
from .profile import ProxyProfile, discover_profiles, import_discovered, save_import
from .settings import current_rules, load_settings, validate_rules


class BenchDashboard:
    def __init__(self, legacy_state) -> None:
        self.legacy = legacy_state
        self.legacy.proxybench = self
        self.root = legacy_state.root
        self.app = self.root / "app" if (self.root / "app/config.yaml").exists() else self.root
        self.settings = load_settings(self.app / "config.yaml")
        self.process = None
        self.lock = threading.RLock()
        self.log_handle = None
        self.file_cache = {}
        atomic_write_json(self.settings["state_dir"] / "session.json", {"session_id": secrets.token_hex(16)})

    def read_cached(self, path, *, compressed=False, default=None):
        if not path.exists():
            return default
        stat = path.stat()
        identity = (stat.st_mtime_ns, stat.st_size)
        cached = self.file_cache.get(path)
        if cached and cached[0] == identity:
            return cached[1]
        content = path.read_bytes()
        value = json.loads(gzip.decompress(content) if compressed else content)
        self.file_cache[path] = (identity, value)
        return value

    def rows(self, kind: str, page: int) -> dict:
        if page < 1:
            raise ValueError("页码必须大于零")
        settings = self.settings
        live = self.read_cached(settings["state_dir"] / "live.json", default={})
        cloud = self.read_cached(self.app / "data/handoff/proxybench-cloud-health.json", default={})
        same_pool = bool(live.get("sources", {}).get("seed") and live["sources"]["seed"] == cloud.get("seed"))
        measured = dict(self.read_cached(settings["state_dir"] / "benchmark-results.json.gz", compressed=True, default={})) if same_pool or not cloud else {}
        active_rows = live.get("candidates", []) if same_pool or not cloud or live.get("phase") == "validation" else []
        for row in active_rows:
            measured[f"{row['ip']}:{row['port']}"] = row
        if kind == "published-results":
            rows = self.read_cached(settings["output_dir"] / "nodes.json", default=[])
        elif kind == "results":
            rows = [row for row in measured.values() if row.get("tested_at")]
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
        if kind == "candidates":
            # Keep full candidate data on disk; send only this page and its actual measurements.
            visible = [{**row, **measured.get(f"{row['ip']}:{row['port']}", {}),
                        "status": measured.get(f"{row['ip']}:{row['port']}", {}).get("status", "Queued")} for row in visible]
        return {"rows": visible, "total": total, "page": page, "pages": pages, "page_size": 300}

    def snapshot(self) -> dict:
        settings = self.settings
        path = settings["state_dir"] / "live.json"
        try:
            live = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            live = {"status": "正在刷新"}
        running = bool(self.process and self.process.poll() is None)
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
        return {"live": live, "profile": profile, "rules": current_rules(settings), "published": health,
                "running": running,
                "actions_url": f"https://github.com/{self.legacy.repository}/actions",
                "cloud": cloud,
                "can_resume": (settings["state_dir"] / "batch-state.json").exists()}

    def action(self, action: str, payload: dict) -> dict:
        with self.lock:
            settings = self.settings
            running = bool(self.process and self.process.poll() is None)
            if action == "resume-testing":
                return self.action("resume-paused" if running else "resume", {})
            if action == "rules":
                rules = validate_rules(payload)
                atomic_write_json(settings["rules_path"], rules)
                return {"saved": True, "rules": rules, "effective": "下一批生效" if running else "立即生效"}
            if action in {"pause", "stop", "resume-paused"}:
                path = settings["state_dir"] / "control.json"
                if action == "resume-paused":
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_json(path, {"action": action})
                return {"requested": action}
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
            if action in {"start", "resume", "continue-fetch", "validate", "auto-start"}:
                if running:
                    raise ValueError("已有任务正在运行")
                if action != "auto-start":
                    ProxyProfile.load(settings["profile"])
                command = "validate-runtime" if action == "validate" else "auto-cloud"
                arguments = ["--mode", "continue" if action == "continue-fetch" else "resume"] if action in {"resume", "continue-fetch"} else []
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
                return {"started": True, "action": action}
            if action == "cloud-start":
                return self.action("auto-start", {})
            if action in {"results", "candidates", "published-results"}:
                return self.rows(action, int(payload.get("page", int(payload.get("offset", 0)) // 300 + 1)))
            raise ValueError("未知操作")
