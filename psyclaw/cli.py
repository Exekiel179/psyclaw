"""PsyClaw CLI — 命令注册与分发。

骨架阶段用 argparse + stdlib，零依赖即可运行。
真实实现里 REPL 会换成 prompt_toolkit、provider 会接 LLM，
但命令骨架与帮助文本即为最终命令契约（见 DESIGN.md §3）。
"""

from __future__ import annotations

import argparse
import sys

from psyclaw import __version__
from psyclaw import config as cfg
from psyclaw.gates.checker import run_gates_selfcheck
from psyclaw.mcp.manager import (is_optional, list_mcp_catalog,
                                  list_mcp_catalog_with_health, probe_capabilities)
from psyclaw.skills.loader import list_skills


def _banner() -> str:
    from psyclaw import ui
    return ui.banner(__version__)


# --------------------------------------------------------------------------
# 子命令处理函数（骨架：打印契约性行为，不含真实实现）
# --------------------------------------------------------------------------

def cmd_repl(args: argparse.Namespace) -> int:
    from psyclaw.repl import run_repl
    return run_repl()


def cmd_status(args: argparse.Namespace) -> int:
    """一屏聚合项目态势(目标/澄清/回路/待决策/产物/下一步)。"""
    from psyclaw.status import collect_status, print_status
    print_status(collect_status("."))
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    """列出已加载插件(用户 项目/全局)与其注册的工具/命令。"""
    from psyclaw import ui
    from psyclaw.plugins import SCOPE_LABEL, load_plugins, plugin_dirs
    reg = load_plugins(".")
    if not (reg.loaded or reg.errors):
        print(ui.dim("未加载插件。放 <项目>/.psyclaw/plugins/*.py 或 ~/.psyclaw/plugins/*.py"
                     "(含 register(api):add_tool/add_command/add_system)即生效。"))
        return 0
    print(ui.title(f"插件({len(reg.loaded)})"))
    for p in reg.loaded:
        print(f"  - {p['name']:<20} [{SCOPE_LABEL.get(p['scope'], p['scope'])}]")
    if reg.commands:
        print(ui.dim("  命令:" + " ".join(reg.commands) + "(REPL 内可用)"))
    if reg.tools:
        print(ui.dim("  工具:" + " ".join(reg.tools) + "(agent 模式/psyclaw agent 可用)"))
    for e in reg.errors:
        print(ui.warn(f"  ⚠ {e}"))
    print(ui.dim("  目录:" + " · ".join(f"{d}[{s}]" for d, s in plugin_dirs("."))))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """投稿前一键质检:JARS + 引用保真(+期刊风格)+ 复现溯源 + KG 溯源,一屏汇总。"""
    from psyclaw.checkup import print_check, run_check
    res = run_check(draft=getattr(args, "draft", None),
                    journal=getattr(args, "journal", None),
                    project_dir=".",
                    research_type=getattr(args, "research_type", "quant"))
    print_check(res)
    return 0 if res["passed"] else 1


def cmd_agent(args: argparse.Namespace) -> int:
    """agent 一次性任务:模型自主多步调用工具(纯工具层循环,provider 无关保底)。"""
    from psyclaw import ui
    from psyclaw.providers import get_provider
    from psyclaw.repl import _build_system_prompt
    from psyclaw.toolloop import log_agent_run, read_agent_runs, run_tool_loop
    if getattr(args, "history", None) is not None:   # feat-037:回看运行痕迹
        runs = read_agent_runs(".", limit=args.history or 10)
        if not runs:
            print("(无 agent 运行记录;跑过 psyclaw agent 后这里会有痕迹)")
            return 0
        for r in runs:
            print(f"{r.get('ts', '?')}  [{r.get('iters', '?')} 轮 · "
                  f"{len(r.get('tools', []))} 工具 · {r.get('stopped', '?')}]  "
                  f"{r.get('task', '')[:60]}")
            print(ui.dim(f"    → {r.get('final_head', '')[:100]}"))
        return 0
    if not args.task:
        print("用法:psyclaw agent <任务描述> 或 psyclaw agent --history [n]")
        return 2
    conf = cfg.load_config()
    provider = get_provider(conf)
    task = " ".join(args.task)
    auto = getattr(args, "auto", False)
    approve = (lambda c: True) if auto else None   # 非 auto:拒副作用工具(只读照跑)
    print(ui.title("PsyClaw agent") + ui.dim(f"  {task}"))
    if not auto:
        print(ui.dim("  (副作用工具默认拒绝;--auto 自动批准。只读工具照常执行。)"))
    res = run_tool_loop(provider, _build_system_prompt(),
                        [{"role": "user", "content": task}], project_dir=".",
                        max_iters=getattr(args, "max_iters", 24),
                        approve=approve, emit=lambda e: print(ui.dim(f"  ⚙ {e}")))
    print(ui.dim(f"  [{res['iters']} 轮 · {len(res['trace'])} 次工具调用 · {res['stopped']}]"))
    print(res["final"])
    # feat-065:循环内蒸馏的环境教训落跨会话待确认卡(HITL:psyclaw memory confirm 才生效)
    if res.get("lessons"):
        from psyclaw.memory import draft_lesson
        for le in res["lessons"]:
            try:
                draft_lesson(le["trigger"], le["lesson"], source="error",
                             kind=le.get("kind"))
            except Exception:  # noqa: BLE001  # 落卡失败不影响任务结果
                break
        print(ui.dim(f"  📎 蒸馏环境教训 {len(res['lessons'])} 条"
                     "(psyclaw memory 查看,confirm 后跨会话生效)"))
    # feat-065:结果里提到的图片,终端支持时内联渲染
    from psyclaw.repl import render_images_in_text
    render_images_in_text("\n".join(
        [res["final"]] + [str(t.get("output", "")) for t in res["trace"]]),
        force=conf.get("image_protocol"))
    log_agent_run(".", task, res)   # feat-037:落运行痕迹(失败静默)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """续接历史会话进入 REPL(不给 id 则续接最近一次)。"""
    from psyclaw import ui
    from psyclaw.recall import ContextArchive
    from psyclaw.repl import run_repl
    sid = getattr(args, "session_id", None)
    if not sid:
        rows = ContextArchive(".").list_sessions()
        if not rows:
            print(ui.warn("无历史会话可续接;直接 `psyclaw` 进 REPL 开新会话。"))
            return 1
        sid = rows[0]["id"]
        print(ui.dim(f"未指定会话,续接最近一次:{sid}"))
    print(_banner())
    return run_repl(resume_id=sid)


def cmd_session(args: argparse.Namespace) -> int:
    """会话管理(REPL 外):list | search <词> | rename <id> <名> | delete <id>。"""
    from psyclaw import ui
    from psyclaw.recall import ContextArchive
    arch = ContextArchive(".")
    action = getattr(args, "action", None) or "list"
    rest = getattr(args, "rest", []) or []
    if action == "list":
        rows = arch.list_sessions()
        if not rows:
            print("(无历史会话)")
            return 0
        print(ui.title(f"历史会话({len(rows)})"))
        for s in rows:
            print(f"  {s['id']:<17} {s['n_turns']:>3} 轮  更新 {s['updated']}  {s['name']}")
        print(ui.dim("psyclaw resume <id> 续接 · psyclaw session search <词> 全文检索"))
        return 0
    if action == "search":
        q = " ".join(rest)
        hits = arch.search(q, limit=15)
        if not hits:
            print(f"未检索到含「{q}」的历史轮次。")
            return 0
        print(ui.title(f"检索「{q}」— {len(hits)} 条"))
        for h in hits:
            snip = h["user_text"][:70].replace("\n", " ")
            print(f"  [{h['session']}] {snip}")
        return 0
    if action == "rename":
        if len(rest) < 2:
            print(ui.err("用法:psyclaw session rename <id> <新名>"))
            return 1
        arch.rename_session(rest[0], " ".join(rest[1:]))
        print(ui.ok(f"✓ 会话 {rest[0]} 已命名:{' '.join(rest[1:])}"))
        return 0
    if action == "delete":
        if not rest:
            print(ui.err("用法:psyclaw session delete <id>"))
            return 1
        n = arch.delete_session(rest[0])
        print(ui.ok(f"✓ 已删除会话 {rest[0]}(移除 {n} 轮)"))
        return 0
    print(ui.err(f"未知子动作:{action}(list|search|rename|delete)"))
    return 1


def cmd_search(args: argparse.Namespace) -> int:
    """来源路由检索:据任务类型路由到学术库/本地(主通道 + 兜底)。"""
    from psyclaw import ui
    from psyclaw.search_router import VALID_TYPES, execute_route, route
    t = getattr(args, "type", None)
    if t and t not in VALID_TYPES:
        print(ui.err(f"未知类型 {t}(可选:{', '.join(VALID_TYPES)})"))
        return 1
    plan = route(args.query, t)
    print(ui.title("来源路由") + ui.dim(f"  {args.query}"))
    print(f"  任务类型:{plan['task_type']} — {plan['rationale']}")
    print(ui.dim(f"  主通道 {plan['primary']['source']}/{plan['primary']['mode']}"
                 f" · 兜底 {plan['fallback']['source']}/{plan['fallback']['mode']}"))
    res = execute_route(plan, args.query, project_dir=".",
                        limit=getattr(args, "limit", 10))
    used, tag = res["used"], (ui.warn("(兜底)") if res["used_fallback"] else "")
    print(ui.accent(f"  经 {used['source']}/{used['mode']} {tag}命中 {len(res['results'])} 条"))
    for r in res["results"][:12]:
        print(f"    · {(r.get('title') or '')[:80]}")
    return 0


def cmd_kg(args: argparse.Namespace) -> int:
    """带引用的知识图谱:seed(据 evidence_map 种图)| show <实体> | verify | stats。"""
    from psyclaw import ui
    from psyclaw.kg import KnowledgeGraph, render_mermaid
    kg = KnowledgeGraph(".")
    action = getattr(args, "action", "stats") or "stats"
    rest = getattr(args, "rest", []) or []
    if action == "seed":
        r = kg.seed_from_evidence_map(".")
        if r.get("error"):
            print(ui.warn(f"  {r['error']}"))
            return 1
        print(ui.ok(f"✓ 种图完成:新增 {r['added']} 条带引用边"
                    f"(节点 {r['nodes']} · 边 {r['edges']})"))
        return 0
    if action == "show":
        if not rest:
            print(ui.err("用法:psyclaw kg show <实体>"))
            return 1
        sub = kg.subgraph(" ".join(rest), depth=1)
        if not sub["nodes"]:
            print(f"  未找到实体「{' '.join(rest)}」(先 psyclaw kg seed)")
            return 0
        print(render_mermaid(sub))
        return 0
    if action == "verify":
        v = kg.verify(".")
        print(ui.title("KG 关系溯源核验")
              + ui.dim(f"  语料:{v['corpus_source'] or '(无)'}"))
        if v.get("manual_review"):
            print(ui.warn(f"  ⚠ {v.get('note', '无检索语料,需人工核')}"))
            return 0
        print(f"  citation 边 {v['citation_edges']} · 溯源命中 {v['grounded']}"
              f" · 孤儿 {len(v['orphans'])}")
        for o in v["orphans"]:
            print(ui.warn(f"    ✗ {o['edge']}(来源 {o['source_ref']} 不在检索语料=疑似杜撰关系)"))
        return 0 if v["no_orphan_relations"] else 1
    s = kg.stats()
    print(ui.title("知识图谱")
          + f"  节点 {s['nodes']} · 边 {s['edges']} · 无来源边 {s['uncited']}")
    print(ui.dim("  seed 据 evidence_map 种图 · show <实体> 看子图 · verify 溯源核验"))
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"psyclaw {__version__}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from psyclaw import ui
    print(ui.title("PsyClaw doctor — 环境自检"))
    print(ui.rule())
    conf = cfg.load_config()
    print(f"配置文件      : {conf['_source']}")
    print(f"LLM provider  : " + ui.accent(conf.get('provider', '(未设置)'))
          + ui.dim(f"  model={conf.get('model', 'default')}"))
    py = sys.version.split()[0]
    print(f"Python        : {py}")
    print("\n" + ui.accent("MCP 健康检查:"))
    mcp_catalog = list_mcp_catalog_with_health()
    mcp_failures: list[str] = []
    for m in mcp_catalog:
        h = m["health"]
        opt = is_optional(m)
        if m["enabled"]:
            if h["ok"]:
                mark = ui.ok("✓")
            else:
                mark = ui.err("✗")
                if not opt:  # 可选商业软件未安装不计入强制门禁
                    mcp_failures.append(m["name"])
        else:
            mark = ui.dim("·")
        opt_label = ui.dim(" [可选]") if opt else ""
        note = m.get("note", "") or m["enable_when"]
        detail = h["detail"] if m["enabled"] else ui.dim(h["detail"])
        print(f"  {mark} {m['name']:<14} {detail:<28} " + ui.dim(note) + opt_label)

    caps = probe_capabilities(mcp_catalog)
    if caps:
        print("\n" + ui.accent("能力探测（已启用且健康）:"))
        for cap, servers in sorted(caps.items()):
            print(f"  • {cap:<28} " + ui.dim(" + ".join(servers)))
    print("\n" + ui.accent("Gates 自检:"))
    ok = run_gates_selfcheck()
    print("\n" + ui.accent("能力矩阵:"))
    try:
        from psyclaw.bootstrap import detect
        d = detect()
        for g, info in d["groups"].items():
            mark = ui.ok("✓") if info["ready"] else ui.warn("缺(psyclaw setup)")
            print(f"  {mark} {g:<6} " + ui.dim(info["desc"]))
        for name, info in d["bins"].items():
            if info["ready"]:
                print(f"  {ui.ok('✓')} {name:<6} " + ui.dim(str(info['path'])))
    except Exception:  # noqa: BLE001
        pass
    all_ok = ok and not mcp_failures
    if mcp_failures:
        print(ui.err(f"MCP 健康失败: {', '.join(mcp_failures)}"))
    print("\n总体状态:" + (ui.ok("OK ✓") if all_ok else ui.err("有问题,请见上方")))
    return 0 if all_ok else 1


def cmd_config(args: argparse.Namespace) -> int:
    return cfg.run_config_wizard(non_interactive=args.non_interactive)


def _setup_print_mcp_skill() -> None:
    """⑤ 列出可用 MCP 服务器 + 已注册 skill(只读目录;新装 MCP 依赖见能力阶段)。"""
    from psyclaw import ui
    from psyclaw.skills.loader import list_skills
    try:
        from psyclaw.mcp.manager import list_mcp_catalog
        cat = list_mcp_catalog()
    except Exception:  # noqa: BLE001
        cat = []
    if cat:
        print(ui.dim("  内置 MCP 服务器(psyclaw mcp --serve <name>):"))
        for s in cat:
            flag = ui.ok("●就绪") if s.get("enabled") else ui.dim("○待依赖")
            print(f"    {flag}  {s['name']:<8} {ui.dim(s.get('provides', '') or s.get('note', ''))}")
    skills = list_skills()
    print(ui.dim(f"  已注册 Skill:{len(skills)} 个(psyclaw skills 看全部)"))


def cmd_setup(args: argparse.Namespace) -> int:
    # 项目脚手架 + 能力选装向导:①目录 ②clarify→概览 ③项目记忆 ④能力依赖 ⑤MCP/skill。
    from psyclaw import ui
    from psyclaw.scaffold import scaffold_project
    ni = getattr(args, "non_interactive", False)
    online = getattr(args, "online", False)

    # --env:一键配置缺失的基础环境(v0.9 feat-051),不做项目脚手架
    if getattr(args, "env", False):
        from psyclaw.env_setup import bootstrap, format_report
        print(ui.title("PsyClaw setup --env — 一键配置基础环境"))
        print(ui.rule())
        res = bootstrap(".", apply=online)
        for c in res["checks"]:
            mark = ui.ok("✓") if c["ok"] else ui.err("✗")
            print(f"  {mark} {c['label']:<16} " + ui.dim(c["detail"]))
            if not c["ok"] and c["fix"]:
                print("      " + ui.accent("→ " + c["fix"]))
        if res["installed"]:
            good = [g for g, v in res["installed"].items() if v is True]
            bad = [g for g, v in res["installed"].items() if v is False]
            if good:
                print(ui.ok("  已自动安装: ") + ", ".join(good))
            if bad:
                print(ui.err("  安装失败(请手动): ") + ", ".join(bad))
        elif res["planned"] and not online:
            print(ui.dim(f"\n  可自动安装: {', '.join(res['planned'])}"
                         " —— 加 --online 实际联网安装。"))
        print("\n环境状态: " + (ui.ok("全部就绪 ✓") if res["all_ok"]
                              else ui.warn("有缺失,见上方修法")))
        return 0 if res["all_ok"] else 1

    print(ui.title("PsyClaw setup — 项目脚手架 + 能力选装"))
    print(ui.rule())

    # ① 目录结构  ② 据澄清卡生成概览  ③ 项目记忆(均幂等)
    res = scaffold_project(".")
    cd = res["created_dirs"]
    print(ui.ok("① 目录结构就绪") + ui.dim(f"（新建 {len(cd)}：{', '.join(cd)}）" if cd else "（已存在）"))
    if res["overview"]:
        print(ui.ok("② 项目概览 → ") + ui.dim(str(res["overview"])))
    else:
        print(ui.dim("② 未找到澄清卡;先 `psyclaw clarify` 再重跑 setup 即据此生成项目概览"))
    print(ui.ok("③ 项目记忆 → ") + ui.dim(str(res["memory"])))

    # ④ 能力依赖(联网安装 opt-in:--online 自动装缺失;交互则 run_setup 内询问;否则只显示矩阵)
    print(ui.accent("\n④ 能力依赖（跑生成的统计脚本需要 pingouin/statsmodels 等）"))
    groups = args.groups.split(",") if getattr(args, "groups", None) else None
    if online:
        from psyclaw.bootstrap import detect, run_setup
        miss = [g for g, i in detect()["groups"].items() if not i["ready"]]
        run_setup(non_interactive=True, groups=groups or miss)
    elif not ni:
        from psyclaw.bootstrap import run_setup
        run_setup(non_interactive=False, groups=groups)
    else:
        from psyclaw.bootstrap import print_matrix
        print_matrix()
        print(ui.dim("  非交互且未 --online:跳过安装。重跑 `psyclaw setup --online` 联网装缺失。"))

    # ⑤ MCP / Skill 目录
    print(ui.accent("\n⑤ MCP / Skill"))
    _setup_print_mcp_skill()

    print(ui.ok("\n✓ setup 完成。下一步:psyclaw clarify(没澄清过)或选一条 loop 起跑(psyclaw guide)。"))
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from psyclaw import ui
    sync_target = getattr(args, "sync", None)
    if sync_target is not None:
        from psyclaw.skills.sync import list_syncable_skills, sync_skills
        name = None if sync_target == "all" else sync_target
        if getattr(args, "dry_run", False):
            items = sync_skills(name=name, dry_run=True)
        else:
            items = sync_skills(name=name)
        if not items:
            known = ", ".join(s.name for s in list_syncable_skills()) or "(无)"
            print(ui.err(f"没有可同步的内置 skill:{sync_target}。可同步:{known}"))
            return 1
        print(ui.title("同步内置 Skills"))
        ok = True
        for item in items:
            ok = ok and bool(item["ok"])
            marker = "✓" if item["ok"] else "✗"
            print(f"  {marker} {item['name']:<14} {item['action']:<6} {item['target']}")
            if item.get("note"):
                print(ui.dim(f"      {item['note'][:180]}"))
        return 0 if ok else 1

    for_type = getattr(args, "for_type", None)
    if for_type:
        from psyclaw.skills.recommend import VALID_TYPES, normalize_type, recommend_skills
        rt = normalize_type(for_type)
        if rt is None:
            print(ui.err(f"未知研究类型:{for_type}(可选:{', '.join(VALID_TYPES)})"))
            return 1
        recs = recommend_skills(rt)
        print(ui.title(f"{rt} 相关外部技能包推荐"))
        if not recs:
            print(ui.dim("  未发现相关外部技能包。装 AcademicForge/AJS 到 .claude/skills 后再试。"))
            return 0
        for s in recs:
            print(f"  - {s['name']:<26} {ui.dim('· '.join(s['matched']))}")
            if s.get("description"):
                print(ui.dim(f"      {s['description'][:64]}  [{s['source']}]"))
        return 0
    skills = list_skills()
    bundled = [s for s in skills if s.get("source") == "bundled"]
    external = [s for s in skills if s.get("source") != "bundled"]
    print(ui.title(f"已注册 Skills（{len(skills)}）"))
    for s in bundled:
        print(f"  - {s['name']:<20} [{s['category']}]  {s['description'][:56]}")
    if external:
        from collections import defaultdict
        by_root: dict[str, list] = defaultdict(list)
        for s in external:
            by_root[s["source"]].append(s)
        print(ui.accent(f"\n外部技能包（{len(external)} 个 · AcademicForge/AJS 等）"))
        _scope_label = {"project": "用户·项目", "global": "用户·全局", "custom": "用户·自定义"}
        for root, items in by_root.items():
            scope = _scope_label.get(items[0].get("scope", ""), "用户")
            print(ui.dim(f"  [{scope}] {root}（{len(items)}）"))
            for s in items[:12]:
                print(f"    - {s['name']:<28} {ui.dim(s['description'][:44])}")
            if len(items) > 12:
                print(ui.dim(f"    …… 另 {len(items) - 12} 个"))
    else:
        from psyclaw.skills.loader import external_skill_roots
        roots = external_skill_roots(".")
        print(ui.dim("\n未发现外部技能包。装 AcademicForge/AJS 到 .claude/skills 后自动出现:"))
        print(ui.dim("  git clone …/AcademicForge && cd AcademicForge && bash install.sh"))
        print(ui.dim(f"  已扫描根:{', '.join(str(r) for r in roots) or '(无)'}"
                     "  ·  或设 PSYCLAW_SKILLS_PATH 指向自定义目录"))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    if getattr(args, "name", None):
        if args.name == "mne":
            from psyclaw.mcp.servers.mne_server import srv
        elif args.name == "spss":
            from psyclaw.mcp.servers.spss_server import srv
        elif args.name == "mplus":
            from psyclaw.mcp.servers.mplus_server import srv
        elif args.name == "stata":
            from psyclaw.mcp.servers.stata_server import srv
        else:
            print("可 serve:mne | spss | mplus | stata")
            return 1
        return srv.run()
    print("MCP 服务器目录（内置 registry.yaml + 用户 .psyclaw/mcp.yaml 项目/全局）：")
    _scope_label = {"builtin": "内置", "project": "用户·项目", "global": "用户·全局"}
    for m in list_mcp_catalog():
        opt_tag = " [可选]" if is_optional(m) else ""
        scope = _scope_label.get(m.get("scope", "builtin"), m.get("scope", ""))
        print(f"  - {m['name']:<14} [{scope:<5}·{m['category']:<14}] "
              f"启用条件: {m.get('enable_when', '—')}{opt_tag}")
    print("\n内置 MCP 可独立 serve 给任意 MCP 客户端(Claude Desktop 等):")
    print("  psyclaw mcp --serve mne    # EEG/MEG/ERP")
    print("  psyclaw mcp --serve spss   # SPSS 语法生成 + 批处理")
    print("  psyclaw mcp --serve mplus  # Mplus CFA/SEM/LGM/Mixture 语法生成")
    print("  psyclaw mcp --serve stata  # Stata do-file 生成(面板/IV/生存等)")
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    print("PsyClaw Gates — 学术规范门禁自检\n" + "-" * 32)
    ok = run_gates_selfcheck(verbose=True)
    return 0 if ok else 1


def cmd_eval(args: argparse.Namespace) -> int:
    """确定性离线评测(feat-073):编排/门禁/自学习契约的端到端 scorecard。"""
    import json
    from pathlib import Path

    from psyclaw import ui
    from psyclaw.evalharness import format_report, run_evals
    try:
        report = run_evals(args.case or None)
    except ValueError as exc:
        print(ui.err(str(exc)))
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    out = Path(".psyclaw") / "eval_report.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        if not args.json:
            print(ui.dim(f"报告已写入 {out}"))
    except OSError as exc:
        print(ui.dim(f"(报告落盘失败,不影响评测结果:{exc})"))
    return 0 if report["all_passed"] else 1


def cmd_scale(args: argparse.Namespace) -> int:
    from psyclaw.psych.scales import print_scale
    print_scale(args.scale_id)
    return 0


def cmd_norms(args: argparse.Namespace) -> int:
    from psyclaw.psych.scales import print_cn_norms
    print_cn_norms(getattr(args, "scale_id", None))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    import json as _json
    from psyclaw import ui
    from psyclaw.psych.scales import score_datafile, write_scored_csv

    result = score_datafile(
        args.data, args.scale,
        prefix=args.prefix,
        suffix=args.suffix,
        method=args.method,
    )
    if "error" in result:
        print(ui.err(result["error"]))
        return 1

    scale = result["scale"]
    print(ui.title(f"量表自动计分 — {scale.get('name', scale['id'])}"))
    print(ui.rule())
    print(f"  数据: {args.data}  |  量表: {scale['id']}  |  聚合: {args.method}")
    print(f"  有效行: {result['n']}  |  完整应答（无缺失条目）: {result['n_complete']}")

    lo_hi = ""
    import re
    m = re.search(r"(\d+)-(\d+)", scale.get("response", ""))
    if m:
        lo_hi = f"  计分范围: {m.group(1)}–{m.group(2)}"
    if lo_hi:
        print(lo_hi)
    if result["reverse_applied"]:
        print(ui.dim(f"  反向计分条目（已翻转）: {result['reverse_applied']}"))

    if result["subscale_stats"]:
        print(ui.accent("\n子量表描述统计"))
        for sub, st in result["subscale_stats"].items():
            if st["n"] == 0:
                print(f"  {sub:<22} 无有效数据")
            else:
                print(f"  {sub:<22} M={st['mean']:.2f}  SD={st['sd']:.2f}"
                      f"  range=[{st['min']:.0f},{st['max']:.0f}]  n={st['n']}")

    ts = result["total_stats"]
    if ts and ts["n"] > 0:
        print(ui.accent("\n总分描述统计"))
        print(f"  Total  M={ts['mean']:.2f}  SD={ts['sd']:.2f}"
              f"  range=[{ts['min']:.0f},{ts['max']:.0f}]  n={ts['n']}")

    for w in result["warnings"]:
        print(ui.warn(f"\n{w}"))

    if args.out:
        write_scored_csv(result, args.out, args.data)
        print(ui.ok(f"\n  已写出计分结果: {args.out}"))

    if args.json:
        safe = {k: v for k, v in result.items() if k not in ("participants", "scale")}
        safe["scale_id"] = scale["id"]
        print(_json.dumps(safe, ensure_ascii=False, indent=2, default=float))

    return 0


def cmd_ethics(args: argparse.Namespace) -> int:
    from psyclaw import ui
    from psyclaw.psych.scales import get_scale
    from psyclaw.psych.ethics import format_ethics_report

    scale = get_scale(args.scale_id)
    if not scale:
        from psyclaw.psych.scales import list_scales
        avail = ", ".join(s["id"] for s in list_scales())
        print(ui.err(f"未知量表: {args.scale_id}。可用: {avail}"))
        return 1

    print(ui.title(f"伦理审查提示 — {scale.get('name', args.scale_id)}"))
    print(ui.rule())
    report = format_ethics_report(scale)
    # 跳过第一行标题（已由 title 显示）
    for line in report.splitlines()[1:]:
        if line.startswith("⚠"):
            print(ui.warn(line))
        elif line.startswith("ℹ"):
            print(ui.accent(line))
        else:
            print(line)
    return 0


def cmd_declare_test(args: argparse.Namespace) -> int:
    from psyclaw import ui
    from psyclaw.psych.analysis_plan import declare, load_plan
    entry = declare(
        project_dir=args.project_dir,
        dv=args.dv,
        test=args.test,
        iv=args.iv,
        hypothesis=args.hypothesis,
        name=args.name,
    )
    print(ui.ok(f"✓ 已声明分析: {entry['name']}"))
    plan = load_plan(args.project_dir)
    print(f"  计划内条目数: {len(plan['analyses'])}")
    print(f"  计划文件: {args.project_dir}/notes/analysis_plan.json")
    print(ui.dim("\n  下次跑 psyclaw stat 时将自动对照此声明校验分析类型。"))
    return 0


def cmd_assume(args: argparse.Namespace) -> int:
    from psyclaw.psych.knowledge import print_assumptions
    print_assumptions(args.test_id)
    return 0


def cmd_method(args: argparse.Namespace) -> int:
    from psyclaw.psych.knowledge import print_method
    print_method(args.method_id)
    return 0


def cmd_journal(args: argparse.Namespace) -> int:
    from psyclaw.psych.journals import print_journal
    print_journal(getattr(args, "journal_id", None))
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    from psyclaw.psych.knowledge import print_design
    print_design(args.design_id)
    return 0


def cmd_preregister(args: argparse.Namespace) -> int:
    from psyclaw.psych.preregister import run_preregister
    fmt = "osf" if args.osf else "aspredicted" if args.aspredicted else "both"
    return run_preregister(fmt=fmt)


def cmd_clarify(args: argparse.Namespace) -> int:
    from psyclaw.psych.clarify import run_clarify_interactive, print_clarify_status
    if args.status:
        return print_clarify_status()
    return run_clarify_interactive()


def cmd_cite(args: argparse.Namespace) -> int:
    from psyclaw.psych.knowledge import print_evidence
    print_evidence(args.topic_id)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    journal = getattr(args, "journal", "apa7") or "apa7"
    if journal != "apa7":
        from psyclaw.output.cn_journal import cn_journal_cli
        argv = [args.file, "--journal", journal]
        if args.md:
            argv += ["--out", args.md]
        return cn_journal_cli(argv)
    from psyclaw.output.apa7 import export_cli
    argv = [args.file]
    if args.docx:
        argv += ["--docx", args.docx]
    if args.md:
        argv += ["--md", args.md]
    return export_cli(argv)


def cmd_jars(args: argparse.Namespace) -> int:
    from psyclaw.output.jars import jars_cli
    argv = []
    if args.draft:
        argv += [args.draft]
    argv += ["--type", args.research_type]
    if args.json:
        argv += ["--json"]
    if args.no_sidecar:
        argv += ["--no-sidecar"]
    return jars_cli(argv)


def cmd_cite_check(args: argparse.Namespace) -> int:
    """引用保真核查:稿件文内引用是否都溯源到检索命中(反杜撰参考文献)。"""
    from psyclaw import ui
    from psyclaw.psych.citations import run_citation_audit
    a = run_citation_audit(args.manuscript, project_dir=getattr(args, "project", "."),
                           journal=getattr(args, "journal", None))
    print(ui.title("引用保真核查") + ui.dim(f"  {args.manuscript}"))
    print(ui.dim(f"  允许键来源:{a.get('corpus_source') or '(无检索语料)'}"))
    print(f"  {a['method']}")
    if a.get("journal"):
        mark = ui.ok("一致") if a.get("citation_style_ok") else ui.warn("不一致")
        print(ui.dim(f"  期刊:{a['journal']} · 期望 {a.get('citation_format_expected')} "
                     f"/ 实测 {a.get('citation_format_detected')} — ") + mark)
    elif a.get("journal_note"):
        print(ui.warn(f"  {a['journal_note']}"))
    if a["orphan_n"]:
        print(ui.err(f"  ✗ 孤儿引用 {a['orphan_n']} 条(疑似杜撰):"))
        for o in a["orphan"]:
            print(ui.warn(f"     · {o['raw']}"))
        print(ui.dim("  详见 notes/citation_audit.md;删除或补检索后复核。"))
        return 1
    if a["manual_review"]:
        print(ui.warn("  ⚠ 未能自动核验(见上),需人工核;详见 notes/citation_audit.md"))
        return 0
    print(ui.ok(f"  ✓ 全部 {a['cited_n']} 条文内引用均可溯源到检索命中"))
    return 0


def cmd_provenance(args: argparse.Namespace) -> int:
    """复现溯源:给生成的脚本/图打包 代码+环境+说明+决策轨迹 → <产物>.provenance.json。"""
    from psyclaw import ui
    from psyclaw.provenance import write_provenance
    prov = write_provenance(
        args.artifact, description=getattr(args, "desc", "") or "",
        project_dir=getattr(args, "project", "."),
        data_path=getattr(args, "data", None),
        data_fingerprint=getattr(args, "fingerprint", None),
        journal=getattr(args, "journal", None))
    env = prov["environment"]
    print(ui.title("复现溯源") + ui.dim(f"  {args.artifact}"))
    print(f"  代码 sha256:{(prov['artifact_sha256'] or '(读不到产物)')[:16]}…"
          if prov["artifact_sha256"] else "  代码:(读不到产物)")
    print(f"  环境:Python {env['python']} · {env['platform']}")
    print(ui.dim(f"  说明:{prov['description'] or '(无)'}"))
    print(ui.dim(f"  决策轨迹:{', '.join(prov['history']) or '(无)'}"))
    if prov.get("journal"):
        req = "要求(须带数据指纹)" if prov.get("data_availability_required") else "非强制"
        print(ui.dim(f"  期刊:{prov['journal']} · 数据可得性 {req}"))
    decl = prov.get("replication_package") or {}
    if decl.get("complete"):
        print(ui.dim("  Replication package 声明已生成(见 .provenance.md,可直接放进稿件)"))
    print(ui.dim(f"  → {prov['_sidecar']}"))
    if prov["provenance_complete"]:
        print(ui.ok("  ✓ 溯源完整(代码+环境+说明"
                    + ("+数据指纹)" if prov.get("data_availability_required") else ")")))
        return 0
    if prov.get("data_availability_required") and not prov.get("data_availability_ok"):
        print(ui.warn("  ⚠ 该期刊强制 replication-package 声明,当前缺:"
                      + ";".join(decl.get("missing") or ["数据指纹"])
                      + " —— 加 --data <数据文件>"))
    else:
        print(ui.warn("  ⚠ 溯源不完整(缺代码/环境/说明)"))
    return 1


def cmd_memory(args: argparse.Namespace) -> int:
    from psyclaw.memory import memory_cli
    return memory_cli(args.args or ["list"])


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        if args.channel == "telegram":
            from psyclaw.messengers import serve_telegram
            return serve_telegram()
        if args.channel == "wechat":
            from psyclaw import config as _cfg
            _cfg.load_env_file()
            if getattr(args, "login", False):
                from psyclaw.wechat_ilink import login_qrcode
                return login_qrcode()
            from psyclaw.wechat_ilink import serve_wechat
            return serve_wechat()
    except KeyboardInterrupt:
        print("\nbot 已停止。")
        return 0
    print("支持的通道:telegram | wechat(iLink,Hermes/OpenClaw 同款)")
    return 1


def cmd_notify(args: argparse.Namespace) -> int:
    from psyclaw import config as _cfg
    _cfg.load_env_file()
    from psyclaw.messengers import notify_cli
    return notify_cli(args.message)


def cmd_auth(args: argparse.Namespace) -> int:
    from psyclaw.psych import institution
    from psyclaw import ui
    if args.verify:
        print(ui.title("机构权限连通自检"))
        st = institution.verify()
        for m, v in st["methods"].items():
            print(f"  {m:<10} {v}")
        print(f"  在校园网  : {'是' if st.get('in_network') else '否/未知'}")
        print(ui.dim("  状态已记录到 ~/.psyclaw/institution.json"))
        return 0
    if args.set:
        print(ui.title("配置机构权限(无密码)"))
        ez = input("  EZProxy 前缀(如 https://xxx.idm.oclc.org,留空跳过): ").strip()
        lid = input("  LibKey library id(留空跳过): ").strip()
        lkey = input("  LibKey access key(留空跳过): ").strip()
        inst = input("  机构名称(可选): ").strip()
        institution.configure(ezproxy=ez, libkey_id=lid, libkey_key=lkey, institution=inst)
        print(ui.ok("  ✓ 已保存(密码永不入库)。psyclaw auth --verify 做连通自检。"))
        return 0
    institution.print_status()
    return 0


def cmd_figures(args: argparse.Namespace) -> int:
    from psyclaw.figures import figures_cli
    argv: list[str] = []
    if getattr(args, "list_styles", False):
        argv += ["--list-styles"]
    if getattr(args, "style", None):
        argv += ["--style", args.style]
    if getattr(args, "check", None):
        argv += ["--check", args.check]
    if getattr(args, "palette", 0):
        argv += ["--palette", str(args.palette)]
    return figures_cli(argv or None)


def cmd_lit(args: argparse.Namespace) -> int:
    from psyclaw.psych.lit_cli import lit_cli
    return lit_cli(query=args.query or "", sources=args.sources, limit=args.limit,
                   year_from=args.year_from, fulltext_doi=args.fulltext,
                   zotero_doi=args.zotero, synthesize=getattr(args, "synthesize", False))


def cmd_plan(args: argparse.Namespace) -> int:
    from psyclaw.loop import run_plan
    return run_plan(topic=getattr(args, "topic", None),
                    auto=getattr(args, "auto", False))


def cmd_goal(args: argparse.Namespace) -> int:
    from psyclaw import ui
    from psyclaw.tasks import get_goal, set_goal
    if args.text:
        p = set_goal(" ".join(args.text))
        print(ui.ok(f"✓ 研究目标已写 {p}"))
        return 0
    g = get_goal()
    print(f"目标:{g}" if g else "(未设定)psyclaw goal <文本> 设定。")
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    from psyclaw.tasks import tasks_cli
    return tasks_cli(args.args or ["list"])


def cmd_research(args: argparse.Namespace) -> int:
    # 不分类型的固定全流程编排(run_pipeline)。
    # 通用 agentic 回路改用 `psyclaw loop`(planner→执行→critic→修复)。
    from psyclaw.pipeline import run_pipeline
    try:
        return run_pipeline(topic=getattr(args, "topic", None),
                            auto=getattr(args, "auto", False),
                            revise=getattr(args, "revise", False),
                            rounds=getattr(args, "rounds", 3))
    except KeyboardInterrupt:
        print("\n流水线已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_loop(args: argparse.Namespace) -> int:
    # 通用流程编排器(类 Claude Code 的 agentic loop):planner→执行→critic→修复→交付。
    # 不绑定研究类型;<type>-loop 是其上预置的具体研究流程(走 workflow 引擎)。
    from psyclaw.loop import run_loop
    try:
        return run_loop(topic=getattr(args, "topic", None),
                        auto=getattr(args, "auto", False))
    except KeyboardInterrupt:
        print("\n回路已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_autoloop(args: argparse.Namespace) -> int:
    # 自主科研回路(Ralph 式自循环):自动发现待办→派发给 <type>-loop→独立验收→记状态→决定下一步。
    # 驱动既有 workflow,不重复实现领域逻辑;控制流确定性,LLM 只在被派发的流程内部。
    from psyclaw.autoloop import run_autoloop
    try:
        return run_autoloop(project_dir=".",
                            max_iters=getattr(args, "max_iters", 6),
                            auto=getattr(args, "auto", False),
                            skip_gates=getattr(args, "skip_gates", False))
    except KeyboardInterrupt:
        print("\n自主回路已中断。状态已保存,下次 psyclaw auto-loop 从此处续。")
        return 0


def cmd_review_lit(args: argparse.Namespace) -> int:
    # L0 路由:lit-loop → 跑 lit-review workflow(引擎按声明式步骤跑)。
    from psyclaw.workflows import get_workflow, run_workflow
    try:
        return run_workflow(get_workflow("lit-review"),
                            topic=getattr(args, "topic", None),
                            project_dir=".", auto=getattr(args, "auto", False),
                            skip_gates=getattr(args, "skip_gates", False))
    except KeyboardInterrupt:
        print("\n流程已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_meta(args: argparse.Namespace) -> int:
    # L0 路由:元分析顶层命令 → 跑 meta workflow(输入 = 效应量 CSV)。
    import pathlib

    from psyclaw.workflows import get_workflow, run_workflow
    topic = getattr(args, "topic", None) or f"针对 {pathlib.Path(args.effects_csv).stem} 的随机效应元分析"
    try:
        return run_workflow(get_workflow("meta"), topic=topic, project_dir=".",
                            auto=getattr(args, "auto", False),
                            seed={"effects_csv": args.effects_csv},
                            skip_gates=getattr(args, "skip_gates", False))
    except KeyboardInterrupt:
        print("\n流程已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_analysis(args: argparse.Namespace) -> int:
    # L0 路由:实证分析顶层命令 → 跑 analysis workflow(输入 = 数据 CSV)。
    import pathlib

    from psyclaw.workflows import get_workflow, run_workflow
    topic = getattr(args, "topic", None) or f"针对 {pathlib.Path(args.data_csv).stem} 的实证分析"
    try:
        return run_workflow(get_workflow("analysis"), topic=topic, project_dir=".",
                            auto=getattr(args, "auto", False),
                            seed={"data_csv": args.data_csv},
                            skip_gates=getattr(args, "skip_gates", False))
    except KeyboardInterrupt:
        print("\n流程已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_qualitative(args: argparse.Namespace) -> int:
    # L0 路由:质性研究顶层命令 → 跑 qualitative workflow(输入 = 转录稿文件/目录)。
    import pathlib

    from psyclaw.workflows import get_workflow, run_workflow
    topic = getattr(args, "topic", None) or f"针对 {pathlib.Path(args.transcripts).stem} 的质性研究"
    try:
        return run_workflow(get_workflow("qualitative"), topic=topic, project_dir=".",
                            auto=getattr(args, "auto", False),
                            seed={"transcripts": args.transcripts},
                            skip_gates=getattr(args, "skip_gates", False))
    except KeyboardInterrupt:
        print("\n流程已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_review(args: argparse.Namespace) -> int:
    from psyclaw.review import run_review
    try:
        return run_review(draft=getattr(args, "draft", None),
                          revise=getattr(args, "revise", False),
                          auto=getattr(args, "auto", False),
                          rounds=getattr(args, "rounds", 3))
    except KeyboardInterrupt:
        print("\n评审已中断。已落盘的评审产物保留在 notes/。")
        return 0


# --------------------------------------------------------------------------
# 解析器
# --------------------------------------------------------------------------

# 常用命令集——`--help` 暴露**全部**命令(不隐藏);CORE_COMMANDS 仅供 `guide`/`commands`
# 标注 ★ 常用,帮助新用户聚焦上手路径。改这个集合只影响 ★ 标注,不影响命令可见性/可用性。
CORE_COMMANDS = {
    "guide", "status", "auto-loop", "loop", "lit-loop", "meta-loop", "analysis-loop", "qual-loop",
    "research", "review", "clarify", "lit", "export",
    "score", "scale", "jars", "cite-check", "check", "preregister", "declare-test",
    "plan", "goal", "tasks", "memory",
    "gates", "config", "setup", "doctor", "repl", "resume", "commands",
}

# 职能分类(每个命令恰好出现一次;`psyclaw commands` 按此展示)。统计方法已外移到
# 成熟库/MCP——本 CLI 只保留研究编排 + 知识参考 + 文献/写作 harness。
COMMAND_CATEGORIES = [
    ("环境 / 系统", ["guide", "status", "repl", "version", "doctor", "config", "setup",
                  "skills", "mcp", "plugins", "gates", "eval", "commands"]),
    ("知识目录(只读)", ["scale", "norms", "assume", "method", "design", "cite", "ethics",
                    "journal"]),
    ("量表 / 数据准备", ["score"]),
    ("研究前规划 / 预注册", ["clarify", "declare-test", "preregister", "jars", "cite-check",
                       "check"]),
    ("研究流程 / 编排回路", ["agent", "auto-loop", "loop", "lit-loop", "meta-loop",
                        "analysis-loop", "qual-loop", "research"]),
    ("工作流 / 编排", ["goal", "plan", "tasks", "review"]),
    ("检索 / 知识图谱", ["search", "kg", "lit"]),
    ("记忆 / 消息 / IO", ["memory", "session", "resume", "serve", "notify", "auth",
                       "export", "figures", "provenance"]),
]


def cmd_guide(args: argparse.Namespace) -> int:
    """首次使用上手:一条默认路径 + 决策树(不再把 8 个入口的选择题抛给用户)。"""
    from psyclaw import __version__, ui
    print(ui.startup(__version__))
    print(ui.panel("Default Path",
                   "\n".join([
                       ui.ok("1. psyclaw status") + ui.dim("      看项目态势:进度/阻塞/下一步"),
                       ui.ok("2. psyclaw auto-loop") + ui.dim("   自动发现待办 -> 派发流程 -> 独立验收"),
                       ui.ok("3. psyclaw check 稿件.md") + ui.dim(" 投稿前质检:JARS/引用/复现/溯源"),
                   ]),
                   color="brmagenta"))
    print(ui.panel("Manual Routes",
                   "\n".join([
                       "search \"问题\"      " + ui.dim("学术库/本地会话自动路由"),
                       "lit-loop <主题>     " + ui.dim("文献综述 / 系统综述"),
                       "analysis-loop data  " + ui.dim("实证分析规划 + 外部统计脚本"),
                       "meta-loop effects   " + ui.dim("元分析脚本 + 报告"),
                       "qual-loop transcripts " + ui.dim("质性主题分析 + COREQ"),
                   ]),
                   color="brcyan"))
    print(ui.dim("配置: psyclaw config   自检: psyclaw doctor   全部命令: psyclaw commands"))
    print(ui.dim("教程: docs/TUTORIAL.md"))
    return 0


def cmd_commands(args: argparse.Namespace) -> int:
    """按职能分类打印全部命令(★=常用)。"""
    from psyclaw import ui
    p = build_parser()
    helps = getattr(p, "_psyclaw_help", {})
    print(ui.title("PsyClaw 命令清单") +
          ui.dim("（★ = 上手常用;全部命令均可直接用）\n"))
    for title, names in COMMAND_CATEGORIES:
        print(ui.accent(title))
        for n in names:
            mark = ui.ok("★") if n in CORE_COMMANDS else " "
            h = helps.get(n, "").replace("%%", "%")  # 还原 argparse 转义
            if len(h) > 42:                            # 目录视图截断,详情看 -h
                h = h[:41] + "…"
            print(f"  {mark} {n:<13} {ui.dim(h)}")
        print()
    try:                                  # 用户别名(v0.2:项目/全局 aliases.yaml)
        from psyclaw.aliases import load_aliases
        aliases = load_aliases(".")
        if aliases:
            print(ui.accent("你的别名(aliases.yaml)"))
            for k, v in aliases.items():
                print(f"    {k:<13} {ui.dim('→ ' + v)}")
            print()
    except Exception:  # noqa: BLE001
        pass
    print(ui.dim("第一次用?运行 `psyclaw guide`。任意命令加 -h 看参数,如 `psyclaw lit-loop -h`。"))
    print(ui.dim("自定义别名:~/.psyclaw/aliases.yaml 或 <项目>/.psyclaw/aliases.yaml,"
                 "一行一条 `名字: 命令 参数`。"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="psyclaw",
        description="心理学研究编排工作台（澄清·文献·设计·写作·评审·门禁）",
        epilog="第一次用?运行  psyclaw guide （上手介绍）。分类清单  psyclaw commands ；任意命令加 -h 看参数。",
    )
    p.add_argument("-v", "--version", action="store_true", help="打印版本")
    p.add_argument("--approval", choices=["suggest", "auto"], default="suggest",
                   help="工具执行审批策略（对齐 codex）")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("repl", help="进入交互式 REPL（默认）").set_defaults(func=cmd_repl)

    sub.add_parser(
        "status",
        help="一屏项目态势:目标/澄清/回路/等人决策(直接打印)/最近产物/下一步建议",
    ).set_defaults(func=cmd_status)

    sub.add_parser(
        "plugins",
        help="列出插件(用户 项目/全局;register(api) 注册工具/命令/system 片段)",
    ).set_defaults(func=cmd_plugins)

    pck = sub.add_parser(
        "check",
        help="投稿前一键质检:JARS+引用保真(+期刊风格)+复现溯源+KG溯源,一屏汇总")
    pck.add_argument("draft", nargs="?", default=None,
                     help="稿件 md(留空取 outputs/report.md)")
    pck.add_argument("--journal", default=None,
                     help="按期刊定制(引用风格核对;psyclaw journal 看目录)")
    pck.add_argument("--type", dest="research_type", default="quant",
                     choices=["quant", "qual", "mixed"], help="研究类型(JARS 用)")
    pck.set_defaults(func=cmd_check)

    pag = sub.add_parser(
        "agent",
        help="agent 一次性任务:模型自主多步调用工具(纯工具层循环,provider 无关保底)")
    pag.add_argument("task", nargs="*", help="任务描述(--history 时可省)")
    pag.add_argument("--auto", action="store_true",
                     help="自动批准副作用工具(默认拒绝;只读工具照跑)")
    pag.add_argument("--max-iters", type=int, default=24, dest="max_iters",
                     help="工具调用轮数上限(默认 24;长研究任务多步调用不够时再调高)")
    pag.add_argument("--history", type=int, nargs="?", const=10, default=None,
                     help="回看最近 n 次 agent 运行痕迹(默认 10),不执行任务")
    pag.set_defaults(func=cmd_agent)

    pres = sub.add_parser("resume",
                          help="续接历史会话进入 REPL(不给 id 续接最近一次)")
    pres.add_argument("session_id", nargs="?", default=None,
                      help="会话 id(psyclaw session 看列表)")
    pres.set_defaults(func=cmd_resume)

    psn = sub.add_parser(
        "session",
        help="会话管理:list|rename|delete(跨会话持久化;找内容用 psyclaw search 统一入口)")
    psn.add_argument("action", nargs="?", default="list",
                     choices=["list", "search", "rename", "delete"])
    psn.add_argument("rest", nargs="*",
                     help="search <词> | rename <id> <名> | delete <id>")
    psn.set_defaults(func=cmd_session)

    psr = sub.add_parser(
        "search",
        help="来源路由检索:据任务类型(事实/概念/趋势/回忆)路由到学术库/本地(主通道+兜底)")
    psr.add_argument("query", help="检索问题")
    psr.add_argument("--type", default=None,
                     choices=["factual", "conceptual", "trend", "local"],
                     help="显式指定任务类型(默认据问题自动判)")
    psr.add_argument("--limit", type=int, default=10, help="每通道命中上限")
    psr.set_defaults(func=cmd_search)

    pkg = sub.add_parser(
        "kg",
        help="带引用的知识图谱:seed(据 evidence_map 种图)|show <实体>|verify|stats")
    pkg.add_argument("action", nargs="?", default="stats",
                     choices=["seed", "show", "verify", "stats"])
    pkg.add_argument("rest", nargs="*", help="show <实体>")
    pkg.set_defaults(func=cmd_kg)

    sub.add_parser("version", help="打印版本").set_defaults(func=cmd_version)
    sub.add_parser("doctor", help="环境自检（配置/MCP/Gates）").set_defaults(func=cmd_doctor)

    pc = sub.add_parser("config", help="交互式配置/环境变量向导")
    pc.add_argument("--non-interactive", action="store_true", help="只写默认配置不提问")
    pc.set_defaults(func=cmd_config)

    pst = sub.add_parser("setup",
                         help="项目脚手架+能力选装:目录/据clarify生成概览/项目记忆/能力依赖/MCP·skill")
    pst.add_argument("--env", action="store_true",
                     help="一键配置缺失的基础环境(检查 provider/key + stats/full 组;--online 实装)")
    pst.add_argument("--groups", default=None, help="直接装指定组(逗号分隔:stats,viz,eeg,full)")
    pst.add_argument("--online", action="store_true",
                     help="联网自动安装缺失的能力依赖(否则交互询问/仅显示矩阵)")
    pst.add_argument("--non-interactive", action="store_true")
    pst.set_defaults(func=cmd_setup)

    pks = sub.add_parser("skills",
                         help="列出 skills(内置+发现 .claude/skills;--for 按研究类型推荐)")
    pks.add_argument("--for", dest="for_type", default=None,
                     help="按研究类型推荐外部技能包:lit-review|meta|analysis|qualitative(亦接受 *-loop 别名)")
    pks.add_argument("--sync", nargs="?", const="all", default=None,
                     help="同步带 upstream.json 的内置 skill。可指定名称,如 ctx2skill/opid")
    pks.add_argument("--dry-run", action="store_true",
                     help="配合 --sync 只显示将执行的同步动作")
    pks.set_defaults(func=cmd_skills)
    pmcp = sub.add_parser("mcp", help="MCP 目录 / 以 stdio 服务器身份运行内置 MCP")
    pmcp.add_argument("--serve", dest="name",
                      choices=["mne", "spss", "mplus", "stata"], default=None,
                      help="作为 stdio MCP 服务器运行(mne/spss/mplus/stata)")
    pmcp.set_defaults(func=cmd_mcp)
    sub.add_parser("gates", help="跑学术规范门禁自检").set_defaults(func=cmd_gates)

    pev = sub.add_parser(
        "eval", help="确定性离线评测(编排/门禁/自学习契约,不调 LLM/不联网)")
    pev.add_argument("--case", action="append",
                     help="只跑指定用例(可重复给多个);缺省跑全部")
    pev.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pev.set_defaults(func=cmd_eval)

    ps = sub.add_parser("scale", help="量表库查询(DASS/PHQ-9/GAD-7/TIPI…)")
    ps.add_argument("scale_id", nargs="?", default=None, help="量表 id,留空列出全部")
    ps.set_defaults(func=cmd_scale)

    psc = sub.add_parser(
        "score",
        help="量表自动计分(反向题翻转 + 子量表总分/均值，据 scales.yaml 定义)")
    psc.add_argument("data", help="CSV/TSV 数据文件")
    psc.add_argument("--scale", required=True, help="量表 id（如 tipi / phq-9 / dass-21）")
    psc.add_argument("--prefix", default="Q", help="条目列前缀（默认 Q）")
    psc.add_argument("--suffix", default="", help="条目列后缀（默认空；OpenPsychometrics DASS 用 A）")
    psc.add_argument("--method", choices=["sum", "mean"], default="sum",
                     help="子量表聚合方式：sum（默认）或 mean")
    psc.add_argument("--out", default=None, help="输出计分结果 CSV 路径（追加子量表/总分列）")
    psc.add_argument("--json", action="store_true", help="输出机器可读 JSON（含描述统计）")
    psc.set_defaults(func=cmd_score)

    pe = sub.add_parser("ethics",
                        help="量表伦理审查提示（IRB 要求 / 危机转介 / 敏感条目，D-3）")
    pe.add_argument("scale_id", help="量表 ID（如 phq-9、dass-42）")
    pe.set_defaults(func=cmd_ethics)

    pdt = sub.add_parser(
        "declare-test",
        help="预注册一个计划分析（A-2 研究者自由度门禁；确证性假设须先声明）")
    pdt.add_argument("--dv", required=True, help="因变量列名")
    pdt.add_argument("--test", required=True,
                     choices=["ttest", "anova", "correlation", "paired",
                              "mann_whitney", "chi2", "regression"],
                     help="计划检验类型")
    pdt.add_argument("--iv", default=None, help="自变量/分组列名（可选）")
    pdt.add_argument("--hypothesis", choices=["confirmatory", "exploratory"],
                     default="confirmatory", help="分析性质（默认 confirmatory）")
    pdt.add_argument("--name", default=None, help="假设名称（如 H1，默认自动生成）")
    pdt.add_argument("--project-dir", default=".", dest="project_dir",
                     help="项目根目录（默认 .）")
    pdt.set_defaults(func=cmd_declare_test)

    pa = sub.add_parser("assume", help="前提假设知识库(t检验/ANOVA/回归/SEM/IRT…)")
    pa.add_argument("test_id", nargs="?", default=None, help="检验 id,留空列出全部")
    pa.set_defaults(func=cmd_assume)

    pm = sub.add_parser("method", help="复杂方法目录(SEM/MLM/LPA/网络/交叉滞后…)")
    pm.add_argument("method_id", nargs="?", default=None, help="方法 id,留空列出全部")
    pm.set_defaults(func=cmd_method)

    pd = sub.add_parser("design", help="实验设计目录(被试间/内/混合/纵向/ESM…)")
    pd.add_argument("design_id", nargs="?", default=None, help="设计 id,留空列出全部")
    pd.set_defaults(func=cmd_design)

    pj = sub.add_parser("journal",
                        help="期刊画像(心理学报/心理科学/Psych Science/JPSP/Psych Bulletin…引用风格/报告标准/退稿红线)")
    pj.add_argument("journal_id", nargs="?", default=None, help="期刊 id,留空列出全部")
    pj.set_defaults(func=cmd_journal)

    ppr = sub.add_parser("preregister",
                         help="预注册模板(OSF/AsPredicted 双格式;据澄清卡抽取)")
    ppr.add_argument("--osf", action="store_true", help="只出 OSF 格式")
    ppr.add_argument("--aspredicted", action="store_true", help="只出 AsPredicted 格式")
    ppr.add_argument("--both", action="store_true", help="两种格式(默认)")
    ppr.set_defaults(func=cmd_preregister)

    pcl = sub.add_parser("clarify", help="研究澄清(grill-me 式,17 槽位,不澄清完不开工)")
    pcl.add_argument("--status", action="store_true", help="只看澄清进度")
    pcl.set_defaults(func=cmd_clarify)

    pci = sub.add_parser("cite", help="方法学背书库(每个设计决策的文献支撑)")
    pci.add_argument("topic_id", nargs="?", default=None, help="决策主题,留空列出全部")
    pci.set_defaults(func=cmd_cite)

    pex = sub.add_parser("export", help="格式化输出(APA7 / 心理学报 / 心理科学,确定性模板)")
    pex.add_argument("file", help="结构化 Markdown 草稿")
    pex.add_argument("--docx", default=None, help="docx 输出路径(仅 APA7 格式可用)")
    pex.add_argument("--md", default=None, help="md 输出路径")
    pex.add_argument(
        "--journal", "-j",
        choices=["apa7", "xinlixuebao", "xinlikexue"],
        default="apa7",
        help="目标格式: apa7(默认) / xinlixuebao(心理学报) / xinlikexue(心理科学)",
    )
    pex.set_defaults(func=cmd_export)

    pnm = sub.add_parser("norms", help="中文量表常模(截断值 + 中国样本均值/SD)")
    pnm.add_argument("scale_id", nargs="?", default=None, help="量表 id(留空列出全部有常模量表)")
    pnm.set_defaults(func=cmd_norms)

    pjars = sub.add_parser(
        "jars",
        help="JARS 检查清单(APA 2018 Quant/Qual/Mixed；缺失数据处理+剔除信息阻断)")
    pjars.add_argument("draft", nargs="?", default=None,
                       help="论文草稿 Markdown 文件（留空从 stdin 读）")
    pjars.add_argument("--type", "-t", dest="research_type",
                       choices=["quant", "qual", "mixed"], default="quant",
                       help="研究类型(默认 quant)")
    pjars.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    pjars.add_argument("--no-sidecar", action="store_true",
                       help="不写 notes/jars_check.json sidecar")
    pjars.set_defaults(func=cmd_jars)

    pcc = sub.add_parser(
        "cite-check",
        help="引用保真核查:文内引用是否都溯源到检索命中(反杜撰参考文献)")
    pcc.add_argument("manuscript", help="稿件 Markdown(如 notes/lit_review.md)")
    pcc.add_argument("--project", default=".", help="项目目录(默认当前)")
    pcc.add_argument("--journal", default=None,
                     help="按期刊定制引用风格核对 + 退稿红线(psyclaw journal 看目录)")
    pcc.set_defaults(func=cmd_cite_check)

    ppv = sub.add_parser(
        "provenance",
        help="复现溯源:给生成脚本/图打包 代码+环境+说明+决策轨迹(<产物>.provenance.json)")
    ppv.add_argument("artifact", help="产物路径(如 outputs/analysis.py)")
    ppv.add_argument("--desc", default="", help="自然语言说明(留空则从脚本 docstring 派生)")
    ppv.add_argument("--data", default=None, help="数据文件路径(记指纹;data/raw 只记路径不哈希)")
    ppv.add_argument("--fingerprint", default=None, help="直接提供已算好的数据指纹")
    ppv.add_argument("--project", default=".", help="项目目录(默认当前)")
    ppv.add_argument("--journal", default=None,
                     help="按期刊定制:要求数据可得性的期刊须带数据指纹(psyclaw journal 看目录)")
    ppv.set_defaults(func=cmd_provenance)

    pme = sub.add_parser("memory", help="三层记忆(画像/决策惯性/教训卡)")
    pme.add_argument("args", nargs="*", help="list | set <键> <值> | lesson <触发> <教训> | confirm <序号>")
    pme.set_defaults(func=cmd_memory)

    psv = sub.add_parser("serve", help="对接消息端(telegram / wechat 双向 bot)")
    psv.add_argument("channel", choices=["telegram", "wechat"], help="通道")
    psv.add_argument("--login", action="store_true", help="wechat:尝试扫码登录获取 token")
    psv.set_defaults(func=cmd_serve)

    pnt = sub.add_parser("notify", help="推送通知(企业微信 webhook / Telegram)")
    pnt.add_argument("message", help="通知内容(HITL 审批提醒等)")
    pnt.set_defaults(func=cmd_notify)

    ppl = sub.add_parser("plan", help="规划:planner 产出 notes/plan.md 并自动写任务看板")
    ppl.add_argument("topic", nargs="?", default=None,
                     help="研究目标(可空,读 notes/goal.md)")
    ppl.add_argument("--auto", action="store_true", help="跳过人工确认")
    ppl.set_defaults(func=cmd_plan)

    pgl = sub.add_parser("goal", help="查看/设定研究目标(notes/goal.md)")
    pgl.add_argument("text", nargs="*", help="目标文本,留空查看当前目标")
    pgl.set_defaults(func=cmd_goal)

    ptk = sub.add_parser("tasks", help="任务看板(list|add|start|done|block|sync|clear)")
    ptk.add_argument("args", nargs="*", help="子命令与参数,留空 list")
    ptk.set_defaults(func=cmd_tasks)

    # research → 一句话研究编排(文献→设计→写作→评审→总验收;统计交外部库/MCP)
    prs = sub.add_parser("research",
                         help="一句话研究编排:文献→设计→写作→评审→总验收")
    prs.add_argument("topic", nargs="?", default=None, help="研究主题(可空,读 notes/goal.md)")
    prs.add_argument("--revise", "-r", action="store_true",
                     help="评审阶段闭合写作→评审→修复(把 BLOCKING/MAJOR 回灌修订)")
    prs.add_argument("--rounds", type=int, default=3, help="评审修订最大轮次(默认 3)")
    prs.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
    prs.set_defaults(func=cmd_research)

    # loop → 通用流程编排器(类 Claude Code 的 agentic loop):planner→执行→critic→修复
    plp = sub.add_parser("loop",
                         help="通用流程编排回路(planner→执行→critic→修复→交付),不绑研究类型")
    plp.add_argument("topic", nargs="?", default=None, help="任务/研究主题(可空,读 notes/goal.md)")
    plp.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
    plp.set_defaults(func=cmd_loop)

    # auto-loop → 自主科研回路(Ralph 式自循环):自动发现→派发 <type>-loop→独立验收→记状态→决定下一步
    pal = sub.add_parser(
        "auto-loop",
        help="自主科研回路:自动发现待办→派发对应流程→独立验收→记状态→决定下一步(Ralph 式)")
    pal.add_argument("--max-iters", dest="max_iters", type=int, default=6,
                     help="迭代上限(默认 6;一个研究项目通常 ≤4 个阶段)")
    pal.add_argument("--auto", action="store_true",
                     help="全程无人值守(默认在每个任务派发前征求确认)")
    pal.add_argument("--skip-gates", dest="skip_gates", action="store_true",
                     help="按你的要求跳过门禁(澄清等不再拦;留痕 notes/gate_skips.md,产出按探索性对待)")
    pal.set_defaults(func=cmd_autoloop)

    # <type>-loop → 按研究类型预置的具体流程(走 workflow 引擎)
    # lit-loop → 文献综述
    prl = sub.add_parser("lit-loop",
                         help="文献综述流程:澄清→检索→筛选(PRISMA)→合成综述→评审")
    prl.add_argument("topic", nargs="?", default=None, help="综述主题(可空,读 notes/goal.md)")
    prl.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    prl.add_argument("--skip-gates", dest="skip_gates", action="store_true",
                     help="按你的要求跳过门禁(留痕 notes/gate_skips.md,产出按探索性对待)")
    prl.set_defaults(func=cmd_review_lit)

    # meta-loop → 元分析(输入效应量表;统计由生成的脚本在外部 statsmodels 跑)
    pma = sub.add_parser("meta-loop",
                         help="元分析流程:校验效应量表→生成可复现脚本(委托 statsmodels)→写→评审")
    pma.add_argument("effects_csv", help="效应量 CSV(含 study / 效应量(d/g/r/yi) / variance|se|ci 列)")
    pma.add_argument("--topic", default=None, help="元分析主题(可空,默认据文件名)")
    pma.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    pma.add_argument("--skip-gates", dest="skip_gates", action="store_true",
                     help="按你的要求跳过门禁(留痕 notes/gate_skips.md,产出按探索性对待)")
    pma.set_defaults(func=cmd_meta)

    # analysis-loop → 实证分析(输入数据表;统计由生成的脚本在外部 pingouin/scipy 跑)
    pan = sub.add_parser("analysis-loop",
                         help="实证分析流程:画像数据→设计→推荐分析+生成可复现脚本(委托 pingouin)→写→评审")
    pan.add_argument("data_csv", help="数据 CSV(被试×变量;自动画像列类型并推荐分析)")
    pan.add_argument("--topic", default=None, help="研究主题(可空,默认据文件名)")
    pan.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    pan.add_argument("--skip-gates", dest="skip_gates", action="store_true",
                     help="按你的要求跳过门禁(留痕 notes/gate_skips.md,产出按探索性对待)")
    pan.set_defaults(func=cmd_analysis)

    # qual-loop → 质性研究(输入转录稿;LLM 辅助编码/主题分析,研究者复核)
    pq = sub.add_parser("qual-loop",
                        help="质性研究流程:载入转录稿→设计→主题分析(LLM辅助)→写COREQ报告→评审")
    pq.add_argument("transcripts", help="转录稿:单个 .txt/.md 文件,或包含它们的目录")
    pq.add_argument("--topic", default=None, help="研究主题(可空,默认据文件名)")
    pq.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    pq.add_argument("--skip-gates", dest="skip_gates", action="store_true",
                     help="按你的要求跳过门禁(留痕 notes/gate_skips.md,产出按探索性对待)")
    pq.set_defaults(func=cmd_qualitative)

    prv = sub.add_parser("review", help="审稿模拟(EIC+3审稿人+Devil's Advocate,产可解析意见)")
    prv.add_argument("draft", nargs="?", default=None,
                     help="待审稿件 md(留空取 outputs/report.md)")
    prv.add_argument("--revise", "-r", action="store_true",
                     help="把 BLOCKING/MAJOR 回灌 executor 修订并复审(闭合写作→评审→修复)")
    prv.add_argument("--rounds", type=int, default=3, help="修订复审最大轮次(默认 3)")
    prv.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用)")
    prv.set_defaults(func=cmd_review)

    pau = sub.add_parser("auth", help="机构权限(EZProxy/LibKey)配置与认证状态自检")
    pau.add_argument("--set", action="store_true", help="配置机构权限(无密码)")
    pau.add_argument("--verify", action="store_true", help="连通自检并记录认证状态")
    pau.set_defaults(func=cmd_auth)

    pfig = sub.add_parser(
        "figures",
        help="图表主题层(E-1): 风格预设 / FIG.honest 诚实性核查 / Okabe-Ito 调色板")
    pfig.add_argument("--list-styles", action="store_true", dest="list_styles",
                      help="列出内置风格(apa7/nature/frontiers/minimal)")
    pfig.add_argument("--style", default=None,
                      help="查看指定风格配置")
    pfig.add_argument("--check", default=None, metavar="SPEC.JSON",
                      help="对图表 sidecar JSON 跑 FIG.honest 诚实性核查")
    pfig.add_argument("--palette", type=int, default=0, metavar="N",
                      help="打印 Okabe-Ito 调色板前 N 色(默认 8)")
    pfig.set_defaults(func=cmd_figures)

    plit = sub.add_parser("lit", help="文献检索 + 全文获取(合法 OA;PRISMA 计数)")
    plit.add_argument("query", nargs="?", default=None, help="检索式")
    plit.add_argument("--sources", default="openalex,europepmc", help="openalex,europepmc,arxiv")
    plit.add_argument("--limit", type=int, default=10)
    plit.add_argument("--year-from", dest="year_from", type=int, default=None)
    plit.add_argument("--fulltext", default=None, help="按 DOI 取合法 OA 全文")
    plit.add_argument("--zotero", default=None, help="按 DOI 从你的 Zotero 文库取全文")
    plit.add_argument("--synthesize", "-s", action="store_true",
                      help="据检索命中一键合成结构化综述(notes/lit_review.md)")
    plit.set_defaults(func=cmd_lit)

    sub.add_parser(
        "guide", help="首次使用上手介绍(是什么 + 每类研究一条 loop + 60 秒上手)"
    ).set_defaults(func=cmd_guide)
    sub.add_parser(
        "commands", help="按职能分类列出全部命令（★=常用）"
    ).set_defaults(func=cmd_commands)

    # 快照各命令短 help(供 `commands`/`guide` 的分类展示与 ★ 标注用),
    # 然后把顶层 --help 收敛到 CORE_COMMANDS(v0.2「命令简单化」:机制可以复杂,
    # 帮助必须简单)。**全部命令仍可调用**,完整分类看 `psyclaw commands`。
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            p._psyclaw_help = {pa.dest: (pa.help or "")
                               for pa in action._choices_actions}
            n_all = len(action.choices)
            action._choices_actions = [
                ca for ca in action._choices_actions if ca.dest in CORE_COMMANDS]
            p.epilog = (f"--help 只列 {len(action._choices_actions)} 条常用命令;"
                        f"全部 {n_all} 条(均可直接用)见 `psyclaw commands`。"
                        "第一次用?`psyclaw guide`;手把手教程 docs/TUTORIAL.md。")

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 用户自定义别名(v0.2):~/.psyclaw/aliases.yaml + <项目>/.psyclaw/aliases.yaml。
    # 内置命令优先,别名不得劫持;别名系统任何异常都不阻塞 CLI。
    try:
        from psyclaw.aliases import expand_alias, load_aliases
        parser_probe = build_parser()
        builtin: set[str] = set()
        for action in parser_probe._actions:
            if isinstance(action, argparse._SubParsersAction):
                builtin = set(action.choices.keys())
        argv = expand_alias(argv, load_aliases("."), builtin=builtin)
        parser = parser_probe
    except Exception:  # noqa: BLE001
        parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "command", None):
        return cmd_repl(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
