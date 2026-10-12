"""Validate full cloud acquisitions before any local measurements start."""
from __future__ import annotations

from collections import defaultdict

from sources.fixed_full import FIXED


def validate(payload, *, session_id, fetch_id, initial_full, official_count=10000):
    report = payload.get("report", {})
    if report.get("session_id") != session_id or report.get("fetch_id") != fetch_id:
        raise ValueError("候选文件与当前请求不匹配，未开始测速；请重试获取")
    rows = payload.get("pool", [])
    addresses = {(row["ip"], row["port"]) for row in rows}
    by_source = defaultdict(set)
    for row in rows:
        for name in row.get("source_names", []):
            by_source[name].add(row["ip"])
    if len(addresses) != len(rows) or report.get("unique_candidate_count") != len(rows):
        raise ValueError("候选数量校验失败，未开始测速；请重试获取")
    if len(by_source["cloudflare-official"]) != official_count or report.get("cloudflare_official_count") != official_count:
        raise ValueError("官方候选未完整获取 10,000 个，未开始测速；已保留获取断点")
    if initial_full:
        counts = report.get("fixed_sources", {})
        if not report.get("fixed_fetched_this_round") or report.get("cycle") != 1 or report.get("continuation"):
            raise ValueError("本次首次获取缺少两个完整链接，未开始测速；请重试全量获取")
        for name, _ in FIXED:
            if not counts.get(name) or len(by_source[name]) != counts[name]:
                raise ValueError("固定链接未全量获取，未开始测速；已保留获取断点")
    return report
