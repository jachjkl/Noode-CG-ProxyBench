"""Local GitHub destinations and read-only connection checks; no credential storage."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from core.io_utils import atomic_write_json

DEFAULT_REPOSITORY = "jachjkl/Noode-CG-ProxyBench"
DEFAULT_BRANCH = "main"


def destination(repository: str, branch: str = DEFAULT_BRANCH) -> dict:
    if not isinstance(repository, str) or not isinstance(branch, str):
        raise ValueError("仓库地址与分支必须是文本")
    repository, branch = repository.strip(), branch.strip()
    if repository.startswith("https://"):
        url = urlsplit(repository)
        if url.hostname != "github.com" or url.username or url.password or url.query or url.fragment or url.port:
            raise ValueError("请输入 GitHub 官方仓库地址或账号/仓库名")
        repository = url.path.strip("/")
    repository = repository.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repository) or repository.split("/")[1] in {".", ".."}:
        raise ValueError("仓库格式应为 账号/仓库名，例如 your-account/your-repository")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}", branch) or ".." in branch or "//" in branch or branch.endswith(("/", ".", ".lock")):
        raise ValueError("请输入有效分支名，例如 main 或 release/v1")
    return {"repository": repository, "branch": branch}


def load_destination(root: Path, defaults=None) -> dict:
    path = root / "data/github-settings.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else (defaults or {})
    return destination(value.get("repository", DEFAULT_REPOSITORY), value.get("branch", DEFAULT_BRANCH))


def save_destination(root: Path, value: dict) -> dict:
    saved = destination(value.get("repository", ""), value.get("branch", DEFAULT_BRANCH))
    atomic_write_json(root / "data/github-settings.json", saved)
    return saved


def check_destination(client, target: dict) -> dict:
    target = destination(target["repository"], target["branch"])
    try:
        actor = client.command(["api", "user", "--jq", ".login"], timeout=8).strip()
    except Exception:
        raise ValueError("尚未登录 GitHub 或授权已失效；点击登录 GitHub 后重新检查") from None
    try:
        repository = client.command(["api", f"repos/{target['repository']}"], timeout=8, as_json=True)
    except Exception:
        raise ValueError("无法读取目标仓库：请检查账号/仓库名，以及该账号的访问权限") from None
    canonical = destination(repository.get("full_name", ""), target["branch"])
    if repository.get("archived") or repository.get("disabled"):
        raise ValueError("目标仓库已归档或已停用，不能推送")
    if not repository.get("permissions", {}).get("push"):
        raise ValueError("当前 GitHub 账号没有此仓库的写入权限，已测 IP 不会丢失")
    owner = canonical["repository"].split("/")[0]
    if actor.casefold() != owner.casefold():
        raise ValueError(f"当前登录 {actor}，云端任务仅允许仓库所有者 {owner} 运行；请切换账号")
    try:
        client.command(["api", f"repos/{canonical['repository']}/branches/{quote(target['branch'], safe='')}"], timeout=8, as_json=True)
    except Exception:
        raise ValueError("目标分支不存在，请在整体设置中修改分支") from None
    for workflow in ("proxybench.yml", "proxybench-publish.yml"):
        try:
            state = client.command(["api", f"repos/{canonical['repository']}/actions/workflows/{workflow}"], timeout=8, as_json=True)
            if state.get("state") != "active":
                raise ValueError
            client.command(["api", f"repos/{canonical['repository']}/contents/.github/workflows/{workflow}?ref={quote(target['branch'], safe='')}"], timeout=8, as_json=True)
        except Exception:
            raise ValueError(f"云端自动化尚未就绪：请按引导上传完整源码并启用 {workflow}") from None
    renamed = canonical["repository"].casefold() != target["repository"].casefold()
    return {**canonical, "status": "Ready", "account": actor, "requested_repository": target["repository"],
            "renamed": renamed, "message": (f"仓库已更名为 {canonical['repository']}；请保存检测到的地址" if renamed else "登录、仓库写权限、分支及两项云端任务检查通过")}
