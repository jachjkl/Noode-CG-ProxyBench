"""Check the isolated rule-mode core. Speed is measured during candidate selection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.proxybench.pipeline import Pipeline
from core.proxybench.profile import safe_error
from core.proxybench.settings import load_settings


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        report = Pipeline(load_settings(Path(__file__).resolve().parent.parent / "config.yaml")).validate_runtime()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("runtime_ready") else 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": safe_error(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
