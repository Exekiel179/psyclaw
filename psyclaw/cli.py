"""PsyClaw CLI — 命令注册与分发。

骨架阶段用 argparse + stdlib，零依赖即可运行。
真实实现里 REPL 会换成 prompt_toolkit、provider 会接 LLM，
但命令骨架与帮助文本即为最终命令契约（见 DESIGN.md §3）。
"""

from __future__ import annotations

import argparse
import math
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

    if result.get("reliability"):
        print(ui.accent("\n子量表信度（Cronbach's α）"))
        for sub, rel in result["reliability"].items():
            a = rel["alpha"]
            if math.isnan(a):
                print(f"  {sub:<22} α = —（{rel['interpretation']}）")
            else:
                print(f"  {sub:<22} α = {a:.3f}  {rel['interpretation']}"
                      f"  (k={rel['n_items']}, n={rel['n_obs']})")
                # 逐题删除后 α：只报降幅最大的条目（便于定位拖后腿条目）
                aid = rel.get("alpha_if_deleted", [])
                if aid and not math.isnan(a):
                    worst_item, worst_a = min(aid, key=lambda x: a - x[1])
                    drop = a - worst_a
                    if drop > 0.02:
                        print(ui.dim(f"      删除条目 {worst_item} 后 α 升 {drop:.3f}"
                                     " → 考虑检查该题措辞"))

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


def cmd_screen(args: argparse.Namespace) -> int:
    from psyclaw.psych.careless import screen_csv_cli
    argv = [args.file]
    if args.prefix != "Q":
        argv += ["--prefix", args.prefix]
    if args.suffix != "A":
        argv += ["--suffix", args.suffix or "''"]
    return screen_csv_cli(argv)


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


def cmd_check(args: argparse.Namespace) -> int:
    from psyclaw.psych.diagnostics import check_cli
    return check_cli(args.file, args.dv, args.group)


def cmd_power(args: argparse.Namespace) -> int:
    from psyclaw.psych.power import run_power
    return run_power(
        args.test, d=args.d, r=args.r, f=args.f, f2=args.f2,
        a=args.a, b=args.b, cp=args.cp, k=args.k, u=args.u,
        n=args.n, power=args.power, alpha=args.alpha, tails=args.tails,
        kind=args.kind, df=args.df, rmsea0=args.rmsea0, rmsea1=args.rmsea1,
        sims=args.sims, as_json=args.json,
    )


def cmd_preregister(args: argparse.Namespace) -> int:
    from psyclaw.psych.preregister import run_preregister
    opts = {}
    for name in ("d", "r", "f", "f2", "a", "b", "cp", "k", "u", "n",
                 "alpha", "tails", "kind", "df", "rmsea0", "rmsea1", "sims"):
        v = getattr(args, name, None)
        if v is not None:
            opts[name] = v
    if getattr(args, "power_target", None) is not None:
        opts["power"] = args.power_target
    fmt = "osf" if args.osf else "aspredicted" if args.aspredicted else "both"
    return run_preregister(fmt=fmt, test=getattr(args, "test", None),
                           power_opts=opts or None)


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


def cmd_stat(args: argparse.Namespace) -> int:
    if getattr(args, "method", None):
        from psyclaw.psych.analyze import analyze_advanced
        kw = {"model": getattr(args, "model", None), "formula": getattr(args, "formula", None),
              "group": getattr(args, "group", None),
              "items": args.items.split(",") if getattr(args, "items", None) else None}
        return analyze_advanced(args.file, args.method, **{k: v for k, v in kw.items() if v})
    from psyclaw.psych.analyze import analyze
    return analyze(args.file, args.dv, getattr(args, "group", None),
                   getattr(args, "with_var", None), getattr(args, "paired", None),
                   cluster=getattr(args, "cluster", None))


def cmd_mediation(args: argparse.Namespace) -> int:
    from psyclaw.psych.decision_tree import analyze_mediation_cli
    argv = [args.file]
    if args.x:
        argv += ["--x", args.x]
    if args.m:
        argv += ["--m", args.m]
    if args.y:
        argv += ["--y", args.y]
    if args.nboot != 5000:
        argv += ["--nboot", str(args.nboot)]
    return analyze_mediation_cli(argv)


def cmd_meta(args: argparse.Namespace) -> int:
    from psyclaw.psych.meta import meta_cli
    argv = [args.csv]
    if args.json:
        argv += ["--json"]
    if args.out:
        argv += ["--out", args.out]
    if not args.forest:
        argv += ["--no-forest"]
    return meta_cli(argv)


def cmd_missing(args: argparse.Namespace) -> int:
    from psyclaw.psych.missing_data import missing_cli
    argv = [args.csv]
    if getattr(args, "json", False):
        argv += ["--json"]
    if getattr(args, "out", None):
        argv += ["--out", args.out]
    return missing_cli(argv)


def cmd_tost(args: argparse.Namespace) -> int:
    from psyclaw.psych.equivalence import equivalence_cli
    argv = [args.csv, "--dv", args.dv, "--lower", str(args.lower), "--upper", str(args.upper)]
    if getattr(args, "group", None):
        argv += ["--group", args.group]
    if getattr(args, "mu0", None) is not None:
        argv += ["--one-sample", str(args.mu0)]
    if getattr(args, "paired", False):
        argv += ["--paired"]
    if getattr(args, "alpha", 0.05) != 0.05:
        argv += ["--alpha", str(args.alpha)]
    if getattr(args, "out", None):
        argv += ["--out", args.out]
    if getattr(args, "json", False):
        argv += ["--json"]
    return equivalence_cli(argv)


def cmd_bayes(args: argparse.Namespace) -> int:
    from psyclaw.psych.bayes import bayes_cli
    argv = [args.csv, "--dv", args.dv]
    if getattr(args, "test", "ttest") != "ttest":
        argv += ["--test", args.test]
    if getattr(args, "group", None):
        argv += ["--group", args.group]
    if getattr(args, "mu0", 0.0) != 0.0:
        argv += ["--mu0", str(args.mu0)]
    if getattr(args, "r_scale", None) is not None:
        import math as _math
        if abs(args.r_scale - _math.sqrt(2) / 2) > 1e-9:
            argv += ["--r-scale", str(args.r_scale)]
    if getattr(args, "out", None):
        argv += ["--out", args.out]
    if getattr(args, "json", False):
        argv += ["--json"]
    return bayes_cli(argv)


def cmd_regress(args: argparse.Namespace) -> int:
    from psyclaw.psych.regression import regression_cli
    argv = [args.csv, "--dv", args.dv, "--iv", args.iv]
    if getattr(args, "alpha", 0.05) != 0.05:
        argv += ["--alpha", str(args.alpha)]
    if getattr(args, "out", "notes") != "notes":
        argv += ["--out", args.out]
    if getattr(args, "json", False):
        argv += ["--json"]
    return regression_cli(argv)


def cmd_describe(args: argparse.Namespace) -> int:
    from psyclaw.psych.descriptives import descriptives_cli
    argv = [args.csv]
    if getattr(args, "cols", None):
        argv += ["--cols", args.cols]
    if getattr(args, "corr", False):
        argv += ["--corr"]
    if getattr(args, "alpha", 0.05) != 0.05:
        argv += ["--alpha", str(args.alpha)]
    if getattr(args, "out", "notes") != "notes":
        argv += ["--out", args.out]
    if getattr(args, "json", False):
        argv += ["--json"]
    return descriptives_cli(argv)


def cmd_sensitivity(args: argparse.Namespace) -> int:
    from psyclaw.psych.sensitivity import sensitivity_cli
    argv = [args.plan]
    if getattr(args, "data", None):
        argv += ["--data", args.data]
    if getattr(args, "dv", None):
        argv += ["--dv", args.dv]
    if getattr(args, "group", None):
        argv += ["--group", args.group]
    if getattr(args, "alpha", 0.05) != 0.05:
        argv += ["--alpha", str(args.alpha)]
    if getattr(args, "out", None):
        argv += ["--out", args.out]
    if getattr(args, "json", False):
        argv += ["--json"]
    return sensitivity_cli(argv)


def cmd_invariance(args: argparse.Namespace) -> int:
    from psyclaw.psych.invariance import run_invariance
    return run_invariance(
        data_path=args.data,
        model=args.model or "",
        group=args.group,
        output_dir=args.output_dir,
        cfi_configural=args.cfi_configural,
        rmsea_configural=args.rmsea_configural,
        cfi_metric=args.cfi_metric,
        rmsea_metric=args.rmsea_metric,
        cfi_scalar=args.cfi_scalar,
        rmsea_scalar=args.rmsea_scalar,
        as_json=args.json,
    )


def cmd_moderation(args: argparse.Namespace) -> int:
    from psyclaw.psych.decision_tree import analyze_moderation_cli
    argv = [args.file]
    if args.x:
        argv += ["--x", args.x]
    if args.w:
        argv += ["--w", args.w]
    if args.y:
        argv += ["--y", args.y]
    return analyze_moderation_cli(argv)


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


def cmd_loop(args: argparse.Namespace) -> int:
    from psyclaw.loop import run_loop
    try:
        return run_loop(topic=getattr(args, "topic", None), auto=getattr(args, "auto", False))
    except KeyboardInterrupt:
        print("\n回路已中断。已落盘的产物保留在 notes/ outputs/。")
        return 0


def cmd_research(args: argparse.Namespace) -> int:
    from psyclaw.pipeline import run_pipeline
    try:
        return run_pipeline(topic=getattr(args, "topic", None),
                            auto=getattr(args, "auto", False),
                            revise=getattr(args, "revise", False),
                            rounds=getattr(args, "rounds", 3))
    except KeyboardInterrupt:
        print("\n流水线已中断。已落盘的产物保留在 notes/ outputs/。")
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


def _stub(name: str):
    def handler(args: argparse.Namespace) -> int:
        print(f"[{name}] 骨架占位 — 该命令的实现见路线图 M2/M5（DESIGN.md §10）。")
        return 0
    return handler


# --------------------------------------------------------------------------
# 解析器
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="psyclaw",
        description="心理学研究全流程 Agent CLI（文献·设计·统计·写作，规范门禁内置）",
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

    pscr = sub.add_parser("screen", help="数据草率作答筛查(longstring/IRV/直线作答)")
    pscr.add_argument("file", help="CSV/TSV 数据文件")
    pscr.add_argument("--prefix", default="Q", help="条目列前缀(默认 Q)")
    pscr.add_argument("--suffix", default="A", help="条目列后缀(默认 A;无后缀传 '')")
    pscr.set_defaults(func=cmd_screen)

    pa = sub.add_parser("assume", help="前提假设知识库(t检验/ANOVA/回归/SEM/IRT…)")
    pa.add_argument("test_id", nargs="?", default=None, help="检验 id,留空列出全部")
    pa.set_defaults(func=cmd_assume)

    pm = sub.add_parser("method", help="复杂方法目录(SEM/MLM/LPA/网络/交叉滞后…)")
    pm.add_argument("method_id", nargs="?", default=None, help="方法 id,留空列出全部")
    pm.set_defaults(func=cmd_method)

    pd = sub.add_parser("design", help="实验设计目录(被试间/内/混合/纵向/ESM…)")
    pd.add_argument("design_id", nargs="?", default=None, help="设计 id,留空列出全部")
    pd.set_defaults(func=cmd_design)

    pck = sub.add_parser("check", help="可运行假设诊断(正态/方差齐性/经典F vs Welch)")
    pck.add_argument("file", help="CSV/TSV 数据文件")
    pck.add_argument("--dv", required=True, help="因变量列名")
    pck.add_argument("--group", default=None, help="分组列名(可选)")
    pck.set_defaults(func=cmd_check)

    pw = sub.add_parser("power",
                        help="先验功效分析(G*Power 对标:t/ANOVA/相关/回归/SEM/中介)")
    pw.add_argument("test", choices=["ttest", "anova", "r", "correlation",
                                     "regression", "sem", "mediation"],
                    help="检验类型")
    pw.add_argument("--d", type=float, default=None, help="Cohen's d(t 检验,默认先验 .40)")
    pw.add_argument("--r", type=float, default=None, help="相关 r(默认先验 .20)")
    pw.add_argument("--f", type=float, default=None, help="Cohen's f(ANOVA,默认 .25)")
    pw.add_argument("--f2", type=float, default=None, help="Cohen's f²(回归,默认 .15)")
    pw.add_argument("--a", type=float, default=None, help="中介 a 路径(默认 .30)")
    pw.add_argument("--b", type=float, default=None, help="中介 b 路径(默认 .30)")
    pw.add_argument("--cp", type=float, default=0.0, help="中介直接路径 c′(默认 0)")
    pw.add_argument("--k", type=int, default=None, help="ANOVA 组数(默认 3)")
    pw.add_argument("--u", type=int, default=None, help="回归受检预测元数(默认 3)")
    pw.add_argument("-n", "--n", type=int, default=None, dest="n",
                    help="样本量(t/ANOVA 为每组,其余为总)→ 求功效")
    pw.add_argument("--power", type=float, default=None, dest="power",
                    help="目标功效 → 反解所需 N(与 -n 二选一,默认 .80)")
    pw.add_argument("--alpha", type=float, default=0.05, help="显著性水平(默认 .05)")
    pw.add_argument("--tails", type=int, choices=[1, 2], default=2, help="单/双尾(默认 2)")
    pw.add_argument("--kind", choices=["two-sample", "paired", "one-sample"],
                    default="two-sample", help="t 检验类型(默认 two-sample)")
    pw.add_argument("--df", type=int, default=None, help="SEM 模型自由度(默认 30)")
    pw.add_argument("--rmsea0", type=float, default=0.05, help="SEM H0 RMSEA(默认 .05)")
    pw.add_argument("--rmsea1", type=float, default=0.08, help="SEM H1 RMSEA(默认 .08)")
    pw.add_argument("--sims", type=int, default=1000, help="中介 Monte Carlo 模拟次数")
    pw.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pw.set_defaults(func=cmd_power)

    ppr = sub.add_parser("preregister",
                         help="预注册模板(OSF/AsPredicted 双格式;据澄清卡抽取,复用功效分析)")
    ppr.add_argument("--osf", action="store_true", help="只出 OSF 格式")
    ppr.add_argument("--aspredicted", action="store_true", help="只出 AsPredicted 格式")
    ppr.add_argument("--both", action="store_true", help="两种格式(默认)")
    ppr.add_argument("--test", choices=["ttest", "anova", "r", "correlation",
                                        "regression", "sem", "mediation"],
                     default=None, help="嵌入 D-1 功效分析的检验类型")
    ppr.add_argument("--d", type=float, default=None, help="Cohen's d")
    ppr.add_argument("--r", type=float, default=None, help="相关 r")
    ppr.add_argument("--f", type=float, default=None, help="Cohen's f(ANOVA)")
    ppr.add_argument("--f2", type=float, default=None, help="Cohen's f²(回归)")
    ppr.add_argument("--a", type=float, default=None, help="中介 a 路径")
    ppr.add_argument("--b", type=float, default=None, help="中介 b 路径")
    ppr.add_argument("--cp", type=float, default=None, help="中介直接路径 c′")
    ppr.add_argument("--k", type=int, default=None, help="ANOVA 组数")
    ppr.add_argument("--u", type=int, default=None, help="回归受检预测元数")
    ppr.add_argument("-n", "--n", type=int, default=None, dest="n", help="样本量 → 求功效")
    ppr.add_argument("--power-target", type=float, default=None, dest="power_target",
                     help="目标功效 → 反解所需 N")
    ppr.add_argument("--alpha", type=float, default=None, help="显著性水平")
    ppr.add_argument("--tails", type=int, choices=[1, 2], default=None, help="单/双尾")
    ppr.add_argument("--kind", choices=["two-sample", "paired", "one-sample"],
                     default=None, help="t 检验类型")
    ppr.add_argument("--df", type=int, default=None, help="SEM 模型自由度")
    ppr.add_argument("--rmsea0", type=float, default=None, help="SEM H0 RMSEA")
    ppr.add_argument("--rmsea1", type=float, default=None, help="SEM H1 RMSEA")
    ppr.add_argument("--sims", type=int, default=None, help="中介 Monte Carlo 次数")
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

    # research → 一句话端到端流水线(文献→设计→统计→写作→评审→门禁)
    prs = sub.add_parser("research",
                         help="一句话端到端流水线:文献→设计→统计→写作→评审→门禁")
    prs.add_argument("topic", nargs="?", default=None, help="研究主题(可空,读 notes/goal.md)")
    prs.add_argument("--revise", "-r", action="store_true",
                     help="评审阶段闭合写作→评审→修复(把 BLOCKING/MAJOR 回灌修订)")
    prs.add_argument("--rounds", type=int, default=3, help="评审修订最大轮次(默认 3)")
    prs.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
    prs.set_defaults(func=cmd_research)

    # research-loop → 通用 HITL 回路(planner→执行→critic→修复→交付)
    prl = sub.add_parser("research-loop",
                         help="通用 HITL 回路:planner→执行→critic→修复→交付")
    prl.add_argument("topic", nargs="?", default=None, help="研究主题(可空,读 notes/goal.md)")
    prl.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
    prl.set_defaults(func=cmd_loop)

    prv = sub.add_parser("review", help="审稿模拟(EIC+3审稿人+Devil's Advocate,产可解析意见)")
    prv.add_argument("draft", nargs="?", default=None,
                     help="待审稿件 md(留空取 outputs/report.md)")
    prv.add_argument("--revise", "-r", action="store_true",
                     help="把 BLOCKING/MAJOR 回灌 executor 修订并复审(闭合写作→评审→修复)")
    prv.add_argument("--rounds", type=int, default=3, help="修订复审最大轮次(默认 3)")
    prv.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用)")
    prv.set_defaults(func=cmd_review)

    pstat = sub.add_parser("stat", help="ARS-Stat 自动分析(选检验+诊断+APA7+复现脚本)")
    pstat.add_argument("file", help="CSV/TSV 数据")
    pstat.add_argument("--dv", default=None, help="因变量/变量1 列名")
    pstat.add_argument("--group", default=None, help="分组列(两组 t / 多组 ANOVA)")
    pstat.add_argument("--with", dest="with_var", default=None, help="另一连续变量(相关)")
    pstat.add_argument("--paired", default=None, help="配对的另一列(配对 t)")
    pstat.add_argument("--cluster", default=None, help="聚类/嵌套列(计算 ICC,提示 MLM)")
    pstat.add_argument("--method", default=None,
                       help="高级方法走 R 后端:cfa/sem/mlm/omega/invariance")
    pstat.add_argument("--model", default=None, help="lavaan 模型语法(cfa/sem/invariance)")
    pstat.add_argument("--formula", default=None, help="lme4 公式(mlm)")
    pstat.add_argument("--items", default=None, help="omega 条目列,逗号分隔")
    pstat.set_defaults(func=cmd_stat)

    pmt = sub.add_parser("meta",
                         help="元分析(DerSimonian-Laird 随机效应；I²/τ²/Egger；ASCII 森林图)")
    pmt.add_argument("csv", help="效应量 CSV（含 study, d/g/r, se/ci/n 列）")
    pmt.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pmt.add_argument("--out", default="notes", help="sidecar 输出目录（默认 notes/）")
    pmt.add_argument("--no-forest", action="store_false", dest="forest",
                     help="不输出 ASCII 森林图")
    pmt.set_defaults(func=cmd_meta, forest=True)

    pmis = sub.add_parser(
        "missing",
        help="缺失数据报告(Little MCAR / MAR 分组比较 / 插补推荐 / APA-7 段落；P3-2)")
    pmis.add_argument("csv", help="CSV 数据文件")
    pmis.add_argument("--json", action="store_true", help="同时输出机器可读 JSON")
    pmis.add_argument("--out", default=None, help="sidecar 输出目录（默认不写文件）")
    pmis.set_defaults(func=cmd_missing)

    psen = sub.add_parser(
        "sensitivity",
        help="敏感性分析/多元宇宙分析(Multiverse + 规格曲线；P3-3)")
    psen.add_argument(
        "plan",
        help="分叉点文件：plan.md（含 ```yaml sensitivity_forks 块）/ .yaml / .json")
    psen.add_argument("--data", default=None,
                      help="CSV 数据文件（提供后自动运行所有规格并生成规格曲线）")
    psen.add_argument("--dv", default=None, help="因变量列名（--data 时必填）")
    psen.add_argument("--group", default=None, help="分组列名（--data 时必填）")
    psen.add_argument("--alpha", type=float, default=0.05, help="显著性阈值（默认 .05）")
    psen.add_argument("--out", default=None,
                      help="sidecar 输出目录（写 sensitivity_report.md + .json）")
    psen.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    psen.set_defaults(func=cmd_sensitivity)

    pmed = sub.add_parser("mediation",
                          help="中介分析(Preacher & Hayes bootstrap CI 5000,拒 Sobel)")
    pmed.add_argument("file", help="CSV/TSV 数据文件")
    pmed.add_argument("--x", required=True, help="自变量(预测变量)列名")
    pmed.add_argument("--m", required=True, help="中介变量列名")
    pmed.add_argument("--y", required=True, help="因变量(结果变量)列名")
    pmed.add_argument("--nboot", type=int, default=5000, help="bootstrap 次数(默认 5000)")
    pmed.set_defaults(func=cmd_mediation)

    pinv = sub.add_parser(
        "invariance",
        help="测量不变性序列检验(configural→metric→scalar；scalar 不成立则阻断潜均值比较)")
    pinv.add_argument("data", help="CSV 数据文件路径")
    pinv.add_argument("--model", default=None,
                      help="lavaan CFA 模型语法(如 'F =~ q1 + q2 + q3');"
                           "缺省时仅凭手动拟合指数判决")
    pinv.add_argument("--group", required=True, help="分组列名(跨组不变性检验)")
    pinv.add_argument("--output-dir", default="notes", dest="output_dir",
                      help="sidecar JSON 输出目录(默认 notes)")
    pinv.add_argument("--cfi-configural", type=float, default=None, dest="cfi_configural",
                      help="手动录入: configural 层 CFI")
    pinv.add_argument("--rmsea-configural", type=float, default=None, dest="rmsea_configural",
                      help="手动录入: configural 层 RMSEA")
    pinv.add_argument("--cfi-metric", type=float, default=None, dest="cfi_metric",
                      help="手动录入: metric 层 CFI")
    pinv.add_argument("--rmsea-metric", type=float, default=None, dest="rmsea_metric",
                      help="手动录入: metric 层 RMSEA")
    pinv.add_argument("--cfi-scalar", type=float, default=None, dest="cfi_scalar",
                      help="手动录入: scalar 层 CFI")
    pinv.add_argument("--rmsea-scalar", type=float, default=None, dest="rmsea_scalar",
                      help="手动录入: scalar 层 RMSEA")
    pinv.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pinv.set_defaults(func=cmd_invariance)

    pmod = sub.add_parser("moderation",
                          help="调节分析(简单斜率 W±1SD + Johnson-Neyman 显著性区间)")
    pmod.add_argument("file", help="CSV/TSV 数据文件")
    pmod.add_argument("--x", required=True, help="自变量列名")
    pmod.add_argument("--w", required=True, help="调节变量列名")
    pmod.add_argument("--y", required=True, help="因变量列名")
    pmod.set_defaults(func=cmd_moderation)

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

    ptost = sub.add_parser(
        "tost",
        help=(
            "TOST 等价检验（Two One-Sided Tests；Lakens, 2017）"
            "——建立两组等价/无差异的统计证据"
        ),
    )
    ptost.add_argument("csv", help="CSV 数据文件")
    ptost.add_argument("--dv", required=True, help="因变量列名")
    ptost.add_argument("--group", default=None,
                       help="分组列名（双样本/配对；需恰好 2 个水平）")
    ptost.add_argument("--lower", type=float, required=True,
                       help="等价区间下界（原始均值差单位，如 -0.5；负值）")
    ptost.add_argument("--upper", type=float, required=True,
                       help="等价区间上界（原始均值差单位，如 0.5；正值）")
    ptost.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ptost.add_argument("--one-sample", type=float, default=None, dest="mu0",
                       metavar="MU0", help="参考均值（单样本模式，与 --group 互斥）")
    ptost.add_argument("--paired", action="store_true", help="配对样本模式")
    ptost.add_argument("--out", default=None,
                       help="sidecar 输出目录（写 notes/equivalence_report.*）")
    ptost.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ptost.set_defaults(func=cmd_tost)

    pbf = sub.add_parser(
        "bayes",
        help=(
            "贝叶斯因子分析（JZS Cauchy 先验；Rouder et al., 2009）"
            "——量化证据强度、补充 p 值 / 接受 H₀ 的证据"
        ),
    )
    pbf.add_argument("csv", help="CSV 数据文件")
    pbf.add_argument("--dv", required=True, help="因变量 / 第一变量列名")
    pbf.add_argument("--test",
                     choices=["ttest", "paired", "correlation"],
                     default="ttest",
                     help="检验类型：ttest（独立/单样本）| paired（配对）| correlation（默认 ttest）")
    pbf.add_argument("--group", default=None,
                     help="分组列名（ttest 双样本 / paired）或第二变量列名（correlation）")
    pbf.add_argument("--mu0", type=float, default=0.0, help="单样本原假设均值（默认 0）")
    pbf.add_argument("--r-scale", type=float, default=None, dest="r_scale",
                     help="Cauchy 先验尺度参数（默认 √2/2 ≈ 0.707）")
    pbf.add_argument("--out", default="notes", help="sidecar 输出目录（默认 notes/）")
    pbf.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pbf.set_defaults(func=cmd_bayes)

    pregress = sub.add_parser(
        "regress",
        help="OLS 多元回归：B/β/SE/t/p/R²/F，输出 APA-7 系数表",
    )
    pregress.add_argument("csv", help="输入数据 CSV 路径")
    pregress.add_argument("--dv", required=True, help="因变量列名")
    pregress.add_argument("--iv", required=True,
                          help="预测变量（逗号分隔，如 --iv age,edu,score）")
    pregress.add_argument("--alpha", type=float, default=0.05,
                          help="显著性水平（默认 .05）")
    pregress.add_argument("--out", default="notes",
                          help="报告输出目录（默认 notes/）")
    pregress.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pregress.set_defaults(func=cmd_regress)

    pdesc = sub.add_parser(
        "describe",
        help="APA-7 描述统计表（M/SD/N/Sk/Kurt/CI）+ 可选 Pearson 相关矩阵",
    )
    pdesc.add_argument("csv", help="输入数据 CSV 路径")
    pdesc.add_argument("--cols", default=None,
                       help="逗号分隔的列名（默认自动选数值列）")
    pdesc.add_argument("--corr", action="store_true",
                       help="附加 Pearson 相关矩阵（含 Fisher-z 95% CI 和 * 标注）")
    pdesc.add_argument("--alpha", type=float, default=0.05,
                       help="显著性水平（默认 .05）")
    pdesc.add_argument("--out", default="notes",
                       help="报告输出目录（默认 notes/）")
    pdesc.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    pdesc.set_defaults(func=cmd_describe)

    for name, helptext in [
        ("write", "按 APA JARS 写作"),
        ("init", "为研究项目铺设标准结构+PSYCLAW.md"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.set_defaults(func=_stub(name))

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
