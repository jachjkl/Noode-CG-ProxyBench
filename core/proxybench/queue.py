from __future__ import annotations

import gzip
import json

from core.io_utils import atomic_write_bytes
from sources.common import merge


def accumulate(settings: dict) -> dict:
    handoff = settings["root"] / "data/handoff/proxybench-pool.json.gz"
    incoming = json.loads(gzip.decompress(handoff.read_bytes()))
    path = settings["state_dir"] / "cloud-candidate-queue.json.gz"
    queued = json.loads(gzip.decompress(path.read_bytes())) if path.exists() else {}
    session = incoming["report"].get("session_id", incoming["report"].get("seed"))
    prior_session = queued.get("report", {}).get("session_id", queued.get("report", {}).get("seed"))
    if session != prior_session:
        queued = {"pool": []}
    # The first complete feeds survive failed validation and later fresh handoffs.
    pool = merge([*queued.get("pool", []), *incoming["pool"]])
    payload = {"pool": pool, "report": incoming["report"], "incumbents": incoming.get("incumbents", [])}
    atomic_write_bytes(path, gzip.compress(json.dumps(payload).encode(), mtime=0))
    return {"session_id": session, "queued_candidate_count": len(pool), "cycle": incoming["report"].get("cycle", 1)}
