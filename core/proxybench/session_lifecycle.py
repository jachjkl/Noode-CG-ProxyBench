"""Normal window exits discard sessions; errors retain resumable checkpoints."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from core.io_utils import atomic_write_bytes, atomic_write_json

from .benchmark import limit_failure
from .settings import current_rules
from .state import Store


def saved_path(settings: dict) -> Path:
    return settings.get("root", settings["state_dir"]) / "data/saved-measurements" / f"{settings.get('measurement_mode', 'proxy')}.json.gz"


def upgrade_direct_parallelism(settings: dict) -> bool:
    marker = settings["root"] / "data/tcpbench-parallelism-v2.json"
    if settings.get("measurement_mode") != "tcp_tls" or marker.exists():
        return False
    path = settings["rules_path"]
    rules = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    changed = all(rules.get(key) == value for key, value in {"speed_concurrency": 4, "tls_concurrency": 32, "tcp_timeout_seconds": 1.2}.items())
    if changed:
        rules.update(speed_concurrency=20, tls_concurrency=100, tcp_timeout_seconds=1.0)
        atomic_write_json(path, rules)
    atomic_write_json(marker, {"applied": changed})
    return changed


def read_saved(settings: dict) -> list[dict]:
    path = saved_path(settings)
    return json.loads(gzip.decompress(path.read_bytes())).get("records", []) if path.exists() else []


def save_measured(settings: dict) -> None:
    try:
        store = Store(settings["state_dir"])
        state = store.load()
        rows = {**state.get("results", {}), **state.get("general_results", {}), **state.get("jp_results", {}), **store.partial}
        rules = current_rules(settings)
        qualified = [row for row in rows.values() if row.get("qualified") and row.get("ip") and not limit_failure(row, rules)]
    except (OSError, ValueError, KeyError):
        return
    if rows:
        previous = {f"{r['ip']}:{r['port']}": r for r in read_saved(settings)}
        for row in rows.values():
            if row.get("ip") and row.get("port"):
                previous.pop(f"{row['ip']}:{row['port']}", None)
        previous.update({f"{r['ip']}:{r['port']}": r for r in qualified})
        atomic_write_bytes(saved_path(settings), gzip.compress(json.dumps({"records": list(previous.values())}, ensure_ascii=False).encode(), compresslevel=1, mtime=0))


def clear_transient(settings: dict) -> None:
    app = settings["root"].resolve()
    state = settings["state_dir"].resolve()
    if app not in state.parents or state.name not in {"proxy-bench", "tcp-bench"}:
        raise ValueError("缓存目录不属于当前软件，未清理")
    if state.exists():
        for path in state.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)


def clear_shared(app: Path) -> None:
    app = app.resolve()
    handoff = app / "data/handoff"
    if not (app / ".git").exists():
        for name in ("proxybench-pool.json.gz", "proxybench-cloud-health.json", "proxybench-session-history.json.gz", "proxybench-attempted.json.gz"):
            (handoff / name).unlink(missing_ok=True)
    (app / "data/window-candidates.json.gz").unlink(missing_ok=True)
