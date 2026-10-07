from __future__ import annotations

import argparse
import json
import sys

from api.server import serve
from core.config import ConfigError, load_config, resolve_path
from core.proxybench.pipeline import Pipeline, prepare
from core.proxybench.profile import ProxyProfile, safe_error
from core.proxybench.settings import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="noode-cg",
        description="验证 Cloudflare 边缘端点并生成 edgetunnel 地址订阅",
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("run", help="运行完整优选流水线")
    subparsers.add_parser("prepare-handoff", help="云端生成 10000 个官方候选并附加首次全量链接")
    subparsers.add_parser("local-select", help="本地复测交接池和上一轮 TOP100")
    subparsers.add_parser("validate", help="只验证配置")
    subparsers.add_parser("validate-profile", help="验证本机代理 Profile")
    subparsers.add_parser("validate-runtime", help="真实 1 / 10 / 100 Candidate 路径验收")
    subparsers.add_parser("resume", help="从安全 Checkpoint 继续真实代理优选")
    dashboard = subparsers.add_parser("dashboard", help="启动本机真实代理优选 Dashboard")
    dashboard.add_argument("--port", type=int, default=13337)
    dashboard.add_argument("--no-browser", action="store_true")
    dashboard.add_argument("--auto-start", action="store_true")
    subparsers.add_parser("auto-cloud", help="自动匹配代理、启动独立执行器、云端发现、本地实测和云端发布")
    server = subparsers.add_parser("serve", help="启动只读 HTTP API")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None:
        from pathlib import Path
        log = Path(__file__).parent / "runtime/dashboard-console.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = log.open("a", encoding="utf-8")
        sys.stderr = sys.stdout
    args = build_parser().parse_args(argv)
    command = args.command or "run"
    try:
        config = load_config(args.config)
        if command == "validate":
            print("配置验证通过")
            return 0
        if command == "serve":
            serve(args.host, args.port, resolve_path(config, config["paths"]["output"]))
            return 0
        settings = load_settings(args.config)
        if command == "validate-profile":
            print(json.dumps(ProxyProfile.load(settings["profile"]).summary(), ensure_ascii=False))
            return 0
        if command == "dashboard":
            sys.path.insert(0, str(settings["root"] / "windows-controller"))
            from dashboard_server import serve as serve_dashboard
            return serve_dashboard(settings["root"], "127.0.0.1", args.port, "jachjkl/Noode-CG-ProxyBench", "main", args.auto_start, not args.no_browser)
        if command == "auto-cloud":
            from core.proxybench.cloud import CloudController
            report = CloudController(settings).run()
        elif command == "prepare-handoff":
            import os
            report = prepare(settings, os.getenv("NOODE_CONTINUATION", "false").lower() == "true")
        elif command == "local-select":
            report = Pipeline(settings).run(resume=True, handoff=True)
        elif command == "validate-runtime":
            report = Pipeline(settings).validate_runtime()
        else:
            report = Pipeline(settings).run(resume=command == "resume")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if command == "validate-runtime" and not report.get("batch100_passed"):
            return 2
        if report.get("status") == "validation_required":
            return 2
        if config["pipeline"].get("fail_on_quality_gate", False) and report["status"] != "ok":
            return 2
        return 0
    except (ConfigError, OSError, ValueError) as exc:
        print(f"错误: {safe_error(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"错误: {safe_error(exc)}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
