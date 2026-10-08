"""Dashboard steps derived from actual workflow jobs and the current local run."""
from __future__ import annotations

STEPS = (("cloud", "云端获取 IP"), ("download", "下载候选 IP"), ("selection", "本地代理优选"),
         ("retest", "发布前复测"), ("publish", "推送 GitHub"))


def progress(live: dict, cloud: dict, health: dict) -> list[dict]:
    rows = [{"id": key, "title": title, "status": "pending", "detail": "等待前一步"} for key, title in STEPS]
    def mark(index, status, detail):
        rows[index].update(status=status, detail=detail)

    jobs = cloud.get("jobs", [])
    def job(*names):
        return next((row for row in jobs if row.get("name") in names), {})

    prepare = job("cloud-prepare", "云端自动获取候选IP")
    local = job("local-select", "本地真实代理测速")
    publish = job("cloud-publish", "云端发布最优IP")
    download = next((step for step in local.get("steps", [])
                     if step.get("name") == "Decode digest-verified cloud candidate handoff"), {})
    phase = live.get("phase", "")
    cloud_run = cloud.get("run_id")
    local_active = bool(live.get("local_process_active"))
    new_local_session = (live.get("session_id") and live.get("session_id") == cloud.get("session_id")
                         and live.get("workflow_run_id") and live.get("workflow_run_id") != cloud.get("local_before_dispatch"))
    current = (str(live.get("workflow_run_id", "")) == str(cloud_run)) if cloud_run else (
        not cloud or new_local_session or local_active and bool(live.get("workflow_run_id")))
    active = None
    if cloud.get("mode") == "validate":
        rows[0]["detail"] = "独立检查代理内核，未启动优选"
        return rows
    if prepare.get("conclusion") == "success" or current and phase in {"scan", "general_retest", "jp_retest", "publish", "completed", "needs_more"}:
        mark(0, "completed", "候选已在云端生成")
    elif prepare.get("status") == "in_progress" or cloud.get("status") in {"Preparing", "Dispatching", "queued", "in_progress"}:
        mark(0, "running", "正在准备或获取候选")
        active = 0
    if download.get("conclusion") == "success" or current and phase in {"scan", "general_retest", "jp_retest", "publish", "completed", "needs_more"}:
        mark(1, "completed", "候选已下载并保存到本机")
    elif local.get("status") == "in_progress" and rows[0]["status"] == "completed":
        mark(1, "running", "正在下载并校验候选")
        active = 1
    if current and phase == "scan":
        mark(2, "running", f"已处理 {live.get('tested_count', 0)} / {live.get('candidate_total', 0)} 个 IP")
        active = 2
    elif current and phase in {"general_retest", "jp_retest", "publish", "completed", "needs_more"}:
        mark(2, "completed", "本轮优选已完成")
    elif rows[1]["status"] == "completed" and local.get("status") == "in_progress":
        mark(2, "running", "准备规则代理与本地优选")
        active = 2
    if current and phase in {"general_retest", "jp_retest"}:
        mark(3, "running", "复测普通新旧 IP" if phase == "general_retest" else "复测日本追加 IP")
        active = 3
    elif current and phase in {"publish", "completed", "needs_more"}:
        mark(3, "completed", "本轮新旧 IP 复测已完成")
    if health.get("needs_more") and current and phase == "needs_more":
        mark(4, "waiting", "合格数不足，等待补测")
    elif cloud.get("status") == "Completed" and health.get("published") or publish.get("conclusion") == "success" and health.get("published"):
        for index in range(5):
            mark(index, "completed", "已完成")
        rows[4]["detail"] = "最优 100＋日本 10 已推送"
    elif publish.get("status") == "in_progress" and health.get("published"):
        mark(4, "running", "正在校验并推送 GitHub")
        active = 4
    elif current and phase in {"publish", "completed"}:
        mark(4, "waiting", "等待云端校验与推送确认")
        active = 4
    if prepare.get("conclusion") in {"failure", "cancelled", "timed_out"}:
        active = 0
    elif download.get("conclusion") in {"failure", "cancelled", "timed_out"}:
        active = 1
    elif publish.get("conclusion") in {"failure", "cancelled", "timed_out"}:
        active = 4
    elif local.get("conclusion") in {"failure", "cancelled", "timed_out"} and active is None:
        active = 3 if current and phase in {"general_retest", "jp_retest"} else 2
    failed = (cloud.get("status") == "Failed" and not local_active) or any(row.get("conclusion") in {"failure", "timed_out"} for row in (prepare, local, publish))
    state = live.get("status") if current else cloud.get("status")
    if active is None and (failed or state == "Failed"):
        active = 0
    if active is not None:
        if failed or state == "Failed":
            mark(active, "failed", "步骤失败，进度已保留")
        elif state == "Paused":
            mark(active, "paused", "已暂停，可继续")
        elif state == "Stopped" or cloud.get("status") == "Stopped":
            mark(active, "paused", cloud.get("stage") if cloud.get("interrupted") else "已停止并保存")
        if cloud.get("status") == "Recovering":
            mark(active, "waiting", cloud.get("stage", "正在恢复云端连接"))
    return rows
