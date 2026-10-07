from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path

from core.io_utils import atomic_write_bytes, atomic_write_json


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.state = {}
        self.generation = 0
        self.partial = {}

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
        partial_path = self.root / "partial-batch.json"
        if partial_path.exists():
            partial = json.loads(partial_path.read_text(encoding="utf-8"))
            if partial.get("run_id") == self.state.get("run_id") and partial.get("phase") == self.state.get("phase"):
                self.partial = partial.get("results", {})
        return self.state

    def save_partial(self, result: dict) -> None:
        self.partial[result["key"]] = result
        atomic_write_json(self.root / "partial-batch.json", {"run_id": self.state["run_id"],
                                                             "phase": self.state["phase"], "results": self.partial})

    def commit(self) -> None:
        self.generation += 1
        name = f"generation-{self.generation:08d}.json.gz"
        content = gzip.compress(json.dumps(self.state, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0)
        atomic_write_bytes(self.root / name, content)
        atomic_write_json(self.root / "batch-state.json", {"generation": self.generation, "snapshot": name,
                                                          "sha256": hashlib.sha256(content).hexdigest()})
        self.partial = {}
        (self.root / "partial-batch.json").unlink(missing_ok=True)
        # These are derivative, inspectable views. The manifest above is the transaction boundary.
        for name, payload in (("candidate-pool", self.state.get("pool", [])),
                              ("attempted", self.state.get("results", {})),
                              ("qualified", [x for x in self.state.get("results", {}).values() if x.get("qualified")]),
                              ("benchmark-results", self.state.get("results", {}))):
            atomic_write_bytes(self.root / f"{name}.json.gz", gzip.compress(json.dumps(payload, ensure_ascii=False).encode(), mtime=0))
        # Retain current and previous generations; every target is a fixed child of the state root.
        for old in self.root.glob("generation-*.json.gz"):
            if old.name < f"generation-{max(0, self.generation - 2):08d}.json.gz":
                old.unlink()


class RunLock:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.handle = (root / "run.lock").open("a+b")

    def __enter__(self):
        self.handle.seek(0)
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
