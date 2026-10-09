"""Keep UI and checkpoint I/O off the network measurement threads."""
from __future__ import annotations

import copy
import threading
import time
from collections import deque


class Observation:
    def __init__(self, update, completed):
        self.on_update = update
        self.on_completed = completed
        self.condition = threading.Condition()
        self.results = deque()
        self.latest = None
        self.closed = False
        self.error = None
        self.last_progress = 0.0
        self.results_since_progress = 0
        self.thread = threading.Thread(target=self.consume, name="benchmark-observer", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def update(self, **values):
        force = values.pop("_force", False)
        with self.condition:
            now = time.monotonic()
            if not force and now - self.last_progress < .2:
                return
            self.last_progress = now
            self.latest = copy.deepcopy(values)
            self.condition.notify()

    def completed(self, record):
        with self.condition:
            self.results.append(copy.deepcopy(record))
            self.condition.notify()

    def consume(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.results or self.latest is not None or self.closed)
                if self.latest is not None and (not self.results or self.results_since_progress >= 8):
                    callback, value = self.on_update, self.latest
                    self.latest = None
                    self.results_since_progress = 0
                elif self.results:
                    callback, value = self.on_completed, self.results.popleft()
                    self.results_since_progress += 1
                elif self.closed:
                    return
            try:
                if callback is self.on_update:
                    callback(**value)
                else:
                    callback(value)
            except BaseException as exc:
                self.error = self.error or exc

    def __exit__(self, exception_type, *_):
        with self.condition:
            self.closed = True
            self.condition.notify()
        # Complete every result callback before committing or handling stop.
        self.thread.join()
        if exception_type is None and self.error:
            raise self.error
