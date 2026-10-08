"""Cloud discovery and publication surrounding a locally owned benchmark process."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time

from core.io_utils import atomic_write_bytes, atomic_write_json
from scripts.proxybench_channel import pack, validate_result_files
from scripts.sync_cloud_handoff import download, sources

from .cloud import REPOSITORY, CloudController, CloudError
from .cloud_network import vpn_environment
from .pipeline import Pipeline
from .profile import ProxyProfile, discover_profiles, import_discovered, refresh_existing, safe_error
from .queue import accumulate
from .state import Stopped, Store


class DesktopCloudController(CloudController):
    """No Actions Worker owns the long-running local measurements."""

    def command(self, args: list[str], **kwargs):
        import subprocess
        repeatable = args[:2] in (["run", "list"], ["run", "view"], ["run", "download"])
        if args and args[0] == "api":
            repeatable = "--method" not in args or any(str(value).endswith("/git/blobs") for value in args)
        for attempt in range(3 if repeatable else 1):
            self.control.checkpoint()
            try:
                return super().command(args, **kwargs)
            except (CloudError, subprocess.TimeoutExpired):
                if attempt == (2 if repeatable else 0):
                    raise
                self.update(monitor_warning="GitHub 官方接口暂时不可用，正在重试；已保存本机结果")
                for _ in range(10 * (attempt + 1)):
                    self.control.checkpoint()
                    time.sleep(0.2)

    def dispatch_named(self, workflow: str, fields: dict) -> None:
        request = secrets.token_hex(16)
        self.run_id = None
        prior_path = self.settings["state_dir"] / "live.json"
        prior = json.loads(prior_path.read_text(encoding="utf-8")) if prior_path.exists() else {}
        context = {key: value for key, value in self.live.items() if key in {"network", "cloud_connection"} or
                   workflow == "proxybench-publish.yml" and key in {"handoff_ready", "download_ready", "local_detached", "session_id"}}
        self.update(status="Dispatching", dispatch_id=request, session_id=fields.get("session_id", ""),
                    local_before_dispatch=prior.get("workflow_run_id", ""))
        self.update(**context)
        args = ["workflow", "run", workflow, "--repo", REPOSITORY, "--ref", "main", "-f", f"dispatch_id={request}"]
        for key, value in fields.items():
            args.extend(["-f", f"{key}={value}"])
        self.command(args)
        for _ in range(60):
            self.control.checkpoint()
            runs = self.command(["run", "list", "--repo", REPOSITORY, "--workflow", workflow, "--limit", "20",
                                 "--json", "databaseId,displayTitle,event"], as_json=True)
            current = next((row for row in runs if request in row.get("displayTitle", "") and row.get("event") == "workflow_dispatch"), None)
            if current:
                self.run_id = current["databaseId"]
                return
            time.sleep(1)
        raise CloudError("暂时无法找到云端任务，已保留候选和断点")

    def fetch_handoff(self, session_id: str, reuse: bool) -> None:
        self.dispatch_named("proxybench.yml", {"session_id": session_id, "reuse_handoff": str(reuse).lower(), "prepare_only": "true"})
        run = self.watch()
        if run.get("conclusion") != "success":
            raise CloudError("云端候选获取未完成，已保留本机候选和断点")
        dest = self.root / "runtime/cloud-handoff" / str(self.run_id)
        dest.mkdir(parents=True, exist_ok=True)
        self.command(["run", "download", str(self.run_id), "--repo", REPOSITORY, "--name", "proxybench-handoff-metadata", "--dir", str(dest)], timeout=60)
        metadata = json.loads((dest / "handoff.json").read_text(encoding="utf-8"))
        if metadata.get("repository") != REPOSITORY or metadata.get("session_id") != session_id or not re.fullmatch(r"[a-f0-9]{40}", metadata.get("ref", "")):
            raise CloudError("云端候选元数据不对应当前会话")
        self.update(status="Downloading", stage="通过多镜像下载并校验候选 IP", handoff_ready=True)
        try:
            download(self.root / "data/handoff/proxybench-pool.json.gz", metadata["sha256"],
                     sources(REPOSITORY, metadata["ref"], "data/handoff/proxybench-pool.json.gz"), timeout=8, checkpoint=self.control.checkpoint)
        except RuntimeError:
            raise CloudError("所有候选镜像暂时不可用，已保留旧候选；可继续重试") from None
        # The checked pool already contains its source report and incumbent nodes.
        import gzip
        payload = json.loads(gzip.decompress((self.root / "data/handoff/proxybench-pool.json.gz").read_bytes()))
        if payload["report"].get("session_id") != session_id:
            raise CloudError("候选文件会话不匹配")
        atomic_write_json(self.root / "data/handoff/proxybench-cloud-health.json", payload["report"])
        accumulate(self.settings)

    def local_select(self) -> dict:
        self.update(status="Local", stage="本地真实代理测速", handoff_ready=True, download_ready=True, local_detached=True,
                    run_id=self.run_id or "local-resume", session_id=Store(self.settings["state_dir"]).load().get("session_id", self.live.get("session_id", "")))
        self.settings["workflow_run_id"] = str(self.run_id or "local-resume")
        return Pipeline(self.settings).run(resume=True, handoff=True)

    def upload_pending(self) -> tuple[str, str]:
        pending = self.root / "runtime/pending-publish"
        pending.mkdir(parents=True, exist_ok=True)
        manifest = pending / "manifest.json"
        if manifest.exists():
            expected = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
            content = (pending / "result.zip").read_bytes()
        else:
            content = pack(self.root, "result")
            expected = hashlib.sha256(content).hexdigest()
            atomic_write_bytes(pending / "result.zip", content)
            atomic_write_json(manifest, {"sha256": expected})
        if hashlib.sha256(content).hexdigest() != expected:
            raise CloudError("本机待发布结果摘要错误，原文件已保留")
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            validate_result_files({name: package.read(name) for name in package.namelist()})
        request_path = pending / "public-upload.json"
        atomic_write_json(request_path, {"encoding": "base64", "content": base64.b64encode(content).decode("ascii")})
        try:
            result = self.command(["api", "--method", "POST", f"repos/{REPOSITORY}/git/blobs", "--input", str(request_path)], as_json=True, timeout=60)
        finally:
            request_path.unlink(missing_ok=True)
        return result["sha"], expected

    def publish_pending(self) -> dict:
        blob, expected = self.upload_pending()
        self.dispatch_named("proxybench-publish.yml", {"blob_sha": blob, "payload_sha256": expected})
        run = self.watch()
        if run.get("conclusion") != "success":
            raise CloudError("云端发布未确认，完整结果已保存在本机；可继续重传")
        pending = self.root / "runtime/pending-publish"
        if json.loads((pending / "manifest.json").read_text(encoding="utf-8"))["sha256"] != expected:
            raise CloudError("发布确认摘要不匹配")
        (pending / "result.zip").unlink()
        (pending / "manifest.json").unlink()
        return run

    def _run(self, mode: str) -> dict:
        self.control.path.unlink(missing_ok=True)
        try:
            network = vpn_environment()
            self.update(network=network, cloud_connection="公开文件使用多镜像，鉴权操作使用 GitHub 官方接口")
            if self.settings.get("auto_refresh_profile"):
                self.update(profile_update=refresh_existing(self.settings["profile"]))
            if not self.settings["profile"].exists():
                references = [row for row in discover_profiles("jackoyu.dpdns.org") if row["matches_worker"] and row["port"] == 443]
                if not references:
                    raise CloudError("缺少可用代理协议配置：请在窗口导入现有节点")
                import_discovered(references[0], self.settings["profile"])
            ProxyProfile.load(self.settings["profile"])
            state = Store(self.settings["state_dir"]).load()
            session_path = self.settings["state_dir"] / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {"session_id": secrets.token_hex(16)}
            if mode in {"resume", "continue"} and state.get("session_id"):
                session["session_id"] = state["session_id"]
            atomic_write_json(session_path, session)
            pending = (self.root / "runtime/pending-publish/manifest.json").exists()
            if pending:
                health = json.loads((self.settings["output_dir"] / "health.json").read_text(encoding="utf-8"))
                run = self.publish_pending()
                if mode == "resume" and health.get("published"):
                    self.update(status="Completed", stage="已恢复推送并确认发布")
                    return {"status": "success", "published": True, "run_url": run["url"]}
            resumable = mode == "resume" and state.get("phase") in {"scan", "general_retest", "jp_retest", "publish"}
            if mode == "resume" and not state and (self.root / "data/handoff/proxybench-pool.json.gz").exists():
                import gzip
                saved = json.loads(gzip.decompress((self.root / "data/handoff/proxybench-pool.json.gz").read_bytes()))
                session["session_id"] = saved["report"]["session_id"]
                atomic_write_json(session_path, session)
                resumable = True
            limit = self.settings["max_cycles"]
            if resumable and limit:
                limit = max(1, limit - int(state.get("cycle", 1)) + 1)
            rounds = 0
            while not limit or rounds < limit:
                rounds += 1
                # Saved handoff and local checkpoints require no live GitHub connection to resume.
                if not resumable:
                    self.fetch_handoff(session["session_id"], reuse=False)
                result = self.local_select()
                resumable = False
                if result.get("status") == "stopped":
                    self.update(status="Stopped", stage="本地测速已停止并保存")
                    return result
                if result.get("published"):
                    run = self.publish_pending()
                    self.update(status="Completed", stage="普通100个和日本10个已复测并推送 GitHub")
                    return {"status": "success", "published": True, "run_url": run["url"]}
                if not result.get("needs_more"):
                    return result
                # Synchronize tested IP history to the cloud without replacing last-good nodes.
                self.publish_pending()
            self.update(status="Needs More", stage="已达到自定义补测上限，可继续获取不同 IP")
            return {"status": "needs_more", "published": False}
        except Stopped:
            if self.run_id:
                try:
                    self.command(["run", "cancel", str(self.run_id), "--repo", REPOSITORY])
                except CloudError:
                    pass
            self.update(status="Stopped", stage="已停止，测速进度已经保存")
            return {"status": "stopped"}
        except Exception as exc:
            self.update(status="Failed", stage=safe_error(exc), interrupted=True)
            raise
