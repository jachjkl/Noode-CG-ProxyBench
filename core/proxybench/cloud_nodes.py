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
    if not isinstance(nodes, list) or not gate(nodes):
        raise CloudError("云端结果未满足普通100个和日本10个，不能当作已发布合格名单")
    # The JSON array order is the published order. Never sort historical nodes by fresh local values.
    return {"status": "Ready", "nodes": nodes, "total": len(nodes), "general": 100, "japan": 10,
            "ref": ref, "synced_at": datetime.now(UTC).isoformat(), "message": "已读取云端原始发布顺序"}


def refresh(client) -> dict:
    report = read_published(client)
    client.control.checkpoint()
    atomic_write_json(client.settings["state_dir"] / "cloud-published.json", report)
    return report
