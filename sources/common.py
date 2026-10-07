from __future__ import annotations

import ipaddress
import urllib.request
from datetime import UTC, datetime

from core.parser import parse_bytes


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def fetch(url: str, timeout: float = 30) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("Candidate Source 必须为 HTTPS")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "Noode-CG-ProxyBench/1.0"})
    with opener.open(request, timeout=timeout) as response:
        payload = response.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError("Source 超出上限，拒绝截断数据")
    return payload


def candidates(payload: bytes, name: str, port: int, *, jp_hint: bool = False, priority: int = 0) -> list[dict]:
    now = timestamp()
    result = []
    for node in parse_bytes("all.txt", payload, source=name, default_port=port):
        address = ipaddress.ip_address(node.ip)
        if address.version != 4 or not address.is_global:
            continue
        result.append({"ip": node.ip, "port": port, "source_names": [name],
                       "source_types": ["cloudflare_edge_candidate"], "source_priority": priority,
                       "jp_hint": jp_hint or node.country_hint.upper() == "JP", "first_seen": now, "last_seen": now})
    return result


def merge(records: list[dict]) -> list[dict]:
    combined = {}
    for record in records:
        key = f"{record['ip']}:{record['port']}"
        if key not in combined:
            combined[key] = dict(record)
            combined[key]["source_names"] = list(record["source_names"])
            combined[key]["source_types"] = list(record["source_types"])
            continue
        existing = combined[key]
        for field in ("source_names", "source_types"):
            existing[field] = sorted(set(existing[field]) | set(record[field]))
        existing["source_priority"] = min(existing["source_priority"], record["source_priority"])
        existing["jp_hint"] |= record["jp_hint"]
        existing["first_seen"] = min(existing["first_seen"], record["first_seen"])
        existing["last_seen"] = max(existing["last_seen"], record["last_seen"])
    return list(combined.values())
