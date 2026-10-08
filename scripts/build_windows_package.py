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
    instructions = "EXE将运行目录放在自身旁边；ZIP解压到任意本地目录，双击【开始自动优选.vbs】，在窗口点击【开始优选】。\n已内置 Mihomo、Python、GitHub CLI，无需手工安装内核。\n自动匹配代理、启动本机执行器，GitHub 云端获取 IP，本地三网站三轮与旧安装包的小样本网速测试，最终交回云端发布。\n网速沿用旧包参数：一次512 KiB样本、95%正文完整度、默认3 Mbps；入口200毫秒仅用于优先排序，不淘汰可连通的稍慢IP；三站统一延迟平均2500毫秒，先初筛再复测；没有另加带宽验收关卡。\n两个固定来源每次打开只全量获取一次；后续只补新的10000个边缘IP，整次会话候选不重复。发布前新候选与上次普通100个IP重新实测竞争、日本10个最后追加；不足就继续补测，直到补齐或停止。\n每页显示300个IP，详细测量点击查看。首次运行下载本机执行器。GitHub使用本机jachjkl的登录授权。正常关闭清理候选缓存与断点；异常中断、报错或主动停止保存可恢复。左右两个窗口独立分页并实时显示测量。每次运行检查代理与内核更新；不足100个普通IP和10个日本IP不覆盖成功结果。\n"
    instructions += "此专用包已内置本机真实代理配置；请仅在自己的电脑使用和保存。\n" if personal else "此公开包不含个人代理配置；可自动读取本机配置。\n"
    instructions = instructions.replace("自动匹配代理、启动本机执行器", "自动匹配代理并检测已有 VPN 环境")
    instructions = instructions.replace("首次运行下载本机执行器。", "多镜像下载候选；本地测速独立运行，不依赖 GitHub 执行器心跳。")
    instructions = instructions.replace("本地三网站三轮", "本地每站至少五次连接")
    instructions = instructions.replace("入口200毫秒仅用于优先排序，不淘汰可连通的稍慢IP；三站统一延迟平均2500毫秒", "入口严格按保存上限筛选；每站至少测五次，分别去掉最高最低，再将三个网站的平均值合并，默认综合上限200毫秒")
    instructions += "规则逐项提供中文说明，保存后再次打开仍使用。云端已发布名单单独显示数量和原始排名；普通取前100，日本另取前10，均按同一规则复测后推送。完成步骤沿用原包底部荧光与上升粒子，去掉扫光。\n"
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
