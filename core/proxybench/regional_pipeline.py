"""Measure the complete pool, then fill a live regional budget with fresh retests."""
from __future__ import annotations

import gzip
import json
import math

from core.io_utils import atomic_write_bytes

from .benchmark import limit_failure
from .export import publish
from .publication_policy import current, preview, select
from .settings import BATCH_SIZE, current_rules


def run(pipeline, profile, handoff, publish_only):
    p, state = pipeline, pipeline.store.state
    while True:
        profiles = p.profiles(state["pool"], profile)
        if state["phase"] == "scan":
            p.scan(p.ordered_candidates(state["pool"]), "results", profiles)
            state.update(phase="regional_retest", competition_rules=current_rules(p.settings))
            p.store.commit()
        rules = current_rules(p.settings)
        if state.get("competition_rules") != rules:
            state.update(phase="regional_retest", competition_rules=rules, regional_results={})
            p.reset_retest_progress()
            p.store.commit()
            p.update(stage="测速规则已更新，按新规则重新复测", status="Running")
        policy = current(p.settings)
        manual = publish_only or p.control.publication_requested()
        fresh = [r for r in state.get("results", {}).values() if r.get("qualified") and not limit_failure(r, rules)]
        checked = [r for r in state.get("regional_results", {}).values() if r.get("qualified") and not limit_failure(r, rules)]
        processed = state.get("processed", {}).get("regional_results", {})
        # Failed retests cannot enter a later shortlist via an old qualification.
        eligible = {f"{r['ip']}:{r['port']}": r for r in fresh if f"{r['ip']}:{r['port']}" not in processed}
        eligible.update({f"{r['ip']}:{r['port']}": r for r in checked})
        shortlist = select(list(eligible.values()), policy)
        pending = [p.candidate(r) for r in shortlist if f"{r['ip']}:{r['port']}" not in processed]
        # Every previously published address joins the new competition, regardless of its old rank.
        incumbents = [r for r in [*state.get("previous_general", []), *state.get("previous_jp", [])]
                      if f"{r['ip']}:{r['port']}" not in processed]
        pending = p.competition_candidates(pending, incumbents)
        if pending:
            state["phase"] = "regional_retest"
            p.update(stage="发布前按地区上限复测新旧 IP", status="Running")
            p.scan(pending, "regional_results", profiles, fixed_rules=rules)
            p.refresh_retests("regional_results")
            p.store.commit()
            continue  # Re-read live settings and use qualified backups before fetching another pool.
        final = select(checked, policy)
        if rules != current_rules(p.settings) or policy != current(p.settings):
            continue
        summary = preview(list(eligible.values()), policy)
        state["phase"] = "publish"
        report = {**state.get("sources", {}),
                  "status": "ok" if len(final) == policy["total"] else "partial" if manual and final else "needs_more",
                  "publication_limits": policy, "publication_preview": summary, "measurement_rules": rules,
                  "measurement_mode": p.settings.get("measurement_mode", "proxy"), "manual_publication": manual,
                  "candidate_total": len(state["pool"]), "tested_count": p.tested_count(),
                  "qualified_count": len(fresh), "jp_qualified_count": sum(r.get("jp_qualified", False) for r in fresh),
                  "mihomo_version": p.manager.version, "batch_total": math.ceil(len(state["pool"]) / BATCH_SIZE),
                  "batch_completed": math.ceil(p.tested_count() / BATCH_SIZE), "run_id": state["run_id"],
                  "cycle": state["cycle"], "session_id": state["session_id"],
                  "previous_general_competitors": len(state.get("previous_general", []))}
        result = publish(p.settings["output_dir"], final, report)
        atomic_write_bytes(p.settings["root"] / "data/handoff/proxybench-attempted.json.gz",
                           gzip.compress(json.dumps(sorted({r["ip"] for r in state["pool"]})).encode(), mtime=0))
        state["publication_limits"] = policy
        if manual or result["published"] or handoff or state["cycle"] >= policy["max_rounds"]:
            state["phase"] = "scan" if manual and p.tested_count() < len(state["pool"]) else "completed" if result["published"] else "needs_more"
            p.store.commit()
            p.update(status="Stopped" if manual else state["phase"],
                     stage="手动复测完成，正在准备推送" if manual else "复测已完成，准备推送" if result["published"] else
                     f"按地区上限可发布 {len(final)}/{policy['total']} 个，需补充候选",
                     publication_phase="publish" if manual else "", candidates=[])
            return result
        p.control.checkpoint()
        fresh_pool, sources = p.new_pool(profile, False)
        previous = {r["ip"] for r in state["pool"]}
        state["pool"].extend(r for r in fresh_pool if r["ip"] not in previous)
        state.update(cycle=state["cycle"] + 1, phase="scan", sources=sources)
        # Fresh, successful retests stay valid in this competition; new candidates are all measured.
        p.store.commit()
