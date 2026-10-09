"""Read published cloud nodes in their persisted order; no writes or proxy credentials."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime

from core.io_utils import atomic_write_json
from scripts.sync_cloud_handoff import download, sources

from .cloud import REPOSITORY, CloudError
from .export import gate
from .modes import OUTPUTS, validate_limits


def read_published(client) -> dict:
    prefix = OUTPUTS[client.settings.get("measurement_mode", "proxy")]
    ref = client.command(["api", f"repos/{REPOSITORY}/commits/main", "--jq", ".sha"]).strip()
    try:
        metadata = client.command(["api", f"repos/{REPOSITORY}/contents/{prefix}/nodes.json?ref={ref}"], as_json=True)
    except CloudError:
        placeholder = client.command(["api", f"repos/{REPOSITORY}/contents/{prefix}/nodes.txt?ref={ref}"], as_json=True)
        if placeholder.get("size") == 0:
            return {"status": "Empty", "nodes": [], "total": 0, "general": 0, "japan": 0, "message": "云端尚未发布合格 IP"}
        raise
    if metadata.get("encoding", "base64") != "base64":
        sha = metadata.get("sha", "")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise CloudError("云端大文件摘要格式错误")
        metadata = client.command(["api", f"repos/{REPOSITORY}/git/blobs/{sha}"], as_json=True)
        if metadata.get("encoding") != "base64":
            raise CloudError("云端大文件编码不支持")
    content = base64.b64decode("".join(metadata["content"].split()), validate=True)
    expected = hashlib.sha256(content).hexdigest()
    cached = client.settings["state_dir"] / "cloud-published-nodes.json"
    download(cached, expected, sources(REPOSITORY, ref, f"{prefix}/nodes.json"), timeout=6, emit=lambda _: None, checkpoint=client.control.checkpoint)
    nodes = json.loads(cached.read_bytes())
    if not isinstance(nodes, list):
        raise CloudError("云端结果格式错误")
    if any(row.get("measurement_mode", "proxy") != client.settings.get("measurement_mode", "proxy") for row in nodes):
        raise CloudError("云端测速方式与当前选择不一致")
    partial = not gate(nodes)
    if partial:
        health_meta = client.command(["api", f"repos/{REPOSITORY}/contents/{prefix}/health.json?ref={ref}"], as_json=True)
        health = json.loads(base64.b64decode("".join(health_meta["content"].split()), validate=True))
        if not health.get("published") or not gate(nodes, allow_partial=health.get("manual_publication") is True, limits=validate_limits(health.get("publication_limits"))):
            raise CloudError("云端结果不满足自动发布门槛，也不是已确认的手动发布名单")
    # The JSON array order is the published order. Never sort historical nodes by fresh local values.
    return {"status": "Ready", "nodes": nodes, "total": len(nodes),
            "general": sum(row["lane"] == "general" for row in nodes), "japan": sum(row["lane"] == "jp_append" for row in nodes),
            "ref": ref, "synced_at": datetime.now(UTC).isoformat(),
            "message": "已读取云端实际名单，保持原始推送顺序"}


def refresh(client) -> dict:
    report = read_published(client)
    client.control.checkpoint()
    atomic_write_json(client.settings["state_dir"] / "cloud-published.json", report)
    return report
