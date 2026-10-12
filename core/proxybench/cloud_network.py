"""Keep authenticated cloud control on official endpoints and inspect VPN state read-only."""
from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlsplit

from core.io_utils import atomic_write_json


def windows_proxy() -> str:
    if os.name != "nt":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return ""
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0])
    except OSError:
        return ""
    if "=" in server:
        values = dict(part.split("=", 1) for part in server.split(";") if "=" in part)
        server = values.get("https") or values.get("http") or ""
    return server if "://" in server else f"http://{server}" if server else ""


def network_settings(root) -> dict:
    path = root / "data/github-network.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {"enabled": bool(value.get("enabled", False)), "proxy_url": value.get("proxy_url", "http://127.0.0.1:7890")}


def save_network(root, value) -> dict:
    proxy = str(value.get("proxy_url", "")).strip()
    address = urlsplit(proxy)
    try:
        valid = address.scheme in {"http", "https"} and address.hostname in {"localhost", "127.0.0.1", "::1"} and 0 < address.port < 65536
    except (TypeError, ValueError):
        valid = False
    if not valid or address.username or address.password or address.query or address.fragment or address.path not in {"", "/"}:
        raise ValueError("请输入本机 HTTP 代理地址，例如 http://127.0.0.1:7890；不填写账号或密码")
    saved = {"enabled": bool(value.get("enabled", False)), "proxy_url": proxy}
    atomic_write_json(root / "data/github-network.json", saved)
    return saved


def cloud_environment(base: dict | None = None, *, root=None) -> dict:
    env = {key: value for key, value in (os.environ if base is None else base).items()
           if key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}}
    bypass = next((value for key, value in env.items() if key.lower() == "no_proxy"), "")
    hosts = list(dict.fromkeys([x.strip() for x in bypass.split(",") if x.strip()] + ["localhost", "127.0.0.1", "::1"]))
    env["no_proxy"] = env["NO_PROXY"] = ",".join(hosts)
    if root is not None:
        selected = network_settings(root)
        if selected["enabled"]:
            env["HTTPS_PROXY"] = env["HTTP_PROXY"] = selected["proxy_url"]
    return env


def vpn_environment() -> dict:
    """A reachable local listener is evidence of a client, not proof of a VPN tunnel."""
    import psutil
    listener = False
    proxy = windows_proxy()
    try:
        address = urlsplit(proxy)
        if address.scheme in {"http", "https"} and address.hostname in {"127.0.0.1", "localhost", "::1"} and address.port:
            with socket.create_connection((address.hostname, address.port), timeout=0.5):
                listener = True
    except (OSError, ValueError):
        pass
    clients = []
    for process in psutil.process_iter(["name"]):
        name = (process.info["name"] or "").lower()
        if name in {"mihomo.exe", "clash.exe", "clash-meta.exe", "clash-party.exe", "clash-verge.exe"}:
            clients.append(name)
    return {"local_proxy_reachable": listener, "client_detected": bool(clients),
            "message": "检测到本机代理客户端，测速保留当前 VPN 和系统路由" if listener or clients else "未检测到本机代理客户端，测速使用当前系统路由",
            "system_route_changed": False, "cloud_uses_local_http_proxy": False}
