"""Use the owner's existing HTTP proxy for cloud control, without changing Windows."""
from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit


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


def cloud_environment(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    explicit = {key.lower(): value for key, value in env.items() if key.lower() in {"http_proxy", "https_proxy"} and value}
    if not explicit:
        proxy = windows_proxy()
        try:
            address = urlsplit(proxy)
            # Automatic discovery uses only a live local client, never a candidate core or remote credentials.
            if address.scheme in {"http", "https"} and address.hostname in {"127.0.0.1", "localhost", "::1"} and address.port:
                with socket.create_connection((address.hostname, address.port), timeout=0.5):
                    pass
                explicit = {"http_proxy": proxy, "https_proxy": proxy}
        except (OSError, ValueError):
            pass
    # Runner gives lowercase variables precedence. Supply consistent values to .NET and gh.
    for key, value in explicit.items():
        env[key] = env[key.upper()] = value
    bypass = next((value for key, value in env.items() if key.lower() == "no_proxy"), "")
    hosts = list(dict.fromkeys([x.strip() for x in bypass.split(",") if x.strip()] + ["localhost", "127.0.0.1", "::1"]))
    env["no_proxy"] = env["NO_PROXY"] = ",".join(hosts)
    return env
