"""Cloud discovery and publication surrounding a locally owned benchmark process."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import secrets
import time
import zipfile

from core.io_utils import atomic_write_bytes, atomic_write_json
from scripts.proxybench_channel import pack, result_prefix, validate_result_files
from scripts.sync_cloud_handoff import download, sources

from .cloud import CloudController, CloudError
from .cloud_network import vpn_environment
from .events import EventLog, chinese
from .pipeline import Pipeline
from .profile import ProxyProfile, discover_profiles, import_discovered, refresh_existing, safe_error
from .publication_policy import PolicyChanged
from .publication_policy import current as publication_policy
from .publication_policy import lock as publication_lock
from .queue import accumulate
from .settings import current_rules
from .state import Stopped, Store


class DesktopCloudController(CloudController):
    """No Actions Worker owns the long-running local measurements."""

    @property
    def pending_dir(self):
        return self.root / "runtime" / ("pending-publish-tcp" if self.settings.get("measurement_mode") == "tcp_tls" else "pending-publish")

    def update(self, **values):
        previous = (self.live.get("status"), self.live.get("stage"))
        super().update(**values)
        if previous != (self.live.get("status"), self.live.get("stage")):
            EventLog(self.root, self.settings.get("measurement_mode", "proxy")).append(chinese(str(values.get("stage") or values.get("status") or "")),
                                                                                level="error" if values.get("status") == "Failed" else "info")

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
        args = ["workflow", "run", workflow, "--repo", self.repository, "--ref", self.branch, "-f", f"dispatch_id={request}"]
        for key, value in fields.items():
            args.extend(["-f", f"{key}={value}"])
        self.command(args)
        for _ in range(60):
            self.control.checkpoint()
            runs = self.command(["run", "list", "--repo", self.repository, "--workflow", workflow, "--limit", "20",
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
        self.command(["run", "download", str(self.run_id), "--repo", self.repository, "--name", "proxybench-handoff-metadata", "--dir", str(dest)], timeout=60)
        metadata = json.loads((dest / "handoff.json").read_text(encoding="utf-8"))
        if metadata.get("repository") != self.repository or metadata.get("session_id") != session_id or not re.fullmatch(r"[a-f0-9]{40}", metadata.get("ref", "")):
            raise CloudError("云端候选元数据不对应当前会话")
        self.update(status="Downloading", stage="通过多镜像下载并校验候选 IP", handoff_ready=True)
        try:
            download(self.root / "data/handoff/proxybench-pool.json.gz", metadata["sha256"],
                     sources(self.repository, metadata["ref"], "data/handoff/proxybench-pool.json.gz"), timeout=8, checkpoint=self.control.checkpoint)
        except RuntimeError:
            raise CloudError("所有候选镜像暂时不可用，已保留旧候选；可继续重试") from None
        # The checked pool already contains its source report and incumbent nodes.
        import gzip
        payload = json.loads(gzip.decompress((self.root / "data/handoff/proxybench-pool.json.gz").read_bytes()))
        if payload["report"].get("session_id") != session_id:
            raise CloudError("候选文件会话不匹配")
        atomic_write_json(self.root / "data/handoff/proxybench-cloud-health.json", payload["report"])
        accumulate(self.settings)

    def local_select(self, *, publish_only: bool = False) -> dict:
        self.update(status="Local", stage="本地 TCP／TLS 直连测速" if self.settings.get("measurement_mode") == "tcp_tls" else "本地真实代理测速", handoff_ready=True, download_ready=True, local_detached=True,
                    run_id=self.run_id or "local-resume", session_id=Store(self.settings["state_dir"]).load().get("session_id", self.live.get("session_id", "")))
        self.settings["workflow_run_id"] = str(self.run_id or "local-resume")
        if publish_only:
            return Pipeline(self.settings).run(resume=True, publish_only=True)
        return Pipeline(self.settings).run(resume=True, handoff=True)

    def finish_manual(self, result: dict) -> dict:
        if result.get("status") == "stopped":
            self.update(status="Stopped", stage="已停止并保存结果，尚未推送")
            return result
        if not result.get("published"):
            self.update(status="Needs More", stage="现有结果复测后没有合格 IP，已保存断点；可继续测试")
            self.control.path.with_name("publish-request.json").unlink(missing_ok=True)
            return result
        result, run = self.publish_current(result)
        if not run:
            return result
        self.control.path.with_name("publish-request.json").unlink(missing_ok=True)
        self.update(status="Completed", stage=f"已手动推送常规 {result['general_final_count']} 个＋日本 {result['jp_final_count']} 个 IP")
        return {**result, "status": "success", "run_url": run["url"], "cloud_confirmed": True}

    def upload_pending(self) -> tuple[str, str]:
        pending = self.pending_dir
        pending.mkdir(parents=True, exist_ok=True)
        manifest = pending / "manifest.json"
        if manifest.exists():
            expected = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
            content = (pending / "result.zip").read_bytes()
        else:
            content = pack(self.root, "result", self.settings.get("measurement_mode", "proxy"))
            expected = hashlib.sha256(content).hexdigest()
            atomic_write_bytes(pending / "result.zip", content)
            atomic_write_json(manifest, {"sha256": expected})
        if hashlib.sha256(content).hexdigest() != expected:
            raise CloudError("本机待发布结果摘要错误，原文件已保留")
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            validate_result_files({name: package.read(name) for name in package.namelist()})
        request_path = pending / "public-upload.json"
        atomic_write_json(request_path, {"encoding": "base64", "content": base64.b64encode(content).decode("ascii")})
        try:
            result = self.command(["api", "--method", "POST", f"repos/{self.repository}/git/blobs", "--input", str(request_path)], as_json=True, timeout=60)
        finally:
            request_path.unlink(missing_ok=True)
        return result["sha"], expected

    def publish_pending(self) -> dict:
        if self.settings.get("regional_publication"):
            with publication_lock(self.settings):
                policy = publication_policy(self.settings)
                health = json.loads((self.settings["output_dir"] / "health.json").read_text(encoding="utf-8"))
                if not health.get("published") or health.get("publication_limits") != policy:
                    raise PolicyChanged("发布设置已更新，上传前重新取最优名单")
                if health.get("measurement_rules", current_rules(self.settings)) != current_rules(self.settings):
                    raise PolicyChanged("测速规则已更新，上传前重新复测")
                if (self.pending_dir / "manifest.json").exists():
                    with zipfile.ZipFile(self.pending_dir / "result.zip") as package:
                        files = {name: package.read(name) for name in package.namelist()}
                        old = json.loads(files[f"{result_prefix(files)}/health.json"])
                    if old.get("run_id") != health.get("run_id") or old != health:
                        atomic_write_bytes(self.pending_dir / "previous-result.zip", (self.pending_dir / "result.zip").read_bytes())
                        (self.pending_dir / "manifest.json").unlink()
                        (self.pending_dir / "result.zip").unlink()
                return self._publish_pending()
        return self._publish_pending()

    def publish_current(self, result):
        while result.get("published"):
            try:
                return result, self.publish_pending()
            except PolicyChanged:
                self.update(status="Local", stage="发布设置已更新，上传前重新复测与排序")
                self.settings["resume_checkpoint_only"] = True
                result = self.local_select(publish_only=bool(result.get("manual_publication")))
        return result, None

    def _publish_pending(self) -> dict:
        self.update(status="Publishing", stage="上传已复测结果，等待云端校验与推送确认")
        blob, expected = self.upload_pending()
        self.dispatch_named("proxybench-publish.yml", {"blob_sha": blob, "payload_sha256": expected})
        run = self.watch()
        if run.get("conclusion") != "success":
            raise CloudError("云端发布未确认，完整结果已保存在本机；可继续重传")
        pending = self.pending_dir
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
            direct = self.settings.get("measurement_mode") == "tcp_tls"
            if not direct and self.settings.get("auto_refresh_profile"):
                self.update(profile_update=refresh_existing(self.settings["profile"]))
            if not direct and not self.settings["profile"].exists():
                references = [row for row in discover_profiles("jackoyu.dpdns.org") if row["matches_worker"] and row["port"] == 443]
                if not references:
                    raise CloudError("缺少可用代理协议配置：请在窗口导入现有节点")
                import_discovered(references[0], self.settings["profile"])
            if not direct:
                ProxyProfile.load(self.settings["profile"])
            state = Store(self.settings["state_dir"]).load()
            session_path = self.settings["state_dir"] / "session.json"
            session = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {"session_id": secrets.token_hex(16)}
            if mode in {"resume", "continue", "publish"} and state.get("session_id"):
                session["session_id"] = state["session_id"]
            atomic_write_json(session_path, session)
            pending = (self.pending_dir / "manifest.json").exists()
            if pending and mode == "auto" and not state:
                saved = self.root / "data/saved-measurements"
                saved.mkdir(parents=True, exist_ok=True)
                tag = self.settings.get("measurement_mode", "proxy")
                for name in ("result.zip", "manifest.json"):
                    original = self.pending_dir / name
                    atomic_write_bytes(saved / f"stopped-{tag}-{name}", original.read_bytes())
                (self.pending_dir / "manifest.json").unlink()
                (self.pending_dir / "result.zip").unlink()
                pending = False
                EventLog(self.root, tag).append("上次停止的待推送结果已另存；本次重新全量获取 IP")
            if pending:
                with zipfile.ZipFile(self.pending_dir / "result.zip") as package:
                    files = {name: package.read(name) for name in package.namelist()}
                    health = json.loads(files[f"{result_prefix(files)}/health.json"])
                stale = self.settings.get("regional_publication") and health.get("publication_limits") != publication_policy(self.settings)
                try:
                    run = None if stale else self.publish_pending()
                except PolicyChanged:
                    run = None
                if run and mode in {"resume", "publish"} and health.get("published"):
                    self.control.path.with_name("publish-request.json").unlink(missing_ok=True)
                    self.update(status="Completed", stage="已恢复推送并确认发布")
                    return {"status": "success", "published": True, "run_url": run["url"]}
            if mode == "publish":
                return self.finish_manual(self.local_select(publish_only=True))
            resumable = mode == "resume" and state.get("phase") in {"scan", "general_retest", "jp_retest", "regional_retest", "publish", "completed", "needs_more"}
            shared_handoff = self.root / "data/handoff/proxybench-pool.json.gz"
            if mode == "auto" and not state and shared_handoff.exists():
                import gzip
                current = json.loads(gzip.decompress(shared_handoff.read_bytes()))
                if current.get("report", {}).get("session_id") == session["session_id"]:
                    accumulate(self.settings)
                    resumable = True
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
            cycle = int(state.get("cycle", 0))
            extra = cycle + 1 if mode == "continue" else 0
            last_policy = state.get("publication_limits")
            while True:
                if self.settings.get("regional_publication"):
                    policy = publication_policy(self.settings)
                    if last_policy is not None and policy != last_policy:
                        resumable = True
                    allowed = max(policy["max_rounds"], extra)
                    if not resumable and cycle >= allowed:
                        break
                elif limit and rounds >= limit:
                    break
                rounds += 1
                self.settings["resume_checkpoint_only"] = bool(resumable and state)
                if self.control.publication_requested():
                    return self.finish_manual(self.local_select(publish_only=True))
                # Saved handoff and local checkpoints require no live GitHub connection to resume.
                if not resumable:
                    self.fetch_handoff(session["session_id"], reuse=False)
                    cycle += 1
                result = self.local_select()
                cycle = max(cycle, int(result.get("cycle", cycle)))
                last_policy = result.get("publication_limits")
                resumable = False
                if result.get("status") == "stopped":
                    self.update(status="Stopped", stage="本地测速已停止并保存")
                    return result
                if result.get("manual_publication"):
                    return self.finish_manual(result)
                if result.get("published"):
                    result, run = self.publish_current(result)
                    if run:
                        self.update(status="Completed", stage=f"已按各地区上限复测并推送 {result.get('unique_final_count', 0)} 个 IP")
                        return {"status": "success", "published": True, "run_url": run["url"]}
                if not result.get("needs_more"):
                    return result
                # Synchronize tested IP history to the cloud without replacing last-good nodes.
                if not self.settings.get("regional_publication"):
                    self.publish_pending()
                else:
                    self.update(status="Needs More", stage=f"按地区上限可发布 {result.get('unique_final_count', 0)}/{publication_policy(self.settings)['total']} 个，准备补充不同 IP")
            self.update(status="Needs More", stage="已达到自动获取轮数上限，合格结果已保存；可修改地区上限、继续获取不同 IP，或手动推送")
            return {"status": "needs_more", "published": False}
        except Stopped:
            if self.run_id:
                try:
                    self.command(["run", "cancel", str(self.run_id), "--repo", self.repository])
                except CloudError:
                    pass
            self.update(status="Stopped", stage="已停止，测速进度已经保存")
            return {"status": "stopped"}
        except Exception as exc:
            self.update(status="Failed", stage=safe_error(exc), interrupted=True)
            raise
