"""Public source enumeration also supports extracted archives without a Git checkout."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

SOURCE_OUTPUTS = {"output/README.md", "output/nodes.txt"}
EXCLUDED_ROOTS = {"data", "runtime", "dist", "dashboard-cache", "logs"}
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}


def allowed_source(name: str) -> bool:
    path = Path(name)
    return (bool(name) and bool(path.parts) and not path.is_absolute() and ".." not in path.parts
            and path.parts[0] not in EXCLUDED_ROOTS and not (set(path.parts) & EXCLUDED_PARTS)
            and (path.parts[0] != "output" or name in SOURCE_OUTPUTS)
            and ".local." not in name and not path.name.startswith(".env")
            and path.suffix not in {".log", ".pyc", ".pyo"})


def public_source_files(root: Path) -> list[str]:
    root = root.resolve()
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        if Path(top).resolve() != root:
            raise ValueError("The enclosing checkout is not this extracted project")
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    except (OSError, ValueError, subprocess.CalledProcessError):
        names = []
        for directory, directories, files in os.walk(root):
            relative = Path(directory).relative_to(root)
            directories[:] = [name for name in directories if name not in EXCLUDED_PARTS
                              and not (relative == Path(".") and name in EXCLUDED_ROOTS)]
            names.extend((relative / name).as_posix() for name in files)
    return sorted({name for name in names if allowed_source(name) and (root / name).is_file()} | {"output/nodes.txt"})
