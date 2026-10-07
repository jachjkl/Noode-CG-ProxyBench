from __future__ import annotations

import base64
import copy
import hashlib
import ipaddress
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from core.io_utils import atomic_write_text


class ProfileError(ValueError):
    def __init__(self, reason: str = "请导入现有节点配置") -> None:
        super().__init__(f"缺少可用代理协议配置：{reason}")


class ProxyProfile:
    def __init__(self, value: dict) -> None:
        proxy = copy.deepcopy(value.get("proxy", value))
        if not isinstance(proxy, dict):
            raise ProfileError("配置格式错误")
        proxy["type"] = proxy.pop("protocol", proxy.get("type", ""))
        proxy.pop("name", None)
        proxy.pop("server", None)
        aliases = {"sni": "servername", "fingerprint": "client-fingerprint", "Host": "host"}
        for old, new in aliases.items():
            if old in proxy:
                proxy[new] = proxy.pop(old)
        if proxy.get("network") == "ws" and ("ws_path" in proxy or "host" in proxy):
            opts = proxy.setdefault("ws-opts", {})
            if "ws_path" in proxy:
                opts["path"] = proxy.pop("ws_path")
            if "host" in proxy:
                opts.setdefault("headers", {})["Host"] = proxy.pop("host")
        kind = str(proxy["type"]).lower()
        if kind not in {"vless", "vmess", "trojan", "ss", "hysteria2", "tuic", "anytls", "socks5", "http"}:
            raise ProfileError("不支持的代理协议")
        try:
            port = int(proxy.get("port", 443))
            if not 1 <= port <= 65535:
                raise ValueError
            if kind in {"vless", "vmess", "tuic"}:
                uuid.UUID(str(proxy.get("uuid", "")))
            if kind in {"trojan", "ss", "hysteria2", "tuic", "anytls"} and not str(proxy.get("password", "")).strip():
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ProfileError("端口或鉴权参数不完整") from None
        if kind == "ss" and not proxy.get("cipher"):
            raise ProfileError("缺少 Shadowsocks cipher")
        if proxy.get("skip-cert-verify"):
            raise ProfileError("需要有效 TLS 证书，不能跳过校验")
        if any(key in proxy for key in ("dialer-proxy", "connect-via")):
            raise ProfileError("不能引用外部策略组")
        proxy.update(type=kind, port=port)
        self._proxy = proxy
        self.port = port
        self.protocol = kind
        self.fingerprint = hashlib.sha256(json.dumps(proxy, sort_keys=True).encode()).hexdigest()

    @classmethod
    def load(cls, path: Path) -> ProxyProfile:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ProfileError("配置必须是 YAML 对象")
            return cls(data)
        except (OSError, yaml.YAMLError, UnicodeError):
            raise ProfileError("本机文件不存在或格式错误") from None

    def definition(self, ip: str, name: str) -> dict:
        ipaddress.ip_address(ip)
        return {**copy.deepcopy(self._proxy), "name": name, "server": ip}

    def summary(self) -> dict:
        return {"configured": True, "protocol": self.protocol, "port": self.port,
                "network": self._proxy.get("network", "tcp"), "tls": bool(self._proxy.get("tls", self.protocol == "trojan"))}


def import_link(text: str) -> dict:
    if len(text) > 131072:
        raise ProfileError("配置过大")
    text = text.strip()
    if text.startswith("vmess://"):
        try:
            raw = text[8:]
            value = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
            return {"type": "vmess", "port": int(value["port"]), "uuid": value["id"],
                    "alterId": int(value.get("aid", 0)), "cipher": value.get("scy", "auto"),
                    "network": value.get("net", "tcp"), "tls": value.get("tls") == "tls",
                    "servername": value.get("sni") or value.get("host") or value["add"],
                    "ws-opts": {"path": value.get("path", "/"), "headers": {"Host": value.get("host", value["add"])}}}
        except Exception:
            raise ProfileError("VMess 链接格式错误") from None
    parsed = urlsplit(text)
    if parsed.scheme not in {"vless", "trojan"}:
        raise ProfileError("支持 VLESS、Trojan、VMess 链接或 Mihomo YAML 节点")
    query = parse_qs(parsed.query)
    def get(key, default=""):
        return query.get(key, [default])[0]
    try:
        proxy = {"type": parsed.scheme, "port": parsed.port or 443,
                 "uuid" if parsed.scheme == "vless" else "password": unquote(parsed.username or ""),
                 "tls": get("security", "tls") == "tls", "servername": get("sni", parsed.hostname or ""),
                 "network": get("type", "tcp")}
    except ValueError:
        raise ProfileError("链接端口错误") from None
    if proxy["network"] == "ws":
        proxy["ws-opts"] = {"path": get("path", "/"), "headers": {"Host": get("host", proxy["servername"])}}
    for key, target in (("fp", "client-fingerprint"), ("flow", "flow")):
        if get(key):
            proxy[target] = get(key)
    if get("alpn"):
        proxy["alpn"] = get("alpn").split(",")
    if get("security") == "reality":
        raise ProfileError("Reality 节点不能直接替换为 Cloudflare Edge IP")
    return proxy


def save_import(text: str, destination: Path) -> dict:
    try:
        value = import_link(text) if "://" in text.splitlines()[0] else yaml.safe_load(text)
        profile = ProxyProfile(value)
    except ProfileError:
        raise
    except Exception:
        raise ProfileError("无法解析节点配置") from None
    destination.parent.mkdir(parents=True, exist_ok=True)
    wrapper = {"proxy": profile._proxy}
    raw = value.get("proxy", value)
    if raw.get("server"):
        try:
            wrapper["validation_servers"] = [str(ipaddress.IPv4Address(raw["server"]))]
        except ValueError:
            pass
    atomic_write_text(destination, yaml.safe_dump(wrapper, allow_unicode=True))
    os.chmod(destination, 0o600)
    return profile.summary()


def discover_profiles(target_host: str = "") -> list[dict]:
    """Read only known client directories. Return local references, never credentials."""
    home = Path.home()
    roots = [home / ".config/mihomo", home / ".config/clash",
             home / "AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev",
             home / "AppData/Roaming/clash-party", home / "AppData/Roaming/mihomo-party"]
    results = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in list(root.glob("*.yaml")) + list((root / "profiles").glob("*.yaml")):
            try:
                if path.stat().st_size > 20 * 1024 * 1024:
                    continue
                payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
                for index, proxy in enumerate((payload or {}).get("proxies", [])):
                    if not isinstance(proxy, dict) or proxy.get("type") not in {"vless", "vmess", "trojan"}:
                        continue
                    profile = ProxyProfile(proxy)
                    host = str(proxy.get("servername") or proxy.get("sni") or "")
                    ws_host = str(proxy.get("ws-opts", {}).get("headers", {}).get("Host", ""))
                    results.append({"path": str(path), "index": index, **profile.summary(),
                                    "matches_worker": bool(target_host and target_host in {host, ws_host}),
                                    "id": hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:16]})
            except Exception:
                continue
    try:
        import psutil
        party_active = any("clash party" in (process.info.get("name") or "").lower()
                           for process in psutil.process_iter(["name"]))
    except Exception:
        party_active = False
    results.sort(key=lambda item: (not item["matches_worker"],
                                  not (party_active and "mihomo-party" in item["path"]),
                                  item["port"] != 443, item["path"], item["index"]))
    return results


def import_discovered(reference: dict, destination: Path) -> dict:
    proxies = yaml.safe_load(Path(reference["path"]).read_text(encoding="utf-8-sig"))["proxies"]
    value = proxies[reference["index"]]
    summary = save_import(yaml.safe_dump(value), destination)
    profile = ProxyProfile(value)
    servers = []
    for item in proxies:
        try:
            if ProxyProfile(item).fingerprint == profile.fingerprint:
                address = ipaddress.IPv4Address(item["server"])
                if address.is_global and str(address) not in servers:
                    servers.append(str(address))
        except Exception:
            continue
    atomic_write_text(destination, yaml.safe_dump({"proxy": profile._proxy, "validation_servers": servers}, allow_unicode=True))
    return summary


def safe_error(exc: BaseException) -> str:
    # Network/Core exceptions can embed URLs, authentication paths or config text.
    if isinstance(exc, ProfileError) or type(exc).__name__ in {"CoreError", "RoutingError", "CloudError"}:
        return str(exc)
    return re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__) or "Error"
