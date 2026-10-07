from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

RULES = {"batch_size": 100, "round_count": 3, "max_proxy_average_latency_ms": 200.0,
         "max_proxy_loss_percent": 0.0, "min_proxy_speed_mbps": 16.0, "download_attempts": 3,
         "download_bytes": 2097152, "request_timeout_seconds": 5.0,
         "download_timeout_seconds": 15.0, "delay_concurrency": 20, "speed_concurrency": 1,
         "round_cooldown_seconds": 0.5}
SITES = (("google", "https://www.gstatic.com/generate_204", "204"),
         ("cloudflare", "https://cp.cloudflare.com/", "200-399"),
         ("github", "https://github.com/", "200-399"))


def validate_rules(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - set(RULES):
        raise ValueError("未知的代理优选规则")
    rules = {**RULES, **value}
    integers = {"batch_size", "round_count", "download_attempts", "download_bytes", "delay_concurrency", "speed_concurrency"}
    for key, number in rules.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise ValueError(f"规则必须是有限数值：{key}")
        if number < 0 or (number == 0 and key not in {"max_proxy_loss_percent", "round_cooldown_seconds"}):
            raise ValueError(f"规则超出范围：{key}")
        if key in integers and int(number) != number:
            raise ValueError(f"规则必须是整数：{key}")
    if not 1 <= rules["batch_size"] <= 100 or rules["round_count"] > 10 or rules["download_attempts"] > 10:
        raise ValueError("Batch 最多 100，轮数和下载次数最多 10")
    if rules["max_proxy_loss_percent"] > 100 or rules["delay_concurrency"] > 100:
        raise ValueError("丢失率或并发超出范围")
    if rules["speed_concurrency"] != 1:
        raise ValueError("当前共享 selector 下载采用单并发，保证各节点公平且路由独立")
    if rules["download_bytes"] not in {1048576, 2097152, 4194304, 8388608}:
        raise ValueError("下载大小必须为 1/2/4/8 MiB")
    if rules["request_timeout_seconds"] > 60 or rules["download_timeout_seconds"] > 120 or rules["round_cooldown_seconds"] > 2:
        raise ValueError("超时或轮间隔超出范围")
    return rules


def load_settings(config_path: str | Path) -> dict:
    path = Path(config_path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    block = config.get("proxybench", {})
    root = path.parent
    result = {"root": root, "profile": root / block.get("profile_path", "config/proxy-profile.local.yaml"),
              "state_dir": root / "data/proxy-bench", "runtime_dir": root / "runtime/mihomo",
              "output_dir": root / "output", "rules_path": root / "data/proxybench-rules.json",
              "official_sample_count": int(block.get("official_sample_count", 10000)),
              "max_cycles": int(block.get("max_cycles", 30)), "sources": block.get("sources", {}),
              "auto_update": bool(block.get("auto_update", True)),
              "geo_urls": block.get("geo_urls", ["https://ipwho.is/", "https://api.country.is/"]),
              "rules": validate_rules(block.get("rules", {}))}
    if result["official_sample_count"] < 1 or not 1 <= result["max_cycles"] <= 30:
        raise ValueError("候选规模或补池轮数错误")
    return result


def current_rules(settings: dict) -> dict:
    path = settings["rules_path"]
    return validate_rules({**settings["rules"], **(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})})
