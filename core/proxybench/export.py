from __future__ import annotations

import csv
import gzip
import io
import ipaddress
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from core.io_utils import atomic_write_bytes, atomic_write_json, atomic_write_text

from .modes import validate_limits

PUBLIC_FIELDS = {"ip", "port", "rank", "lane", "jp_hint", "geo_country", "geo_verified", "geo_conflict",
                 "entry_latency_ms", "entry_connected", "entry_preferred", "entry_method", "proxy_probe_count",
                 "google_rounds_ms", "google_average_ms", "cloudflare_rounds_ms", "cloudflare_average_ms",
                 "github_rounds_ms", "github_average_ms", "round_averages_ms", "proxy_average_latency_ms",
                 "proxy_loss_percent", "download_rounds_mbps", "proxy_download_average_mbps",
                 "proxy_download_median_mbps", "proxy_download_average_mbytes", "stability_score", "tested_at",
                 "site_success_count", "latency_jitter_ms", "latency_variance", "qualified", "rules", "latency_method",
                 "google_retained_ms", "google_discarded_ms", "cloudflare_retained_ms", "cloudflare_discarded_ms",
                 "github_retained_ms", "github_discarded_ms", "entry_passed", "latency_passed"}
PUBLIC_FIELDS.update({"measurement_mode", "latency_probe", "latency_domain", "rejection_reason", "tcp_rounds_ms", "tcp_average_latency_ms", "tcp_loss_percent", "tcp_jitter_ms", "tcp_success_count",
                      "tls_rounds_ms", "tls_average_latency_ms", "tls_jitter_ms", "tls_loss_percent", "tls_enabled", "tls_passed",
                      "download_mbps", "download_measurement", "colo", "city", "geo_method", "latency_targets", "probe_method"})
ARTIFACTS = ("nodes.txt", "nodes.json", "nodes.csv", "api.json", "ip.zip")
TRANSACTION_FILES = (*ARTIFACTS, "health.json")
DIRECT_SUBSCRIPTION = "output/Npdex-Tcp/Tls.txt"
DIRECT_ALIAS_KEY = "shared-direct-subscription"


def transaction_paths(root: Path) -> dict[str, Path]:
    paths = {name: root / name for name in TRANSACTION_FILES}
    if root.name == "Nodes-TCP":
        paths[DIRECT_ALIAS_KEY] = root.parent / "Npdex-Tcp/Tls.txt"
    return paths


def refresh_direct_subscription(root: Path) -> None:
    if root.name != "Nodes-TCP" or not (root / "health.json").is_file() or not (root / "nodes.json").is_file():
        return
    health = json.loads((root / "health.json").read_text(encoding="utf-8"))
    good = health if health.get("published") else health.get("last_good_publication", {})
    if good.get("published"):
        text = nodes_text(json.loads((root / "nodes.json").read_text(encoding="utf-8"))).encode("utf-8")
        if text != (root / "nodes.txt").read_bytes():
            raise ValueError("共享直连文件必须与已发布的排序结果一致")
        destination = transaction_paths(root)[DIRECT_ALIAS_KEY]
        if not destination.exists() or destination.read_bytes() != text:
            atomic_write_bytes(destination, text)


def nodes_text(records: list[dict]) -> str:
    lines = []
    for record in records:
        ip = str(ipaddress.IPv4Address(record["ip"]))
        port = record["port"]
        country = str(record.get("geo_country") or record.get("country") or "XX").upper()
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535 or not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("输出地址必须为 IPv4:端口#两位国家代码")
        lines.append(f"{ip}:{port}#{country}")
    return "\n".join(lines) + ("\n" if lines else "")


def gate(records: list[dict], *, allow_partial: bool = False, limits: dict | None = None) -> bool:
    limits = validate_limits(limits)
    general = sum(item.get("lane") == "general" for item in records)
    japan = sum(item.get("lane") == "jp_append" for item in records)
    counts = (0 < len(records) <= sum(limits.values()) and general <= limits["general"] and japan <= limits["japan"]
              if allow_partial else general == limits["general"] and japan == limits["japan"])
    return (counts and len(records) == general + japan and len({item["ip"] for item in records}) == len(records)
            and all(item.get("qualified") for item in records)
            and [item.get("lane") for item in records] == ["general"] * general + ["jp_append"] * japan
            and all(item.get("geo_country") == "JP" and item.get("geo_verified") and not item.get("geo_conflict") for item in records[general:]))


def publish(root: Path, records: list[dict], health: dict) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    limits = validate_limits(health.get("publication_limits"))
    passed = gate(records, allow_partial=health.get("manual_publication") is True, limits=limits)
    report = {**health, "publish_gate_passed": passed, "published": passed, "needs_more": not passed,
              "quota_complete": gate(records, limits=limits), "publication_limits": limits,
              "general_final_count": sum(item.get("lane") == "general" for item in records),
              "jp_final_count": sum(item.get("lane") == "jp_append" for item in records),
              "unique_final_count": len({item["ip"] for item in records})}
    if not passed:
        previous_path = root / "health.json"
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
        except (OSError, ValueError):
            previous = {}
        good = previous if previous.get("published") else previous.get("last_good_publication", {})
        if good.get("published"):
            report["last_good_publication"] = {key: good[key] for key in ("published", "manual_publication", "publication_limits", "general_final_count", "jp_final_count", "unique_final_count") if key in good}
        atomic_write_json(root / "health.json", report)
        return report
    public = [{**{key: value for key, value in record.items() if key in PUBLIC_FIELDS},
               "sources": record.get("source_names", []), "rank": index,
               "country": record.get("geo_country") or "XX",
               "ip_port": f"{record['ip']}:{record['port']}"} for index, record in enumerate(records, 1)]
    staged = Path(tempfile.mkdtemp(prefix=".proxybench-publish-", dir=root))
    try:
        atomic_write_json(staged / "nodes.json", public)
        atomic_write_json(staged / "api.json", {"project": "Noode-CG-ProxyBench", "count": len(public), "nodes": public})
        atomic_write_text(staged / "nodes.txt", nodes_text(public))
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
        paths = transaction_paths(root)
        backup = {name: path.read_bytes().hex() if path.exists() else None for name, path in paths.items()}
        journal = root / ".publish-transaction.json.gz"
        atomic_write_bytes(journal, gzip.compress(json.dumps(backup).encode(), mtime=0))
        try:
            for name in ARTIFACTS:
                atomic_write_bytes(root / name, (staged / name).read_bytes())
            if DIRECT_ALIAS_KEY in paths:
                atomic_write_bytes(paths[DIRECT_ALIAS_KEY], (staged / "nodes.txt").read_bytes())
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
        refresh_direct_subscription(root)
        return
    payload = json.loads(gzip.decompress(journal.read_bytes()))
    paths = transaction_paths(root)
    if set(payload) not in (set(TRANSACTION_FILES), set(paths)):
        raise ValueError("发布恢复日志无效")
    for name, content in payload.items():
        if content is None:
            paths[name].unlink(missing_ok=True)
        else:
            atomic_write_bytes(paths[name], bytes.fromhex(content))
    journal.unlink()
    refresh_direct_subscription(root)
