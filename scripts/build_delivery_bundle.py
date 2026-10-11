"""Create one repair bundle containing cloud source, Windows packages and build inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.proxybench import VERSION
from scripts.build_windows_installer import build as build_installer
from scripts.build_windows_package import build as build_windows
from scripts.package_proxybench import package

ROOT = Path(__file__).resolve().parent.parent


def build_inputs(root: Path) -> list[Path]:
    runtime = root / "runtime"
    required = [runtime / "python-3.12.10-embed-amd64.zip", runtime / "gh-release.json",
                runtime / "mihomo/mihomo.exe", runtime / "mihomo/version.json"]
    required.extend(runtime.glob("gh_*_windows_amd64.zip"))
    required.extend(path for path in (runtime / "mihomo/mihomo.previous", runtime / "mihomo/previous-version.json") if path.exists())
    required.extend(path for path in (runtime / "wheels").glob("*.whl")
                    if path.name.lower().startswith(("pyyaml-", "psutil-")))
    wheels = [path.name.lower() for path in required if path.suffix == ".whl"]
    if (not any(name.startswith("pyyaml-") for name in wheels) or not any(name.startswith("psutil-") for name in wheels)
            or not list(runtime.glob("gh_*_windows_amd64.zip")) or any(not path.is_file() for path in required)):
        raise ValueError("缺少已验证的 Python、依赖、GitHub 工具或内核构建缓存")
    return sorted(required)


def assemble(destination: Path, *, windows: Path, installer: Path, source: Path,
             inputs: list[Path], personal: bool, root: Path = ROOT) -> Path:
    files = {f"本地测速/安装包/{windows.name}": windows, f"本地测速/安装包/{installer.name}": installer,
             f"云端部署/源码/{source.name}": source}
    files.update({f"构建缓存/{path.relative_to(root / 'runtime').as_posix()}": path for path in inputs})
    roles = {"windows_zip": f"本地测速/安装包/{windows.name}", "windows_exe": f"本地测速/安装包/{installer.name}",
             "cloud_source": f"云端部署/源码/{source.name}"}
    manifest = {"version": VERSION, "contains_local_profile": personal, "roles": roles,
                "files": [{"path": name, "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in sorted(files.items())]}
    guide = f"""# Noode-CG-ProxyBench {VERSION} 完整维护包

本包把本地安装包、云端完整源码、目录说明和已验证的构建缓存放在一起，方便后续修复。修复与重新打包均在解压后的工作区进行。

运行：打开“本地测速/安装包”中的 EXE；或解压同目录的 ZIP 后双击“开始自动优选.vbs”。

修复：双击“准备修复工作区.cmd”，生成“修复工作区/Noode-CG-ProxyBench”后编辑其中的源码。再次运行准备脚本会保留已有源码修改。修复后双击“重新打包.cmd”，新包写入修复工作区的 dist 文件夹。本包使用自带 Python 和依赖，无需单独安装 Python，也不要求工作区有 .git 目录。

本地界面：windows-controller/dashboard/proxybench.html、proxybench.js、proxybench.css 和 app.css；原有粒子上升、选中荧光与点击波纹均包含。
本地测速：core/proxybench/benchmark.py、direct_benchmark.py、controller.py、network_deadline.py、settings.py。顶部选择代理三网站、TCPing 直连或 TLS 直连（后两者二选一），最终总数与各地区推送上限在实测窗口下方独立设置、分别保存；每批 100 个 IP，不进行初筛。
五步流程与完成动画：core/proxybench/workflow.py、cloud.py、dashboard.py，以及本地界面的 proxybench.js、proxybench.css。
云端流程：.github/workflows/proxybench.yml、sources/、core/proxybench/pipeline.py。
输出与推送：core/proxybench/export.py、scripts/proxybench_channel.py；代理结果在 output/nodes.txt，TCPing／TLS 共用结果在 output/Npdex-Tcp/Tls.txt，每行如 82.139.242.5:443#DE。初始空文件不是已完成的优选结果。
发布设置：data/proxy-publication.json 与 data/tcp_tls-publication.json，关闭后保留；地区限制与最终排序由 core/proxybench/publication_policy.py、regional_pipeline.py 执行。
运行状态：代理 data/proxy-bench，免代理 data/tcp-bench；规则 data/proxybench-rules.json 与 data/tcpbench-rules.json；中文日志 logs/proxy-events.jsonl 与 logs/tcp_tls-events.jsonl，关闭后保留。
版本与打包：core/proxybench/__init__.py 中的 VERSION；scripts/build_windows_package.py、build_windows_installer.py、package_proxybench.py 和 build_delivery_bundle.py。修改版本时只需更新 VERSION。

构建缓存只包含 Python 压缩包、依赖安装包、GitHub 工具和 Mihomo 内核，不包含执行器注册、登录凭据、日志或测速运行状态。
{'这是含本机代理配置的专用包，保存在本机；云端源码压缩包不含代理鉴权。' if personal else '这是公开维护包，不含个人代理配置。'}

manifest.json 记录各文件的 SHA-256 与路径；目录结构.txt 列出实际文件。README 与开发文档在源码包中使用英文，网页界面使用中文。
"""
    tree = "Noode-CG-ProxyBench 完整维护包\n" + "\n".join(f"  {name}" for name in sorted(files))
    tree += "\n  manifest.json\n  修复与重新打包说明.md\n  目录结构.txt\n  准备修复工作区.cmd\n  重新打包.cmd\n  维护与重新打包.ps1\n"
    powershell = (root / "scripts/windows/Rebuild-Bundle.ps1").read_text(encoding="utf-8-sig").encode("utf-8-sig")
    prepare = '@echo off\r\nchcp 65001 >nul\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0维护与重新打包.ps1" -PrepareOnly\r\npause\r\n'
    rebuild = '@echo off\r\nchcp 65001 >nul\r\npowershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0维护与重新打包.ps1"\r\npause\r\n'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in files.items():
            archive.write(path, name)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        archive.writestr("修复与重新打包说明.md", guide.encode("utf-8"))
        archive.writestr("目录结构.txt", tree.encode("utf-8"))
        archive.writestr("维护与重新打包.ps1", powershell)
        archive.writestr("准备修复工作区.cmd", prepare.encode("utf-8"))
        archive.writestr("重新打包.cmd", rebuild.encode("utf-8"))
    return destination


def build(personal: bool = False) -> Path:
    source = ROOT / f"dist/Noode-CG-ProxyBench-{VERSION}.zip"
    package(source)
    windows = build_windows(personal)
    installer = build_installer(personal)
    destination = ROOT / "dist" / f"Noode-CG-ProxyBench-{'专用维护包' if personal else '完整维护包'}-{VERSION}.zip"
    return assemble(destination, windows=windows, installer=installer, source=source,
                    inputs=build_inputs(ROOT), personal=personal)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", action="store_true")
    print(build(parser.parse_args().personal))
