"""Persist active optimization time; GUI lifetime is measured independently."""
from __future__ import annotations

import json
import time
from pathlib import Path

from core.io_utils import atomic_write_json


class RunClock:
    def __init__(self, path: Path, clock=time.monotonic) -> None:
        self.path = path
        self.clock = clock
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.elapsed = max(0.0, float(saved["elapsed_seconds"]))
        except (OSError, ValueError, KeyError, TypeError):
            self.elapsed = 0.0
        self.anchor = None  # Downtime after a crash/reopen never counts as active work.
        self.last_saved = self.clock()

    def seconds(self) -> float:
        return self.elapsed + (max(0.0, self.clock() - self.anchor) if self.anchor is not None else 0.0)

    def save(self) -> None:
        atomic_write_json(self.path, {"elapsed_seconds": self.seconds()})
        self.last_saved = self.clock()

    def start(self, *, reset=False) -> None:
        if reset:
            self.elapsed = 0.0
            self.anchor = None
        if self.anchor is None:
            self.anchor = self.clock()
        self.save()

    def stop(self) -> None:
        if self.anchor is not None:
            self.elapsed = self.seconds()
            self.anchor = None
            self.save()

    def snapshot(self, running: bool, paused: bool) -> dict:
        if not running or paused:
            self.stop()
        elif self.anchor is None:
            self.start()
        elif self.clock() - self.last_saved >= 5:
            self.save()
        return {"elapsed_seconds": self.seconds(), "active": self.anchor is not None}
