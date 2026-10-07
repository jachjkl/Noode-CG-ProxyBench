from __future__ import annotations

import concurrent.futures
import copy
import json
import math
import statistics
import time

from .profile import safe_error
from .settings import SITES


def ranking_key(result: dict) -> tuple:
    return (result.get("proxy_loss_percent", 100), -result.get("site_success_count", 0),
            result["proxy_average_latency_ms"] if result.get("proxy_average_latency_ms") is not None else math.inf, result.get("latency_jitter_ms", math.inf),
            -result.get("proxy_download_average_mbps", 0), result["ip"], result["port"])


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
        result[f"{site}_average_ms"] = statistics.fmean(values)
    averages = [statistics.fmean(result["probes"][site][index]["latency_ms"]
                                if result["probes"][site][index]["success"] else rules["request_timeout_seconds"] * 1000
                                for site, _, _ in SITES) for index in range(rounds)]
    result["round_averages_ms"] = averages
    result["proxy_average_latency_ms"] = statistics.fmean(averages)
    result["latency_jitter_ms"] = statistics.pstdev(averages)
    result["latency_variance"] = statistics.pvariance(averages)
    result["stability_score"] = 100 / (1 + result["latency_jitter_ms"])
    result["latency_passed"] = result["proxy_loss_percent"] <= rules["max_proxy_loss_percent"] and result["proxy_average_latency_ms"] <= rules["max_proxy_average_latency_ms"]


class Benchmark:
    def __init__(self, manager, rules: dict, control, *, geo_urls: list[str], update=None, cloudflare_url="https://cp.cloudflare.com/") -> None:
        self.manager = manager
        self.rules = copy.deepcopy(rules)
        self.control = control
        self.geo_urls = geo_urls
        self.sites = tuple((site, cloudflare_url if site == "cloudflare" else url,
                            "200" if site == "cloudflare" and "/cdn-cgi/trace" in cloudflare_url else expected)
                           for site, url, expected in SITES)
        self.update = update or (lambda **_: None)

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
        records = {item["proxy_name"]: {**copy.deepcopy(item), "key": f"{item['ip']}:{item['port']}",
                   "probes": {site: [] for site, _, _ in SITES}, "qualified": False,
                   "download_rounds_mbps": [], "rules": rules, "status": "Loading Proxy"} for item in candidates}
        names = list(records)
        with concurrent.futures.ThreadPoolExecutor(max_workers=rules["delay_concurrency"]) as executor:
            for round_index in range(rules["round_count"]):
                for site, url, expected in self.sites:
                    self.control.checkpoint()
                    for record in records.values():
                        record["status"] = f"Round {round_index + 1}"
                    self.update(stage=f"Round {round_index + 1}: {site}", candidates=list(records.values()))
                    for offset in range(0, len(names), rules["delay_concurrency"]):
                        self.control.checkpoint()
                        futures = {executor.submit(self.manager.controller.delay, name, url, expected,
                                                   rules["request_timeout_seconds"]): name
                                   for name in names[offset:offset + rules["delay_concurrency"]]}
                        for future in concurrent.futures.as_completed(futures):
                            name = futures[future]
                            records[name]["probes"][site].append(future.result())
                if round_index + 1 < rules["round_count"]:
                    time.sleep(rules["round_cooldown_seconds"])
        for name, result in records.items():
            self.control.checkpoint()
            calculate(result, rules)
            if not result["latency_passed"]:
                result["status"] = "Rejected Loss" if result["proxy_loss_percent"] > rules["max_proxy_loss_percent"] else "Rejected Latency"
            else:
                result["status"] = "Latency Passed"
                downloads = []
                for _ in range(rules["download_attempts"]):
                    self.control.checkpoint()
                    result["status"] = "Speed Testing"
                    self.update(stage="Speed Testing", candidates=list(records.values()))
                    try:
                        measurement = self.manager.controller.legacy_speed(name, f"https://speed.cloudflare.com/__down?bytes={rules['download_bytes']}",
                                                                           timeout=rules["download_timeout_seconds"], wanted_bytes=rules["download_bytes"],
                                                                           maximum_download_seconds=rules["maximum_download_seconds"],
                                                                           minimum_completion_ratio=rules["minimum_completion_ratio"])
                        measurement.pop("body", None)
                        downloads.append(measurement)
                    except Exception as exc:
                        downloads.append({"success": False, "speed_mbps": 0.0, "error": safe_error(exc),
                                          "stage": getattr(exc, "stage", "Proxy Request"),
                                          "received_bytes": getattr(exc, "received", 0),
                                          "cause": getattr(exc, "cause", type(exc).__name__),
                                          **getattr(exc, "proof", {})})
                speeds = [item["speed_mbps"] for item in downloads]
                result.update(download_measurements=downloads, download_rounds_mbps=speeds,
                              proxy_download_average_mbps=statistics.fmean(speeds), proxy_download_median_mbps=statistics.median(speeds),
                              proxy_download_average_mbytes=statistics.fmean(speeds) / 8)
                result["qualified"] = all(item["success"] for item in downloads) and statistics.fmean(speeds) >= rules["min_proxy_speed_mbps"]
                result["status"] = "Qualified" if result["qualified"] else "Rejected Speed"
                if result["qualified"]:
                    result.update(self.geo(name))
            from datetime import UTC, datetime
            result["tested_at"] = datetime.now(UTC).isoformat()
            completed(result)
            self.update(candidates=list(records.values()))
        return list(records.values())
