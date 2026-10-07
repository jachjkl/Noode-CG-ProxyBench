from __future__ import annotations

import secrets

from . import authorized_proxy_source, cloudflare_official, fixed_full, github_candidate_feed
from .common import fetch, merge


def build(settings: dict, port: int, excluded: set[str] | None = None, seed: str | None = None, downloader=fetch) -> tuple[list[dict], dict]:
    seed = seed or secrets.token_hex(16)
    excluded = excluded or set()
    fixed, fixed_counts = fixed_full.collect(port, downloader)
    official, networks = cloudflare_official.collect(settings["official_sample_count"], port, seed,
                                                     excluded | {item["ip"] for item in fixed}, downloader)
    hints, hint_report = github_candidate_feed.collect(settings["sources"].get("jp_supplemental", []), networks, port,
                                                      settings["state_dir"] / "source-cache", downloader)
    authorized_path = settings["root"] / "config/authorized-proxies.local.yaml"
    authorized = authorized_proxy_source.collect(authorized_path if authorized_path.exists() else None)
    records = merge([*fixed, *official, *hints, *authorized])
    for index, item in enumerate(records, 1):
        item["proxy_name"] = f"PB-{index:06d}"
    report = {"seed": seed, "fixed_sources": fixed_counts, "fixed_source_count": len(merge(fixed)),
              "cloudflare_official_count": len(official), "jp_supplement_count": len(merge(hints)),
              "authorized_proxy_count": len(authorized), "candidate_total": len(fixed) + len(official) + len(hints) + len(authorized),
              "unique_candidate_count": len(records), "official_ipv4_ranges": [str(network) for network in networks], **hint_report}
    return records, report
