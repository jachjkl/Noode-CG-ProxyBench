from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import zipfile
from pathlib import Path

from core.io_utils import atomic_write_json

from .cloud_network import cloud_environment
from .execution import cli_python
from .github_destination import DEFAULT_REPOSITORY, load_destination
from .mihomo_manager import owned_core_running
from .profile import ProxyProfile, discover_profiles, import_discovered, refresh_existing, safe_error
from .state import Control, RunLock, Stopped, Store

REPOSITORY = DEFAULT_REPOSITORY


class CloudError(ValueError):
    pass


class CloudController:
    """Owner-authenticated dispatch with a separate, application-owned Windows runner."""
    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.root = settings["root"]
        target = load_destination(self.root, {"repository": settings.get("repository", REPOSITORY), "branch": settings.get("branch", "main")})
        self.settings.update(target)
        self.repository, self.branch = target["repository"], target["branch"]
        self.runner_root = self.root / "runtime/runner" if self.repository == REPOSITORY else self.root / "runtime/runner-targets" / hashlib.sha256(self.repository.casefold().encode()).hexdigest()[:16]
        bundled = self.root / "runtime/gh/bin/gh.exe"
        self.gh = str(bundled) if bundled.exists() else shutil.which("gh")
        self.runner = None
        self.log = None
        self.run_id = None
        self.live = {}
        self.diag_offsets = {}
        self.control = Control(settings["state_dir"])

    def update(self, **values) -> None:
        path = self.settings["state_dir"] / "cloud-live.json"
        if values.get("status") == "Dispatching":
            self.live = {}
        self.live.update(repository=self.repository, **values)
        atomic_write_json(path, self.live)

    def command(self, args: list[str], *, timeout: float = 30, as_json: bool = False):
        if not self.gh:
            raise CloudError("缺少 GitHub CLI；请使用完整 Windows 运行包")
        writing = args[:2] == ["workflow", "run"] or (args[:1] == ["api"] and "--method" in args and args[args.index("--method") + 1] != "GET")
        if writing:
            actor = self.command(["api", "user", "--jq", ".login"], timeout=8).strip()
            if actor.casefold() != self.repository.split("/")[0].casefold():
                raise CloudError("当前 GitHub 登录账号与目标仓库所有者不一致；请在整体设置中登录正确账号，已测 IP 已保留")
        result = subprocess.run([self.gh, *args], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
                                env=cloud_environment(),
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise CloudError("GitHub 连接或账户授权失败")
        return json.loads(result.stdout) if as_json and result.stdout.strip() else result.stdout

    def prepare_runner(self) -> None:
        if os.name != "nt":
            raise CloudError("本地自动控制器需要 Windows")
        actor = self.command(["api", "user", "--jq", ".login"]).strip()
        if actor.casefold() != self.repository.split("/")[0].casefold():
            raise CloudError("请登录目标仓库的所有者账号，再开始云端任务")
        self.runner_root.mkdir(parents=True, exist_ok=True)
        executable = self.runner_root / "bin/Runner.Listener.exe"
        if not executable.exists():
            self.update(stage="下载独立 Windows Runner", status="Preparing")
            release = self.command(["api", "repos/actions/runner/releases/latest"], as_json=True)
            if release.get("prerelease") or release.get("draft"):
                raise CloudError("拒绝非正式 Runner")
            asset = next(x for x in release["assets"] if x["name"].startswith("actions-runner-win-x64-") and x["name"].endswith(".zip"))
            archive = self.runner_root / asset["name"]
            self.command(["release", "download", release["tag_name"], "--repo", "actions/runner", "--pattern", asset["name"],
                          "--dir", str(self.runner_root), "--clobber"], timeout=300)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != asset.get("digest", "").removeprefix("sha256:"):
                raise CloudError("Runner 官方摘要不匹配")
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    target = (self.runner_root / member.filename).resolve()
                    if self.runner_root.resolve() not in target.parents:
                        raise CloudError("Runner ZIP 路径错误")
                package.extractall(self.runner_root)
            archive.unlink()
        registration = self.runner_root / ".runner"
        if registration.exists():
            registered = json.loads(registration.read_text(encoding="utf-8-sig"))
            if registered.get("gitHubUrl", "").rstrip("/") != f"https://github.com/{self.repository}":
                raise CloudError("Runner 归属不是新仓库，拒绝修改")
        else:
            self.update(stage="为新仓库注册独立本机执行器", status="Preparing")
            # Token exists only in memory and official Runner credential storage. Never log command arguments.
            token = self.command(["api", "--method", "POST", f"repos/{self.repository}/actions/runners/registration-token"], as_json=True)["token"]
            suffix = hashlib.sha256(str(self.root).encode()).hexdigest()[:8]
            configured = subprocess.run([str(executable), "configure", "--unattended", "--url", f"https://github.com/{self.repository}",
                                         "--token", token, "--name", f"Noode-ProxyBench-{socket.gethostname()}-{suffix}",
                                         "--labels", "noode-cg-proxybench", "--work", "_work"],
                                        cwd=self.runner_root, env=cloud_environment(), capture_output=True, timeout=120,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            token = ""
            if configured.returncode:
                raise CloudError("独立 Runner 注册失败")
        log_path = self.root / "runtime/runner-console.log"
        self.log = log_path.open("wb")
        env = {**cloud_environment(), "NOODE_PROXYBENCH_APP": str(self.root), "NOODE_PROXYBENCH_PYTHON": cli_python(),
               "NOODE_LOCAL_ROOT": str(self.root), "PYTHONUTF8": "1"}
        if self.gh:
            env["PATH"] = str(Path(self.gh).parent) + os.pathsep + env.get("PATH", "")
        self.update(cloud_connection="使用现有代理连接 GitHub" if env.get("https_proxy") else "直接连接 GitHub")
        self.runner = subprocess.Popen([str(executable), "run"], cwd=self.runner_root, env=env, stdout=self.log, stderr=self.log,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(360):
            if self.runner.poll() is not None:
                raise CloudError("独立 Runner 启动失败")
            if "Listening for Jobs" in log_path.read_text(encoding="utf-8", errors="replace")[-10000:]:
                return
            self.control.checkpoint()
            time.sleep(0.5)
        raise CloudError("独立 Runner 未能连接 GitHub")

    def unregister_runner(self) -> None:
        registration = self.runner_root / ".runner"
        if not registration.exists():
            return
        registered = json.loads(registration.read_text(encoding="utf-8-sig"))
        suffix = hashlib.sha256(str(self.root).encode()).hexdigest()[:8]
        expected_name = f"Noode-ProxyBench-{socket.gethostname()}-{suffix}"
        if registered.get("gitHubUrl", "").rstrip("/") != f"https://github.com/{self.repository}" or registered.get("agentName") != expected_name:
            raise CloudError("Runner 清理归属不匹配")
        token = self.command(["api", "--method", "POST", f"repos/{self.repository}/actions/runners/remove-token"], as_json=True)["token"]
        try:
            removed = subprocess.run([str(self.runner_root / "bin/Runner.Listener.exe"), "remove", "--unattended", "--token", token],
                                     cwd=self.runner_root, env=cloud_environment(), capture_output=True, timeout=60,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if removed.returncode:
                raise CloudError("独立 Runner 注册清理失败，下次启动将自动恢复连接")
        finally:
            token = ""

    def dispatch(self, session_id: str, reuse: bool) -> None:
        self.diag_offsets = {path: path.stat().st_size for path in (self.runner_root / "_diag").glob("Runner_*.log")}
        request_id = secrets.token_hex(16)
        self.run_id = None
        live_path = self.settings["state_dir"] / "live.json"
        prior = json.loads(live_path.read_text(encoding="utf-8")) if live_path.exists() else {}
        self.update(session_id=session_id, dispatch_id=request_id, local_before_dispatch=prior.get("workflow_run_id", ""))
        self.command(["workflow", "run", "proxybench.yml", "--repo", self.repository, "--ref", self.branch, "-f",
                      f"session_id={session_id}", "-f", f"dispatch_id={request_id}", "-f", f"reuse_handoff={str(reuse).lower()}", "-f", "prepare_only=false"])
        for _ in range(30):
            self.control.checkpoint()
            runs = self.command(["run", "list", "--repo", self.repository, "--workflow", "proxybench.yml", "--limit", "20",
                                 "--json", "databaseId,createdAt,event,status,displayTitle"], as_json=True)
            fresh = [x for x in runs if x.get("event") == "workflow_dispatch"
                     and request_id in x.get("displayTitle", "")]
            if fresh:
                self.run_id = fresh[0]["databaseId"]
                return
            time.sleep(1)
        raise CloudError("未找到新云端任务")

    def wait_local_exit(self) -> None:
        """Never dispatch over a cancelling Worker or the owned candidate core."""
        import psutil
        for _ in range(180):
            self.control.checkpoint()
            workers = False
            if self.runner and isinstance(self.runner.pid, int):
                try:
                    workers = any(child.name().lower() == "runner.worker.exe"
                                  for child in psutil.Process(self.runner.pid).children(recursive=True))
                except psutil.Error:
                    pass
            if not workers and not owned_core_running(self.settings["runtime_dir"]):
                return
            time.sleep(1)
        raise CloudError("上次测速任务尚未退出，已保留断点；退出后可继续测试")

    def runner_lost_connection(self) -> bool:
        # Only this dispatch's new diagnostic bytes can prove an infrastructure cancellation.
        # Do not report raw Runner logs: they may contain signed URLs and credential material.
        for path in sorted((self.runner_root / "_diag").glob("Runner_*.log"), reverse=True):
            try:
                with path.open("rb") as handle:
                    handle.seek(max(self.diag_offsets.get(path, 0), path.stat().st_size - 256_000))
                    content = handle.read().decode("utf-8", errors="replace")
            except OSError:
                continue
            lost = re.findall(r"Catch exception during renew runner job ([a-f0-9-]{36})\.", content)
            if any(f"finish job request for job {job} with result: Abandoned" in content for job in lost):
                return True
        return False

    def interrupted(self, message: str) -> None:
        path = self.settings["state_dir"] / "live.json"
        live = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        # Preserve every measurement and the current phase, but stop presenting stale in-flight work.
        live.update(status="Stopped", stage=message, speed_active=[])
        core = live.setdefault("mihomo", {})
        core.update(status="Stopped", loaded_proxies=0, controller_healthy=False)
        atomic_write_json(path, live)
        self.update(status="Stopped", stage=message, interrupted=True)

    def watch(self) -> dict:
        while True:
            self.control.checkpoint()
            try:
                run = self.command(["run", "view", str(self.run_id), "--repo", self.repository,
                                    "--json", "status,conclusion,url,jobs"], as_json=True)
            except (CloudError, subprocess.TimeoutExpired):
                self.update(monitor_warning="云端状态读取暂时失败，正在重试；本地测量继续")
                for _ in range(25):
                    self.control.checkpoint()
                    time.sleep(0.2)
                continue
            current = next((job for job in run.get("jobs", []) if job.get("status") == "in_progress"), {})
            self.update(stage=current.get("name") or run["status"], status=run["status"], run_id=self.run_id, run_url=run["url"], monitor_warning="",
                        jobs=[{"name": job["name"], "status": job["status"], "conclusion": job.get("conclusion"),
                               "steps": [{"name": step["name"], "status": step["status"], "conclusion": step.get("conclusion")}
                                         for step in job.get("steps", [])]} for job in run.get("jobs", [])])
            if run["status"] == "completed":
                return run
            for _ in range(25):
                self.control.checkpoint()
                time.sleep(0.2)

    def run(self, mode: str = "auto") -> dict:
        with RunLock(self.root / "runtime/cloud"):
            if owned_core_running(self.settings["runtime_dir"]):
                raise CloudError("本地测速仍在运行，请先暂停或停止保存；不能重复发送任务")
            return self._run(mode)

    def _run(self, mode: str) -> dict:
        self.control.path.unlink(missing_ok=True)
        try:
            if self.settings.get("auto_refresh_profile"):
                self.update(profile_update=refresh_existing(self.settings["profile"]))
            if not self.settings["profile"].exists():
                references = [x for x in discover_profiles("jackoyu.dpdns.org") if x["matches_worker"] and x["port"] == 443]
                if not references:
                    raise CloudError("缺少可用代理协议配置：请在窗口导入现有节点")
                import_discovered(references[0], self.settings["profile"])
            ProxyProfile.load(self.settings["profile"])
            self.prepare_runner()
            state = Store(self.settings["state_dir"]).load()
            session_path = self.settings["state_dir"] / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {"session_id": secrets.token_hex(16)}
            unfinished = state.get("phase") in {"scan", "general_retest", "jp_retest", "publish"}
            pending = (self.root / "runtime/pending-publish/manifest.json").exists()
            requested_session = state.get("session_id", session["session_id"]) if mode in {"continue", "resume"} else session["session_id"]
            reuse = pending or (unfinished and mode == "resume")
            queued_report_path = self.root / "data/handoff/proxybench-cloud-health.json"
            if mode == "resume" and not state and queued_report_path.exists():
                queued_report = json.loads(queued_report_path.read_text(encoding="utf-8"))
                session["session_id"] = queued_report.get("session_id", session["session_id"])
                requested_session, reuse = session["session_id"], True
            resend_before_fresh = pending and mode != "resume"
            if reuse or mode in {"continue", "resume"}:
                session["session_id"] = state.get("session_id", session["session_id"])
            atomic_write_json(session_path, session)
            budget = self.settings["max_cycles"]
            if reuse and budget:
                budget = max(1, budget - int(state.get("cycle", 1)) + 1)
            attempt = 0
            recoveries = 0
            while not budget or attempt < budget:
                attempt += 1
                self.update(stage="恢复云端交接与已完成批次" if reuse else f"请求云端获取不同 IP（本次第 {attempt} 轮）", status="Dispatching")
                self.dispatch(session["session_id"], reuse)
                run = self.watch()
                if run.get("conclusion") != "success":
                    if run.get("conclusion") == "cancelled":
                        self.wait_local_exit()
                        lost = self.runner_lost_connection()
                        message = "执行器与 GitHub 连接中断，已保存测速断点" if lost else "GitHub 任务已取消，已保存测速断点"
                        self.interrupted(message)
                        if lost and recoveries < 3:
                            recoveries += 1
                            self.update(status="Recovering", stage=f"云端连接中断，正在从已保存批次恢复（第 {recoveries} 次）", recovery_attempt=recoveries)
                            for _ in range(25):
                                self.control.checkpoint()
                                time.sleep(0.2)
                            reuse = True
                            attempt -= 1  # A network retry is the same candidate round, not replenishment.
                            continue
                        return {"status": "stopped", "reason": "runner_connection_lost" if lost else "cancelled", "run_url": run["url"]}
                    message = "云端或本地步骤失败，已保留 Last Good 和状态"
                    validation_path = self.settings["runtime_dir"] / "validation.json"
                    if any(job.get("name") in {"local-select", "本地真实代理测速"} and job.get("conclusion") == "failure" for job in run.get("jobs", [])) and validation_path.exists():
                        validation = json.loads(validation_path.read_text(encoding="utf-8"))
                        if validation.get("method") == "isolated-rule-core-check-v2" and not validation.get("runtime_ready"):
                            message = validation.get("failure_reason", "规则代理内核初始化未完成") + "，已保留候选和 Last Good"
                    self.update(stage=message, status="Failed", run_url=run["url"])
                    return {"status": run.get("conclusion"), "run_url": run["url"]}
                health_path = self.settings["output_dir"] / "health.json"
                health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
                if health.get("published"):
                    if resend_before_fresh:
                        session["session_id"] = requested_session
                        atomic_write_json(session_path, session)
                        resend_before_fresh, reuse, attempt = False, False, 0
                        continue
                    self.update(stage="普通100个和日本10个已测量并发布", status="Completed", run_url=run["url"])
                    return {"status": "success", "published": True, "run_url": run["url"]}
                if not health.get("needs_more"):
                    return {"status": "success", "published": False, "run_url": run["url"]}
                # Keep this application's Runner alive for all automatic replenishment cycles.
                reuse = False
            self.update(stage="已达到自定义补测上限，合格数不足；可点击继续获取 IP", status="Needs More", run_url=run["url"])
            return {"status": "needs_more", "published": False, "run_url": run["url"]}
        except Stopped:
            if self.run_id:
                self.command(["run", "cancel", str(self.run_id), "--repo", self.repository])
            self.update(status="Stopped", stage="停止请求已交给本地任务，进度已经保存")
            return {"status": "stopped"}
        except Exception as exc:
            self.update(status="Failed", stage=safe_error(exc))
            raise
        finally:
            if self.runner and self.runner.poll() is None:
                self.runner.terminate()
                try:
                    self.runner.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.runner.kill()
                    self.runner.wait(timeout=10)
            if self.log:
                self.log.close()
            if self.runner:
                try:
                    self.unregister_runner()
                except (CloudError, OSError, subprocess.TimeoutExpired):
                    pass  # Preserve owned registration for retry if GitHub is unavailable.
