from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

from core.io_utils import atomic_write_bytes, atomic_write_json


def partial_results(root: Path, run_id, phase) -> dict:
    results = {}
    old = root / "partial-batch.json"
    if old.exists():
        payload = json.loads(old.read_text(encoding="utf-8"))
        if payload.get("run_id") == run_id and payload.get("phase") == phase:
            results.update(payload.get("results", {}))
    journal = root / "partial-batch.jsonl"
    if journal.exists():
        for line in journal.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                break  # An abrupt exit can truncate only the final append.
            payload = json.loads(line)
            if payload.get("run_id") == run_id and payload.get("phase") == phase:
                results[payload["result"]["key"]] = payload["result"]
    return results


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.state = {}
        self.generation = 0
        self.partial = {}
        self.pool_digest = None
        self.partial_ready = False

    def load(self) -> dict:
        pointer = self.root / "batch-state.json"
        if not pointer.exists():
            return {}
        manifest = json.loads(pointer.read_text(encoding="utf-8"))
        name = manifest["snapshot"]
        if Path(name).name != name or not name.startswith("generation-"):
            raise ValueError("非法 Checkpoint 路径")
        content = (self.root / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
            raise ValueError("Checkpoint 摘要不匹配；保留 Last Good")
        self.state = json.loads(gzip.decompress(content))
        self.generation = manifest["generation"]
        self.partial = partial_results(self.root, self.state.get("run_id"), self.state.get("phase"))
        return self.state

    def save_partial(self, result: dict) -> None:
        self.partial[result["key"]] = result
        journal = self.root / "partial-batch.jsonl"
        if not self.partial_ready:
            if journal.exists():
                content = journal.read_bytes()
                if content and not content.endswith(b"\n"):
                    with journal.open("r+b") as stream:
                        stream.truncate(content.rfind(b"\n") + 1)
            self.partial_ready = True
        line = json.dumps({"run_id": self.state["run_id"], "phase": self.state["phase"], "result": result}, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        with journal.open("ab") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def commit(self) -> None:
        self.generation += 1
        name = f"generation-{self.generation:08d}.json.gz"
        content = gzip.compress(json.dumps(self.state, ensure_ascii=False, separators=(",", ":")).encode(), compresslevel=1, mtime=0)
        atomic_write_bytes(self.root / name, content)
        atomic_write_json(self.root / "batch-state.json", {"generation": self.generation, "snapshot": name,
                                                          "sha256": hashlib.sha256(content).hexdigest()})
        self.partial = {}
        (self.root / "partial-batch.json").unlink(missing_ok=True)
        (self.root / "partial-batch.jsonl").unlink(missing_ok=True)
        # These are derivative, inspectable views. The manifest above is the transaction boundary.
        pool = json.dumps(self.state.get("pool", []), ensure_ascii=False).encode()
        digest = hashlib.sha256(pool).digest()
        if digest != self.pool_digest or not (self.root / "candidate-pool.json.gz").exists():
            atomic_write_bytes(self.root / "candidate-pool.json.gz", gzip.compress(pool, compresslevel=1, mtime=0))
            self.pool_digest = digest
        results = self.state.get("results", {})
        content = gzip.compress(json.dumps(results, ensure_ascii=False).encode(), compresslevel=1, mtime=0)
        for name in ("attempted", "benchmark-results"):
            atomic_write_bytes(self.root / f"{name}.json.gz", content)
        qualified = [x for x in results.values() if x.get("qualified")]
        atomic_write_bytes(self.root / "qualified.json.gz", gzip.compress(json.dumps(qualified, ensure_ascii=False).encode(), compresslevel=1, mtime=0))
        atomic_write_bytes(self.root / "processed.json.gz", gzip.compress(json.dumps(self.state.get("processed", {}).get("results", {})).encode(), compresslevel=1, mtime=0))
        # Retain current and previous generations; every target is a fixed child of the state root.
        for old in self.root.glob("generation-*.json.gz"):
            if old.name < f"generation-{max(0, self.generation - 2):08d}.json.gz":
                old.unlink()


class RunLock:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.handle = (root / "run.lock").open("a+b")

    def __enter__(self):
        # Do not write an existing Windows byte range before acquiring its lock.
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError("已有 ProxyBench 任务正在运行") from None
        return self

    def __exit__(self, *_):
        self.handle.close()


class Stopped(Exception):
    pass


class Control:
    def __init__(self, root: Path, update=None) -> None:
        self.path = root / "control.json"
        self.update = update or (lambda **_: None)
        self.announced_status = None

    def publication_requested(self) -> bool:
        request = self.path.with_name("publish-request.json")
        return request.exists() and json.loads(request.read_text(encoding="utf-8")).get("requested") is True

    def announce(self, status: str) -> None:
        if status != self.announced_status:
            self.announced_status = status
            self.update(status=status)

    def checkpoint(self) -> None:
        while self.path.exists():
            action = json.loads(self.path.read_text(encoding="utf-8")).get("action")
            if action == "stop":
                raise Stopped
            if action != "pause":
                return
            self.announce("Paused")
            time.sleep(0.2)
        self.announce("Running")

    async def async_checkpoint(self) -> None:
        while self.path.exists():
            action = json.loads(self.path.read_text(encoding="utf-8")).get("action")
            if action == "stop":
                raise Stopped
            if action != "pause":
                return
            self.announce("Paused")
            await asyncio.sleep(.2)
        self.announce("Running")
