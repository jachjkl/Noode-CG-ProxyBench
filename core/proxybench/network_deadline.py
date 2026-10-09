"""Bound blocking socket operations, including peers that trickle response bytes."""
from __future__ import annotations

import socket
import threading


class SocketDeadline:
    def __init__(self, connection, seconds: float):
        self.connection = connection
        self.transports = []
        self.expired = threading.Event()
        self.timer = threading.Timer(seconds, self.abort)
        self.timer.daemon = True

    def __enter__(self):
        self.timer.start()
        return self

    def watch(self, transport):
        self.transports.append(transport)

    def abort(self):
        self.expired.set()
        for transport in [getattr(self.connection, "sock", None), *self.transports]:
            if transport is None:
                continue
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                transport.close()
            except OSError:
                pass

    def check(self):
        if self.expired.is_set():
            raise TimeoutError("网络操作超过总时限")

    def __exit__(self, *_):
        self.timer.cancel()
        self.timer.join()
