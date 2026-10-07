"""Fast connection screening, separate from authenticated proxy/site measurements."""
from __future__ import annotations

import socket
import time


def probe(candidate: dict, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        with socket.create_connection((candidate["ip"], candidate["port"]), timeout=timeout):
            elapsed = (time.perf_counter() - started) * 1000
        return {"entry_connected": True, "entry_latency_ms": elapsed,
                "entry_method": "local-tcp-connect", "entry_destination": f"{candidate['ip']}:{candidate['port']}"}
    except OSError:
        return {"entry_connected": False, "entry_latency_ms": None,
                "entry_method": "local-tcp-connect", "entry_error": "入口端口连接失败或超时"}
