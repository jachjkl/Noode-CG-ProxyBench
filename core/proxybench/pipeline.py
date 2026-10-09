from __future__ import annotations

import concurrent.futures
import copy
import gzip
import json
import math
import os
import secrets
import threading
import time

import yaml

from core.io_utils import atomic_write_bytes, atomic_write_json
from sources.common import merge
from sources.pool import build

from .benchmark import Benchmark, limit_failure, ranking_key
from .controller import CoreError
from .entry_probe import probe as entry_probe
from .events import EventLog, chinese
from .export import publish, recover
from .mihomo_manager import MihomoManager
from .modes import OUTPUTS, publication_limits
from .profile import ProfileChanged, ProxyProfile, refresh_existing, safe_error
from .settings import current_rules
from .state import Control, RunLock, Stopped, Store

PROXY_POLICY = "entry-proxy-v10-nonblocking-observation"


def prepare(settings: dict, continuation: bool = False, session_id: str = "", reuse: bool = False) -> dict:
    destination = settings["root"] / "data/handoff/proxybench-pool.json.gz"
    if reuse:
        payload = json.loads(gzip.decompress(destination.read_bytes()))
        if session_id and payload["report"].get("session_id") != session_id:
            raise ValueError("云端交接与本机断点不属于同一会话")
        return payload["report"]
    history_path = destination.with_name("proxybench-session-history.json.gz")
    history = json.loads(gzip.decompress(history_path.read_bytes())) if history_path.exists() else {}
    if not session_id:
        session_id = history.get("session_id", "") if continuation else secrets.token_hex(16)
    if not session_id:
        session_id = secrets.token_hex(16)
    if history.get("session_id") != session_id:
        history = {"session_id": session_id, "cycle": 0, "ips": []}
    excluded = set(history["ips"])
    prior_path = settings["root"] / "data/handoff/proxybench-attempted.json.gz"
    if history["cycle"] and prior_path.exists():
        excluded.update(json.loads(gzip.decompress(prior_path.read_bytes())))
    # Cloud does not need or receive the local Profile. The local stage normalizes port from the Profile.
    pool, report = build(settings, 443, excluded, include_fixed=history["cycle"] == 0)
    report.update(continuation=bool(history["cycle"]), session_id=session_id, cycle=history["cycle"] + 1)
    incumbents_path = settings["output_dir"] / "nodes.json"
    incumbents = json.loads(incumbents_path.read_text(encoding="utf-8")) if incumbents_path.exists() else []
    atomic_write_bytes(destination, gzip.compress(json.dumps({"schema": 2, "pool": pool, "report": report,
                                                             "incumbents": incumbents,
                                                             "incumbents_by_mode": {mode: json.loads((settings["root"] / folder / "nodes.json").read_text(encoding="utf-8"))
                                                                                    if (settings["root"] / folder / "nodes.json").exists() else []
                                                                                    for mode, folder in OUTPUTS.items()}}).encode(), mtime=0))
    history.update(cycle=report["cycle"], ips=sorted(excluded | {item["ip"] for item in pool}))
    atomic_write_bytes(history_path, gzip.compress(json.dumps(history).encode(), mtime=0))
    atomic_write_json(destination.with_name("proxybench-cloud-health.json"), report)
    return report


class Pipeline:
    def __init__(self, settings: dict, manager=None, pool_builder=build) -> None:
        self.settings = settings
        self.direct = settings.get("measurement_mode") == "tcp_tls"
        self.policy = ("direct-exclusive-v3-nonblocking-" + ("tls" if current_rules(settings)["tls_enabled"] else "tcp")) if self.direct else PROXY_POLICY
        self.store = Store(settings["state_dir"])
        if self.direct and manager is None:
            from .direct_benchmark import DirectManager
            manager = DirectManager()
        self.manager = manager or MihomoManager(settings["runtime_dir"])
        self.pool_builder = pool_builder
        self.control = Control(settings["state_dir"], self.update)
        self.status = {}
        self.cloudflare_url = "https://www.cloudflare.com/cdn-cgi/trace"
        self.events = EventLog(settings.get("root", settings["state_dir"]), settings.get("measurement_mode", "proxy"))
        self.incumbents = []
        self.update_lock = threading.RLock()
        self.last_flush = 0.0
        self.last_profile_check = 0.0

    def update(self, **values) -> None:
        with self.update_lock:
            changed = any(values.get(key) is not None and values[key] != self.status.get(key) for key in ("stage", "status"))
            self.status.update(values)
            if changed:
                self.events.append(chinese(str(values.get("stage") or values.get("status") or "")), level="error" if values.get("status") == "Failed" else "info")
            if not changed and time.monotonic() - self.last_flush < 0.5:
                return
            self.last_flush = time.monotonic()
            self.flush_update()

    def flush_update(self) -> None:
        self.status["mihomo"] = self.manager.health()
        state = self.store.state
        self.status.update(candidate_total=len(state.get("pool", [])), tested_count=len(state.get("results", {})),
                           run_id=state.get("run_id"), session_id=state.get("session_id"),
                           workflow_run_id=self.settings.get("workflow_run_id", os.environ.get("GITHUB_RUN_ID", "")),
                           qualified_count=sum(x.get("qualified", False) for x in state.get("results", {}).values()),
                           phase=state.get("phase", ""), cycle=state.get("cycle", 1), sources=state.get("sources", {}),
                           entry_screened_count=len(state.get("entry_results", {})),
                           proxy_tested_count=sum(bool(row.get("proxy_probe_count")) for row in state.get("results", {}).values()),
                           measurement_mode=self.settings.get("measurement_mode", "proxy"))
        try:
            atomic_write_json(self.settings["state_dir"] / "live.json", self.status)
        except OSError:
            pass  # UI is best effort; checkpoint commits remain strict.

    def screen_candidates(self, candidates: list[dict], *, result_field="results", refresh=False) -> list[dict]:
        if self.direct:
            # Match the reference: finish each 100-IP group end to end before
            # opening more sockets. TLS selection has no separate TCP gate.
            return sorted(candidates, key=lambda row: (not row.get("jp_hint", False), row.get("source_priority", 999)))
        if not self.settings.get("fast_entry_screen"):
            return candidates
        rules = current_rules(self.settings)
        self.store.state.setdefault(result_field, {}).update(self.store.partial)
        screens = self.store.state.setdefault("entry_results", {})
        remaining = candidates if refresh else [row for row in candidates if f"{row['ip']}:{row['port']}" not in screens]
        with concurrent.futures.ThreadPoolExecutor(max_workers=rules["entry_concurrency"]) as executor:
            for offset in range(0, len(remaining), rules["entry_concurrency"]):
                self.control.checkpoint()
                if result_field == "results" and self.control.publication_requested():
                    self.store.commit()
                    return []
                self.update(stage="快速初筛候选入口端口", status="Running")
                futures = {executor.submit(entry_probe, row, rules["entry_timeout_seconds"]): row for row in remaining[offset:offset + rules["entry_concurrency"]]}
                for future in concurrent.futures.as_completed(futures):
                    row = futures[future]
                    screens[f"{row['ip']}:{row['port']}"] = future.result()
                self.store.commit()
                self.update(stage="快速初筛候选入口端口")
        survivors = []
        from datetime import UTC, datetime
        for row in candidates:
            key = f"{row['ip']}:{row['port']}"
            result = screens[key]
            row.update(result)
            if result["entry_connected"] and result["entry_latency_ms"] <= rules["max_entry_latency_ms"]:
                row["entry_preferred"] = True
                survivors.append(row)
            else:
                self.store.state[result_field][key] = {**row, "key": key, "qualified": False, "status": "Rejected Entry",
                                                  "proxy_probe_count": 0, "tested_at": datetime.now(UTC).isoformat()}
        self.store.commit()
        return sorted(survivors, key=lambda row: (not row.get("jp_hint", False), not row["entry_preferred"], row["entry_latency_ms"], row["ip"]))

    def profiles(self, pool: list[dict], default: ProxyProfile) -> dict:
        if self.direct:
            return {"default": default}
        profiles = {"default": default}
        for item in pool:
            if "profile_file" in item:
                path = (self.settings["root"] / item["profile_file"]).resolve()
                if self.settings["root"].resolve() not in path.parents or not path.name.endswith(".local.yaml"):
                    raise ValueError("授权 Profile 必须在本项目本机配置目录")
                profiles[item["profile_file"]] = ProxyProfile.load(path)
                if profiles[item["profile_file"]].port != item["port"]:
                    raise ValueError("授权代理端口与 Profile 不一致")
        return profiles

    def scan(self, candidates: list[dict], result_field: str, profiles: dict, *, fixed_rules: dict | None = None) -> None:
        state = self.store.state
        state.setdefault(result_field, {}).update(self.store.partial)
        if fixed_rules is not None and (self.direct or self.settings.get("fast_entry_screen")):
            candidates = self.screen_candidates(candidates, result_field=result_field, refresh=True)
        remaining = [item for item in candidates if f"{item['ip']}:{item['port']}" not in state[result_field]]
        batch_number = 0
        while remaining:
            self.control.checkpoint()
            if result_field == "results" and self.control.publication_requested():
                break  # Finish the current batch before switching to the publication competition.
            if self.settings.get("auto_refresh_profile") and time.monotonic() - self.last_profile_check >= self.settings["profile_refresh_seconds"]:
                self.last_profile_check = time.monotonic()
                refreshed = refresh_existing(self.settings["profile"])
                self.update(profile_update=refreshed)
                if refreshed["changed"]:
                    raise ProfileChanged
            rules = fixed_rules or current_rules(self.settings)
            batch = remaining[:rules["batch_size"]]
            remaining = remaining[rules["batch_size"]:]
            batch_number += 1
            self.update(batch_current=batch_number, batch_total=math.ceil(len(candidates) / rules["batch_size"]),
                        batch_completed=len(state[result_field]) // rules["batch_size"], stage=("TLS Testing" if rules["tls_enabled"] else "TCP Testing") if self.direct else "Loading Proxy", active_rules=rules)
            for attempt in range(3):
                try:
                    batch = [item for item in batch if f"{item['ip']}:{item['port']}" not in state[result_field]]
                    if not batch:
                        break
                    benchmark = None if self.direct else Benchmark(self.manager, rules, self.control, geo_urls=self.settings["geo_urls"], update=self.update,
                                          cloudflare_url=self.cloudflare_url, speed_url=self.settings.get("speed_url", "https://dl.google.com/chrome/install/standalonesetup64.exe"))
                    def completed(result):
                        with self.update_lock:
                            state[result_field][result["key"]] = result
                            self.store.save_partial(result)
                            reason = result.get("rejection_reason", "")
                            self.events.append(f"{result['key']}：{chinese(result.get('status', ''))}" + (f"；{reason}" if reason else ""), level="info" if result.get("qualified") else "warning")
                    if self.direct:
                        from .direct_benchmark import DirectBenchmark
                        DirectBenchmark(rules, self.control, self.update, domain=self.settings.get("direct_tls_domain", "www.cloudflare.com")).batch(batch, completed, reuse_tcp=False)
                    else:
                        from .observation import Observation
                        benchmark.geo_policy = "confirm" if fixed_rules else "quick"
                        with Observation(self.update, completed) as observer:
                            benchmark.update = observer.update
                            benchmark.batch(batch, profiles, observer.completed)
                    break
                except CoreError:
                    self.manager.stop()
                    self.store.commit()
                    self.update(stage="代理内核连接异常，重启本软件内核并继续未完成的候选")
                    if attempt == 2:
                        raise
            self.store.commit()
            self.update(batch_completed=batch_number)
            if result_field == "results" and rules.get("quick_finish") and self.targets_ready(rules):
                self.events.append("已达到所设数量并留出复测余量，开始发布前竞赛；未测试候选保留，可继续优选")
                break

    def targets_ready(self, rules: dict) -> bool:
        limits = publication_limits(rules)
        winners = [r for r in self.store.state.get("results", {}).values() if r.get("qualified") and not limit_failure(r, rules)]
        japan = sum(bool(r.get("jp_qualified")) for r in winners)
        return len(winners) >= math.ceil(limits["general"] * 1.25) + limits["japan"] and japan >= math.ceil(limits["japan"] * 1.25)

    def new_pool(self, profile: ProxyProfile, handoff: bool) -> tuple[list[dict], dict]:
        if handoff:
            path = self.settings["root"] / "data/handoff/proxybench-pool.json.gz"
            payload = json.loads(gzip.decompress(path.read_bytes()))
            shared = self.settings["root"] / "data/window-candidates.json.gz"
            if shared.exists() and not self.store.state.get("pool"):
                saved_window = json.loads(gzip.decompress(shared.read_bytes()))
                if saved_window.get("report", {}).get("session_id") == payload["report"].get("session_id"):
                    payload = saved_window
            queue_path = self.settings["state_dir"] / "cloud-candidate-queue.json.gz"
            if queue_path.exists() and not self.store.state.get("pool"):
                queued = json.loads(gzip.decompress(queue_path.read_bytes()))
                if not shared.exists() and queued.get("report", {}).get("session_id") == payload["report"].get("session_id"):
                    payload = queued
            pool, report = payload["pool"], payload["report"]
            self.incumbents = payload.get("incumbents_by_mode", {}).get(self.settings.get("measurement_mode", "proxy"), payload.get("incumbents", []) if not self.direct else [])
            for item in pool:
                if "authorized_proxy_candidate" not in item["source_types"]:
                    item["port"] = profile.port
            pool = merge(pool)
        else:
            arguments = {"include_fixed": False} if self.store.state.get("pool") else {}
            pool, report = self.pool_builder(self.settings, profile.port,
                                            {item["ip"] for item in self.store.state.get("pool", [])}, **arguments)
            path = self.settings["output_dir"] / "nodes.json"
            self.incumbents = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        # Proxy names remain unique across replenishment cycles.
        for index, item in enumerate(pool, len(self.store.state.get("pool", [])) + 1):
            item["proxy_name"] = f"PB-{index:06d}"
        return pool, report

    def run(self, resume: bool = False, handoff: bool = False, publish_only: bool = False) -> dict:
        while True:
            try:
                if self.settings.get("auto_refresh_profile"):
                    self.update(profile_update=refresh_existing(self.settings["profile"]))
                    self.last_profile_check = time.monotonic()
                return self._run(resume, handoff, publish_only)
            except ProfileChanged:
                resume = True
                self.update(stage="代理配置已更新，保留候选并重新测量", status="Running")

    def _run(self, resume: bool = False, handoff: bool = False, publish_only: bool = False) -> dict:
        if self.direct:
            from .direct_benchmark import direct_profile
            profile = direct_profile()
        else:
            profile = ProxyProfile.load(self.settings["profile"])
        with RunLock(self.settings["runtime_dir"]):
            recover(self.settings["output_dir"])
            state = self.store.load() if resume else {}
            fresh_handoff = False
            if state and handoff and not publish_only and not self.settings.get("resume_checkpoint_only"):
                channel = self.settings["root"] / "data/handoff/proxybench-pool.json.gz"
                handoff_report = json.loads(gzip.decompress(channel.read_bytes()))["report"]
                fresh_handoff = handoff_report.get("seed") != state.get("sources", {}).get("seed")
                if fresh_handoff and (not handoff_report.get("continuation") or
                                      handoff_report.get("session_id") != state.get("session_id")):
                    state = {}
            if state and state.get("profile_fingerprint") != profile.fingerprint:
                if not self.settings.get("auto_refresh_profile"):
                    raise ValueError("Profile 已更改，不能混用旧测量；请开始新一轮")
                atomic_write_bytes(self.settings["state_dir"] / f"previous-profile-{secrets.token_hex(4)}-results.json.gz",
                                   gzip.compress(json.dumps(state.get("results", {})).encode(), mtime=0))
                state.update(results={}, general_results={}, jp_results={}, entry_results={}, phase="scan", profile_fingerprint=profile.fingerprint)
                for item in [*state.get("pool", []), *state.get("previous_general", []), *state.get("previous_jp", [])]:
                    if "authorized_proxy_candidate" not in item.get("source_types", []):
                        item["port"] = profile.port
                self.store.partial = {}
            if state and state.get("measurement_policy") != self.policy:
                if publish_only:
                    measured = {**state.get("results", {}), **state.get("general_results", {}), **state.get("jp_results", {}), **self.store.partial}
                    state["manual_retest_seeds"] = [copy.deepcopy(row) for row in measured.values() if row.get("qualified")]
                if state.get("results"):
                    atomic_write_bytes(self.settings["state_dir"] / f"previous-policy-{secrets.token_hex(4)}-results.json.gz",
                                       gzip.compress(json.dumps(state["results"]).encode(), mtime=0))
                state.update(results={}, general_results={}, jp_results={}, entry_results={}, phase="scan", measurement_policy=self.policy)
                self.events.append("旧测速策略的结果已归档；候选和会话保留，按新方法重新测量")
                self.store.partial = {}
            self.control.path.unlink(missing_ok=True)
            self.store.state = state
            if publish_only:
                if not state:
                    saved_path = self.settings["output_dir"] / "nodes.json"
                    records = json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.exists() else []
                    from .session_lifecycle import read_saved
                    records = self.unique_ips([*read_saved(self.settings), *records])
                    if not records:
                        raise ValueError("没有可手动推送的已测结果，请先开始优选")
                    state = {"run_id": secrets.token_hex(16), "session_id": secrets.token_hex(16), "cycle": 1,
                             "pool": [self.candidate(row) for row in records], "results": {f"{row['ip']}:{row['port']}": row for row in records},
                             "sources": {}, "profile_fingerprint": profile.fingerprint, "measurement_policy": self.policy}
                    self.store.state = state
                elif self.store.partial:
                    field = {"scan": "results", "general_retest": "general_results", "jp_retest": "jp_results"}.get(state.get("phase"))
                    if field:
                        state.setdefault(field, {}).update(self.store.partial)
                        if field != "results":
                            self.refresh_retests(field)
                state.update(phase="general_retest", competition_rules=current_rules(self.settings), general_results={}, jp_results={})
                seeds = state.pop("manual_retest_seeds", [])
                from .session_lifecycle import read_saved
                seeds.extend(read_saved(self.settings))
                saved_path = self.settings["output_dir"] / "nodes.json"
                seeds.extend(json.loads(saved_path.read_text(encoding="utf-8")) if saved_path.exists() else [])
                if seeds:
                    seeds = self.unique_ips(sorted((row for row in seeds if row.get("qualified")), key=ranking_key))
                    limits = publication_limits(state["competition_rules"])
                    japanese = [row for row in seeds if row.get("geo_country") == "JP" and row.get("geo_verified")][:limits["japan"]]
                    reserved = {row["ip"] for row in japanese}
                    ordinary = [row for row in seeds if row["ip"] not in reserved][:limits["general"]]
                    state["previous_general"] = self.competition_candidates(ordinary, state.get("previous_general", []))
                    state["previous_jp"] = self.competition_candidates(japanese, state.get("previous_jp", []))
                self.store.commit()
            try:
                self.update(stage="准备免代理 TCP／TLS 测试引擎" if self.direct else "检查代理环境与内核更新", status="Running")
                self.manager.ensure(self.settings["auto_update"])
                validation_path = self.settings["runtime_dir"] / "validation.json"
                validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
                if validation.get("profile_fingerprint") == profile.fingerprint and "/cdn-cgi/trace" in validation.get("cloudflare_url", ""):
                    self.cloudflare_url = validation["cloudflare_url"]
                if not state:
                    pool, source_report = self.new_pool(profile, handoff)
                    state = {"run_id": secrets.token_hex(16), "pool": pool, "results": {}, "sources": source_report,
                             "phase": "scan", "cycle": 1, "profile_fingerprint": profile.fingerprint,
                             "mihomo_version": self.manager.version, "measurement_policy": self.policy}
                    state.update(session_id=source_report.get("session_id", state["run_id"]),
                                 cycle=source_report.get("cycle", 1),
                                 previous_general=self.incumbent_candidates(profile, "general"),
                                 previous_jp=self.incumbent_candidates(profile, "jp_append"))
                    self.store.state = state
                    self.store.commit()
                elif state["phase"] == "completed" and not fresh_handoff:
                    return json.loads((self.settings["output_dir"] / "health.json").read_text(encoding="utf-8"))
                elif fresh_handoff or state["phase"] == "needs_more":
                    fresh, source_report = self.new_pool(profile, handoff)
                    previous = {item["ip"] for item in state["pool"]}
                    state["pool"].extend(item for item in fresh if item["ip"] not in previous)
                    state.update(phase="scan", cycle=source_report.get("cycle", state["cycle"] + 1), sources=source_report,
                                 general_results={}, jp_results={})
                    if self.incumbents:
                        state.update(previous_general=self.incumbent_candidates(profile, "general"),
                                     previous_jp=self.incumbent_candidates(profile, "jp_append"))
                    self.store.commit()
                while True:
                    profiles = self.profiles(state["pool"], profile)
                    if state["phase"] == "scan":
                        candidates = self.screen_candidates(state["pool"])
                        self.scan(candidates, "results", profiles)
                        state["phase"] = "general_retest"
                        state["competition_rules"] = current_rules(self.settings)
                        self.store.commit()
                    manual = publish_only or self.control.publication_requested()
                    limits = publication_limits(state["competition_rules"])
                    qualified = sorted((x for x in state["results"].values() if x.get("qualified") and
                                        not limit_failure(x, state["competition_rules"])), key=ranking_key)
                    reserved_jp = {x["ip"] for x in self.unique_ips([x for x in qualified if x.get("jp_qualified")])[:limits["japan"]]}
                    if state["phase"] == "general_retest":
                        general_pool = self.competition_candidates([x for x in qualified if x["ip"] not in reserved_jp][:limits["general"]], state.get("previous_general", []))
                        self.scan(general_pool, "general_results", profiles, fixed_rules=state["competition_rules"])
                        self.refresh_retests("general_results")
                        qualified = sorted((x for x in state["results"].values() if x.get("qualified")), key=ranking_key)
                        state["phase"] = "jp_retest"
                        self.store.commit()
                    generals = sorted((x for x in state.get("general_results", {}).values() if x.get("qualified")), key=ranking_key)
                    generals = self.unique_ips(generals)[:limits["general"]]
                    general_ips = {item["ip"] for item in generals}
                    if state["phase"] == "jp_retest":
                        jp_pool = self.competition_candidates([x for x in qualified if x.get("jp_qualified") and x["ip"] not in general_ips][:limits["japan"]], state.get("previous_jp", [])[:limits["japan"]])
                        jp_pool = [x for x in jp_pool if x["ip"] not in general_ips]
                        for offset in range(0, len(jp_pool), 20):
                            self.scan(jp_pool[offset:offset + 20], "jp_results", profiles, fixed_rules=state["competition_rules"])
                            jp_passed = [x for x in state.get("jp_results", {}).values() if x.get("qualified") and x.get("jp_qualified")]
                            if len(self.unique_ips(jp_passed)) >= limits["japan"]:
                                break
                        state["phase"] = "publish"
                        self.refresh_retests("jp_results")
                        self.store.commit()
                    japan = self.unique_ips(sorted((x for x in state.get("jp_results", {}).values()
                                                    if x.get("qualified") and x.get("jp_qualified") and x["ip"] not in general_ips), key=ranking_key))[:limits["japan"]]
                    latest = current_rules(self.settings)
                    if latest != state["competition_rules"]:
                        state.update(phase="general_retest", competition_rules=latest, general_results={}, jp_results={})
                        self.store.commit()
                        self.update(stage="规则已更新，按保存的新规则重新复测", status="Running")
                        continue
                    final = [{**item, "lane": "general"} for item in generals] + [{**item, "lane": "jp_append"} for item in japan]
                    qualified = [x for x in state["results"].values() if x.get("qualified")]
                    report = {**state["sources"], "status": "ok" if len(final) == sum(limits.values()) else "partial" if manual and final else "needs_more",
                              "publication_limits": limits, "measurement_mode": self.settings.get("measurement_mode", "proxy"),
                              "manual_publication": manual,
                              "candidate_total": len(state["pool"]), "tested_count": len(state["results"]),
                              "qualified_count": len(qualified), "jp_qualified_count": sum(x.get("jp_qualified", False) for x in qualified),
                              "mihomo_version": self.manager.version, "batch_total": math.ceil(len(state["pool"]) / 100),
                              "batch_completed": math.ceil(len(state["results"]) / 100), "run_id": state["run_id"],
                              "cycle": state["cycle"], "session_id": state["session_id"],
                              "previous_general_competitors": len(state.get("previous_general", []))}
                    result = publish(self.settings["output_dir"], final, report)
                    atomic_write_bytes(self.settings["root"] / "data/handoff/proxybench-attempted.json.gz",
                                       gzip.compress(json.dumps(sorted({x["ip"] for x in state["pool"]})).encode(), mtime=0))
                    if manual or result["published"] or (self.settings["max_cycles"] and state["cycle"] >= self.settings["max_cycles"]) or handoff:
                        state["phase"] = "scan" if manual and len(state["results"]) < len(state["pool"]) else "completed" if result["published"] else "needs_more"
                        self.store.commit()
                        self.update(status="Stopped" if manual else state["phase"], stage="手动复测完成，正在准备推送" if manual else state["phase"],
                                    publication_phase="publish" if manual else "", candidates=[])
                        return result
                    self.control.checkpoint()
                    fresh, source_report = self.new_pool(profile, False)
                    previous = {item["ip"] for item in state["pool"]}
                    state["pool"].extend(item for item in fresh if item["ip"] not in previous)
                    state.update(cycle=state["cycle"] + 1, phase="scan", sources=source_report, general_results={}, jp_results={})
                    self.store.commit()
            except ProfileChanged:
                self.store.commit()
                raise
            except Stopped:
                self.store.commit()
                self.update(status="Stopped", stage="状态已保存，可继续")
                return {"status": "stopped", "published": False}
            except Exception as exc:
                if self.store.state:
                    self.store.commit()
                self.update(status="Failed", stage=safe_error(exc))
                publish(self.settings["output_dir"], [], {"status": "failed", "measurement_mode": self.settings.get("measurement_mode", "proxy"), "error_category": safe_error(exc),
                        "last_good_preserved": (self.settings["output_dir"] / "nodes.json").exists()})
                raise
            finally:
                self.manager.benchmark_active = False
                self.manager.stop()
                self.update(mihomo=self.manager.health())

    @staticmethod
    def competition_candidates(fresh: list[dict], incumbents: list[dict]) -> list[dict]:
        # Incumbents are always admitted to the final competition, even outside the fresh top 200.
        records = Pipeline.unique_ips([Pipeline.candidate(x) for x in [*incumbents, *fresh]])
        for index, row in enumerate(records, 1):
            row["proxy_name"] = f"PB-COMP-{index:06d}"
        return records

    def refresh_retests(self, field: str) -> None:
        # A failed competition result must not freeze the next round's shortlist with stale passes.
        for key, result in self.store.state.get(field, {}).items():
            if key in self.store.state["results"]:
                self.store.state["results"][key] = copy.deepcopy(result)

    def incumbent_candidates(self, profile: ProxyProfile, lane: str) -> list[dict]:
        limits = publication_limits(current_rules(self.settings))
        limit = limits["general"] if lane == "general" else limits["japan"]
        candidates = []
        for index, item in enumerate(self.incumbents):
            if item.get("lane", "general" if index < 100 else "jp_append") != lane:
                continue
            candidates.append({"ip": item["ip"], "port": profile.port, "proxy_name": f"PB-OLD-{index + 1:03d}",
                               "source_names": item.get("sources", ["last-good"]),
                               "source_types": ["previous_published_candidate"], "source_priority": 0,
                               "jp_hint": lane == "jp_append"})
        return self.unique_ips(candidates)[:limit]

    @staticmethod
    def candidate(result: dict) -> dict:
        fields = {"ip", "port", "proxy_name", "source_names", "source_types", "source_priority", "jp_hint", "first_seen", "last_seen", "profile_file"}
        return {key: copy.deepcopy(value) for key, value in result.items() if key in fields}

    @staticmethod
    def unique_ips(records: list[dict]) -> list[dict]:
        seen = set()
        return [item for item in records if item["ip"] not in seen and not seen.add(item["ip"])]

    def validate_runtime(self) -> dict:
        profile = ProxyProfile.load(self.settings["profile"])
        payload = yaml.safe_load(self.settings["profile"].read_text(encoding="utf-8-sig"))
        ips = payload.get("validation_servers", [])
        import ipaddress

        from sources.cloudflare_official import collect
        self.update(stage="准备规则代理内核检查", status="Running")
        pool, networks = collect(100, profile.port, secrets.token_hex(16), set(ips))
        ips = [ip for ip in ips if any(ipaddress.IPv4Address(ip) in network for network in networks)]
        ips = list(dict.fromkeys([*ips, *(item["ip"] for item in pool)]))
        rules = current_rules(self.settings)
        self.store.state = {"run_id": secrets.token_hex(16), "phase": "validation"}
        report = {"profile_fingerprint": profile.fingerprint, "steps": [],
                  "runtime_ready": False, "method": "isolated-rule-core-check-v2",
                  "speed_method": "legacy-proxy-speed", "speed_acceptance_gate": False}
        with RunLock(self.settings["runtime_dir"]):
            self.control.path.unlink(missing_ok=True)
            try:
                self.manager.ensure(self.settings["auto_update"])
                for count in (1, 10, 100):
                    self.control.checkpoint()
                    candidates = [{"ip": ip, "port": profile.port, "proxy_name": f"PB-{index:06d}",
                                   "source_names": ["local-profile-validation"], "source_types": ["cloudflare_edge_candidate"],
                                   "source_priority": 0, "jp_hint": False} for index, ip in enumerate(ips[:count], 1)]
                    self.update(stage=f"规则代理内核检查：加载 {count} 个节点", status="Running")
                    self.manager.load_batch(candidates, profile)
                    if count == 1:
                        primary = self.manager.controller.delay(candidates[0]["proxy_name"], "https://cp.cloudflare.com/", "200-399", rules["request_timeout_seconds"])
                        report["cloudflare_primary_preflight"] = primary["success"]
                        if not primary["success"]:
                            trace_url = "https://www.cloudflare.com/cdn-cgi/trace"
                            trace = self.manager.controller.delay(candidates[0]["proxy_name"], trace_url, "200", rules["request_timeout_seconds"])
                            report["cloudflare_trace_preflight"] = trace["success"]
                            if trace["success"]:
                                self.cloudflare_url = trace_url
                        report["cloudflare_url"] = self.cloudflare_url
                    step = {"candidate_count": count, "loaded_proxies": len(candidates), "passed": True,
                            "rule_mode": True, "speed_measurements": 0}
                    report["steps"].append(step)
                    report["mihomo_version"] = self.manager.version
                    atomic_write_json(self.settings["runtime_dir"] / "validation.json", report)
                report["runtime_ready"] = True
                atomic_write_json(self.settings["runtime_dir"] / "validation.json", report)
                self.update(status="Validation Passed", stage="规则代理内核已就绪，网速将在逐个 IP 优选时测量")
                return report
            finally:
                self.manager.benchmark_active = False
                self.manager.stop()
                self.update()
