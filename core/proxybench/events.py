"""Bounded persistent Chinese event logs; never serialize profile data."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATES = {"Running": "运行中", "Stopped": "已停止并保存", "Failed": "运行失败", "Paused": "已暂停",
          "Loading Proxy": "正在加载候选节点", "Speed Testing": "正在测量下载速度", "completed": "本轮优选完成",
          "needs_more": "合格数量不足，准备补充候选", "Qualified": "通过", "Rejected Entry": "入口连接失败或延迟超限",
          "Rejected Loss": "请求失败率超限", "Rejected Latency": "平均延迟超限", "Rejected Speed": "下载速度不合格",
          "Rejected Jitter": "抖动超限", "Rejected TCP": "TCP 延迟、丢包或抖动不合格",
          "Rejected TLS": "TLS 握手、延迟或抖动不合格", "Preparing": "准备任务", "Dispatching": "请求云端",
          "Downloading": "下载候选", "Local": "本地实测", "Publishing": "准备推送", "Completed": "推送已确认",
          "Needs More": "等待补充候选", "TCP Testing": "正在测量三次 TCP 延迟、丢包和抖动",
          "TCP Passed": "TCP 延迟通过，等待下载测速", "TLS Passed": "TLS 延迟通过，等待下载测速", "TLS Testing": "正在测量三次 TLS 握手",
          "Direct Speed Testing": "正在直连测量下载速度", "Direct Location": "正在确认直连边缘位置"}


def chinese(value: str) -> str:
    if value in STATES:
        return STATES[value]
    if value.startswith("Round ") and ": " in value:
        number, site = value.removeprefix("Round ").split(": ", 1)
        return f"第 {number} 轮：检测{dict(google='谷歌', cloudflare='Cloudflare', github='GitHub').get(site, '网站')}响应"
    return value if any("\u4e00" <= c <= "\u9fff" for c in value) else f"状态更新：{value}" if value.endswith("Error") else "状态更新"


class EventLog:
    def __init__(self, root: Path, mode="proxy") -> None:
        self.root = root
        self.mode = mode
        self.path = root / "logs" / f"{mode}-events.jsonl"
        self.lock = threading.RLock()

    def append(self, message: str, *, level="info") -> None:
        record = {"time": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                  "level": level, "mode": self.mode, "message": message[:600]}
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size >= 5 * 1024 * 1024:
                self.path.with_suffix(".3.jsonl").unlink(missing_ok=True)
                for number in (2, 1):
                    old = self.path.with_suffix(f".{number}.jsonl")
                    if old.exists():
                        old.replace(self.path.with_suffix(f".{number + 1}.jsonl"))
                self.path.replace(self.path.with_suffix(".1.jsonl"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def tail(self, limit=150) -> list[dict]:
        with self.lock:
            if not self.path.exists():
                return []
            with self.path.open("rb") as stream:
                size = stream.seek(0, 2)
                offset = max(0, size - 160 * 1024)
                stream.seek(offset)
                data = stream.read().decode("utf-8", errors="replace").splitlines()
            if offset:
                data = data[1:]
            rows = []
            for line in data[-limit:]:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows
