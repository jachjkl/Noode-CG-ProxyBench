"""Read published cloud nodes in their persisted order; no writes or proxy credentials."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from core.io_utils import atomic_write_bytes, atomic_write_json
from scripts.sync_cloud_handoff import download, sources

from .cloud import REPOSITORY, CloudError
from .export import gate
from .modes import OUTPUTS, validate_limits


def read_published(client) -> dict:
    repository = client.settings.get("repository", REPOSITORY)
    branch = client.settings.get("branch", "main")
    prefix = OUTPUTS[client.settings.get("measurement_mode", "proxy")]
    ref = client.command(["api", f"repos/{repository}/commits/{quote(branch, safe='')}", "--jq", ".sha"]).strip()
    try:
        metadata = client.command(["api", f"repos/{repository}/contents/{prefix}/nodes.json?ref={ref}"], as_json=True)
    except CloudError:
        placeholder = client.command(["api", f"repos/{repository}/contents/{prefix}/nodes.txt?ref={ref}"], as_json=True)
        if placeholder.get("size") == 0:
            return {"status": "Empty", "nodes": [], "total": 0, "general": 0, "japan": 0, "message": "云端尚未发布合格 IP"}
        raise
    if metadata.get("encoding", "base64") != "base64":
        sha = metadata.get("sha", "")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise CloudError("云端大文件摘要格式错误")
        metadata = client.command(["api", f"repos/{repository}/git/blobs/{sha}"], as_json=True)
        if metadata.get("encoding") != "base64":
            raise CloudError("云端大文件编码不支持")
    content = base64.b64decode("".join(metadata["content"].split()), validate=True)
    expected = hashlib.sha256(content).hexdigest()
    target_id = hashlib.sha256(f"{repository}/{branch}".encode()).hexdigest()[:16]
    cached = client.settings["state_dir"] / f"cloud-published-{target_id}-nodes.json"
    try:
        download(cached, expected, sources(repository, ref, f"{prefix}/nodes.json"), timeout=6, emit=lambda _: None, checkpoint=client.control.checkpoint)
    except RuntimeError:
        # Private repositories and unavailable mirrors still have authenticated API content.
        client.control.checkpoint()
        atomic_write_bytes(cached, content)
    nodes = json.loads(cached.read_bytes())
    if not isinstance(nodes, list):
        raise CloudError("云端结果格式错误")
    if any(row.get("measurement_mode", "proxy") != client.settings.get("measurement_mode", "proxy") for row in nodes):
        raise CloudError("云端测速方式与当前选择不一致")
    partial = not gate(nodes) or any(row.get("publication_role") for row in nodes)
    if partial:
        health_meta = client.command(["api", f"repos/{repository}/contents/{prefix}/health.json?ref={ref}"], as_json=True)
        health = json.loads(base64.b64decode("".join(health_meta["content"].split()), validate=True))
        if not health.get("published"):
            health = health.get("last_good_publication", {})
        if not health.get("published") or not gate(nodes, allow_partial=health.get("manual_publication") is True, limits=validate_limits(health.get("publication_limits"))):
            raise CloudError("云端结果不满足自动发布门槛，也不是已确认的手动发布名单")
    # The JSON array order is the published order. Never sort historical nodes by fresh local values.
    return {"repository": repository, "branch": branch, "status": "Ready", "nodes": nodes, "total": len(nodes),
            "general": sum(row["lane"] == "general" for row in nodes), "japan": sum(row["lane"] == "jp_append" for row in nodes),
            "ref": ref, "synced_at": datetime.now(UTC).isoformat(),
            "message": "已读取云端实际名单，保持原始推送顺序"}


def refresh(client) -> dict:
    report = read_published(client)
    client.control.checkpoint()
    atomic_write_json(client.settings["state_dir"] / "cloud-published.json", report)
    return report
