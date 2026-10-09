"""Exclusive TCPing or TLS, then the original direct download probe per batch."""
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

from .observation import Observation
from .settings import validate_tcp_rules


def selected_probe(rules: dict) -> str:
    # The legacy numeric setting selects a method, never an additional gate.
    return "tls" if rules.get("tls_enabled") else "tcp"


def summarize(values: list[float | None]) -> tuple[float | None, float, float]:
    successful = [value for value in values if value is not None]
    return (statistics.fmean(successful) if successful else None,
            statistics.pstdev(successful) if successful else 0.0,
            100 * (len(values) - len(successful)) / len(values) if values else 100.0)


def direct_failure(record: dict, rules: dict, *, check_tls=True, check_download=True) -> str:
    probe = selected_probe(rules)
    if record.get("latency_probe", probe) != probe:
        return "Retest Required"
    average = record.get(f"{probe}_average_latency_ms")
    if (average is None or average > rules[f"max_{probe}_average_latency_ms"] or
            record.get(f"{probe}_loss_percent", 100) > rules["max_loss_percent"] or
            record.get(f"{probe}_jitter_ms", math.inf) > rules["max_jitter_ms"]):
        return f"Rejected {probe.upper()}"
    if check_download and (not record.get("download_measurement", {}).get("success") or
                           record.get("download_mbps", 0) < rules["min_download_mbps"]):
        return "Rejected Speed"
    return ""


class DirectManager:
    version = "TCPing／TLS 二选一直连引擎"
    benchmark_active = False

    def __init__(self):
        self.loaded = 0
        self.updater = None

    def ensure(self, _auto_update=False):
        if self.updater is not None:
            self.updater.ensure(True, validate_start=False)

    def health(self):
        return {"version": self.version, "mode": "direct", "status": "Healthy", "loaded_proxies": 0, "controller_healthy": False}

    def stop(self):
        self.loaded = 0


def direct_profile():
    return SimpleNamespace(port=443, fingerprint="direct-tcp-tls-no-proxy-v1")


class DirectBenchmark:
    def __init__(self, rules: dict, control, update=None, *, domain="www.cloudflare.com"):
        self.rules = validate_tcp_rules(rules)
        self.control = control
        self.update = update or (lambda **_: None)
        self.domain = domain
        self.probe = selected_probe(self.rules)
        self.context = make_ssl_context(True, "TLSv1.2")
        path = Path(__file__).with_name("colo-locations.json")
        self.locations = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def tcp(self, candidate: dict) -> dict:
        return await self.latency(candidate, probe="tcp")

    async def latency(self, candidate: dict, *, probe=None, progress=None) -> dict:
        probe = probe or self.probe
        record = {**copy.deepcopy(candidate), "measurement_mode": "tcp_tls", "latency_probe": probe,
                  "latency_domain": self.domain if probe == "tls" else "", "key": f"{candidate['ip']}:{candidate['port']}",
                  "rules": self.rules, "qualified": False, "tcp_rounds_ms": [], "tls_rounds_ms": [],
                  "tls_enabled": probe == "tls", "status": f"{probe.upper()} Testing"}
        node = NodeResult(ip=candidate["ip"], port=candidate["port"])
        values = []
        for _ in range(3):
            await self.control.async_checkpoint()
            try:
                if probe == "tcp":
                    value = await tcp_probe(node, self.rules["tcp_timeout_seconds"])
                else:
                    value, _version, _cipher = await tls_probe(node, self.domain, self.context, self.rules["tls_timeout_seconds"])
            except (TimeoutError, OSError):
                value = None
            values.append(value)
            record[f"{probe}_rounds_ms"] = list(values)
            if progress:
                progress(record)
        average, jitter, loss = summarize(values)
        record.update({f"{probe}_average_latency_ms": average, f"{probe}_jitter_ms": jitter,
                       f"{probe}_loss_percent": loss, f"{probe}_success_count": sum(x is not None for x in values)})
        record.update(entry_connected=average is not None, entry_latency_ms=average,
                      entry_method=f"three-consecutive-direct-{probe}-" + ("connects" if probe == "tcp" else "handshakes"))
        failure = direct_failure(record, self.rules, check_download=False)
        record["status"] = failure or f"{probe.upper()} Passed"
        if failure:
            record["rejection_reason"] = (f"{probe.upper()}：成功 {sum(x is not None for x in values)}/3 次；平均 {average:.2f} 毫秒"
                                          if average is not None else f"{probe.upper()}：三次连接全部失败")
            record["rejection_reason"] += (f"；丢包 {loss:.2f}%，抖动 {jitter:.2f} 毫秒；"
                                           f"上限 {self.rules[f'max_{probe}_average_latency_ms']:g} 毫秒／"
                                           f"{self.rules['max_loss_percent']:g}%／{self.rules['max_jitter_ms']:g} 毫秒")
        return record

    def batch(self, candidates: list[dict], completed, *, reuse_tcp=False) -> list[dict]:
        with Observation(self.update, completed) as observer:
            return asyncio.run(self._batch(candidates, observer.completed, observer.update))

    async def _batch(self, candidates: list[dict], completed, notify=None) -> list[dict]:
        records = {}
        notify = notify or self.update
        stage = f"{self.probe.upper()} Testing"

        def show(record):
            records[record["key"]] = record
            notify(stage=stage, candidates=list(records.values()), status="Running")

        def finish(record):
            record.update(tested_at=datetime.now(UTC).isoformat())
            show(record)
            completed(record)

        async def measure(candidate):
            record = await self.latency(candidate, progress=show)
            show(record)
            if record["status"].startswith("Rejected"):
                finish(record)
            return record

        # Match the reference's barrier between latency and bandwidth tests.
        tested = await run_worker_pool(candidates, measure, min(100, self.rules[f"{self.probe}_concurrency"]))
        survivors = [r for r in tested if r["status"].endswith("Passed")]
        stage = "Direct Speed Testing"

        async def download(record):
            record["status"] = "Direct Speed Testing"
            show(record)
            node = NodeResult(ip=record["ip"], port=record["port"])
            await self.control.async_checkpoint()
            await test_speed([node], {"enabled": True, "candidates": 1, "domain": "speed.cloudflare.com",
                                     "path": f"/__down?bytes={self.rules['download_bytes']}", "bytes_per_test": self.rules["download_bytes"],
                                     "timeout_seconds": self.rules["download_timeout_seconds"], "maximum_download_seconds": self.rules["maximum_download_seconds"],
                                     "minimum_completion_ratio": self.rules["minimum_completion_ratio"], "minimum_mbps": self.rules["min_download_mbps"],
                                     "concurrency": 1}, user_agent="Noode-CG-ProxyBench/1.2.1")
            record.update(download_mbps=node.speed_mbps or 0.0,
                          download_measurement={**node.probe_results.get("speed", {}), "success": node.speed_mbps is not None,
                                                "routing_proof": "direct-pinned-candidate", "destination": f"{node.ip}:{node.port}", "host": "speed.cloudflare.com"})
            failure = direct_failure(record, self.rules)
            if failure:
                record["rejection_reason"] = f"下载 {record['download_mbps']:g} Mbps；最低 {self.rules['min_download_mbps']:g} Mbps；正文完整度或连接失败也会淘汰"
            else:
                record["status"] = "Direct Location"
                show(record)
                try:
                    status, headers, body, _ttfb = await _request(node, domain="www.cloudflare.com", path="/cdn-cgi/trace", context=self.context,
                                                                 timeout=self.rules["tls_timeout_seconds"], user_agent="Noode-CG-ProxyBench/1.2.1")
                    trace = _parse_trace(body)
                    colo = trace.get("colo", "").upper()
                    location = self.locations.get(colo, {})
                    country = location.get("country", "") if status == 200 else ""
                    record.update(colo=colo, geo_country=country, city=location.get("city", ""), geo_verified=bool(country), geo_conflict=False,
                                  jp_qualified=country == "JP", geo_method="cloudflare-edge-colo", cf_ray=headers.get("cf-ray", ""))
                except (TimeoutError, OSError, ValueError, EOFError):
                    record.update(geo_country="", geo_verified=False, geo_conflict=False, jp_qualified=False)
            record.update(qualified=not failure, status=failure or "Qualified")
            finish(record)
            return record

        await run_worker_pool(survivors, download, self.rules["speed_concurrency"])
        notify(_force=True, stage=stage, candidates=list(records.values()), status="Running")
        return tested
