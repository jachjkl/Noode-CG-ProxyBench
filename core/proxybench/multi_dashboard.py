"""One desktop window, one active task, two independently persisted methods."""
from __future__ import annotations

import json
import secrets
import threading
from types import SimpleNamespace

from core.io_utils import atomic_write_json

from .dashboard import BenchDashboard
from .mihomo_manager import MihomoManager, owned_core_running
from .modes import MODES, publication_limits
from .session_lifecycle import clear_shared
from .settings import current_rules


class MultiModeDashboard:
    def __init__(self, legacy):
        self.legacy = legacy
        self.lock = threading.RLock()
        session = secrets.token_hex(16)
        self.controllers = {mode: BenchDashboard(SimpleNamespace(root=legacy.root, repository=legacy.repository), mode=mode, session_id=session) for mode in MODES}
        self.app = self.controllers["proxy"].app
        if any(child.cleaned_on_open for child in self.controllers.values()) and not any(child.recovery_pending for child in self.controllers.values()):
            clear_shared(self.app)
        self.options = self.app / "data/proxybench-ui.json"
        try:
            self.mode = json.loads(self.options.read_text(encoding="utf-8")).get("mode", "proxy")
        except (OSError, ValueError):
            self.mode = "proxy"
        if self.mode not in MODES:
            self.mode = "proxy"
        self.active_mode = None
        self.core_manager = MihomoManager(self.app / "runtime/mihomo")
        self.core_thread = None
        self.core_checked = False
        self.core_message = "每次打开检查内核更新，最多保留两个版本"
        legacy.proxybench = self

    def refresh_core(self, version="latest", *, automatic=True):
        if self.core_thread and self.core_thread.is_alive():
            raise ValueError("内核正在更新，请稍候")
        if self.active():
            raise ValueError("请先停止测速，再更新或切换内核")
        self.core_message = "正在检查内核更新，完成后可以开始测试" if automatic else "正在切换内核版本"
        def check():
            try:
                if automatic:
                    self.core_manager.ensure(True, validate_start=False)
                else:
                    self.core_manager.choose_version(version)
                self.core_message = self.core_manager.update_status or "内核版本已就绪，最多保留当前版和上一版"
                self.controllers["proxy"].events.append(self.core_message)
            except Exception:
                self.core_message = "内核更新或切换失败，原版本已保留；可重试更新"
                self.controllers["proxy"].events.append(self.core_message, level="error")
        self.core_thread = threading.Thread(target=check, daemon=True)
        self.core_thread.start()

    def active(self):
        return next((mode for mode, child in self.controllers.items() if child.process and child.process.poll() is None or owned_core_running(child.settings["runtime_dir"])), None)

    def refresh_cloud(self):
        if not self.core_checked and not self.active():
            self.core_checked = True
            self.refresh_core()
        for child in self.controllers.values():
            child.refresh_cloud()

    def snapshot(self, mode=None):
        selected = mode if mode in MODES else self.mode
        value = self.controllers[selected].snapshot()
        active = self.active()
        value.update(measurement_mode=selected, active_mode=active, global_running=active is not None,
                     core_versions={**self.core_manager.version_catalog(), "busy": bool(self.core_thread and self.core_thread.is_alive()), "message": self.core_message},
                     modes={mode: {"title": title, "limits": publication_limits(current_rules(self.controllers[mode].settings)),
                                    "cloud": {k: v for k, v in self.controllers[mode].cloud_published.items() if k != "nodes"}}
                            for mode, title in MODES.items()})
        return value

    def action(self, action, payload):
        with self.lock:
            return self._action(action, dict(payload))

    def _action(self, action, payload):
        if action == "core-version":
            self.refresh_core(str(payload.get("version", "latest")), automatic=False)
            return {"requested": action, "message": self.core_message}
        if action == "choose-mode":
            mode = payload.get("mode")
            if mode not in MODES:
                raise ValueError("请选择有效测速方式")
            if mode == "tcp_tls" and "probe" in payload:
                if payload["probe"] not in {"tcp", "tls"}:
                    raise ValueError("直连延迟只能选择 TCPing 或 TLS")
                child = self.controllers[mode]
                saved = current_rules(child.settings)
                selected = int(payload["probe"] == "tls")
                if saved["tls_enabled"] != selected:
                    if self.active() == mode:
                        raise ValueError("直连测速正在运行，请先停止并保存，再切换 TCPing 或 TLS")
                    child.action("rules", {"tls_enabled": selected})
            self.mode = mode
            atomic_write_json(self.options, {"mode": mode})
            return {"selected": mode, "title": MODES[mode]}
        mode = payload.pop("measurement_mode", self.mode)
        if mode not in MODES:
            raise ValueError("未知测速方式")
        active = self.active()
        if action in {"start", "auto-start", "resume", "continue-fetch", "validate", "publish"} and self.core_thread and self.core_thread.is_alive():
            raise ValueError("正在检查或更新内核，完成后再开始测试")
        if action in {"start", "auto-start", "resume", "continue-fetch", "validate"} and active:
            raise ValueError(f"{MODES[active]}正在运行，请先停止保存")
        if action in {"pause", "stop", "resume-testing", "resume-paused"} and active:
            mode = active
        if action == "publish" and active and mode != active:
            raise ValueError("另一种测速正在运行，可先查看结果，停止后再推送此方式")
        if action == "cloud-published-results":
            rows = []
            for name, child in self.controllers.items():
                result = child.action(action, {})
                rows.extend({**r, "measurement_mode": name} for r in result["rows"])
            page = max(1, int(payload.get("page", 1)))
            pages = max(1, (len(rows) + 299) // 300)
            page = min(page, pages)
            return {"rows": rows[(page - 1) * 300:page * 300], "total": len(rows), "page": page, "pages": pages}
        if action == "refresh-cloud-results":
            self.refresh_cloud()
            return {"requested": action}
        result = self.controllers[mode].action(action, payload)
        if result.get("started"):
            self.active_mode = mode
            self.legacy.process = self.controllers[mode].process
        return result

    def request_close(self):
        for child in self.controllers.values():
            child.request_close()

    def ready_to_close(self):
        return not (self.core_thread and self.core_thread.is_alive()) and all(child.ready_to_close() for child in self.controllers.values())

    def finish_close(self, normal):
        results = [child.finish_close(normal, clear_shared_cache=False) for child in self.controllers.values()]
        if all(results):
            clear_shared(self.app)
        return all(results)
