from __future__ import annotations

import hashlib
import time
from pathlib import Path

from core.io_utils import atomic_write_bytes

from .common import candidates, fetch


def collect(entries: list[dict], networks: list, port: int, cache_dir: Path, downloader=fetch) -> tuple[list[dict], dict]:
    result = []
    report = {"warnings": [], "source_invalid": [], "source_from_cache": {}}
    cache_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        name = str(entry["name"])
        cache = cache_dir / (hashlib.sha256(entry["url"].encode()).hexdigest() + ".txt")
        from_cache = False
        try:
            payload = downloader(entry["url"])
            parsed = candidates(payload, name, port, jp_hint=True, priority=0)
            if not parsed:
                raise ValueError
            atomic_write_bytes(cache, payload)
        except Exception:
            if cache.exists() and time.time() - cache.stat().st_mtime <= int(entry.get("cache_max_age_seconds", 86400)):
                parsed = candidates(cache.read_bytes(), name, port, jp_hint=True)
                from_cache = True
            else:
                report["warnings"].append(f"Optional Source 不可用：{name}")
                continue
        report["source_from_cache"][name] = from_cache
        import ipaddress
        for item in parsed:
            if any(ipaddress.IPv4Address(item["ip"]) in network for network in networks):
                item["source_types"].append("candidate_hint")
                result.append(item)
            else:
                report["source_invalid"].append({"ip": item["ip"], "source": name, "status": "source_invalid"})
    return result, report
