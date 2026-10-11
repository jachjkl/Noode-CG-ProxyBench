"""Live, per-method regional publication budgets, independent of probe quality rules."""
from __future__ import annotations

import json
import math
import re
from collections import Counter

from core.io_utils import atomic_write_json

from .state import RunLock

KIND = "regional-v1"
DEFAULT_CAPS = {"JP": 10, "HK": 20, "SG": 20}
ALIASES = {"日本": "JP", "香港": "HK", "中国香港": "HK", "新加坡": "SG", "美国": "US", "德国": "DE",
           "法国": "FR", "英国": "GB", "英格兰": "GB", "UK": "GB", "荷兰": "NL", "韩国": "KR",
           "中国": "CN", "台湾": "TW", "中国台湾": "TW", "澳大利亚": "AU", "加拿大": "CA", "俄罗斯": "RU",
           "未知": "XX", "未知地区": "XX"}


class PolicyChanged(ValueError):
    pass


def region_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("地区应填写两位代码，例如 JP、HK、SG、US、DE、FR、GB、NL")
    code = ALIASES.get(value.strip(), value.strip().upper())
    matched = re.fullmatch(r"([A-Z]{2})(?:\d+)?", code)
    if not matched:
        raise ValueError("地区应填写两位代码；FR2 按 FR，英格兰按 GB")
    return matched[1]


def integer(value, minimum, maximum, title):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{title}必须是 {minimum} 至 {maximum} 的整数")
    return value


def validate(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"kind", "total", "regions", "append", "max_rounds"} or value.get("kind") != KIND:
        raise ValueError("地区发布设置格式错误")
    total = integer(value["total"], 1, 1000, "最终推送总数")
    maps = {}
    for name in ("regions", "append"):
        if not isinstance(value[name], dict) or len(value[name]) > 676:
            raise ValueError("地区设置格式错误")
        maps[name] = {}
        for code, number in value[name].items():
            normalized = region_code(code)
            if normalized in maps[name]:
                raise ValueError(f"地区 {normalized} 重复，请在同一行修改")
            maps[name][normalized] = integer(number, 0, 1000, f"{normalized} 数量")
    if sum(maps["append"].values()) > total:
        raise ValueError("优先追加数量合计不能超过最终推送总数；追加也计入总数")
    if any(number > maps["regions"].get(code, 1000) for code, number in maps["append"].items()):
        raise ValueError("优先追加数量不能超过该地区的推送上限")
    return {"kind": KIND, "total": total, **maps, "max_rounds": integer(value["max_rounds"], 1, 30, "自动获取轮数")}


def policy_path(settings):
    return settings["root"] / "data" / f"{settings.get('measurement_mode', 'proxy')}-publication.json"


def lock(settings):
    return RunLock(settings["root"] / "runtime/publication-policy" / settings.get("measurement_mode", "proxy"))


def current(settings) -> dict:
    path = policy_path(settings)
    if path.exists():
        return validate(json.loads(path.read_text(encoding="utf-8")))
    from .settings import current_rules
    rules = current_rules(settings)
    total = rules["publish_count"]
    return validate({"kind": KIND, "total": total, "regions": DEFAULT_CAPS,
                     "append": {"JP": min(10, total, rules["jp_publish_count"])}, "max_rounds": 3})


def editable(settings):
    try:
        with lock(settings):
            return True
    except ValueError:
        return False


def save(settings, value):
    policy = validate(value)
    try:
        with lock(settings):
            atomic_write_json(policy_path(settings), policy)
    except ValueError:
        raise ValueError("已开始上传，发布设置已锁定；完成或失败后可修改并重推") from None
    return policy


def country(record):
    return region_code(record.get("geo_country") or record.get("country") or "XX")


def select(records, policy, *, bounded=True):
    from .benchmark import ranking_key
    policy = validate(policy)
    seen, counts = set(), Counter()
    ranked = []
    for row in sorted((r for r in records if r.get("qualified")), key=ranking_key):
        code = country(row)
        if row["ip"] in seen or counts[code] >= policy["regions"].get(code, math.inf):
            continue
        if code == "JP" and (not row.get("geo_verified") or row.get("geo_conflict")):
            continue
        seen.add(row["ip"])
        counts[code] += 1
        ranked.append(row)
    reserved, reserve_counts = [], Counter()
    if bounded:
        for row in ranked:
            code = country(row)
            if reserve_counts[code] < policy["append"].get(code, 0):
                reserved.append(row)
                reserve_counts[code] += 1
        ids = {row["ip"] for row in reserved}
        chosen = [*reserved, *(row for row in ranked if row["ip"] not in ids)][:policy["total"]]
    else:
        ids, chosen = set(), ranked
    return [{**row, "lane": "jp_append" if row["ip"] in ids and country(row) == "JP" else "general",
             "publication_role": "append" if row["ip"] in ids else "ranked"} for row in sorted(chosen, key=ranking_key)]


def gate(records, policy, *, allow_partial=False):
    from .benchmark import ranking_key
    policy = validate(policy)
    if not (0 < len(records) <= policy["total"] if allow_partial else len(records) == policy["total"]):
        return False
    if len({row["ip"] for row in records}) != len(records) or not all(row.get("qualified") for row in records):
        return False
    counts = Counter(country(row) for row in records)
    appended = Counter(country(row) for row in records if row.get("publication_role") == "append")
    return (all(counts[code] <= cap for code, cap in policy["regions"].items())
            and all(count <= policy["append"].get(code, 0) for code, count in appended.items())
            and all(row.get("lane") in {"general", "jp_append"} and row.get("publication_role") in {"ranked", "append"} for row in records)
            and all(row.get("lane") == ("jp_append" if country(row) == "JP" and row.get("publication_role") == "append" else "general") for row in records)
            and all(row.get("geo_verified") and not row.get("geo_conflict") for row in records if country(row) == "JP")
            and records == sorted(records, key=ranking_key))


def preview(records, policy):
    counts = Counter(country(row) for row in records if row.get("qualified"))
    available = select(records, policy, bounded=False)
    selected = select(available, policy)
    return {"qualified": sum(counts.values()), "available": len(available), "selected": len(selected), "total": policy["total"],
            "by_region": dict(counts), "selected_by_region": dict(Counter(country(row) for row in selected))}
