"""Compile a one-file Windows installer from a reviewed public or personal package."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(personal: bool = False) -> Path:
    filename = "Noode-CG-ProxyBench-专用版-1.0.0" if personal else "Noode-CG-ProxyBench-Windows-1.0.0"
    archive = ROOT / "dist" / (filename + ".zip")
    destination = ROOT / "dist" / (filename + ".exe")
    framework = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319"
    subprocess.run([str(framework / "csc.exe"), "/nologo", "/target:winexe", "/optimize+",
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    f"/reference:{framework / 'System.IO.Compression.dll'}",
                    f"/resource:{archive},ProxyBenchPackage", f"/out:{destination}",
                    str(ROOT / "scripts/windows/ProxyBenchSetup.cs")], check=True, cwd=ROOT)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", action="store_true")
    args = parser.parse_args()
    print(build(args.personal))
