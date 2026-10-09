from __future__ import annotations

import concurrent.futures
import copy
import json
import math
import statistics
import threading
import time

from .profile import safe_error
from .settings import SITES, validate_rules


def ranking_key(result: dict) -> tuple:
    if result.get("measurement_mode") == "tcp_tls":
        return (result.get("tcp_loss_percent", 100), result.get("tcp_average_latency_ms") or math.inf,
                result.get("tcp_jitter_ms", math.inf), -result.get("download_mbps", 0), result["ip"], result["port"])
    return (result.get("proxy_loss_percent", 100), -result.get("site_success_count", 0),
            result["proxy_average_latency_ms"] if result.get("proxy_average_latency_ms") is not None else math.inf, result.get("latency_jitter_ms", math.inf),
            -result.get("proxy_download_average_mbps", 0), result.get("entry_latency_ms", math.inf), result["ip"], result["port"])


def limit_failure(result: dict, rules: dict) -> str:
    """Revoke a cached pass when its real measurements exceed the currently saved limits."""
    if result.get("measurement_mode") == "tcp_tls":
        from .direct_benchmark import direct_failure
        return direct_failure(result, rules)
    if result.get("entry_latency_ms") is not None and result["entry_latency_ms"] > rules["max_entry_latency_ms"]:
        return "Rejected Entry"
    if result.get("proxy_loss_percent") is not None and result["proxy_loss_percent"] > rules["max_proxy_loss_percent"]:
        return "Rejected Loss"
    if result.get("proxy_average_latency_ms") is not None and result["proxy_average_latency_ms"] > rules["max_proxy_average_latency_ms"]:
        return "Rejected Latency"
    if result.get("proxy_download_average_mbps") is not None and result["proxy_download_average_mbps"] < rules["min_proxy_speed_mbps"]:
        return "Rejected Speed"
    if result.get("latency_jitter_ms") is not None and result["latency_jitter_ms"] > rules.get("max_proxy_jitter_ms", 500):
        return "Rejected Jitter"
    if result.get("rules", {}).get("round_count", 5) < 5:
        return "Retest Required"
    return ""


def calculate(result: dict, rules: dict) -> None:
    rounds = rules["round_count"]
    probes = result["probes"]
    successes = sum(probe["success"] for values in probes.values() for probe in values)
    result["site_success_count"] = successes
    result["proxy_loss_percent"] = 100 * (rounds * 3 - successes) / (rounds * 3)
    for site, _, _ in SITES:
        latencies = [probe["latency_ms"] for probe in probes[site]]
        result[f"{site}_rounds_ms"] = latencies
        values = [number if number is not None else rules["request_timeout_seconds"] * 1000 for number in latencies]
        ordered = sorted(values)
        retained = ordered[1:-1]
        result[f"{site}_retained_ms"] = retained
        result[f"{site}_discarded_ms"] = [ordered[0], ordered[-1]]
        result[f"{site}_average_ms"] = statistics.fmean(retained)
    averages = [statistics.fmean(result["probes"][site][index]["latency_ms"]
                                if result["probes"][site][index]["success"] else rules["request_timeout_seconds"] * 1000
                                for site, _, _ in SITES) for index in range(rounds)]
    result["round_averages_ms"] = averages
    result["proxy_average_latency_ms"] = statistics.fmean(result[f"{site}_average_ms"] for site, _, _ in SITES)
    result["latency_method"] = "per-site-trim-one-low-and-high-v1"
    result["latency_jitter_ms"] = statistics.pstdev(averages)
    result["latency_variance"] = statistics.pvariance(averages)
    result["stability_score"] = 100 / (1 + result["latency_jitter_ms"])
    result["entry_passed"] = (result.get("entry_latency_ms") is None or result["entry_latency_ms"] <= rules["max_entry_latency_ms"])
    result["latency_passed"] = result["entry_passed"] and result["proxy_loss_percent"] <= rules["max_proxy_loss_percent"] and result["proxy_average_latency_ms"] <= rules["max_proxy_average_latency_ms"] and result["latency_jitter_ms"] <= rules.get("max_proxy_jitter_ms", 500)


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
                   "download_rounds_mbps": [], "rules": rules, "status": "Loading Proxy"} for item in candidates}
        names = list(records)
        if callable(getattr(self.manager.controller, "site_samples", None)) and getattr(self.manager.controller, "named_ports", None):
            self.persistent_site_batch(records)
            return self.finish_measurements(records, completed)
        effective_concurrency = min(rules["delay_concurrency"], 24) if rules.get("adaptive_concurrency") else rules["delay_concurrency"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=rules["delay_concurrency"]) as executor:
            for round_index in range(rules["round_count"]):
                for site, url, expected in self.sites:
                    self.control.checkpoint()
                    for record in records.values():
                        record["status"] = f"Round {round_index + 1}"
                        record.update(active_site=site, active_round=round_index + 1)
                    self.update(stage=f"Round {round_index + 1}: {site}", candidates=list(records.values()))
                    pending = [name for name in names if not records[name].get("skip_reason")]
                    for offset in range(0, len(pending), effective_concurrency):
                        self.control.checkpoint()
                        futures = {executor.submit(self.manager.controller.delay, name, url, expected,
                                                   rules["request_timeout_seconds"]): name
                                   for name in pending[offset:offset + effective_concurrency]}
                        for future in concurrent.futures.as_completed(futures):
                            name = futures[future]
                            probe = future.result()
                            records[name]["probes"][site].append(probe)
                            seen = [item for values in records[name]["probes"].values() for item in values]
                            if sum(not item["success"] for item in seen) / (rules["round_count"] * 3) * 100 > rules["max_proxy_loss_percent"]:
                                records[name]["skip_reason"] = "前序请求失败，已无法满足成功率门槛"
                            self.update(candidates=list(records.values()))
                    if rules.get("adaptive_concurrency") and pending:
                        successes = sum(records[name]["probes"][site][-1]["success"] for name in pending)
                        latencies = [records[name]["probes"][site][-1]["latency_ms"] for name in pending if records[name]["probes"][site][-1]["success"]]
                        if successes / len(pending) < .7 and latencies and statistics.median(latencies) > rules["request_timeout_seconds"] * 600:
                            effective_concurrency = max(1, effective_concurrency // 2)
                        self.update(effective_concurrency=effective_concurrency)
                    for name in names:
                        if len(records[name]["probes"][site]) <= round_index:
                            records[name]["probes"][site].append({"success": False, "latency_ms": None, "skipped": True,
                                                                 "error": records[name].get("skip_reason", "提前结束")})
                if round_index + 1 < rules["round_count"]:
                    time.sleep(rules["round_cooldown_seconds"])
        return self.finish_measurements(records, completed)

    def persistent_site_batch(self, records: dict) -> None:
        rules = self.rules
        concurrency = min(rules["delay_concurrency"], 24) if rules.get("adaptive_concurrency") else rules["delay_concurrency"]
        self.update(stage="复用代理连接，快速测量三个网站", status="Running", effective_concurrency=concurrency)
        for record in records.values():
            record.update(probe_method="named-proxy-persistent-head-v1", latency_targets={site: url for site, url, _ in self.sites})
        def worker(name):
            record = records[name]
            for site, url, expected in self.sites:
                self.control.checkpoint()
                def observed(probe):
                    with self.activity_lock:
                        record["probes"][site].append(probe)
                        record.update(status=f"Round {len(record['probes'][site])}", active_site=site, active_round=len(record["probes"][site]))
                        failures = sum(not p["success"] for samples in record["probes"].values() for p in samples)
                        if failures / (rules["round_count"] * 3) * 100 > rules["max_proxy_loss_percent"]:
                            record["skip_reason"] = "前序请求失败，已无法满足成功率门槛"
                        self.update(candidates=list(records.values()))
                if not record.get("skip_reason"):
                    self.manager.controller.site_samples(name, url, expected, rules["request_timeout_seconds"], rules["round_count"],
                                                         checkpoint=self.control.checkpoint, observed=observed, should_stop=lambda: bool(record.get("skip_reason")))
                with self.activity_lock:
                    while len(record["probes"][site]) < rules["round_count"]:
                        record["probes"][site].append({"success": False, "latency_ms": None, "skipped": True,
                                                      "error": record.get("skip_reason", "连接未完成，剩余请求未测")})
            return record
        names = list(records)
        with concurrent.futures.ThreadPoolExecutor(max_workers=rules["delay_concurrency"]) as executor:
            offset = 0
            while offset < len(names):
                self.control.checkpoint()
                group = names[offset:offset + concurrency]
                offset += len(group)
                for future in concurrent.futures.as_completed([executor.submit(worker, name) for name in group]):
                    future.result()
                if rules.get("adaptive_concurrency"):
                    success = sum(sum(p["success"] for samples in records[name]["probes"].values() for p in samples) for name in group)
                    latencies = [p["latency_ms"] for name in group for samples in records[name]["probes"].values() for p in samples if p["success"]]
                    if success / (len(group) * rules["round_count"] * 3) < .7 and latencies and statistics.median(latencies) > rules["request_timeout_seconds"] * 600:
                        concurrency = max(1, concurrency // 2)
                    self.update(effective_concurrency=concurrency)

    def finish_measurements(self, records: dict, completed) -> list[dict]:
        rules = self.rules
        pending_speed = []
        for name, result in records.items():
            self.control.checkpoint()
            calculate(result, rules)
            result["proxy_probe_count"] = sum(not probe.get("skipped", False) for values in result["probes"].values() for probe in values)
            if not result["latency_passed"]:
                result["status"] = "Rejected Loss" if result["proxy_loss_percent"] > rules["max_proxy_loss_percent"] else "Rejected Latency"
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
