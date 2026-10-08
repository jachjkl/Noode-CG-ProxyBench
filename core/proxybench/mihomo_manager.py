from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import platform
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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def download(url: str, limit: int = 80 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Noode-CG-ProxyBench/1.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise CoreError("Mihomo 下载超过上限")
    return data


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

    def ensure(self, auto_update: bool = True) -> None:
        if self.process is not None or self.benchmark_active:
            raise CoreError("测速过程中禁止更新 Core")
        self.cleanup_orphan()
        if self.binary.exists() and not auto_update:
            self.version = self.read_version()
            return
        try:
            release = json.loads(download("https://api.github.com/repos/MetaCubeX/mihomo/releases/latest", 1024 * 1024))
            if release.get("draft") or release.get("prerelease"):
                raise CoreError("拒绝非 Stable Core")
            metadata = self.root / "version.json"
            if self.binary.exists() and metadata.exists() and json.loads(metadata.read_text()).get("version") == release["tag_name"]:
                self.version = self.read_version()
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
                    archive = download(asset["browser_download_url"])
                except OSError:
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
            if had_old:
                atomic_write_bytes(backup, self.binary.read_bytes())
                os.chmod(backup, 0o700)
            os.replace(staged, self.binary)
            try:
                self.read_version()
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
            atomic_write_json(metadata, {"version": release["tag_name"], "asset": preferred, "digest": digest})
            backup.unlink(missing_ok=True)
            self.version = release["tag_name"]
        except Exception:
            if not self.binary.exists():
                raise CoreError("无法安装官方 Stable Mihomo") from None
            self.version = self.read_version()

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
        if len(candidates) > 100:
            raise CoreError("一个 Core 最多加载 100 个 Candidate")
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
