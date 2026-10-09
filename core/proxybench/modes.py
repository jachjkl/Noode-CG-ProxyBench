"""Separate measurement state, rules and published files for the two methods."""
from __future__ import annotations

from copy import deepcopy

MODES = {"proxy": "代理三网站测速", "tcp_tls": "免代理 TCP／TLS 测速"}
OUTPUTS = {"proxy": "output", "tcp_tls": "output/Nodes-TCP"}


def mode_settings(settings: dict, mode: str) -> dict:
    from .settings import TCP_RULES, validate_rules
    if mode not in MODES:
        raise ValueError("未知测速方式")
    result = deepcopy(settings)
    root = result["root"]
    result.update(measurement_mode=mode, output_dir=root / OUTPUTS[mode])
    if mode == "tcp_tls":
        result.update(state_dir=root / "data/tcp-bench", runtime_dir=root / "runtime/tcp-bench",
                      rules_path=root / "data/tcpbench-rules.json", rules=validate_rules(TCP_RULES, mode),
                      fast_entry_screen=True, auto_refresh_profile=False)
    return result


def publication_limits(rules: dict | None = None) -> dict:
    value = rules or {}
    return validate_limits({"general": value.get("publish_count", 100), "japan": value.get("jp_publish_count", 10)})


def validate_limits(value: dict | None = None) -> dict:
    value = value or {"general": 100, "japan": 10}
    if set(value) != {"general", "japan"}:
        raise ValueError("发布名额格式错误")
    if any(isinstance(n, bool) or not isinstance(n, int) for n in value.values()):
        raise ValueError("发布数量必须是整数")
    if not 1 <= value["general"] <= 1000 or not 0 <= value["japan"] <= 300:
        raise ValueError("常规发布数量可设为 1 至 1000，日本追加数量可设为 0 至 300")
    return dict(value)
