from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def package(destination: Path) -> list[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
    included = []
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            if not name or name.startswith(("data/", "output/", "runtime/", "dist/", ".git/")) or ".local." in name:
                continue
            source = ROOT / name
            if source.is_file():
                archive.write(source, "Noode-CG-ProxyBench/" + name)
                included.append(name)
    return included


if __name__ == "__main__":
    path = ROOT / "dist/Noode-CG-ProxyBench-1.0.1.zip"
    print(f"Packaged {len(package(path))} files: {path}")
