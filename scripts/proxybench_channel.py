"""Allowlisted Runner control-channel payloads; no proxy credentials or runtime configs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.io_utils import atomic_write_bytes, atomic_write_json
from core.proxybench.export import gate

HANDOFF = {"data/handoff/proxybench-pool.json.gz", "data/handoff/proxybench-cloud-health.json"}
RESULTS = {"output/nodes.txt", "output/nodes.json", "output/nodes.csv", "output/api.json", "output/ip.zip",
           "output/health.json", "data/handoff/proxybench-attempted.json.gz"}


def pack(root: Path, kind: str) -> bytes:
    allowed = HANDOFF if kind == "handoff" else RESULTS
    if kind == "result":
        health = json.loads((root / "output/health.json").read_text(encoding="utf-8"))
        if health.get("published"):
            records = json.loads((root / "output/nodes.json").read_text(encoding="utf-8"))
            if not gate(records):
                raise ValueError("云端发布门槛校验失败")
        else:
            allowed = {"output/health.json", "data/handoff/proxybench-attempted.json.gz"}
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as package:
        for relative in sorted(allowed):
            source = root / relative
            if source.is_file():
                package.writestr(relative, source.read_bytes())
    return stream.getvalue()


def unpack(content: bytes, expected: str, root: Path, kind: str) -> None:
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("交接 SHA-256 不匹配")
    import io
    allowed = HANDOFF if kind == "handoff" else RESULTS
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) - allowed or sum(x.file_size for x in package.infolist()) > 64 * 1024 * 1024:
            raise ValueError("交接包成员不在白名单")
        # Validate every member and final gate before writing any repository output.
        files = {name: package.read(name) for name in names}
        if kind == "result":
            if "output/health.json" not in files:
                raise ValueError("缺少发布健康报告")
            health = json.loads(files["output/health.json"])
            if health.get("published"):
                if not gate(json.loads(files.get("output/nodes.json", b"[]"))):
                    raise ValueError("拒绝不满足 100+10+110 的发布结果")
            elif any(name.startswith("output/") and name != "output/health.json" for name in files):
                raise ValueError("未通过门槛的结果不能覆盖订阅")
        for name, data in files.items():
            atomic_write_bytes(root / name, data)


def emit_outputs(content: bytes, kind: str, root: Path) -> None:
    encoded = base64.b64encode(content).decode("ascii")
    if len(encoded) > 450000:
        raise ValueError("交接超过 Runner control channel 上限；保留本机 pending")
    values = {"sha256": hashlib.sha256(content).hexdigest()}
    values.update({f"payload_{index}": encoded[index * 75000:(index + 1) * 75000] for index in range(6)})
    if kind == "result":
        import io
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            health = json.loads(package.read("output/health.json"))
        values["needs_more"] = str(bool(health.get("needs_more")) and int(health.get("cycle", 30)) < 30).lower()
    output = Path(os.environ["GITHUB_OUTPUT"])
    with output.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["encode", "decode", "confirm"])
    parser.add_argument("--kind", choices=["handoff", "result"], default="result")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--file", type=Path)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--pending", type=Path)
    args = parser.parse_args()
    if args.mode == "confirm":
        manifest = args.pending / "manifest.json"
        payload = json.loads(manifest.read_text())
        if payload["sha256"] != args.sha256:
            raise ValueError("发布确认不对应本机 pending")
        (args.pending / "result.zip").unlink(missing_ok=True)
        manifest.unlink()
    elif args.mode == "encode":
        if args.pending and (args.pending / "manifest.json").exists():
            manifest = json.loads((args.pending / "manifest.json").read_text())
            content = (args.pending / "result.zip").read_bytes()
            if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
                raise ValueError("本机 pending 摘要错误")
        else:
            content = pack(args.root, args.kind)
            if args.pending:
                atomic_write_bytes(args.pending / "result.zip", content)
                atomic_write_json(args.pending / "manifest.json", {"sha256": hashlib.sha256(content).hexdigest()})
        emit_outputs(content, args.kind, args.root)
    else:
        encoded = args.file.read_text(encoding="utf-8").strip()
        content = base64.b64decode(encoded, validate=True)
        unpack(content, args.sha256, args.root, args.kind)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"交接失败：{type(exc).__name__}", file=sys.stderr)
        raise SystemExit(2)
