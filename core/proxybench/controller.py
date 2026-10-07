from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit


class CoreError(RuntimeError):
    pass


class RoutingError(CoreError):
    pass


class RequestError(RuntimeError):
    def __init__(self, stage: str, received: int, cause: str, proof: dict) -> None:
        super().__init__("Proxy Request Failed")
        self.stage = stage
        self.received = received
        self.cause = cause
        self.proof = proof


class Controller:
    def __init__(self, port: int, secret: str, mixed_port: int) -> None:
        self.url = f"http://127.0.0.1:{port}"
        self._secret = secret
        self.mixed_port = mixed_port
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path: str, method: str = "GET", data=None, timeout: float = 10):
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.url + path, data=body, method=method,
                                         headers={"Authorization": f"Bearer {self._secret}", "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content = response.read(4 * 1024 * 1024)
                return json.loads(content) if content else {}
        except (OSError, ValueError, urllib.error.URLError):
            raise CoreError("Mihomo Controller 请求失败") from None

    def verify(self, names: list[str]) -> None:
        if self.call("/configs").get("mode") != "rule":
            raise RoutingError("Mihomo 不是 Rule Mode")
        proxies = self.call("/proxies").get("proxies", {})
        for name in names:
            if name not in proxies or proxies[name].get("type", "").lower() in {"direct", "reject", "selector"}:
                raise RoutingError("Candidate 未加载为独立真实代理")
        group = proxies.get("BENCHMARK-PROXY", {})
        if set(group.get("all", [])) != set(names):
            raise RoutingError("Benchmark group 包含错误节点或 fallback")
        if not any(rule.get("type") == "InName" and rule.get("payload") == "proxybench-mixed"
                   and rule.get("proxy") == "BENCHMARK-PROXY" for rule in self.call("/rules").get("rules", [])):
            raise RoutingError("Benchmark 入站规则缺失")

    def delay(self, name: str, url: str, expected: str, timeout: float) -> dict:
        query = urlencode({"url": url, "timeout": int(timeout * 1000), "expected": expected})
        try:
            result = self.call(f"/proxies/{quote(name, safe='')}/delay?{query}", timeout=timeout + 2)
            delay = float(result["delay"])
            if delay < 0 or delay >= 65535:
                raise ValueError
            return {"success": True, "latency_ms": delay, "selected_proxy": name,
                    "destination": url, "routing_proof": "specified-proxy-controller-api", "expected_status": expected}
        except (CoreError, ValueError, KeyError, TypeError):
            return {"success": False, "latency_ms": None, "selected_proxy": name,
                    "destination": url, "error": "Proxy Failed", "expected_status": expected}

    def select(self, name: str) -> None:
        self.call("/proxies/BENCHMARK-PROXY", "PUT", {"name": name})
        if self.call("/proxies/BENCHMARK-PROXY").get("now") != name:
            raise RoutingError("Selected Proxy 不匹配")

    def _connection_proof(self, name: str, source_port: int) -> dict:
        for _ in range(8):
            for connection in (self.call("/connections").get("connections") or []):
                if str(connection.get("metadata", {}).get("sourcePort")) != str(source_port):
                    continue
                chains = connection.get("chains", [])
                if name not in chains or "DIRECT" in chains or connection.get("rule") != "InName":
                    raise RoutingError("Benchmark 请求路由无效")
                return {"routing_proof": "connection-chain", "selected_proxy": name, "chains": chains,
                        "rule": connection["rule"], "rule_payload": connection.get("rulePayload", "")}
            time.sleep(0.025)
        raise RoutingError("无法确认 Benchmark 连接实际出站")

    def request(self, name: str, url: str, *, timeout: float, wanted_bytes: int | None = None) -> dict:
        curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
        if not curl:
            raise CoreError("需要 Windows 内置 curl 或运行包内的 curl")
        destination = urlsplit(url)
        if destination.scheme != "https" or destination.username or destination.password:
            raise ValueError("Benchmark endpoint 必须为 HTTPS")
        self.select(name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            source_port = sock.getsockname()[1]
        fd, temporary = tempfile.mkstemp(prefix="proxybench-body-")
        os.close(fd)
        process = None
        proof = {}
        try:
            command = [curl, "--disable", "--silent", "--show-error", "--noproxy", "", "--proxy",
                       f"http://127.0.0.1:{self.mixed_port}", "--local-port", str(source_port),
                       "--connect-timeout", str(min(timeout, 10)), "--max-time", str(timeout),
                       "--max-filesize", str(wanted_bytes or 65536), "--output", temporary,
                       "--write-out", "%{http_code} %{size_download} %{time_starttransfer} %{time_total}", url]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + timeout
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    proof = self._connection_proof(name, source_port)
                    break
                except RoutingError:
                    continue
            stdout, _stderr = process.communicate(timeout=max(0.1, deadline - time.monotonic()) + 1)
            if not proof:
                raise RoutingError("请求缺少指定 Candidate 的连接链证据")
            values = stdout.decode("ascii", errors="replace").strip().split()
            if process.returncode or len(values) != 4:
                raise RequestError("Proxy Download", os.path.getsize(temporary),
                                   "TimeoutError" if process.returncode == 28 else "CurlError", proof)
            status, received, ttfb, total = int(values[0]), int(float(values[1])), float(values[2]), float(values[3])
            if status != 200 or (wanted_bytes is not None and received != wanted_bytes):
                raise RequestError("HTTP Body", received, "UnexpectedStatusOrIncompleteBody", proof)
            elapsed = max(total - ttfb, 0.000001)
            return {**proof, "success": True, "http_status": status, "received_bytes": received,
                    "seconds": elapsed, "speed_mbps": received * 8 / elapsed / 1_000_000 if wanted_bytes else None,
                    "body": open(temporary, "rb").read() if wanted_bytes is None else b""}
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.unlink(temporary)

    def _request_python(self, name: str, url: str, *, timeout: float, wanted_bytes: int | None = None) -> dict:
        """Serial caller owns selection. Standard library HTTPS through HTTP CONNECT only."""
        destination = urlsplit(url)
        if destination.scheme != "https" or destination.username or destination.password:
            raise ValueError("Benchmark endpoint 必须为 HTTPS")
        self.select(name)
        connection = http.client.HTTPSConnection("127.0.0.1", self.mixed_port, timeout=timeout,
                                                 context=ssl.create_default_context())
        connection.set_tunnel(destination.hostname, destination.port or 443)
        deadline = time.monotonic() + timeout
        stage = "Connect/TLS"
        received = 0
        proof = {}
        try:
            connection.connect()
            transport = connection.sock
            stage = "Routing Verification"
            proof = self._connection_proof(name, transport.getsockname()[1])
            transport.settimeout(max(0.001, deadline - time.monotonic()))
            path = destination.path or "/"
            if destination.query:
                path += "?" + destination.query
            stage = "HTTP Headers"
            connection.request("GET", path, headers={"User-Agent": "Noode-CG-ProxyBench/1.0", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Benchmark endpoint 状态异常")
            stage = "HTTP Body"
            chunks = []
            limit = wanted_bytes if wanted_bytes is not None else 65536
            started = time.perf_counter()
            while received < limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                transport.settimeout(remaining)
                chunk = response.read(min(65536, limit - received))
                if not chunk:
                    break
                received += len(chunk)
                if wanted_bytes is None:
                    chunks.append(chunk)
            elapsed = max(time.perf_counter() - started, 0.000001)
            if wanted_bytes is not None and received != wanted_bytes:
                raise ValueError("测速正文不完整")
            return {**proof, "success": True, "received_bytes": received, "seconds": elapsed,
                    "speed_mbps": received * 8 / elapsed / 1_000_000 if wanted_bytes else None,
                    "body": b"".join(chunks) if wanted_bytes is None else b""}
        except Exception as exc:
            raise RequestError(stage, received, type(exc).__name__, proof) from None
        finally:
            connection.close()
