from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlsplit

from core.speed_test import _accepted_speed_mbps
from core.tls_check import make_ssl_context

from .network_deadline import SocketDeadline


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
        self.named_ports = {}
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
        rules = self.call("/rules").get("rules", [])
        if not any(rule.get("type") == "InName" and rule.get("payload") == "proxybench-mixed"
                   and rule.get("proxy") == "BENCHMARK-PROXY" for rule in rules):
            raise RoutingError("Benchmark 入站规则缺失")
        for index, name in enumerate(names):
            if name in self.named_ports and not any(rule.get("type") == "InName" and rule.get("payload") == f"proxybench-node-{index}"
                                                   and rule.get("proxy") == name for rule in rules):
                raise RoutingError("独立节点入站规则不匹配，不能并发测速")

    def delay(self, name: str, url: str, expected: str, timeout: float) -> dict:
        query = urlencode({"url": url, "timeout": int(timeout * 1000), "expected": expected})
        try:
            result = self.call(f"/proxies/{quote(name, safe='')}/delay?{query}", timeout=timeout + 2)
            delay = float(result["delay"])
            if delay < 0 or delay >= 65535:
                raise ValueError
            metadata = self.call(f"/proxies/{quote(name, safe='')}", timeout=timeout + 2)
            if metadata.get("extra", {}).get(url, {}).get("alive") is not True:
                raise ValueError  # A nonzero core delay alone does not prove the expected HTTP status.
            return {"success": True, "latency_ms": delay, "selected_proxy": name,
                    "destination": url, "routing_proof": "specified-proxy-controller-api", "expected_status": expected}
        except (CoreError, ValueError, KeyError, TypeError):
            return {"success": False, "latency_ms": None, "selected_proxy": name,
                    "destination": url, "error": "Proxy Failed", "expected_status": expected}

    def select(self, name: str) -> None:
        self.call("/proxies/BENCHMARK-PROXY", "PUT", {"name": name})
        if self.call("/proxies/BENCHMARK-PROXY").get("now") != name:
            raise RoutingError("Selected Proxy 不匹配")

    def site_probe(self, name: str, url: str, expected: str, timeout: float) -> dict:
        """Exactly one request through a named rule inbound, with a total deadline."""
        destination = urlsplit(url)
        if destination.scheme != "https" or destination.username or destination.password or name not in self.named_ports:
            raise RoutingError("网站测试必须使用独立候选入站和 HTTPS")
        trace = destination.path == "/cdn-cgi/trace"
        path = (destination.path or "/") + ("?" + destination.query if destination.query else "")
        connection = http.client.HTTPSConnection("127.0.0.1", self.named_ports[name], timeout=timeout, context=make_ssl_context(True, "TLSv1.2"))
        connection.set_tunnel(destination.hostname, destination.port or 443)
        end = time.monotonic() + timeout
        proof = {}
        stage = "连接与 TLS"
        try:
            with SocketDeadline(connection, timeout) as deadline:
                connection.connect()
                transport = connection.sock
                deadline.watch(transport)
                stage = "指定代理路由验证"
                proof = self._connection_proof(name, transport.getsockname()[1], timeout=max(.001, min(1.0, timeout, end - time.monotonic())))
                deadline.check()
                transport.settimeout(max(.001, end - time.monotonic()))
                stage = "网站响应"
                started = time.perf_counter()
                connection.request("GET" if trace else "HEAD", path, headers={"Host": destination.hostname, "User-Agent": "Go-http-client/1.1", "Connection": "close"})
                response = connection.getresponse()
                latency = (time.perf_counter() - started) * 1000
                status = response.status
                body = response.read(65537) if trace else b""
                response.close()
                deadline.check()
                if time.monotonic() > end:
                    raise TimeoutError
                bounds = [int(v) for v in expected.split("-")]
                passed = bounds[0] <= status <= bounds[-1] and (not trace or len(body) <= 65536 and b"colo=" in body)
                return {**proof, "success": passed, "latency_ms": latency if passed else None, "http_status": status,
                        "destination": url, "expected_status": expected, "request_count": 1,
                        "error": "" if passed else "网站状态或响应正文不符合要求"}
        except (OSError, ValueError, http.client.HTTPException, CoreError):
            return {**proof, "success": False, "latency_ms": None, "destination": url, "expected_status": expected,
                    "error": "候选代理连接或网站响应失败／超时", "failure_stage": stage, "request_count": 1}
        finally:
            connection.close()

    def request_port(self, name: str) -> int:
        if name in self.named_ports:
            return self.named_ports[name]
        self.select(name)
        return self.mixed_port

    def _connection_proof(self, name: str, source_port: int, *, timeout: float = 1.0) -> dict:
        deadline = time.monotonic() + timeout
        for _ in range(8):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for connection in (self.call("/connections", timeout=min(.2, remaining, timeout)).get("connections") or []):
                if str(connection.get("metadata", {}).get("sourcePort")) != str(source_port):
                    continue
                chains = connection.get("chains", [])
                if name not in chains or "DIRECT" in chains or connection.get("rule") != "InName":
                    raise RoutingError("Benchmark 请求路由无效")
                return {"routing_proof": "connection-chain", "selected_proxy": name, "chains": chains,
                        "rule": connection["rule"], "rule_payload": connection.get("rulePayload", "")}
            time.sleep(max(0, min(.025, deadline - time.monotonic())))
        raise RoutingError("无法确认 Benchmark 连接实际出站")

    def request(self, name: str, url: str, *, timeout: float, wanted_bytes: int | None = None) -> dict:
        curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
        if not curl:
            raise CoreError("需要 Windows 内置 curl 或运行包内的 curl")
        destination = urlsplit(url)
        if destination.scheme != "https" or destination.username or destination.password:
            raise ValueError("Benchmark endpoint 必须为 HTTPS")
        proxy_port = self.request_port(name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            source_port = sock.getsockname()[1]
        fd, temporary = tempfile.mkstemp(prefix="proxybench-body-")
        os.close(fd)
        process = None
        proof = {}
        try:
            command = [curl, "--disable", "--silent", "--show-error", "--noproxy", "", "--proxy",
                       f"http://127.0.0.1:{proxy_port}", "--local-port", str(source_port),
                       "--connect-timeout", str(min(timeout, 10)), "--max-time", str(timeout),
                       "--max-filesize", str(wanted_bytes or 65536), "--output", temporary,
                       "--write-out", "%{http_code} %{size_download} %{time_starttransfer} %{time_total}", url]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = time.monotonic() + timeout
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    proof = self._connection_proof(name, source_port, timeout=max(.001, min(1.0, deadline - time.monotonic())))
                    break
                except RoutingError:
                    continue
            stdout, _stderr = process.communicate(timeout=max(.001, deadline - time.monotonic()))
            if time.monotonic() > deadline:
                raise RequestError("Proxy Request Deadline", os.path.getsize(temporary), "TimeoutError", proof)
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
                    "seconds": elapsed, "latency_ms": ttfb * 1000, "speed_mbps": received * 8 / elapsed / 1_000_000 if wanted_bytes else None,
                    "body": open(temporary, "rb").read() if wanted_bytes is None else b""}
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.unlink(temporary)

    def legacy_speed(self, name: str, url: str, *, timeout: float, wanted_bytes: int,
                     maximum_download_seconds: float = 7.0, minimum_completion_ratio: float = 0.95) -> dict:
        """The original package's body-timed speed algorithm, over the named proxy."""
        destination = urlsplit(url)
        if destination.scheme != "https" or destination.username or destination.password:
            raise ValueError("Benchmark endpoint 必须为 HTTPS")
        proxy_port = self.request_port(name)
        connection = http.client.HTTPSConnection("127.0.0.1", proxy_port, timeout=timeout,
                                                 context=make_ssl_context(True, "TLSv1.2"))
        connection.set_tunnel(destination.hostname, destination.port or 443)
        stage = "Connect/TLS"
        received = 0
        proof = {}
        try:
            with SocketDeadline(connection, timeout) as connect_budget:
                connection.connect()
                transport = connection.sock
                connect_budget.watch(transport)
                stage = "Routing Verification"
                proof = self._connection_proof(name, transport.getsockname()[1], timeout=min(1.0, timeout))
                connect_budget.check()
            transport.settimeout(timeout)
            path = destination.path or "/"
            if destination.query:
                path += "?" + destination.query
            stage = "HTTP Headers"
            headers = {"Host": destination.hostname,
                               "User-Agent": "Noode-CG-ProxyBench/1.0.1", "Accept": "application/octet-stream",
                               "Accept-Encoding": "identity", "Connection": "close"}
            if destination.hostname != "speed.cloudflare.com":
                headers["Range"] = f"bytes=0-{wanted_bytes - 1}"
            with SocketDeadline(connection, timeout) as header_budget:
                header_budget.watch(transport)
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                header_budget.check()
            if response.status not in {200, 206}:
                raise ValueError("Benchmark endpoint 状态异常")
            if response.status == 206:
                content_range = re.fullmatch(r"bytes 0-(\d+)/(\d+|\*)", response.getheader("Content-Range", ""))
                if not content_range or int(content_range[1]) != wanted_bytes - 1:
                    raise ValueError("测速字节范围不匹配")
            stage = "HTTP Body"
            started = time.perf_counter()
            deadline = started + maximum_download_seconds
            with SocketDeadline(connection, maximum_download_seconds) as body_budget:
                body_budget.watch(transport)
                while received < wanted_bytes:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        raise TimeoutError
                    transport.settimeout(min(timeout, remaining))
                    chunk = response.read(min(65536, wanted_bytes - received))
                    if not chunk:
                        break
                    received += len(chunk)
                body_budget.check()
            elapsed = max(time.perf_counter() - started, 0.001)
            if elapsed > maximum_download_seconds:
                raise TimeoutError
            speed = _accepted_speed_mbps(received, wanted_bytes, elapsed, minimum_completion_ratio)
            if speed is None:
                raise ValueError("测速正文不完整")
            return {**proof, "success": True, "http_status": response.status,
                    "method": "legacy-proxy-speed", "destination": url, "wanted_bytes": wanted_bytes,
                    "received_bytes": received, "completion_ratio": received / wanted_bytes,
                    "minimum_completion_ratio": minimum_completion_ratio,
                    "seconds": elapsed, "speed_mbps": speed}
        except Exception as exc:
            raise RequestError(stage, received, type(exc).__name__, proof) from None
        finally:
            connection.close()
