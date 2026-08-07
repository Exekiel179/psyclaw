"""Auditable orchestration for the academic-agent tool surface.

The model remains responsible for interpretation and judgment. This module
provides deterministic routing, checkpoints, candidate extraction, and stop
conditions so those judgments have a stable workflow to operate within.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from psyclaw.knowledge_compile import append_claim, compile_materials

ROUTES = {
    "distill": ("蒸馏资料/生成 Skill", ("蒸馏", "skill", "导师", "知识库", "材料")),
    "evidence": ("Claim-Evidence 核验", ("证据", "引用", "claim", "reference", "文献")),
    "figure": ("科研绘图/组图", ("画图", "绘图", "figure", "组图", "plot", "图片")),
    "handoff": ("跨会话交接", ("交接", "handoff", "续接", "下一会话")),
}


def route_task(task: str, requested: str | None = None) -> dict:
    """Route by explicit mode first, then conservative keyword matching."""
    if requested in ROUTES:
        mode = requested
        reason = "用户显式指定"
    else:
        low = (task or "").lower()
        scores = {name: sum(1 for word in words if word.lower() in low)
                  for name, (_label, words) in ROUTES.items()}
        mode = max(scores, key=scores.get) if max(scores.values(), default=0) else "distill"
        reason = "关键词路由" if max(scores.values(), default=0) else "无明确意图，默认资料蒸馏"
    return {"mode": mode, "label": ROUTES[mode][0], "reason": reason}


def _base_steps(mode: str) -> list[dict]:
    common = [{"id": "route", "status": "planned", "tool": "academic_orchestrate",
               "stop_if": "任务对象或权限边界不清，先向用户澄清"},
              {"id": "skill_discovery", "status": "planned", "tool": "skill_search",
               "stop_if": "没有可靠匹配时按普通流程继续，不编造或强行套用 Skill"}]
    if mode == "distill":
        return common + [
            {"id": "compile", "status": "planned", "tool": "material_compile",
             "stop_if": "源材料缺失或转换失败率过高"},
            {"id": "candidate_claims", "status": "planned", "tool": "skill_claim_record",
             "stop_if": "候选 Claim 没有来源定位；全部保持 unverified"},
            {"id": "evidence_review", "status": "pending", "tool": "skill_validate",
             "stop_if": "没有直接证据或出现反证，不得晋升"},
            {"id": "forward_validation", "status": "pending", "tool": "skill_validate",
             "stop_if": "新任务表现没有优于普通流程，保持 staged"},
            {"id": "promote", "status": "pending", "tool": "skill_promote",
             "stop_if": "四类验证或 verified Claim 任一缺失，fail-closed"},
        ]
    if mode == "evidence":
        return common + [
            {"id": "split_claims", "status": "planned", "tool": "skill_claim_record",
             "stop_if": "无法给 Claim 提供稳定 locator"},
            {"id": "match_sources", "status": "pending", "tool": "skill_validate",
             "stop_if": "主题相关但没有实际支持，标 unknown"},
        ]
    if mode == "figure":
        return common + [
            {"id": "inspect_data", "status": "planned", "tool": "read_file",
             "stop_if": "数据摘要不足或原始数据路径受保护"},
            {"id": "generate_or_compose", "status": "pending", "tool": "figure_compose",
             "stop_if": "图件缺 sidecar、坐标/误差棒不诚实，停止交付"},
        ]
    return common + [
        {"id": "write_handoff", "status": "planned", "tool": "session_handoff_write",
         "stop_if": "目标、完成项和下一步无法核对"},
        {"id": "reverify", "status": "pending", "tool": "skill_bundle_status",
         "stop_if": "下一会话必须重新检查文件和测试，不信任旧状态"},
    ]


def _candidate_claims(bundle: Path) -> list[dict]:
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates: list[dict] = []
    for item in manifest.get("materials", []):
        path = bundle / item.get("path", "")
        if not path.is_file():
            continue
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            text = re.sub(r"^#+\s*", "", raw).strip()
            if not text or text.startswith("|") or text.startswith("---") or len(text) < 12:
                continue
            # A candidate is a locator-backed prompt for review, never a fact.
            candidates.append({"claim": text[:500], "source": item.get("id", ""),
                               "status": "unverified", "locator": f"line {line_no}",
                               "notes": "auto-extracted candidate; human/evidence review required"})
    return candidates


def orchestrate_academic_task(task: str, *, project_dir: str | Path = ".",
                              mode: str | None = None, source_dir: str | Path | None = None,
                              output_dir: str | Path = "notes/compiled-skill",
                              execute: bool = True, claims: list[dict] | None = None,
                              inputs: list[str | Path] | None = None,
                              handoff_goal: str | None = None,
                              next_steps: list[str] | None = None) -> dict:
    """Return a plan and optionally execute only deterministic, reversible stages."""
    route = route_task(task, mode)
    steps = _base_steps(route["mode"])
    result: dict = {"ok": True, "status": "planned", "route": route,
                    "task": task, "steps": steps, "executed": []}
    from psyclaw.skills.registry import search_skills
    result["skill_matches"] = search_skills(task, project_dir=str(project_dir), top_k=5)
    if not execute:
        return result
    root = Path(project_dir).resolve()
    bundle = Path(output_dir)
    if not bundle.is_absolute():
        bundle = root / bundle
    try:
        bundle = bundle.resolve()
        bundle.relative_to(root)
    except ValueError:
        return {**result, "status": "blocked", "note": "output_dir 超出项目目录"}
    if route["mode"] == "distill":
        if source_dir is None:
            result["status"] = "needs_input"
            result["note"] = "资料蒸馏需要 source_dir；未执行写盘步骤"
            return result
        source = Path(source_dir)
        if not source.is_absolute():
            source = root / source
        try:
            source = source.resolve()
            relative_source = source.relative_to(root)
            if relative_source.parts[:2] == ("data", "raw"):
                raise ValueError("data/raw 是受保护的原始数据路径")
        except ValueError as exc:
            return {**result, "status": "blocked", "note": f"source_dir 不可访问:{exc}"}
        compiled = compile_materials(source, bundle, skill_name=str(task)[:100] or "Compiled Research Skill")
        result["executed"].append({"step": "compile", "result": compiled})
        if not compiled.get("ok"):
            result["status"] = "blocked"
            result["note"] = "资料转换失败，保持 fail-closed"
            return result
        candidates = _candidate_claims(bundle)
        for candidate in candidates:
            append_claim(bundle, claim=candidate["claim"], source=candidate["source"],
                         status="unverified", locator=candidate["locator"])
        result["executed"].append({"step": "candidate_claims", "count": len(candidates),
                                    "status": "unverified"})
        result["status"] = "staged"
        result["next_action"] = "review candidates and run known/forward/contrast/boundary validations"
        return result
    if route["mode"] == "evidence":
        if not claims:
            result["status"] = "needs_input"
            result["note"] = "证据路由需要 claims 列表；未自动推断真假"
            return result
        if not (bundle / "claims.json").is_file():
            result["status"] = "blocked"
            result["note"] = "bundle 缺少 claims.json；先执行 distill 或 material_compile"
            return result
        recorded = []
        for item in claims:
            recorded.append(append_claim(bundle, claim=str(item.get("claim") or ""),
                                          source=str(item.get("source") or ""),
                                          status=str(item.get("status") or "unverified"),
                                          locator=str(item.get("locator") or "")))
        result["executed"].append({"step": "evidence_review", "count": len(recorded),
                                    "status": "recorded"})
        result["status"] = "staged"
        result["next_action"] = "only a human/evidence verifier may mark claims verified"
        return result
    if route["mode"] == "figure":
        from psyclaw.figures import compose_figures
        paths = []
        for raw in inputs or []:
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            try:
                path = path.resolve()
                path.relative_to(root)
            except ValueError:
                return {**result, "status": "blocked", "note": f"图片路径超出项目目录:{raw}"}
            paths.append(path)
        output = bundle if bundle.suffix else bundle / "composed.png"
        composed = compose_figures(paths, output)
        result["executed"].append({"step": "generate_or_compose", "result": composed})
        result["status"] = "completed" if composed.get("ok") else "blocked"
        return result
    if route["mode"] == "handoff":
        from psyclaw.handoff import write_handoff
        handoff = write_handoff(root, goal=handoff_goal or task,
                                next_steps=next_steps or ["Re-read HANDOFF.md and verify worktree"],
                                output=bundle if bundle.suffix else root / "HANDOFF.md")
        result["executed"].append({"step": "write_handoff", "result": handoff})
        result["status"] = "completed"
        return result
    result["status"] = "planned"
    result["note"] = "该路由只生成执行计划；具体动作须由 Agent 根据输入调用对应工具"
    return result
