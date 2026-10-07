from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml

from .common import timestamp


def collect(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    if payload.get("enabled") is not True:
        return []
    if payload.get("authorized") is not True:
        raise ValueError("授权代理 Source 必须明确 authorized=true")
    result = []
    for item in payload.get("candidates", []):
        ip = ipaddress.ip_address(item["ip"])
        if not ip.is_global or not item.get("profile_file", "").endswith(".local.yaml"):
            raise ValueError("授权代理需要公网地址和仅本机 Profile 引用")
        result.append({"ip": str(ip), "port": int(item["port"]), "profile_file": item["profile_file"],
                       "source_names": [str(payload.get("name", "authorized-local"))],
                       "source_types": ["authorized_proxy_candidate"], "source_priority": 0, "jp_hint": True,
                       "first_seen": timestamp(), "last_seen": timestamp()})
    return result
