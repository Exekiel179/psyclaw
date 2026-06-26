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
    print(_banner())
    from psyclaw.repl import run_repl
    return run_repl()


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


def cmd_setup(args: argparse.Namespace) -> int:
    from psyclaw.bootstrap import run_setup
    groups = args.groups.split(",") if getattr(args, "groups", None) else None
    return run_setup(non_interactive=getattr(args, "non_interactive", False), groups=groups)


def cmd_skills(args: argparse.Namespace) -> int:
    print("已注册 Skills：")
    for s in list_skills():
        print(f"  - {s['name']:<18} [{s['category']}]  {s['description']}")
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
    print("MCP 服务器目录（registry.yaml）：")
    for m in list_mcp_catalog():
        opt_tag = " [可选]" if is_optional(m) else ""
        print(f"  - {m['name']:<14} [{m['category']:<16}] 启用条件: {m.get('enable_when', '—')}{opt_tag}")
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
    # --freeform → 通用 HITL 回路(run_loop);默认 → 固定四象限流水线(run_pipeline)。
    # 两者同源:pipeline 本就搭在 loop 的 planner/executor 积木之上,此处只在 CLR 层分流。
    if getattr(args, "freeform", False):
        from psyclaw.loop import run_loop
        try:
            return run_loop(topic=getattr(args, "topic", None),
                            auto=getattr(args, "auto", False))
        except KeyboardInterrupt:
            print("\n回路已中断。已落盘的产物保留在 notes/ outputs/。")
            return 0
    from psyclaw.pipeline import run_pipeline
    try:
        return run_pipeline(topic=getattr(args, "topic", None),
                            auto=getattr(args, "auto", False),
                            revise=getattr(args, "revise", False),
                            rounds=getattr(args, "rounds", 3))
    except KeyboardInterrupt:
        print("\n流水线已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_review_lit(args: argparse.Namespace) -> int:
    # L0 路由:文献综述顶层命令 → 跑 lit-review workflow(引擎按声明式步骤跑)。
    from psyclaw.workflows import get_workflow, run_workflow
    try:
        return run_workflow(get_workflow("lit-review"),
                            topic=getattr(args, "topic", None),
                            project_dir=".", auto=getattr(args, "auto", False))
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
                            seed={"effects_csv": args.effects_csv})
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

# 渐进式披露(progressive disclosure):默认 `--help` 只展示「常用」命令,降低上手门槛;
# 其余进阶/内部命令照常可调用,完整分类清单见 `psyclaw commands`(★ 标常用)。
# 调常用集只需改这一个集合——隐藏≠删除,不破坏任何既有命令契约。
CORE_COMMANDS = {
    "research", "review-lit", "meta", "review", "clarify", "lit", "export",
    "score", "scale", "jars", "preregister", "declare-test",
    "plan", "goal", "tasks", "memory",
    "gates", "config", "setup", "doctor", "repl", "commands",
}

# 职能分类(每个命令恰好出现一次;`psyclaw commands` 按此展示)。统计方法已外移到
# 成熟库/MCP——本 CLI 只保留研究编排 + 知识参考 + 文献/写作 harness。
COMMAND_CATEGORIES = [
    ("环境 / 系统", ["repl", "version", "doctor", "config", "setup",
                  "skills", "mcp", "gates", "commands"]),
    ("知识目录(只读)", ["scale", "norms", "assume", "method", "design", "cite", "ethics"]),
    ("量表 / 数据准备", ["score"]),
    ("研究前规划 / 预注册", ["clarify", "declare-test", "preregister", "jars"]),
    ("研究流程(按类型路由)", ["review-lit", "meta", "research"]),
    ("工作流 / 编排", ["goal", "plan", "tasks", "review"]),
    ("记忆 / 消息 / IO", ["memory", "serve", "notify", "lit", "auth", "export", "figures"]),
]


def cmd_commands(args: argparse.Namespace) -> int:
    """按职能分类打印全部命令(★=常用)。配合默认 `--help` 仅示常用做渐进式披露。"""
    from psyclaw import ui
    p = build_parser()
    helps = getattr(p, "_psyclaw_help", {})
    print(ui.title("PsyClaw 命令清单") +
          ui.dim("（★ = 常用，默认 `--help` 只显示这些；其余命令照常可用）\n"))
    for title, names in COMMAND_CATEGORIES:
        print(ui.accent(title))
        for n in names:
            mark = ui.ok("★") if n in CORE_COMMANDS else " "
            h = helps.get(n, "").replace("%%", "%")  # 还原 argparse 转义
            if len(h) > 42:                            # 目录视图截断,详情看 -h
                h = h[:41] + "…"
            print(f"  {mark} {n:<13} {ui.dim(h)}")
        print()
    print(ui.dim("任意命令加 -h 看详细参数，如 `psyclaw ttest -h`。"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="psyclaw",
        description="心理学研究全流程 Agent CLI（文献·设计·统计·写作，规范门禁内置）",
        epilog="上方为常用命令；完整分类清单运行  psyclaw commands （任意命令加 -h 看参数）。",
    )
    p.add_argument("-v", "--version", action="store_true", help="打印版本")
    p.add_argument("--approval", choices=["suggest", "auto"], default="suggest",
                   help="工具执行审批策略（对齐 codex）")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("repl", help="进入交互式 REPL（默认）").set_defaults(func=cmd_repl)
    sub.add_parser("version", help="打印版本").set_defaults(func=cmd_version)
    sub.add_parser("doctor", help="环境自检（配置/MCP/Gates）").set_defaults(func=cmd_doctor)

    pc = sub.add_parser("config", help="交互式配置/环境变量向导")
    pc.add_argument("--non-interactive", action="store_true", help="只写默认配置不提问")
    pc.set_defaults(func=cmd_config)

    pst = sub.add_parser("setup", help="能力选装(检测缺失依赖,征求同意按组安装)")
    pst.add_argument("--groups", default=None, help="直接装指定组(逗号分隔:stats,viz,eeg,full)")
    pst.add_argument("--non-interactive", action="store_true")
    pst.set_defaults(func=cmd_setup)

    sub.add_parser("skills", help="列出已注册 skills").set_defaults(func=cmd_skills)
    pmcp = sub.add_parser("mcp", help="MCP 目录 / 以 stdio 服务器身份运行内置 MCP")
    pmcp.add_argument("--serve", dest="name",
                      choices=["mne", "spss", "mplus", "stata"], default=None,
                      help="作为 stdio MCP 服务器运行(mne/spss/mplus/stata)")
    pmcp.set_defaults(func=cmd_mcp)
    sub.add_parser("gates", help="跑学术规范门禁自检").set_defaults(func=cmd_gates)

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
    prs.add_argument("--freeform", "-f", action="store_true",
                     help="改走通用 HITL 回路(planner→执行→critic→修复),不按固定流程")
    prs.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
    prs.set_defaults(func=cmd_research)

    # review-lit → 文献综述 workflow(L0 路由:每类研究一条顶层命令)
    prl = sub.add_parser("review-lit",
                         help="文献综述流程:澄清→检索→筛选(PRISMA)→合成综述→评审")
    prl.add_argument("topic", nargs="?", default=None, help="综述主题(可空,读 notes/goal.md)")
    prl.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    prl.set_defaults(func=cmd_review_lit)

    # meta → 元分析 workflow(输入效应量表;统计由生成的脚本在外部 statsmodels 跑)
    pma = sub.add_parser("meta",
                         help="元分析流程:校验效应量表→生成可复现脚本(委托 statsmodels)→写→评审")
    pma.add_argument("effects_csv", help="效应量 CSV(含 study / 效应量(d/g/r/yi) / variance|se|ci 列)")
    pma.add_argument("--topic", default=None, help="元分析主题(可空,默认据文件名)")
    pma.add_argument("--auto", action="store_true", help="跳过步间人工确认(CI 用)")
    pma.set_defaults(func=cmd_meta)

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
        "commands", help="按职能分类列出全部命令（★=常用，进阶命令在此查）"
    ).set_defaults(func=cmd_commands)

    # 渐进式披露:快照各命令短 help(供 `commands` 用),再从顶层 --help 的列表里
    # 摘除非常用命令——只动 _choices_actions(帮助展示),choices(分发)原样保留,
    # 故被隐藏的命令仍能正常 `psyclaw <cmd>` 调用,不破坏任何契约。
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {pa.dest: (pa.help or "") for pa in action._choices_actions}
            action._choices_actions = [
                pa for pa in action._choices_actions if pa.dest in CORE_COMMANDS
            ]
            p._psyclaw_help = helps

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "command", None):
        return cmd_repl(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
