"""Bounded real proxy measurements and a long-running Runner connection check."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.io_utils import atomic_write_json
from core.proxybench.benchmark import Benchmark
from core.proxybench.mihomo_manager import MihomoManager
from core.proxybench.profile import ProxyProfile
from core.proxybench.settings import RULES
from core.proxybench.state import Control


def check(app: Path, destination: Path, hold_seconds: int = 780) -> dict:
    started = time.monotonic()
    destination.mkdir(parents=True, exist_ok=True)
    profile = ProxyProfile.load(app / "config/proxy-profile.local.yaml")
    # Read an existing checkpoint, but never write to the owner's live benchmark state.
    qualified = app / "data/proxy-bench/qualified.json.gz"
    records = json.loads(gzip.decompress(qualified.read_bytes())) if qualified.exists() else []
    candidates = []
    for row in records:
        if row.get("qualified") and row["port"] == profile.port:
            candidates.append({key: row[key] for key in ("ip", "port", "proxy_name", "source_types", "jp_hint") if key in row})
        if len(candidates) == 100:
            break
    if not candidates:
        raise ValueError("No saved qualified candidates available for this diagnostic")
    manager = MihomoManager(destination / "runtime")
    shutil.copy2(app / "runtime/mihomo/mihomo.exe", manager.binary)
    report = {"candidate_count": len(candidates), "diagnostic_only": True, "published": False,
              "cloud_proxy_configured": bool(os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY"))}
    try:
        manager.ensure(False)
        results = Benchmark(manager, RULES, Control(destination), geo_urls=[],
                            cloudflare_url="https://www.cloudflare.com/cdn-cgi/trace").batch(candidates, {"default": profile})
        report.update(proxy_seconds=round(time.monotonic() - started, 3),
                      proxy_tested=len(results), qualified=sum(row["qualified"] for row in results),
                      all_nine_successful=sum(row["site_success_count"] == 9 for row in results),
                      routing_verified=all(sample.get("routing_proof") == "connection-chain" and
                                           row["proxy_name"] in sample.get("chains", []) and "DIRECT" not in sample.get("chains", [])
                                           for row in results for sample in row.get("download_measurements", []) if sample.get("success")),
                      geo_queries_performed=False)
        atomic_write_json(destination / "results.json", results)
    finally:
        manager.stop()
    print(json.dumps(report), flush=True)
    # Keep the real Actions job alive beyond the reported 12-minute failure, exercising Runner's renewjob traffic.
    next_heartbeat = 0
    while time.monotonic() - started < hold_seconds:
        elapsed = int(time.monotonic() - started)
        if elapsed >= next_heartbeat:
            print(json.dumps({"elapsed_seconds": elapsed, "runner_job": "active"}), flush=True)
            next_heartbeat = elapsed + 30
        time.sleep(1)
    report["job_seconds"] = round(time.monotonic() - started, 3)
    atomic_write_json(destination / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-seconds", type=int, default=780, choices=range(0, 1801))
    args = parser.parse_args()
    app = Path(os.environ["NOODE_PROXYBENCH_APP"])
    destination = Path(os.environ["RUNNER_TEMP"]) / "proxybench-connection-check"
    print(json.dumps(check(app, destination, args.hold_seconds)), flush=True)
