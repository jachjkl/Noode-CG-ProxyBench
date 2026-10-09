from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.proxybench import VERSION
from scripts.package_sources import public_source_files

ROOT = Path(__file__).resolve().parent.parent


def package(destination: Path) -> list[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = public_source_files(ROOT)
    included = []
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            source = ROOT / name
            if name in {"output/nodes.txt", "output/Nodes-TCP/nodes.txt", "output/Npdex-Tcp/Tls.txt"}:
                archive.writestr("Noode-CG-ProxyBench/" + name, b"")
                included.append(name)
            elif source.is_file():
                archive.write(source, "Noode-CG-ProxyBench/" + name)
                included.append(name)
    return included


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path)
    path = parser.parse_args().destination or ROOT / f"dist/Noode-CG-ProxyBench-{VERSION}.zip"
    print(f"Packaged {len(package(path))} files: {path}")
