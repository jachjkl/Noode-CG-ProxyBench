from __future__ import annotations

import time

from .common import candidates, fetch

FIXED = (("fixed-source-a", "https://zip.cm.edu.kg/all.txt"),
         ("fixed-source-b", "https://bestcf.pages.dev/lzj/all.txt"))


def collect(port: int, downloader=fetch) -> tuple[list[dict], dict]:
    records = []
    counts = {}
    for name, url in FIXED:
        for attempt in range(3):
            try:
                parsed = candidates(downloader(url), name, port)
                if not parsed:
                    raise ValueError("固定源没有有效 IPv4 Candidate")
                records.extend(parsed)
                counts[name] = len({item["ip"] for item in parsed})
                break
            except Exception:
                if attempt == 2:
                    raise ValueError(f"核心 Source 获取失败：{name}；未使用缓存替代本轮全量") from None
                time.sleep(0.25)
    return records, counts
