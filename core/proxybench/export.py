from __future__ import annotations

import csv
import gzip
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from core.io_utils import atomic_write_bytes, atomic_write_json, atomic_write_text

PUBLIC_FIELDS = {"ip", "port", "rank", "lane", "jp_hint", "geo_country", "geo_verified", "geo_conflict",
                 "google_rounds_ms", "google_average_ms", "cloudflare_rounds_ms", "cloudflare_average_ms",
                 "github_rounds_ms", "github_average_ms", "round_averages_ms", "proxy_average_latency_ms",
                 "proxy_loss_percent", "download_rounds_mbps", "proxy_download_average_mbps",
                 "proxy_download_median_mbps", "proxy_download_average_mbytes", "stability_score", "tested_at",
                 "site_success_count", "latency_jitter_ms", "latency_variance", "qualified"}
ARTIFACTS = ("nodes.txt", "nodes.json", "nodes.csv", "api.json", "ip.zip")
TRANSACTION_FILES = (*ARTIFACTS, "health.json")


def gate(records: list[dict]) -> bool:
    return (len(records) == 110 and len({item["ip"] for item in records}) == 110
            and all(item.get("qualified") for item in records)
            and [item.get("lane") for item in records] == ["general"] * 100 + ["jp_append"] * 10
            and all(item.get("geo_country") == "JP" and item.get("geo_verified") and not item.get("geo_conflict") for item in records[100:]))


def publish(root: Path, records: list[dict], health: dict) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    passed = gate(records)
    report = {**health, "publish_gate_passed": passed, "published": passed, "needs_more": not passed,
              "general_final_count": sum(item.get("lane") == "general" for item in records),
              "jp_final_count": sum(item.get("lane") == "jp_append" for item in records),
              "unique_final_count": len({item["ip"] for item in records})}
    if not passed:
        atomic_write_json(root / "health.json", report)
        return report
    public = [{**{key: value for key, value in record.items() if key in PUBLIC_FIELDS},
               "sources": record.get("source_names", []), "rank": index,
               "country": record.get("geo_country") or "XX",
               "ip_port": f"{record['ip']}:{record['port']}"} for index, record in enumerate(records, 1)]
    staged = Path(tempfile.mkdtemp(prefix=".proxybench-publish-", dir=root))
    try:
        atomic_write_json(staged / "nodes.json", public)
        atomic_write_json(staged / "api.json", {"project": "Noode-CG-ProxyBench", "count": 110, "nodes": public})
        atomic_write_text(staged / "nodes.txt", "\n".join(f"{item['ip_port']}#{item['country']}" for item in public) + "\n")
        stream = io.StringIO()
        columns = list(public[0]) + sorted({key for item in public for key in item} - set(public[0]))
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(public)
        atomic_write_text(staged / "nodes.csv", stream.getvalue())
        grouped = {}
        for item in public:
            grouped.setdefault(f"{item['port']}/ALL.txt", []).append(item["ip"])
            grouped.setdefault(f"{item['port']}/{item['country']}.txt", []).append(item["ip"])
        with zipfile.ZipFile(staged / "ip.zip", "w", zipfile.ZIP_DEFLATED) as package:
            for name, ips in grouped.items():
                package.writestr(name, "\n".join(ips) + "\n")
        # Durable transaction backup. Interrupted application rolls back on the next call/start.
        backup = {name: (root / name).read_bytes().hex() if (root / name).exists() else None for name in TRANSACTION_FILES}
        journal = root / ".publish-transaction.json.gz"
        atomic_write_bytes(journal, gzip.compress(json.dumps(backup).encode(), mtime=0))
        try:
            for name in ARTIFACTS:
                atomic_write_bytes(root / name, (staged / name).read_bytes())
            atomic_write_json(root / "health.json", report)
        except BaseException:
            recover(root)
            raise
        journal.unlink()
    finally:
        shutil.rmtree(staged)
    return report


def recover(root: Path) -> None:
    journal = root / ".publish-transaction.json.gz"
    if not journal.exists():
        return
    payload = json.loads(gzip.decompress(journal.read_bytes()))
    if set(payload) != set(TRANSACTION_FILES):
        raise ValueError("发布恢复日志无效")
    for name, content in payload.items():
        if content is None:
            (root / name).unlink(missing_ok=True)
        else:
            atomic_write_bytes(root / name, bytes.fromhex(content))
    journal.unlink()
