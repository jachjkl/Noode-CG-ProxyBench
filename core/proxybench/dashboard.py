from __future__ import annotations

import gzip
import json
import secrets
import subprocess
import sys
import threading

from core.io_utils import atomic_write_json

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
        atomic_write_json(self.settings["state_dir"] / "session.json", {"session_id": secrets.token_hex(16)})

    def snapshot(self) -> dict:
        settings = self.settings
        path = settings["state_dir"] / "live.json"
        try:
            live = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            live = {"status": "正在刷新"}
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
        cloud_path = settings["state_dir"] / "cloud-live.json"
        cloud = json.loads(cloud_path.read_text(encoding="utf-8")) if cloud_path.exists() else {}
        source_path = self.app / "data/handoff/proxybench-cloud-health.json"
        if source_path.exists() and not live.get("sources"):
            source_report = json.loads(source_path.read_text(encoding="utf-8"))
            live["sources"] = source_report
            live["candidate_total"] = source_report.get("unique_candidate_count", 0)
        if self.process and self.process.poll() is not None and self.log_handle:
            self.log_handle.close()
            self.log_handle = None
        return {"live": live, "profile": profile, "rules": current_rules(settings), "published": health,
                "running": bool(self.process and self.process.poll() is None),
                "actions_url": f"https://github.com/{self.legacy.repository}/actions",
                "cloud": cloud,
                "can_resume": (settings["state_dir"] / "batch-state.json").exists()}

    def action(self, action: str, payload: dict) -> dict:
        with self.lock:
            settings = self.settings
            running = bool(self.process and self.process.poll() is None)
            if action == "rules":
                rules = validate_rules(payload)
                atomic_write_json(settings["rules_path"], rules)
                return {"saved": True, "rules": rules, "effective": "下一 Batch 生效" if running else "立即生效"}
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
                self.process = subprocess.Popen([sys.executable, "-X", "utf8", str(self.app / "main.py"), "--config", str(self.app / "config.yaml"), command, *arguments],
                                                cwd=self.app, stdout=self.log_handle, stderr=self.log_handle,
                                                env=env,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.legacy.process = self.process
                return {"started": True, "action": action}
            if action == "cloud-start":
                return self.action("auto-start", {})
            if action == "results":
                path = settings["state_dir"] / "benchmark-results.json.gz"
                rows = list(json.loads(gzip.decompress(path.read_bytes())).values()) if path.exists() else []
                offset = max(0, int(payload.get("offset", 0)))
                return {"rows": rows[offset:offset + 100], "total": len(rows)}
            if action == "candidates":
                path = self.app / "data/handoff/proxybench-pool.json.gz"
                rows = json.loads(gzip.decompress(path.read_bytes()))["pool"] if path.exists() else []
                offset = max(0, int(payload.get("offset", 0)))
                return {"rows": [{**row, "status": "Queued"} for row in rows[offset:offset + 100]], "total": len(rows)}
            raise ValueError("未知操作")
