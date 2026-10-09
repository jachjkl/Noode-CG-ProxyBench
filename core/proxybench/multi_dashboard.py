"""One desktop window, one active task, two independently persisted methods."""
from __future__ import annotations

import json
import secrets
import threading
from types import SimpleNamespace

from core.io_utils import atomic_write_json

from .dashboard import BenchDashboard
from .mihomo_manager import owned_core_running
from .modes import MODES, publication_limits
from .settings import current_rules


class MultiModeDashboard:
    def __init__(self, legacy):
        self.legacy = legacy
        self.lock = threading.RLock()
        session = secrets.token_hex(16)
        self.controllers = {mode: BenchDashboard(SimpleNamespace(root=legacy.root, repository=legacy.repository), mode=mode, session_id=session) for mode in MODES}
        self.app = self.controllers["proxy"].app
        self.options = self.app / "data/proxybench-ui.json"
        try:
            self.mode = json.loads(self.options.read_text(encoding="utf-8")).get("mode", "proxy")
        except (OSError, ValueError):
            self.mode = "proxy"
        if self.mode not in MODES:
            self.mode = "proxy"
        self.active_mode = None
        legacy.proxybench = self

    def active(self):
        return next((mode for mode, child in self.controllers.items() if child.process and child.process.poll() is None or owned_core_running(child.settings["runtime_dir"])), None)

    def refresh_cloud(self):
        for child in self.controllers.values():
            child.refresh_cloud()

    def snapshot(self, mode=None):
        selected = mode if mode in MODES else self.mode
        value = self.controllers[selected].snapshot()
        active = self.active()
        value.update(measurement_mode=selected, active_mode=active, global_running=active is not None,
                     modes={mode: {"title": title, "limits": publication_limits(current_rules(self.controllers[mode].settings)),
                                    "cloud": {k: v for k, v in self.controllers[mode].cloud_published.items() if k != "nodes"}}
                            for mode, title in MODES.items()})
        return value

    def action(self, action, payload):
        with self.lock:
            return self._action(action, dict(payload))

    def _action(self, action, payload):
        if action == "choose-mode":
            mode = payload.get("mode")
            if mode not in MODES:
                raise ValueError("请选择有效测速方式")
            self.mode = mode
            atomic_write_json(self.options, {"mode": mode})
            return {"selected": mode, "title": MODES[mode]}
        mode = payload.pop("measurement_mode", self.mode)
        if mode not in MODES:
            raise ValueError("未知测速方式")
        active = self.active()
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
        return all(child.ready_to_close() for child in self.controllers.values())

    def finish_close(self, normal):
        if not normal or any(child.preserve_on_close or child.read_cached(child.settings["state_dir"] / "cloud-live.json", default={}).get("status") == "Failed"
                             for child in self.controllers.values()):
            return False
        results = [child.finish_close(normal) for child in self.controllers.values()]
        if all(results):
            (self.app / "data/window-candidates.json.gz").unlink(missing_ok=True)
        return all(results)
