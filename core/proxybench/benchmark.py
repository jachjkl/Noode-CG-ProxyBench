from __future__ import annotations

import concurrent.futures
import copy
import json
import math
import statistics
import threading

from .profile import safe_error
from .settings import SITES, validate_rules


def ranking_key(result: dict) -> tuple:
    if result.get("measurement_mode") == "tcp_tls":
        probe = result.get("latency_probe", "tls" if result.get("tls_enabled") else "tcp")
        return (result.get(f"{probe}_loss_percent", 100), result.get(f"{probe}_average_latency_ms") or math.inf,
                result.get(f"{probe}_jitter_ms", math.inf), -result.get("download_mbps", 0), result["ip"], result["port"])
    return (result.get("proxy_loss_percent", 100), -result.get("site_success_count", 0),
            result["proxy_average_latency_ms"] if result.get("proxy_average_latency_ms") is not None else math.inf, result.get("latency_jitter_ms", math.inf),
            -result.get("proxy_download_average_mbps", 0), result["ip"], result["port"])


def limit_failure(result: dict, rules: dict) -> str:
    """Revoke a cached pass when its real measurements exceed the currently saved limits."""
    if result.get("measurement_mode") == "tcp_tls":
        from .direct_benchmark import direct_failure
        return direct_failure(result, rules)
    if result.get("proxy_loss_percent") is not None and result["proxy_loss_percent"] > rules["max_proxy_loss_percent"]:
        return "Rejected Loss"
    if result.get("proxy_average_latency_ms") is not None and result["proxy_average_latency_ms"] > rules["max_proxy_average_latency_ms"]:
        return "Rejected Latency"
    if result.get("proxy_download_average_mbps") is not None and result["proxy_download_average_mbps"] < rules["min_proxy_speed_mbps"]:
        return "Rejected Speed"
    if result.get("rules", {}).get("round_count", 1) != 1:
        return "Retest Required"
    return ""


def calculate(result: dict, rules: dict) -> None:
    probes = result["probes"]
    if any(len(probes[site]) != 1 for site, _, _ in SITES):
        raise ValueError("单轮测试必须对三个网站各记录一次，不能缺测或重复")
    successes = sum(probe["success"] for values in probes.values() for probe in values)
    result["site_success_count"] = successes
    result["proxy_loss_percent"] = 100 * (3 - successes) / 3
    for site, _, _ in SITES:
        latency = probes[site][0]["latency_ms"]
        value = latency if latency is not None else rules["request_timeout_seconds"] * 1000
        result[f"{site}_rounds_ms"] = [latency]
        result[f"{site}_retained_ms"] = [value]
        result[f"{site}_discarded_ms"] = []
        result[f"{site}_average_ms"] = value
    average = statistics.fmean(result[f"{site}_average_ms"] for site, _, _ in SITES)
    result.update(proxy_average_latency_ms=average, round_averages_ms=[average],
                  latency_method="one-round-three-site-mean-v2", latency_jitter_ms=0.0,
                  latency_variance=0.0, stability_score=None)
    result["latency_passed"] = result["proxy_loss_percent"] <= rules["max_proxy_loss_percent"] and average <= rules["max_proxy_average_latency_ms"]


class Benchmark:
    def __init__(self, manager, rules: dict, control, *, geo_urls: list[str], update=None, cloudflare_url="https://www.cloudflare.com/cdn-cgi/trace",
                 speed_url="https://dl.google.com/chrome/install/standalonesetup64.exe", geo_policy="confirm") -> None:
        self.manager = manager
        self.rules = copy.deepcopy(validate_rules(rules))
        self.control = control
        self.geo_urls = geo_urls
        self.geo_policy = geo_policy
        self.speed_url = speed_url
        self.sites = tuple((site, cloudflare_url if site == "cloudflare" else url,
                            "200" if site == "cloudflare" and "/cdn-cgi/trace" in cloudflare_url else expected)
                           for site, url, expected in SITES)
        self.update = update or (lambda **_: None)
        self.speed_active = set()
        self.activity_lock = threading.Lock()

    def geo(self, name: str) -> dict:
        observations = []
        for url in self.geo_urls:
            self.control.checkpoint()
            try:
                response = self.manager.controller.request(name, url, timeout=self.rules["request_timeout_seconds"])
                payload = json.loads(response["body"])
                country = str(payload.get("country_code") or payload.get("country", "")).upper()
                if len(country) != 2 or payload.get("success") is False:
                    raise ValueError
                observations.append({"service": url, "country": country, "routing_proof": response["routing_proof"]})
                if self.geo_policy == "quick":
                    break
            except Exception as exc:
                observations.append({"service": url, "error": safe_error(exc)})
        countries = {item["country"] for item in observations if "country" in item}
        conflict = len(countries) > 1
        country = next(iter(countries)) if len(countries) == 1 else ""
        return {"geo_country": country, "geo_conflict": conflict, "geo_verified": bool(country) and not conflict,
                "geo_observations": observations, "jp_qualified": country == "JP" and not conflict}

    def batch(self, candidates: list[dict], profile, completed=None) -> list[dict]:
        completed = completed or (lambda _: None)
        self.manager.load_batch(candidates, profile)
        self.manager.benchmark_active = True
        rules = self.rules
        records = {item["proxy_name"]: {**copy.deepcopy(item), "measurement_mode": "proxy", "key": f"{item['ip']}:{item['port']}",
                   "probes": {site: [] for site, _, _ in SITES}, "qualified": False,
                   "download_rounds_mbps": [], "rules": rules, "status": "Loading Proxy",
                   "probe_method": "named-proxy-single-http-v3", "latency_targets": {site: url for site, url, _ in self.sites}} for item in candidates}
        self.update(stage="单轮测试三个网站", status="Running", batch_input_count=len(records),
                    batch_probe_completed=0, batch_probe_total=len(records) * 3, batch_latency_completed=0)
        concurrency = min(rules["delay_concurrency"], 24) if rules.get("adaptive_concurrency") else rules["delay_concurrency"]
        counters = {"probes": 0, "latency": 0}
        def worker(name):
            record = records[name]
            for site, url, expected in self.sites:
                self.control.checkpoint()
                with self.activity_lock:
                    record.update(status="Round 1", active_site=site, active_round=1)
                    self.update(candidates=list(records.values()))
                probe_method = getattr(self.manager.controller, "site_probe", None)
                probe = (probe_method if callable(probe_method) else self.manager.controller.delay)(name, url, expected, rules["request_timeout_seconds"])
                with self.activity_lock:
                    record["probes"][site].append(probe)
                    record.update(status="Round 1", active_site=site, active_round=1)
                    counters["probes"] += 1
                    self.update(candidates=list(records.values()), batch_probe_completed=counters["probes"],
                                batch_latency_completed=counters["latency"])
            with self.activity_lock:
                calculate(record, rules)
                record["proxy_probe_count"] = 3
                record["status"] = "Latency Passed" if record["latency_passed"] else "Rejected Loss" if record["proxy_loss_percent"] > rules["max_proxy_loss_percent"] else "Rejected Latency"
                if not record["latency_passed"]:
                    failed = [site for site, _, _ in self.sites if not record["probes"][site][0]["success"]]
                    record["rejection_reason"] = (f"三站平均 {record['proxy_average_latency_ms']:.2f} 毫秒，上限 {rules['max_proxy_average_latency_ms']:g} 毫秒；"
                                                  f"请求失败率 {record['proxy_loss_percent']:.2f}%，上限 {rules['max_proxy_loss_percent']:g}%；"
                                                  f"每站总超时 {rules['request_timeout_seconds']:g} 秒" + ("；失败网站：" + "、".join(failed) if failed else ""))
                    self.finish(record, completed)
                counters["latency"] += 1
                self.update(candidates=list(records.values()), batch_latency_completed=counters["latency"], batch_probe_completed=counters["probes"])
        names = list(records)
        with concurrent.futures.ThreadPoolExecutor(max_workers=rules["delay_concurrency"]) as executor:
            offset = 0
            while offset < len(names):
                self.control.checkpoint()
                group = names[offset:offset + concurrency]
                offset += len(group)
                futures = [executor.submit(worker, name) for name in group]
                try:
                    for future in concurrent.futures.as_completed(futures):
                        future.result()
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
                if rules.get("adaptive_concurrency"):
                    probes = [p for name in group for values in records[name]["probes"].values() for p in values]
                    successful = [p["latency_ms"] for p in probes if p["success"]]
                    if successful and len(successful) / len(probes) < .7 and statistics.median(successful) > rules["request_timeout_seconds"] * 600:
                        concurrency = max(1, concurrency // 2)
                self.update(effective_concurrency=concurrency)
        return self.finish_measurements(records, completed)

    def finish_measurements(self, records: dict, completed) -> list[dict]:
        rules = self.rules
        pending_speed = []
        for name, result in records.items():
            self.control.checkpoint()
            calculate(result, rules)
            result["proxy_probe_count"] = sum(not probe.get("skipped", False) for values in result["probes"].values() for probe in values)
            if not result["latency_passed"]:
                result["status"] = "Rejected Loss" if result["proxy_loss_percent"] > rules["max_proxy_loss_percent"] else "Rejected Latency"
                if not result.get("tested_at"):
                    self.finish(result, completed)
            else:
                result["status"] = "Latency Passed"
                pending_speed.append((name, result))
        if pending_speed:
            self.update(stage="Speed Testing", candidates=list(records.values()))
            # Each production candidate has its own listener/rule, avoiding shared-selector races.
            workers = rules["speed_concurrency"] if getattr(self.manager.controller, "named_ports", None) else 1
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(self.speed_result, name, result): name for name, result in pending_speed}
                for future in concurrent.futures.as_completed(futures):
                    name = futures[future]
                    records[name] = future.result()
                    self.finish(records[name], completed)
                    self.update(candidates=list(records.values()))
        return list(records.values())

    def finish(self, result: dict, completed) -> None:
        from datetime import UTC, datetime
        result["tested_at"] = datetime.now(UTC).isoformat()
        completed(result)

    def speed_result(self, name: str, record: dict) -> dict:
        with self.activity_lock:
            self.speed_active.add(name)
            self.update(speed_active=sorted(self.speed_active))
        try:
            return self._speed_result(name, record)
        finally:
            with self.activity_lock:
                self.speed_active.discard(name)
                self.update(speed_active=sorted(self.speed_active))

    def _speed_result(self, name: str, record: dict) -> dict:
        result = copy.deepcopy(record)
        downloads = []
        for _ in range(self.rules["download_attempts"]):
            self.control.checkpoint()
            try:
                measurement = self.manager.controller.legacy_speed(name, self.speed_url,
                    timeout=self.rules["download_timeout_seconds"], wanted_bytes=self.rules["download_bytes"],
                    maximum_download_seconds=self.rules["maximum_download_seconds"],
                    minimum_completion_ratio=self.rules["minimum_completion_ratio"])
                measurement.pop("body", None)
                downloads.append(measurement)
            except Exception as exc:
                downloads.append({"success": False, "speed_mbps": 0.0, "error": safe_error(exc),
                                  "stage": getattr(exc, "stage", "Proxy Request"), "received_bytes": getattr(exc, "received", 0),
                                  "cause": getattr(exc, "cause", type(exc).__name__), **getattr(exc, "proof", {})})
        speeds = [item["speed_mbps"] for item in downloads]
        result.update(download_measurements=downloads, download_rounds_mbps=speeds,
                      proxy_download_average_mbps=statistics.fmean(speeds), proxy_download_median_mbps=statistics.median(speeds),
                      proxy_download_average_mbytes=statistics.fmean(speeds) / 8)
        result["qualified"] = all(item["success"] for item in downloads) and statistics.fmean(speeds) >= self.rules["min_proxy_speed_mbps"]
        result["status"] = "Qualified" if result["qualified"] else "Rejected Speed"
        if result["qualified"]:
            result.update(self.geo(name))
        return result
