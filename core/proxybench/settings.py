from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

RULES = {"batch_size": 100, "round_count": 3, "max_proxy_average_latency_ms": 2500.0,
         "max_entry_latency_ms": 200.0, "entry_timeout_seconds": 1.2, "entry_concurrency": 256,
         "max_proxy_loss_percent": 0.0, "min_proxy_speed_mbps": 3.0, "download_attempts": 1,
         "download_bytes": 524288, "minimum_completion_ratio": 0.95, "maximum_download_seconds": 7.0,
         "request_timeout_seconds": 3.0,
         "download_timeout_seconds": 8.0, "delay_concurrency": 60, "speed_concurrency": 4,
         "round_cooldown_seconds": 0.5}
SITES = (("google", "https://www.gstatic.com/generate_204", "204"),
         ("cloudflare", "https://cp.cloudflare.com/", "200-399"),
         ("github", "https://github.com/", "200-399"))


def validate_rules(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - set(RULES):
        raise ValueError("未知的代理优选规则")
    rules = {**RULES, **value}
    integers = {"batch_size", "round_count", "download_attempts", "download_bytes", "delay_concurrency", "speed_concurrency", "entry_concurrency"}
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
    if rules["speed_concurrency"] > 8 or rules["entry_concurrency"] > 512 or rules["entry_timeout_seconds"] > 5:
        raise ValueError("网速并发最多 8，入口初筛并发最多 512，入口连接超时最多 5 秒")
    if rules["download_bytes"] not in {524288, 1048576, 2097152, 4194304, 8388608}:
        raise ValueError("测速样本大小必须为 0.5/1/2/4/8 MiB")
    if not 0.95 <= rules["minimum_completion_ratio"] <= 1 or rules["maximum_download_seconds"] > 120:
        raise ValueError("测速正文完整度须为 95% 至 100%，正文计时上限最多 120 秒")
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
              "max_cycles": int(block.get("max_cycles", 0)), "sources": block.get("sources", {}),
              "auto_update": bool(block.get("auto_update", True)),
              "auto_refresh_profile": bool(block.get("auto_refresh_profile", True)),
              "profile_refresh_seconds": max(5.0, float(block.get("profile_refresh_seconds", 30))),
              "fast_entry_screen": bool(block.get("fast_entry_screen", True)),
              "speed_url": block.get("speed_url", "https://dl.google.com/chrome/install/standalonesetup64.exe"),
              "geo_urls": block.get("geo_urls", ["https://ipwho.is/", "https://api.country.is/"]),
              "rules": validate_rules(block.get("rules", {}))}
    if result["official_sample_count"] < 1 or not 0 <= result["max_cycles"] <= 30:
        raise ValueError("候选规模或补池轮数错误")
    return result


def current_rules(settings: dict) -> dict:
    path = settings["rules_path"]
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # Upgrade the former untouched speed preset, preserving independently edited response rules.
    former = {"min_proxy_speed_mbps": 16.0, "download_attempts": 3,
              "download_bytes": 2097152, "download_timeout_seconds": 15.0}
    if isinstance(saved, dict) and all(saved.get(key) == value for key, value in former.items()):
        saved = {**saved, **{key: RULES[key] for key in former}}
    if isinstance(saved, dict):
        for key, previous in {"max_proxy_average_latency_ms": 200.0, "request_timeout_seconds": 5.0,
                              "delay_concurrency": 20, "speed_concurrency": 1}.items():
            if saved.get(key) == previous:
                saved[key] = RULES[key]
    return validate_rules({**settings["rules"], **saved})
