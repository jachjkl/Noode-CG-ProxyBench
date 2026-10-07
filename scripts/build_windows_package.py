"""Build public and explicitly requested private Windows webpage packages separately."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(personal: bool = False) -> Path:
    profile_path = ROOT / "config/proxy-profile.local.yaml"
    if personal:
        from core.proxybench.profile import ProxyProfile
        ProxyProfile.load(profile_path)
    distribution = ROOT / "dist/Noode-CG-ProxyBench-Windows"
    app = distribution / "app"
    app.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
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
    instructions = "解压到任意本地目录，双击【开始自动优选.vbs】，在窗口点击【开始优选】。\n已内置 Mihomo、Python、GitHub CLI，无需手工安装内核。\n自动匹配代理、启动本机执行器，GitHub 云端获取 IP，本地三网站三轮与实际带宽测试，最终交回云端发布。\n两个固定来源每次打开只全量获取一次；后续只补新的10000个边缘IP，整次会话候选不重复。发布前新候选与上次普通100个IP重新实测竞争、日本10个最后追加；不足就继续补测，直到补齐或停止。\n每页显示300个IP，详细测量点击查看。首次运行下载本机执行器。GitHub使用本机jachjkl的登录授权。暂停和停止均保存状态；不足100个普通IP和10个日本IP不覆盖成功结果。\n"
    instructions += "此专用包已内置本机真实代理配置；请仅在自己的电脑使用和保存。\n" if personal else "此公开包不含个人代理配置；可自动读取本机配置。\n"
    (distribution / "运行说明.txt").write_text(instructions, encoding="utf-8")
    archive_path = ROOT / ("dist/Noode-CG-ProxyBench-专用版-1.0.0.zip" if personal else "dist/Noode-CG-ProxyBench-Windows-1.0.0.zip")
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in distribution.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(distribution).as_posix()
            # Rebuilding after a local test must never ship imported credentials or Runner registration files.
            if ".local." in relative or "/runner/" in relative or relative.startswith(("app/data/", "app/output/")) or "session-" in relative or relative.endswith(".log"):
                continue
            archive.write(path, "Noode-CG-ProxyBench-Windows/" + relative)
        if personal:
            archive.writestr("Noode-CG-ProxyBench-Windows/app/config/proxy-profile.local.yaml", profile_path.read_bytes())
    return archive_path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    print(build(personal="--personal" in sys.argv))
