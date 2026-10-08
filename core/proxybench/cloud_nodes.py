"""Read published cloud nodes in their persisted order; no writes or proxy credentials."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime

from core.io_utils import atomic_write_json
from scripts.sync_cloud_handoff import download, sources

from .cloud import REPOSITORY, CloudError
from .export import gate


def read_published(client) -> dict:
    ref = client.command(["api", f"repos/{REPOSITORY}/commits/main", "--jq", ".sha"]).strip()
    try:
        metadata = client.command(["api", f"repos/{REPOSITORY}/contents/output/nodes.json?ref={ref}"], as_json=True)
    except CloudError:
        placeholder = client.command(["api", f"repos/{REPOSITORY}/contents/output/nodes.txt?ref={ref}"], as_json=True)
        if placeholder.get("size") == 0:
            return {"status": "Empty", "nodes": [], "total": 0, "general": 0, "japan": 0, "message": "云端尚未发布合格 IP"}
        raise
    content = base64.b64decode("".join(metadata["content"].split()), validate=True)
    expected = hashlib.sha256(content).hexdigest()
    cached = client.settings["state_dir"] / "cloud-published-nodes.json"
    download(cached, expected, sources(REPOSITORY, ref, "output/nodes.json"), timeout=6, emit=lambda _: None, checkpoint=client.control.checkpoint)
    nodes = json.loads(cached.read_bytes())
    if not isinstance(nodes, list):
        raise CloudError("云端结果格式错误")
    partial = not gate(nodes)
    if partial:
        health_meta = client.command(["api", f"repos/{REPOSITORY}/contents/output/health.json?ref={ref}"], as_json=True)
        health = json.loads(base64.b64decode("".join(health_meta["content"].split()), validate=True))
        if health.get("manual_publication") is not True or not health.get("published") or not gate(nodes, allow_partial=True):
            raise CloudError("云端结果不满足自动发布门槛，也不是已确认的手动发布名单")
    # The JSON array order is the published order. Never sort historical nodes by fresh local values.
    return {"status": "Ready", "nodes": nodes, "total": len(nodes),
            "general": sum(row["lane"] == "general" for row in nodes), "japan": sum(row["lane"] == "jp_append" for row in nodes),
            "ref": ref, "synced_at": datetime.now(UTC).isoformat(),
            "message": "已读取手动推送的实际名单，保持原始顺序" if partial else "已读取云端原始发布顺序"}


def refresh(client) -> dict:
    report = read_published(client)
    client.control.checkpoint()
    atomic_write_json(client.settings["state_dir"] / "cloud-published.json", report)
    return report
