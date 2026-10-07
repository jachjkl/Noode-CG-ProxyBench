from __future__ import annotations

import hashlib
import ipaddress

from core.fetcher import sample_ranges

from .common import candidates, fetch


def collect(count: int, port: int, seed: str, exclude: set[str], downloader=fetch) -> tuple[list[dict], list]:
    lines = downloader("https://www.cloudflare.com/ips-v4/").decode("ascii").splitlines()
    networks = [ipaddress.IPv4Network(line.strip()) for line in lines if line.strip()]
    if not networks or any(not network.network_address.is_global for network in networks):
        raise ValueError("Cloudflare 官方 IPv4 范围无效")
    numeric_seed = int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big")
    chosen = {}
    for cycle in range(20):
        sampled = sample_ranges([str(network) for network in networks], max(count, 100),
                                ports=[port], seed=numeric_seed + cycle, source="cloudflare-official")
        # sample_ranges groups by CIDR. A shuffled deterministic order prevents top-up truncation
        # from dropping the last ranges and preserves proportional coverage of the first full draw.
        sampled.sort(key=lambda node: hashlib.sha256(f"{seed}:{cycle}:{node.ip}".encode()).digest())
        for node in sampled:
            if node.ip not in exclude and node.ip not in chosen:
                chosen[node.ip] = candidates(node.ip.encode(), "cloudflare-official", port, priority=1)[0]
                if len(chosen) == count:
                    return list(chosen.values()), networks
    raise ValueError("官方网段没有足够新的 Unique Candidate")
