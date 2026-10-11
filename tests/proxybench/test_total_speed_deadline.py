from __future__ import annotations

import asyncio
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.proxybench.controller import Controller, RequestError
from core.proxybench.direct_benchmark import DirectBenchmark
from core.proxybench.settings import TCP_RULES
from core.proxybench.state import Control
from tests.proxybench.test_benchmark import pool


class TotalSpeedDeadlineTests(unittest.TestCase):
    def test_direct_location_does_not_hold_a_download_slot(self):
        second_download = None
        calls = []
        async def latency(candidate, **kwargs):
            return {**candidate, "key": f"{candidate['ip']}:{candidate['port']}", "measurement_mode": "tcp_tls", "latency_probe": "tcp", "status": "TCP Passed", "qualified": False,
                    "tcp_average_latency_ms": 100, "tcp_loss_percent": 0, "tcp_jitter_ms": 0, "tcp_rounds_ms": [100]*3}
        async def speed(nodes, *args, **kwargs):
            nonlocal second_download
            if second_download is None:
                second_download = asyncio.Event()
            calls.append(nodes[0].ip)
            if len(calls) == 2:
                second_download.set()
            nodes[0].speed_mbps = 10
            return nodes
        async def trace(node, **kwargs):
            await asyncio.wait_for(second_download.wait(), timeout=.15)
            return 200, {}, b"colo=FRA\n", 1
        with tempfile.TemporaryDirectory() as directory:
            bench = DirectBenchmark({**TCP_RULES, "speed_concurrency": 1}, Control(Path(directory)))
            bench.latency = AsyncMock(side_effect=latency)
            with patch("core.proxybench.direct_benchmark.test_speed", side_effect=speed), patch("core.proxybench.direct_benchmark._request", side_effect=trace):
                started = time.monotonic()
                result = bench.batch(pool(2), lambda row: None)
            self.assertLess(time.monotonic() - started, .1)
            self.assertTrue(all(r["qualified"] and r["geo_country"] == "DE" for r in result))
    def test_proxy_combined_connect_headers_and_body_cannot_restart_total_timeout(self):
        connection = Mock()
        connection.sock.getsockname.return_value = ("127.0.0.1", 4321)
        connection.connect.side_effect = lambda: time.sleep(.12)
        response = Mock(status=200)
        def headers():
            time.sleep(.12)
            return response
        connection.getresponse.side_effect = headers
        body = io.BytesIO(b"x" * 1000)
        def read(n):
            time.sleep(.12)
            return body.read(n)
        response.read.side_effect = read
        controller = Controller(1, "fixture", 2)
        controller.select = Mock()
        controller._connection_proof = Mock(return_value={"routing_proof": "connection-chain"})
        with patch("core.proxybench.controller.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaises(RequestError) as caught:
                controller.legacy_speed("PB-1", "https://speed.cloudflare.com/__down", timeout=.2,
                                        wanted_bytes=1000, maximum_download_seconds=1)
        self.assertEqual(caught.exception.cause, "TimeoutError")

    def test_direct_worker_rejects_total_timeout_and_continues_other_candidates(self):
        async def slow_speed(nodes, *args, **kwargs):
            await asyncio.sleep(.15)
            await asyncio.sleep(.15)
            nodes[0].speed_mbps = 100
            return nodes
        async def latency(candidate, **kwargs):
            return {**candidate, "key": f"{candidate['ip']}:{candidate['port']}", "measurement_mode": "tcp_tls", "latency_probe": "tcp", "status": "TCP Passed", "qualified": False,
                    "tcp_average_latency_ms": 100, "tcp_loss_percent": 0, "tcp_jitter_ms": 0, "tcp_rounds_ms": [100]*3}
        with tempfile.TemporaryDirectory() as directory:
            rules = {**TCP_RULES, "download_timeout_seconds": .2}
            bench = DirectBenchmark(rules, Control(Path(directory)))
            bench.latency = AsyncMock(side_effect=latency)
            with patch("core.proxybench.direct_benchmark.test_speed", side_effect=slow_speed), \
                    patch("core.proxybench.direct_benchmark._request", return_value=(200, {}, b"colo=FRA\n", 1)):
                started = time.monotonic()
                result = bench.batch(pool(2), lambda row: None)
            self.assertLess(time.monotonic() - started, .29)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(not row["qualified"] and row["status"] == "Rejected Speed" for row in result))
