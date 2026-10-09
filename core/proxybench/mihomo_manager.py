from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

import psutil
import yaml

from core.io_utils import atomic_write_bytes, atomic_write_json, atomic_write_text

from .controller import Controller, CoreError
from .settings import BATCH_SIZE


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def owned_core_running(root: Path) -> bool:
    """Read-only ownership check, including an orphaned local benchmark child."""
    root = root.resolve()
    try:
        owner = json.loads((root / "owner.json").read_text(encoding="utf-8"))
        process = psutil.Process(int(owner["pid"]))
        work = Path(owner["work"]).resolve()
        return (root in work.parents and work.name.startswith("session-")
                and Path(process.exe()).resolve() == root / ("mihomo.exe" if os.name == "nt" else "mihomo")
                and abs(process.create_time() - owner["created"]) < 0.01 and str(work) in process.cmdline())
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        return False


def download(url: str, limit: int = 80 * 1024 * 1024, *, timeout: float = 12) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Noode-CG-ProxyBench/1.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise CoreError("Mihomo 下载超过上限")
    return data


def release_download(url: str, expected: str) -> bytes:
    for address in [f"https://ghfast.top/{url}", f"https://gh.ddlc.top/{url}", f"https://gh-proxy.com/{url}", url]:
        try:
            content = download(address, timeout=10)
            if hashlib.sha256(content).hexdigest() == expected:
                return content
        except (OSError, ValueError):
            continue
    raise CoreError("全部内核镜像下载失败或摘要不匹配")


class MihomoManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.binary = self.root / ("mihomo.exe" if os.name == "nt" else "mihomo")
        self.owner_path = self.root / "owner.json"
        self.process = None
        self.controller = None
        self.work = None
        self.version = ""
        self.loaded = 0
        self.benchmark_active = False
        self.update_status = ""

    def version_catalog(self) -> dict:
        def read(name):
            path = self.root / name
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        current = read("version.json").get("version", "")
        previous = read("previous-version.json").get("version", "") if (self.root / "mihomo.previous").exists() else ""
        choice = read("core-choice.json")
        check = read("update-check.json")
        return {"current": current, "previous": previous, "pinned": bool(choice.get("version")),
                "update_required": bool(check.get("latest") and check["latest"] != current and not choice.get("version")),
                "latest": check.get("latest", ""), "checked_at": check.get("checked_at", 0),
                "message": check.get("message", ""),
                "versions": [v for v in (current, previous) if v], "limit": 2}

    def choose_version(self, version: str) -> dict:
        if self.process is not None or self.benchmark_active or owned_core_running(self.root):
            raise CoreError("请先停止测速，再切换内核版本")
        catalog = self.version_catalog()
        if version == "latest":
            (self.root / "core-choice.json").unlink(missing_ok=True)
            self.ensure(True, validate_start=False)
            return self.version_catalog()
        if version not in catalog["versions"]:
            raise ValueError("只能选择本机保存的当前版或上一版内核")
        if version == catalog["previous"]:
            prior = self.root / "mihomo.previous"
            old, selected = self.binary.read_bytes(), prior.read_bytes()
            metadata = self.root / "version.json"
            previous_meta = self.root / "previous-version.json"
            old_meta, selected_meta = metadata.read_bytes(), previous_meta.read_bytes()
            expected = json.loads(selected_meta).get("binary_sha256")
            if not expected or hashlib.sha256(selected).hexdigest() != expected:
                raise CoreError("上一版内核摘要不匹配，未切换")
            try:
                atomic_write_bytes(self.binary, selected)
                os.chmod(self.binary, 0o700)
                self.read_version()
                atomic_write_bytes(prior, old)
                atomic_write_bytes(metadata, selected_meta)
                old_value = json.loads(old_meta)
                old_value["binary_sha256"] = hashlib.sha256(old).hexdigest()
                atomic_write_json(previous_meta, old_value)
            except BaseException:
                atomic_write_bytes(self.binary, old)
                os.chmod(self.binary, 0o700)
                atomic_write_bytes(prior, selected)
                atomic_write_bytes(metadata, old_meta)
                atomic_write_bytes(previous_meta, selected_meta)
                raise
        atomic_write_json(self.root / "core-choice.json", {"version": version})
        self.update_status = f"已选择内核 {version}；继续检查更新并保留此选择"
        return self.version_catalog()

    def cleanup_orphan(self) -> None:
        if not self.owner_path.exists():
            return
        owner = json.loads(self.owner_path.read_text())
        try:
            process = psutil.Process(int(owner["pid"]))
            work = Path(owner["work"]).resolve()
            if self.root not in work.parents or not work.name.startswith("session-"):
                raise CoreError("孤儿进程工作目录不属于 ProxyBench")
            if (Path(process.exe()).resolve() != self.binary.resolve()
                    or abs(process.create_time() - owner["created"]) > 0.01
                    or str(work) not in process.cmdline()):
                raise CoreError("孤儿进程归属不匹配，未终止用户 Core")
            process.terminate()
            try:
                process.wait(5)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(5)
        except psutil.NoSuchProcess:
            pass
        self.owner_path.unlink(missing_ok=True)
        work_value = owner.get("work")
        if work_value:
            work = Path(work_value).resolve()
            if self.root in work.parents and work.name.startswith("session-"):
                (work / "config.yaml").unlink(missing_ok=True)

    def ensure(self, auto_update: bool = True, *, validate_start=True) -> None:
        if self.process is not None or self.benchmark_active or owned_core_running(self.root):
            raise CoreError("测速过程中禁止更新 Core")
        self.cleanup_orphan()
        if self.binary.exists() and not auto_update:
            self.version = self.read_version()
            return
        release = {}
        try:
            release = json.loads(download("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest", 1024 * 1024))
            if release.get("draft") or release.get("prerelease"):
                raise CoreError("拒绝非 Stable Core")
            metadata = self.root / "version.json"
            atomic_write_json(self.root / "update-check.json", {"latest": release["tag_name"], "checked_at": time.time(), "message": "已检查官方稳定版"})
            choice = self.root / "core-choice.json"
            if self.binary.exists() and choice.exists() and json.loads(choice.read_text()).get("version") == self.version_catalog()["current"]:
                self.version = self.read_version()
                self.update_status = "已检查更新，保留手动选择的内核版本"
                return
            if self.binary.exists() and metadata.exists() and json.loads(metadata.read_text()).get("version") == release["tag_name"]:
                self.version = self.read_version()
                self.update_status = "已检查更新，当前内核为最新稳定版"
                return
            machine = platform.machine().lower()
            arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
            prefix = f"mihomo-windows-{arch}" if os.name == "nt" else f"mihomo-linux-{arch}"
            preferred = f"{prefix}-compatible-{release['tag_name']}.zip" if os.name == "nt" and arch == "amd64" else f"{prefix}-{release['tag_name']}.{'zip' if os.name == 'nt' else 'gz'}"
            asset = next(item for item in release["assets"] if item["name"] == preferred)
            digest = asset.get("digest", "")
            if not digest.startswith("sha256:"):
                raise CoreError("官方 asset 缺少完整性摘要")
            cached = self.root / preferred
            if cached.exists() and hashlib.sha256(cached.read_bytes()).hexdigest() == digest[7:]:
                archive = cached.read_bytes()
            else:
                try:
                    archive = release_download(asset["browser_download_url"], digest[7:])
                except (OSError, CoreError):
                    gh = shutil.which("gh")
                    if not gh:
                        raise
                    result = subprocess.run([gh, "release", "download", release["tag_name"], "--repo", "MetaCubeX/mihomo",
                                             "--pattern", preferred, "--dir", str(self.root), "--clobber"],
                                            capture_output=True, timeout=120,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if result.returncode:
                        raise CoreError("官方 Core 下载失败")
                    archive = cached.read_bytes()
            if hashlib.sha256(archive).hexdigest() != digest[7:]:
                raise CoreError("官方 Core 摘要不匹配")
            if preferred.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(archive)) as package:
                    members = [name for name in package.namelist() if name.endswith(".exe")]
                    if len(members) != 1 or package.getinfo(members[0]).file_size > 150 * 1024 * 1024:
                        raise CoreError("Core ZIP 内容异常")
                    executable = package.read(members[0])
            else:
                executable = gzip.decompress(archive)
            staged = self.root / "mihomo.download"
            atomic_write_bytes(staged, executable)
            os.chmod(staged, 0o700)
            backup = self.root / "mihomo.backup"
            had_old = self.binary.exists()
            old_metadata = json.loads(metadata.read_text()) if metadata.exists() else {}
            if had_old:
                if not old_metadata.get("version"):
                    match = re.search(r"v\d+\.\d+\.\d+", self.read_version())
                    old_metadata["version"] = match.group() if match else "previous"
                atomic_write_bytes(backup, self.binary.read_bytes())
                os.chmod(backup, 0o700)
            os.replace(staged, self.binary)
            try:
                self.read_version()
                if validate_start:
                    self.start([], None)
                    self.controller.call("/version")
                    self.stop()
            except BaseException:
                self.stop()
                if had_old:
                    os.replace(backup, self.binary)
                else:
                    self.binary.unlink(missing_ok=True)
                raise
            if had_old:
                old_metadata["binary_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
                os.replace(backup, self.root / "mihomo.previous")
                atomic_write_json(self.root / "previous-version.json", old_metadata)
            atomic_write_json(metadata, {"version": release["tag_name"], "asset": preferred, "digest": digest, "binary_sha256": hashlib.sha256(executable).hexdigest()})
            for archive_path in [*self.root.glob("mihomo-*.zip"), *self.root.glob("mihomo-*.gz")]:
                archive_path.unlink(missing_ok=True)
            self.version = release["tag_name"]
            self.update_status = "内核已更新；上一版已保留，可在版本菜单中回退"
        except Exception:
            if not self.binary.exists():
                raise CoreError("无法安装官方 Stable Mihomo") from None
            self.version = self.read_version()
            self.update_status = "更新检查或安装未完成，保留可用内核；下次运行重新检查"
            atomic_write_json(self.root / "update-check.json", {"latest": release.get("tag_name", ""), "checked_at": time.time(), "message": self.update_status})
            if self.version_catalog()["update_required"]:
                raise CoreError("发现新内核但更新失败，已保留原版本；请重试更新或选择上一版后再测试") from None

    def read_version(self) -> str:
        result = subprocess.run([str(self.binary), "-v"], capture_output=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise CoreError("Core Version Check 失败")
        return result.stdout.decode(errors="replace").splitlines()[0][:100]

    def config(self, candidates: list[dict], profile) -> dict:
        names = [item["proxy_name"] for item in candidates]
        ports = self.controller.named_ports
        for name in names:
            if name not in ports:
                port = free_port()
                while port in {self.controller.mixed_port, int(self.controller.url.rsplit(":", 1)[1]), *ports.values()}:
                    port = free_port()
                ports[name] = port
        self.controller.named_ports = {name: ports[name] for name in names}
        dedicated = [{"name": f"proxybench-node-{index}", "type": "mixed", "listen": "127.0.0.1", "port": ports[name]}
                     for index, name in enumerate(names)]
        return {"mixed-port": 0, "bind-address": "127.0.0.1", "allow-lan": False,
                "listeners": [{"name": "proxybench-mixed", "type": "mixed", "listen": "127.0.0.1", "port": self.controller.mixed_port}, *dedicated],
                "mode": "rule", "unified-delay": True, "log-level": "silent", "external-controller": self.controller.url[7:],
                "secret": self.controller._secret, "tun": {"enable": False}, "ipv6": False,
                "profile": {"store-selected": False}, "dns": {"enable": False},
                "proxies": [(profile[item.get("profile_file", "default")] if isinstance(profile, dict) else profile)
                            .definition(item["ip"], item["proxy_name"]) for item in candidates] if profile else [],
                "proxy-groups": [{"name": "BENCHMARK-PROXY", "type": "select", "proxies": names or ["REJECT"]},
                                 {"name": "BENCHMARK-GROUP", "type": "select", "proxies": names or ["REJECT"]}],
                "rules": [*(f"IN-NAME,proxybench-node-{index},{name}" for index, name in enumerate(names)),
                          "IN-NAME,proxybench-mixed,BENCHMARK-PROXY", "MATCH,DIRECT"]}

    def start(self, candidates: list[dict], profile) -> None:
        self.stop()
        self.cleanup_orphan()
        mixed_port = free_port()
        controller_port = free_port()
        while controller_port == mixed_port:
            controller_port = free_port()
        self.controller = Controller(controller_port, secrets.token_urlsafe(32), mixed_port)
        self.work = self.root / f"session-{secrets.token_hex(8)}"
        self.work.mkdir(mode=0o700)
        config_path = self.work / "config.yaml"
        atomic_write_text(config_path, yaml.safe_dump(self.config(candidates, profile)))
        os.chmod(config_path, 0o600)
        self.process = subprocess.Popen([str(self.binary), "-d", str(self.work), "-f", str(config_path)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        atomic_write_json(self.owner_path, {"pid": self.process.pid, "created": psutil.Process(self.process.pid).create_time(),
                                           "work": str(self.work)})
        for _ in range(80):
            if self.process.poll() is not None:
                self.stop()
                raise CoreError("Mihomo 启动失败；请检查真实 Profile 的协议参数")
            try:
                version = self.controller.call("/version", timeout=0.2)
                self.version = version["version"]
                self.loaded = len(candidates)
                if candidates:
                    self.controller.verify([item["proxy_name"] for item in candidates])
                return
            except CoreError:
                time.sleep(0.1)
        self.stop()
        raise CoreError("Mihomo Health Check 超时")

    def load_batch(self, candidates: list[dict], profile) -> None:
        if len(candidates) > BATCH_SIZE:
            raise CoreError("一个内核每批最多加载 300 个候选")
        if self.process is None or self.process.poll() is not None:
            self.start(candidates, profile)
        else:
            payload = yaml.safe_dump(self.config(candidates, profile))
            self.controller.call("/configs?force=true", "PUT", {"payload": payload})
            self.controller.verify([item["proxy_name"] for item in candidates])
            self.loaded = len(candidates)

    def health(self) -> dict:
        alive = self.process is not None and self.process.poll() is None
        healthy = False
        if alive and self.controller:
            try:
                self.controller.call("/version", timeout=0.2)
                healthy = True
            except CoreError:
                pass
        return {"version": self.version, "status": "Healthy" if healthy else "Failed" if alive else "Stopped", "mode": "rule",
                "loaded_proxies": self.loaded if alive else 0, "controller_healthy": healthy}

    def clear_batch(self) -> None:
        """Unload only this owned core's candidates and close its batch connections."""
        if self.process is None or self.process.poll() is not None:
            return
        self.controller.call("/connections", "DELETE")
        self.controller.call("/configs?force=true", "PUT", {"payload": yaml.safe_dump(self.config([], None))})
        self.loaded = 0
        if self.work is not None:
            atomic_write_text(self.work / "config.yaml", yaml.safe_dump(self.config([], None)))

    def stop(self) -> None:
        owned = self.process is not None or self.work is not None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.work is not None:
            (self.work / "config.yaml").unlink(missing_ok=True)
            self.work = None
        if owned:
            self.owner_path.unlink(missing_ok=True)
        if self.controller:
            self.controller._secret = ""
        self.controller = None
        self.loaded = 0
