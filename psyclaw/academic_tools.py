"""Native Agent tools for academic material, Skill, handoff, and figure work."""
from __future__ import annotations

import json
from pathlib import Path


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _project_path(project_dir: str, raw: str, *, default: str = "") -> tuple[Path | None, str]:
    root = Path(project_dir).resolve()
    candidate = Path(raw or default).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None, f"路径超出项目目录:{path}"
    parts = rel.parts
    if parts[:2] == ("data", "raw") or (parts and parts[0] in {".git", ".psyclaw"}):
        return None, f"受保护路径不可用于 Agent 工具:{rel}"
    return path, ""


def merge_academic_tools(tools: dict, project_dir: str = ".") -> None:
    """Register structured tools; existing names always win."""
    def register(name, desc, args, run, *, side_effect=True):
        def safe_run(payload):
            try:
                return run(payload or {})
            except Exception as exc:  # every native tool fails as structured JSON
                return _json({"ok": False, "status": "tool_error",
                              "tool": name, "note": f"{type(exc).__name__}: {exc}"})
        tools.setdefault(name, {"desc": desc, "args": args, "run": safe_run,
                                "side_effect": side_effect})

    def orchestrate(a):
        from psyclaw.academic_orchestrator import orchestrate_academic_task
        return _json(orchestrate_academic_task(
            str(a.get("task") or ""), project_dir=project_dir,
            mode=str(a.get("mode") or "") or None,
            source_dir=a.get("source_dir"), output_dir=str(a.get("output_dir") or "notes/compiled-skill"),
            execute=bool(a.get("execute", True)), claims=a.get("claims"), inputs=a.get("inputs"),
            handoff_goal=a.get("handoff_goal"), next_steps=a.get("next_steps")))
    register("academic_orchestrate",
             "识别学术任务并生成可审计步骤；可执行确定性阶段，遇到判断/证据/权限边界自动停下",
             "task:str, mode?:distill|evidence|figure|handoff, source_dir?:str, output_dir?:str, execute?:bool, claims?:list, inputs?:list[str], handoff_goal?:str, next_steps?:list[str]",
             orchestrate)

    def material_convert(a):
        from psyclaw.materials import convert_to_markdown, convert_video_url
        url = str(a.get("url") or "").strip()
        source = str(a.get("source") or "").strip()
        default = "notes/materials/video-material.md" if url else f"notes/materials/{Path(source).stem or 'material'}.md"
        output, error = _project_path(project_dir, str(a.get("output") or ""), default=default)
        if error:
            return _json({"ok": False, "status": "denied", "note": error})
        if url:
            return _json(convert_video_url(url, output, language=str(a.get("language") or "zh,en")))
        path, error = _project_path(project_dir, source)
        if error or not source:
            return _json({"ok": False, "status": "denied", "note": error or "需要 source 或 url"})
        return _json(convert_to_markdown(path, output))
    register("material_convert",
             "将项目内资料或视频 URL 转成 Markdown，并返回 SHA-256/complete|partial|error 审计",
             "source?:str, url?:str, output?:str, language?:str", material_convert)

    def material_compile(a):
        from psyclaw.knowledge_compile import compile_materials
        source, error = _project_path(project_dir, str(a.get("source_dir") or ""))
        output, out_error = _project_path(project_dir, str(a.get("output_dir") or ""),
                                          default="notes/compiled-skill")
        if error or out_error or not a.get("source_dir"):
            return _json({"ok": False, "status": "denied",
                          "note": error or out_error or "需要 source_dir"})
        return _json(compile_materials(source, output,
                                       skill_name=str(a.get("skill_name") or "Compiled Research Skill")))
    register("material_compile",
             "把项目内资料目录编译成可导航 INDEX、manifest、Claim 账本、验证清单和 staged/v0 Skill",
             "source_dir:str, output_dir?:str, skill_name?:str", material_compile)

    def claim_record(a):
        from psyclaw.knowledge_compile import append_claim
        bundle, error = _project_path(project_dir, str(a.get("bundle") or ""))
        if error or not a.get("bundle"):
            return _json({"ok": False, "status": "denied", "note": error or "需要 bundle"})
        return _json(append_claim(bundle, claim=str(a.get("claim") or ""),
                                  source=str(a.get("source") or ""),
                                  status=str(a.get("status") or "unverified"),
                                  locator=str(a.get("locator") or "")))
    register("skill_claim_record",
             "向编译 Skill 的 Claim-Evidence 账本追加一条声明；默认 unverified，不推断真实性",
             "bundle:str, claim:str, source:str, status?:verified|unverified|inferred|unknown, locator?:str",
             claim_record)

    def validation_record(a):
        from psyclaw.knowledge_compile import record_validation
        bundle, error = _project_path(project_dir, str(a.get("bundle") or ""))
        if error or not a.get("bundle"):
            return _json({"ok": False, "status": "denied", "note": error or "需要 bundle"})
        evidence = a.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        return _json(record_validation(bundle, kind=str(a.get("kind") or ""),
                                       passed=bool(a.get("passed", False)),
                                       evidence=evidence, notes=str(a.get("notes") or "")))
    register("skill_validate",
             "记录 known/forward/contrast/boundary 验证；失败或缺证据时不会晋升",
             "bundle:str, kind:known|forward|contrast|boundary, passed:bool, evidence?:list[str], notes?:str",
             validation_record)

    def promote(a):
        from psyclaw.knowledge_compile import promote_compiled_skill
        bundle, error = _project_path(project_dir, str(a.get("bundle") or ""))
        if error or not a.get("bundle"):
            return _json({"ok": False, "status": "denied", "note": error or "需要 bundle"})
        return _json(promote_compiled_skill(bundle, reviewer=str(a.get("reviewer") or "agent+human")))
    register("skill_promote",
             "仅在四类验证全通过且存在带来源 verified claim 时，将 staged Skill 晋升 v3",
             "bundle:str, reviewer?:str", promote)

    def status(a):
        bundle, error = _project_path(project_dir, str(a.get("bundle") or ""))
        if error or not bundle or not bundle.is_dir():
            return _json({"ok": False, "status": "missing", "note": error or "bundle 不存在"})
        result = {"ok": True, "bundle": str(bundle)}
        for name in ("manifest.json", "claims.json", "validation.json"):
            path = bundle / name
            result[name.removesuffix(".json")] = (json.loads(path.read_text(encoding="utf-8"))
                                                    if path.is_file() else None)
        skill = bundle / "SKILL.md"
        result["skill_exists"] = skill.is_file()
        return _json(result)
    register("skill_bundle_status", "读取编译 Skill 的 manifest、Claim 和四类验证状态，不写文件",
             "bundle:str", status, side_effect=False)

    def skill_search(a):
        from psyclaw.skills.registry import search_skills
        tags = a.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        results = search_skills(
            str(a.get("query") or ""), category=str(a.get("category") or "") or None,
            tags=tags, scope=str(a.get("scope") or "") or None,
            top_k=int(a.get("top_k") or 8), project_dir=project_dir,
            include_duplicates=bool(a.get("include_duplicates", False)),
            include_disabled=bool(a.get("include_disabled", False)))
        return _json({"ok": True, "status": "matched" if results else "no_match",
                      "count": len(results), "results": results})
    register("skill_search",
             "按任务、分类、标签和作用域检索 Skill 摘要；不执行 Skill，也不默认加载完整正文",
             "query:str, category?:str, tags?:list[str], scope?:builtin|project|global|custom, top_k?:int, include_duplicates?:bool, include_disabled?:bool",
             skill_search, side_effect=False)

    def skill_get(a):
        from psyclaw.skills.registry import get_skill
        name = str(a.get("name") or "").strip()
        if not name:
            return _json({"ok": False, "status": "invalid", "note": "需要 Skill name"})
        skill = get_skill(name, project_dir=project_dir,
                          include_body=bool(a.get("include_body", True)),
                          include_duplicates=bool(a.get("include_duplicates", False)),
                          include_disabled=bool(a.get("include_disabled", False)))
        if skill is None:
            return _json({"ok": False, "status": "not_found", "name": name})
        return _json({"ok": True, "status": "found", "skill": skill})
    register("skill_get", "按精确名称读取单个已索引 Skill；路径由 Registry 决定，不能任意读文件",
             "name:str, include_body?:bool, include_duplicates?:bool, include_disabled?:bool", skill_get, side_effect=False)

    def duplicates(a):
        from psyclaw.skills.registry import load_registry
        items = load_registry(project_dir).get("duplicates", [])
        name = str(a.get("name") or "").strip()
        if name:
            items = [item for item in items if item.get("name") == name]
        return _json({"ok": True, "count": len(items), "duplicates": items})
    register("skill_duplicates", "列出同名 Skill 的全部来源、副本路径和主选项；不加载正文",
             "name?:str", duplicates, side_effect=False)

    def plugins_catalog(_a):
        from psyclaw.plugins_catalog import discover_plugins
        plugins = discover_plugins(project_dir)
        return _json({"ok": True, "count": len(plugins), "plugins": plugins})
    register("skill_plugin_catalog", "识别 Claude Code/Codex/cc-switch 插件及其 Skill 数量；只读元数据，不导入插件代码",
             "", plugins_catalog, side_effect=False)

    def set_skill(a, enabled):
        from psyclaw.skills.registry import build_registry, rebuild_registry
        from psyclaw.skills.state import set_skill_enabled, source_preference
        name = str(a.get("name") or "")
        registry = build_registry(project_dir)
        matches = [s for s in registry.get("skills", []) if s.get("name") == name]
        if not matches:
            return _json({"ok": False, "status": "not_found", "name": name})
        if (enabled and len(matches) > 1 and not any(s.get("scope") == "builtin" for s in matches)
                and not source_preference(name, project_dir)):
            return _json({"ok": False, "status": "source_required", "name": name,
                          "sources": [s.get("path") for s in matches],
                          "note": "同名 Skill 必须先用 skill_source_select 选择来源"})
        result = set_skill_enabled(name, enabled, project_dir=project_dir,
                                   scope=str(a.get("scope") or "global"))
        if result.get("ok"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_enable", "启用一个已发现 Skill；项目设置优先于全局设置",
             "name:str, scope?:global|project", lambda a: set_skill(a, True))
    register("skill_disable", "停用一个 Skill 但保留文件和来源；锁定 core 不可停用",
             "name:str, scope?:global|project", lambda a: set_skill(a, False))

    def source_select(a):
        from psyclaw.skills.registry import build_registry, rebuild_registry
        from psyclaw.skills.state import select_source
        name = str(a.get("name") or "")
        registry = build_registry(project_dir)
        matches = [s for s in registry.get("skills", []) if s.get("name") == name]
        candidates = []
        for item in matches:
            path = Path(str(item.get("path", "")))
            candidates.append(str(path if path.is_absolute() else Path(project_dir).resolve() / path))
        result = select_source(name, str(a.get("source") or ""), candidates,
                               project_dir=project_dir,
                               scope=str(a.get("scope") or "project"))
        if result.get("ok"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_source_select", "为同名 Skill 显式选择唯一来源；选择后才能启用冲突项",
             "name:str, source:str, scope?:global|project", source_select)

    def skill_state(_a):
        from psyclaw.skills.registry import build_registry
        from psyclaw.skills.state import load_state
        registry = build_registry(project_dir)
        selected = [s for s in registry.get("skills", []) if s.get("selected", True)]
        return _json({"ok": True,
                      "enabled": sum(1 for s in selected if s.get("enabled")),
                      "disabled": sum(1 for s in selected if not s.get("enabled")),
                      "global": load_state(project_dir, "global"),
                      "project": load_state(project_dir, "project")})
    register("skill_state", "读取全局/项目 Skill 启停覆盖和当前有效数量，不加载 Skill 正文",
             "", skill_state, side_effect=False)

    def pack_list(_a):
        from psyclaw.skills.packs import list_packs
        packs = list_packs(project_dir)
        return _json({"ok": True, "count": len(packs), "packs": packs})
    register("skill_pack_list", "列出系统领域包、安装状态、启用状态和同步来源",
             "", pack_list, side_effect=False)

    def pack_install(a):
        from psyclaw.skills.packs import install_pack
        from psyclaw.skills.registry import rebuild_registry
        result = install_pack(str(a.get("pack") or ""), project_dir=project_dir,
                              scope=str(a.get("scope") or "global"),
                              dry_run=bool(a.get("dry_run", False)))
        if result.get("ok") and not a.get("dry_run"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_pack_install", "一键安装并启用系统领域 Skill 包；远程 source 仅接受 catalog 中的 HTTPS 地址",
             "pack:str, scope?:global|project, dry_run?:bool", pack_install)

    def pack_update(a):
        from psyclaw.skills.packs import update_pack
        from psyclaw.skills.registry import rebuild_registry
        result = update_pack(str(a.get("pack") or ""), project_dir=project_dir,
                             scope=str(a.get("scope") or "global"),
                             dry_run=bool(a.get("dry_run", False)))
        if result.get("ok") and not a.get("dry_run"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_pack_update", "同步更新一个已安装领域包的全部 Git source",
             "pack:str, scope?:global|project, dry_run?:bool", pack_update)

    def pack_catalog_sync(a):
        from psyclaw.skills.packs import sync_pack_catalog
        from psyclaw.skills.registry import rebuild_registry
        result = sync_pack_catalog(str(a.get("url") or "") or None)
        if result.get("ok"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_pack_catalog_sync", "同步官方领域包目录；核心包定义不可被远程覆盖",
             "url?:str", pack_catalog_sync)

    def set_pack(a, enabled):
        from psyclaw.skills.packs import load_pack_catalog
        from psyclaw.skills.registry import rebuild_registry
        from psyclaw.skills.state import set_pack_enabled
        pack_id = str(a.get("pack") or "")
        pack = next((p for p in load_pack_catalog().get("packs", []) if p.get("id") == pack_id), None)
        if pack is None:
            return _json({"ok": False, "status": "not_found", "pack": pack_id})
        from psyclaw.skills.packs import list_packs
        current = next((p for p in list_packs(project_dir) if p.get("id") == pack_id), pack)
        if enabled and not current.get("installed"):
            return _json({"ok": False, "status": "not_installed", "pack": pack_id})
        result = set_pack_enabled(pack_id, enabled, project_dir=project_dir,
                                  scope=str(a.get("scope") or "global"),
                                  locked=bool(pack.get("required")),
                                  installed=bool(current.get("installed")))
        if result.get("ok"):
            rebuild_registry(project_dir)
        return _json(result)
    register("skill_pack_enable", "启用整个领域包；单 Skill 显式设置仍可覆盖",
             "pack:str, scope?:global|project", lambda a: set_pack(a, True))
    register("skill_pack_disable", "停用整个领域包但保留已安装文件；core 包不可停用",
             "pack:str, scope?:global|project", lambda a: set_pack(a, False))

    def categories(_a):
        from psyclaw.skills.registry import skill_categories
        items = skill_categories(project_dir=project_dir)
        return _json({"ok": True, "categories": items,
                      "count": sum(item["count"] for item in items)})
    register("skill_categories", "列出 Skill 标准分类和各分类数量，不加载 Skill 正文",
             "", categories, side_effect=False)

    def registry_rebuild(a):
        from psyclaw.skills.registry import rebuild_registry
        result = rebuild_registry(project_dir,
                                  include_external=bool(a.get("include_external", True)),
                                  include_legacy=bool(a.get("include_legacy", False)))
        result["duplicates"] = result.get("registry", {}).get("duplicates", [])
        result.pop("registry", None)
        return _json(result)
    register("skill_registry_rebuild", "重建项目 Skill 索引到 .psyclaw/skill_registry.json；不修改源 Skill",
             "include_external?:bool, include_legacy?:bool", registry_rebuild)

    def handoff(a):
        from psyclaw.handoff import write_handoff
        output, error = _project_path(project_dir, str(a.get("output") or ""), default="HANDOFF.md")
        if error:
            return _json({"ok": False, "status": "denied", "note": error})
        def values(name):
            value = a.get(name) or []
            return [value] if isinstance(value, str) else list(value)
        return _json(write_handoff(project_dir, goal=str(a.get("goal") or ""),
                                   next_steps=values("next_steps"), completed=values("completed"),
                                   blockers=values("blockers"), output=output))
    register("session_handoff_write",
             "写可验证 HANDOFF.md + JSON，保存目标、完成项、下一步和阻塞，供新会话核验",
             "goal:str, next_steps:list[str], completed?:list[str], blockers?:list[str], output?:str",
             handoff)

    def compose(a):
        from psyclaw.figures import compose_figures
        raw_inputs = a.get("inputs") or []
        if isinstance(raw_inputs, str):
            raw_inputs = [raw_inputs]
        inputs = []
        for raw in raw_inputs:
            path, error = _project_path(project_dir, str(raw))
            if error:
                return _json({"ok": False, "status": "denied", "note": error})
            inputs.append(path)
        output, error = _project_path(project_dir, str(a.get("output") or ""),
                                      default="figures/composed.png")
        if error:
            return _json({"ok": False, "status": "denied", "note": error})
        return _json(compose_figures(inputs, output, columns=int(a.get("columns", 2)),
                                     labels=bool(a.get("labels", True)), gap=int(a.get("gap", 24))))
    register("figure_compose",
             "把已有科研 PNG/JPG 确定性组装为多面板图，并生成输入哈希审计；不生成统计数值",
             "inputs:list[str], output?:str, columns?:int, labels?:bool, gap?:int", compose)
