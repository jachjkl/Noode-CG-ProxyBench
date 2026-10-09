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
from core.proxybench.export import ARTIFACTS, gate, nodes_text
from core.proxybench.modes import OUTPUTS, validate_limits

HANDOFF = {"data/handoff/proxybench-pool.json.gz", "data/handoff/proxybench-cloud-health.json"}
RESULTS = {"output/nodes.txt", "output/nodes.json", "output/nodes.csv", "output/api.json", "output/ip.zip",
           "output/health.json", "data/handoff/proxybench-attempted.json.gz"}
RESULTS.update(f"output/Nodes-TCP/{name}" for name in (*ARTIFACTS, "health.json"))


def result_prefix(files: dict[str, bytes]) -> str:
    paths = [prefix for prefix in OUTPUTS.values() if f"{prefix}/health.json" in files]
    if len(paths) != 1:
        raise ValueError("结果交接必须只包含一种测速方式的健康报告")
    prefix = paths[0]
    if any(name.startswith("output/") and (not name.startswith(prefix + "/") or "/" in name[len(prefix) + 1:]) for name in files):
        raise ValueError("禁止一种测速方式覆盖另一种结果目录")
    return prefix


def validate_result_files(files: dict[str, bytes]) -> None:
    prefix = result_prefix(files)
    health = json.loads(files[f"{prefix}/health.json"])
    expected_mode = "tcp_tls" if prefix == OUTPUTS["tcp_tls"] else "proxy"
    if health.get("measurement_mode", "proxy") != expected_mode:
        raise ValueError("测速方式与发布目录不一致")
    limits = validate_limits(health.get("publication_limits"))
    if health.get("published"):
        if {f"{prefix}/{name}" for name in ARTIFACTS} - files.keys():
            raise ValueError("发布结果缺少输出文件，必须包含 output/nodes.txt")
        records = json.loads(files[f"{prefix}/nodes.json"])
        if not gate(records, allow_partial=health.get("manual_publication") is True, limits=limits):
            raise ValueError("拒绝不满足所设发布数量和质量的结果")
        if any(row.get("measurement_mode", "proxy") != expected_mode for row in records):
            raise ValueError("不得混合不同测速方式的记录")
        if files[f"{prefix}/nodes.txt"] != nodes_text(records).encode("utf-8"):
            raise ValueError("nodes.txt 必须与优选结果一致，使用 IP:端口#国家代码 格式")
    elif any(name.startswith("output/") and name != f"{prefix}/health.json" for name in files):
        raise ValueError("未通过门槛的结果不能覆盖订阅")


def pack(root: Path, kind: str, mode="proxy") -> bytes:
    allowed = HANDOFF if kind == "handoff" else RESULTS
    if kind == "result":
        prefix = OUTPUTS[mode]
        health = json.loads((root / prefix / "health.json").read_text(encoding="utf-8"))
        allowed = {f"{prefix}/{name}" for name in (*ARTIFACTS, "health.json")} | {"data/handoff/proxybench-attempted.json.gz"}
        if health.get("published"):
            records = json.loads((root / prefix / "nodes.json").read_text(encoding="utf-8"))
            if not gate(records, allow_partial=health.get("manual_publication") is True, limits=health.get("publication_limits")):
                raise ValueError("云端发布门槛校验失败")
        else:
            allowed = {f"{prefix}/health.json", "data/handoff/proxybench-attempted.json.gz"}
    files = {relative: (root / relative).read_bytes() for relative in sorted(allowed) if (root / relative).is_file()}
    if kind == "result":
        validate_result_files(files)
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as package:
        for relative, data in files.items():
            package.writestr(relative, data)
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
            validate_result_files(files)
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
            files = {name: package.read(name) for name in package.namelist()}
            health = json.loads(files[f"{result_prefix(files)}/health.json"])
        values["needs_more"] = str(bool(health.get("needs_more"))).lower()
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
