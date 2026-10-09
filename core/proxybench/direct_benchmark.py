"""Three consecutive TCP/TLS measurements using the original package's direct probes."""
from __future__ import annotations

import asyncio
import copy
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from core.async_utils import run_worker_pool
from core.http_check import _parse_trace, _request
from core.models import NodeResult
from core.speed_test import test_speed
from core.tcp_scan import _probe_once as tcp_probe
from core.tls_check import _probe_once as tls_probe
from core.tls_check import make_ssl_context

from .settings import validate_tcp_rules


def summarize(values: list[float | None]) -> tuple[float | None, float, float]:
    successful = [value for value in values if value is not None]
    return (statistics.fmean(successful) if successful else None,
            statistics.pstdev(successful) if successful else 0.0,
            100 * (len(values) - len(successful)) / len(values) if values else 100.0)


def direct_failure(record: dict, rules: dict, *, check_tls=True, check_download=True) -> str:
    if record.get("tcp_average_latency_ms") is None or record["tcp_average_latency_ms"] > rules["max_tcp_average_latency_ms"]:
        return "Rejected TCP"
    if record.get("tcp_loss_percent", 100) > rules["max_loss_percent"] or record.get("tcp_jitter_ms", math.inf) > rules["max_jitter_ms"]:
        return "Rejected TCP"
    if check_tls and rules["tls_enabled"]:
        if len(record.get("tls_rounds_ms", [])) != 3 or record.get("tls_average_latency_ms") is None:
            return "Rejected TLS"
        if record.get("tls_loss_percent", 100) > rules["max_loss_percent"] or record["tls_average_latency_ms"] > rules["max_tls_average_latency_ms"] or record.get("tls_jitter_ms", math.inf) > rules["max_jitter_ms"]:
            return "Rejected TLS"
    if check_download and (not record.get("download_measurement", {}).get("success") or record.get("download_mbps", 0) < rules["min_download_mbps"]):
        return "Rejected Speed"
    return ""


class DirectManager:
    version = "TCP／TLS 直连引擎"
    benchmark_active = False

    def __init__(self):
        self.loaded = 0

    def ensure(self, _auto_update=False):
        pass

    def health(self):
        return {"version": self.version, "mode": "direct", "status": "Healthy", "loaded_proxies": 0, "controller_healthy": False}

    def stop(self):
        self.loaded = 0


def direct_profile():
    return SimpleNamespace(port=443, fingerprint="direct-tcp-tls-no-proxy-v1")


class DirectBenchmark:
    def __init__(self, rules: dict, control, update=None):
        self.rules = validate_tcp_rules(rules)
        self.control = control
        self.update = update or (lambda **_: None)
        self.context = make_ssl_context(True, "TLSv1.2")
        path = Path(__file__).with_name("colo-locations.json")
        self.locations = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def tcp(self, candidate: dict) -> dict:
        record = {**copy.deepcopy(candidate), "measurement_mode": "tcp_tls", "key": f"{candidate['ip']}:{candidate['port']}",
                  "rules": self.rules, "qualified": False, "tcp_rounds_ms": [], "tls_rounds_ms": []}
        node = NodeResult(ip=candidate["ip"], port=candidate["port"])
        for _ in range(3):
            await self.control.async_checkpoint()
            try:
                value = await tcp_probe(node, self.rules["tcp_timeout_seconds"])
            except (TimeoutError, OSError):
                value = None
            record["tcp_rounds_ms"].append(value)
        average, jitter, loss = summarize(record["tcp_rounds_ms"])
        record.update(tcp_average_latency_ms=average, tcp_jitter_ms=jitter, tcp_loss_percent=loss,
                      tcp_success_count=sum(x is not None for x in record["tcp_rounds_ms"]),
                      entry_connected=average is not None, entry_latency_ms=average, entry_method="three-consecutive-direct-tcp-connects")
        record["status"] = direct_failure(record, self.rules, check_tls=False, check_download=False) or "TCP Passed"
        return record

    async def screen(self, candidates: list[dict], completed) -> list[dict]:
        async def worker(row):
            record = await self.tcp(row)
            completed(record)
            return record
        return await run_worker_pool(candidates, worker, self.rules["tcp_concurrency"])

    def batch(self, candidates: list[dict], completed, *, reuse_tcp=True) -> list[dict]:
        return asyncio.run(self._batch(candidates, completed, reuse_tcp=reuse_tcp))

    async def _batch(self, candidates: list[dict], completed, *, reuse_tcp=True) -> list[dict]:
        speed_slots = asyncio.Semaphore(self.rules["speed_concurrency"])
        tls_slots = asyncio.Semaphore(self.rules["tls_concurrency"])
        records = {f"{row['ip']}:{row['port']}": {**copy.deepcopy(row), "measurement_mode": "tcp_tls", "status": "TCP Testing"} for row in candidates}

        def show(record, stage):
            records[record["key"]] = record
            record["status"] = stage
            self.update(stage=stage, candidates=list(records.values()), status="Running")

        async def worker(candidate):
            if reuse_tcp and len(candidate.get("tcp_rounds_ms", [])) == 3:
                record = {**copy.deepcopy(candidate), "rules": self.rules, "qualified": False, "key": f"{candidate['ip']}:{candidate['port']}"}
            else:
                record = await self.tcp(candidate)
            node = NodeResult(ip=record["ip"], port=record["port"])
            failure = direct_failure(record, self.rules, check_tls=False, check_download=False)
            record.update(tls_enabled=bool(self.rules["tls_enabled"]))
            if not failure and self.rules["tls_enabled"]:
                show(record, "TLS Testing")
                values = []
                async with tls_slots:
                    for _ in range(3):
                        await self.control.async_checkpoint()
                        try:
                            value, _version, _cipher = await tls_probe(node, "www.cloudflare.com", self.context, self.rules["tls_timeout_seconds"])
                        except (TimeoutError, OSError):
                            value = None
                        values.append(value)
                average, jitter, loss = summarize(values)
                record.update(tls_rounds_ms=values, tls_average_latency_ms=average, tls_jitter_ms=jitter, tls_loss_percent=loss)
                failure = direct_failure(record, self.rules, check_download=False)
            record["tls_passed"] = not failure
            if not failure:
                show(record, "Direct Speed Testing")
                async with speed_slots:
                    await self.control.async_checkpoint()
                    await test_speed([node], {"enabled": True, "candidates": 1, "domain": "speed.cloudflare.com",
                                             "path": f"/__down?bytes={self.rules['download_bytes']}", "bytes_per_test": self.rules["download_bytes"],
                                             "timeout_seconds": self.rules["download_timeout_seconds"], "maximum_download_seconds": self.rules["maximum_download_seconds"],
                                             "minimum_completion_ratio": self.rules["minimum_completion_ratio"], "minimum_mbps": self.rules["min_download_mbps"],
                                             "concurrency": 1}, user_agent="Noode-CG-ProxyBench/1.2")
                record.update(download_mbps=node.speed_mbps or 0.0,
                              download_measurement={**node.probe_results.get("speed", {}), "success": node.speed_mbps is not None,
                                                    "routing_proof": "direct-pinned-candidate", "destination": f"{node.ip}:{node.port}", "host": "speed.cloudflare.com"})
                failure = direct_failure(record, self.rules)
            if not failure:
                show(record, "Direct Location")
                try:
                    await self.control.async_checkpoint()
                    status, headers, body, _ttfb = await _request(node, domain="www.cloudflare.com", path="/cdn-cgi/trace", context=self.context,
                                                                 timeout=self.rules["tls_timeout_seconds"], user_agent="Noode-CG-ProxyBench/1.2")
                    trace = _parse_trace(body)
                    colo = trace.get("colo", "").upper()
                    location = self.locations.get(colo, {})
                    country = location.get("country", "") if status == 200 else ""
                    record.update(colo=colo, geo_country=country, city=location.get("city", ""), geo_verified=bool(country), geo_conflict=False,
                                  jp_qualified=country == "JP", geo_method="cloudflare-edge-colo", cf_ray=headers.get("cf-ray", ""))
                except (TimeoutError, OSError, ValueError, EOFError):
                    record.update(geo_country="", geo_verified=False, geo_conflict=False, jp_qualified=False)
            record.update(qualified=not failure, status=failure or "Qualified", tested_at=datetime.now(UTC).isoformat())
            records[record["key"]] = record
            completed(record)
            self.update(candidates=list(records.values()))
            return record

        return await run_worker_pool(candidates, worker, max(self.rules["tls_concurrency"], self.rules["speed_concurrency"]))
