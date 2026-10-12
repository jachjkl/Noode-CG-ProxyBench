"""Official CLI device authorization with a code visible in the local window."""
from __future__ import annotations

import re
import subprocess
import threading

from .cloud_network import cloud_environment


def start(client, on_code):
    env = cloud_environment(root=client.root)
    # Login writes to the official CLI credential store; environment tokens cannot be reauthorized.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        env.pop(name, None)
    process = subprocess.Popen([client.gh, "auth", "login", "--web", "--clipboard", "--hostname", "github.com",
                                "--git-protocol", "https", "--scopes", "workflow"], cwd=client.root,
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    def read():
        received_code = False
        try:
            for line in process.stdout:
                if any(word in line.lower() for word in ("expired_token", "code has expired", "code expired")) or received_code and any(word in line.lower() for word in ("context deadline exceeded", "authentication timed out")):
                    process.device_expired = True
                if "code" in line.lower():
                    match = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", line)
                    if match:
                        received_code = True
                        on_code(process, match[1], "copied to clipboard" in line.lower())
        finally:
            process.stdout.close()
    threading.Thread(target=read, daemon=True).start()
    return process
