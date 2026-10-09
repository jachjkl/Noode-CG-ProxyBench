from __future__ import annotations

import asyncio
import http.client
import tempfile
import threading
import time
import unittest
from pathlib import Path
from socketserver import BaseRequestHandler, ThreadingTCPServer
from unittest.mock import AsyncMock, Mock, patch

from core.proxybench.controller import Controller, RequestError, RoutingError
from core.proxybench.direct_benchmark import DirectBenchmark
from core.proxybench.observation import Observation
from core.proxybench.settings import TCP_RULES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import pool


class TrickleHandler(BaseRequestHandler):
    def handle(self):
        def headers():
            data = b""
            while not data.endswith(b"\r\n\r\n"):
                chunk = self.request.recv(1)
                if not chunk:
                    return False
                data += chunk
            return True
        try:
            if not headers():
                return
            self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if not headers():
                return
            self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\ncolo=SJC\n")
            for _ in range(200):
                self.request.sendall(b"x")
                time.sleep(.01)
        except OSError:
            pass


class BoundedProbeTests(unittest.TestCase):
    def test_route_confirmation_cannot_use_eight_default_ten_second_waits(self):
        controller = Controller(1, "fixture", 2)
        timeouts = []
        def slow_call(path, *args, timeout=10, **kwargs):
            timeouts.append(timeout)
            time.sleep(min(.02, timeout))
            return {"connections": []}
        controller.call = slow_call
        start = time.monotonic()
        with self.assertRaises(RoutingError):
            controller._connection_proof("PB-1", 1234, timeout=.05)
        self.assertLess(time.monotonic() - start, .2)
        self.assertTrue(all(timeout <= .05 for timeout in timeouts))

    def test_single_website_probe_sends_exactly_one_request_without_warmup_or_delay_fallback(self):
        controller = Controller(1, "fixture", 2)
        controller.named_ports = {"PB-1": 3456}
        controller._connection_proof = Mock(return_value={"routing_proof": "connection-chain", "selected_proxy": "PB-1"})
        controller.delay = Mock(side_effect=AssertionError("no second probe"))
        connection = Mock()
        connection.sock.getsockname.return_value = ("127.0.0.1", 1234)
        connection.getresponse.return_value.status = 200
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            result = controller.site_probe("PB-1", "https://github.com/", "200-399", .5)
        self.assertTrue(result["success"])
        self.assertEqual(result["request_count"], 1)
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.args[0], "HEAD")
        controller.delay.assert_not_called()
        self.assertLessEqual(controller._connection_proof.call_args.kwargs["timeout"], .5)

    def test_trickling_trace_and_download_cannot_keep_worker_alive_past_total_budget(self):
        with ThreadingTCPServer(("127.0.0.1", 0), TrickleHandler) as server:
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                controller = Controller(1, "fixture", server.server_address[1])
                controller.named_ports = {"PB-1": server.server_address[1]}
                controller._connection_proof = Mock(return_value={"routing_proof": "connection-chain", "selected_proxy": "PB-1"})
                def connect(host, port, **kwargs):
                    return http.client.HTTPConnection(host, port, timeout=kwargs["timeout"])
                with patch("core.proxybench.controller.http.client.HTTPSConnection", side_effect=connect):
                    start = time.monotonic()
                    result = controller.site_probe("PB-1", "https://www.cloudflare.com/cdn-cgi/trace", "200", .08)
                    self.assertFalse(result["success"])
                    self.assertLess(time.monotonic() - start, .5)
                    start = time.monotonic()
                    with self.assertRaises(RequestError):
                        controller.legacy_speed("PB-1", "https://example.test/", timeout=.2, maximum_download_seconds=.08, wanted_bytes=1000)
                    self.assertLess(time.monotonic() - start, .5)
            finally:
                server.shutdown()
                thread.join(2)

    def test_unresponsive_selected_direct_probe_times_out_all_three_attempts_and_never_qualifies(self):
        async def ignored_timeout(*args):
            await asyncio.Event().wait()
        for tls in (0, 1):
            with self.subTest(tls=tls), tempfile.TemporaryDirectory() as folder:
                rules = {**TCP_RULES, "tls_enabled": tls, "tcp_timeout_seconds": .02, "tls_timeout_seconds": .02}
                with patch("core.proxybench.direct_benchmark.tcp_probe", AsyncMock(side_effect=ignored_timeout)), \
                     patch("core.proxybench.direct_benchmark.tls_probe", AsyncMock(side_effect=ignored_timeout)):
                    start = time.monotonic()
                    result = asyncio.run(DirectBenchmark(rules, Control(Path(folder))).latency(pool(1)[0]))
                self.assertLess(time.monotonic() - start, .5)
                self.assertEqual(result["tls_rounds_ms" if tls else "tcp_rounds_ms"], [None] * 3)
                self.assertFalse(result["qualified"])

    def test_progress_updates_are_not_starved_by_large_completion_queue(self):
        progress = []
        completed = []
        observer = Observation(lambda **values: progress.append(len(completed)), completed.append)
        for i in range(80):
            observer.completed({"key": str(i)})
        observer.update(_force=True, stage="working")
        with observer:
            pass
        self.assertEqual(len(completed), 80)
        self.assertTrue(progress)
        self.assertLessEqual(progress[0], 8)
