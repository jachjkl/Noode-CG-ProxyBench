"""Build public and explicitly requested private Windows webpage packages separately."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.proxybench import VERSION
from scripts.package_sources import SOURCE_OUTPUTS, public_source_files

ROOT = Path(__file__).resolve().parent.parent


def build(personal: bool = False) -> Path:
    profile_path = ROOT / "config/proxy-profile.local.yaml"
    if personal:
        from core.proxybench.profile import ProxyProfile
        ProxyProfile.load(profile_path)
    distribution = ROOT / "dist/Noode-CG-ProxyBench-Windows"
    app = distribution / "app"
    app.mkdir(parents=True, exist_ok=True)
    tracked = public_source_files(ROOT)
    for name in tracked:
        if not name or name.startswith(("data/", "output/", "runtime/", "dist/", ".git/")) or ".local." in name:
            continue
        path = ROOT / name
        if path.is_file():
            target = app / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    python_zip = ROOT / "runtime/python-3.12.10-embed-amd64.zip"
    # Digest published on the official Python release download table; TLS and ZIP CRC also checked.
    if hashlib.md5(python_zip.read_bytes()).hexdigest() != "fe8ef205f2e9c3ba44d0cf9954e1abd3":
        raise ValueError("Official embedded Python archive checksum mismatch")
    python = distribution / "runtime/python"
    python.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(python_zip) as package:
        package.extractall(python)
    (python / "python312._pth").write_text("python312.zip\n.\nLib/site-packages\n../../app\nimport site\n", encoding="utf-8")
    dependencies = python / "Lib/site-packages"
    dependencies.mkdir(parents=True, exist_ok=True)
    for wheel in (ROOT / "runtime/wheels").glob("*.whl"):
        with zipfile.ZipFile(wheel) as package:
            package.extractall(dependencies)
    core = app / "runtime/mihomo"
    core.mkdir(parents=True, exist_ok=True)
    for name in ("mihomo.exe", "version.json"):
        shutil.copy2(ROOT / "runtime/mihomo" / name, core / name)
    gh_zip = next((ROOT / "runtime").glob("gh_*_windows_amd64.zip"))
    release = json.loads((ROOT / "runtime/gh-release.json").read_text(encoding="utf-8"))
    asset = next(x for x in release["assets"] if x["name"] == gh_zip.name)
    if hashlib.sha256(gh_zip.read_bytes()).hexdigest() != asset["digest"].removeprefix("sha256:"):
        raise ValueError("GitHub CLI official digest mismatch")
    with zipfile.ZipFile(gh_zip) as package:
        executable = next(name for name in package.namelist() if name.endswith("bin/gh.exe"))
        target = app / "runtime/gh/bin/gh.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.read(executable))
    # Windows' native curl uses system TLS and is explicitly directed to the owned local Mihomo proxy.
    curl = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/curl.exe"
    if curl.exists():
        target = app / "runtime/curl/curl.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(curl, target)
    vbs = '''Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = root & "\\runtime\\python\\pythonw.exe"
main = root & "\\app\\main.py"
config = root & "\\app\\config.yaml"
shell.CurrentDirectory = root & "\\app"
command = Chr(34) & python & Chr(34) & " -X utf8 " & Chr(34) & main & Chr(34) & " --config " & Chr(34) & config & Chr(34) & " dashboard"
shell.Run command, 0, False
'''
    (distribution / "开始自动优选.vbs").write_text(vbs, encoding="utf-16")
    (distribution / "Start-ProxyBench.vbs").write_text(vbs, encoding="utf-16")
    (distribution / "开始自动优选.cmd").write_text('@echo off\r\nstart "" wscript.exe "%~dp0Start-ProxyBench.vbs"\r\n', encoding="ascii")
    instructions = """EXE 将软件目录解压到自身旁边；ZIP 可解压到任意本地目录，双击【开始自动优选.vbs】。不会固定解压到桌面。
已内置 Mihomo、Python、GitHub CLI。点击【开始优选】，自动读取代理、检查内核更新，云端获取 IP，通过多镜像下载后在本机独立测速。
默认规则采用当前保存的设置：入口上限 300 毫秒，三站平均上限 300 毫秒，每站 5 次，去掉一次最高和最低后取中间三次平均，三站均值再平均。请求失败率 0%，网速至少 3.01 Mbps。
网速沿用原安装包：一次 512 KiB 样本，至少 95% 正文完成，I/O 超时 8 秒，正文计时上限 7 秒。所有规则均有中文解释，保存后再次打开继续使用。
两个固定来源每次打开只获取一次全量 IP；自动补充和继续获取均获取 10000 个本窗口未获取过的边缘 IP。
【停止并保存】只停止并保留已测结果与断点，不自动推送。【手动推送】复测已有结果并按实际合格数量推送，不获取新 IP；运行中点击会在当前批次完成后执行。最多 100 个常规 IP 和 10 个追加日本 IP，质量规则不放宽。自动优选仍补足 100＋10 后发布。
运行计时器显示优选累计时间和软件打开时长；暂停不计入优选时间，恢复时继续计时，重新开始会清零。推送失败保留待发布包，手动推送可重传。
左右列表独立分页，每页 300 个 IP，云端结果显示实际数量和原推送排名。步骤完成保留底部荧光与上升粒子效果。
正常关闭清除候选缓存；异常中断、报错或主动停止保存保留断点。真实代理参数只保存在本机。
"""
    instructions += "这是含本机代理配置的专用包，请仅保存在自己的电脑。\n" if personal else "公开包不含个人代理配置，可自动读取本机配置。\n"
    (distribution / "运行说明.txt").write_text(instructions, encoding="utf-8")
    archive_path = ROOT / "dist" / f"Noode-CG-ProxyBench-{'专用版' if personal else 'Windows'}-{VERSION}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in distribution.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(distribution).as_posix()
            app_runtime = {"app/runtime/mihomo/mihomo.exe", "app/runtime/mihomo/version.json", "app/runtime/gh/bin/gh.exe", "app/runtime/curl/curl.exe"}
            if relative.startswith("app/") and relative[4:] not in tracked and relative not in app_runtime:
                continue  # A previous staging build must not reintroduce removed code or runtime state.
            # Rebuilding after a local test must never ship imported credentials or Runner registration files.
            if "__pycache__" in path.parts or ".local." in relative or "/runner/" in relative or relative.startswith(("app/data/", "app/output/")) or "session-" in relative or relative.endswith(".log"):
                continue
            archive.write(path, "Noode-CG-ProxyBench-Windows/" + relative)
        for name in sorted(SOURCE_OUTPUTS):
            source = ROOT / name
            if name == "output/nodes.txt" or source.is_file():
                archive.writestr("Noode-CG-ProxyBench-Windows/app/" + name, b"" if name == "output/nodes.txt" else source.read_bytes())
        if personal:
            archive.writestr("Noode-CG-ProxyBench-Windows/app/config/proxy-profile.local.yaml", profile_path.read_bytes())
    return archive_path


if __name__ == "__main__":
    print(build(personal="--personal" in sys.argv))
