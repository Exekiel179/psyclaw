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
from psyclaw.mcp.manager import list_mcp_catalog
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
    print("\n" + ui.accent("MCP 目录:"))
    for m in list_mcp_catalog():
        mark = ui.ok("✓") if m["enabled"] else ui.dim("·")
        print(f"  {mark} {m['name']:<14} " + ui.dim(f"[{m['category']}] {m['enable_when']}"))
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
    print("\n总体状态:" + (ui.ok("OK ✓") if ok else ui.err("有问题,请见上方")))
    return 0 if ok else 1


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
        else:
            print("可 serve:mne | spss")
            return 1
        return srv.run()
    print("MCP 服务器目录（registry.yaml）：")
    for m in list_mcp_catalog():
        gate = "本地软件检测" if m["category"] == "stats-optional" else "—"
        print(f"  - {m['name']:<14} [{m['category']:<14}] 启用条件: {m.get('enable_when', gate)}")
    print("\n内置 MCP 可独立 serve 给任意 MCP 客户端(Claude Desktop 等):")
    print("  psyclaw mcp --serve mne    # EEG/MEG/ERP")
    print("  psyclaw mcp --serve spss   # SPSS 语法生成 + 批处理")
    return 0


def cmd_gates(args: argparse.Namespace) -> int:
    print("PsyClaw Gates — 学术规范门禁自检\n" + "-" * 32)
    ok = run_gates_selfcheck(verbose=True)
    return 0 if ok else 1


def cmd_scale(args: argparse.Namespace) -> int:
    from psyclaw.psych.scales import print_scale
    print_scale(args.scale_id)
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
    from psyclaw.output.apa7 import export_cli
    argv = [args.file]
    if args.docx:
        argv += ["--docx", args.docx]
    if args.md:
        argv += ["--md", args.md]
    return export_cli(argv)


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


def cmd_lit(args: argparse.Namespace) -> int:
    from psyclaw.psych.lit_cli import lit_cli
    return lit_cli(query=args.query or "", sources=args.sources, limit=args.limit,
                   year_from=args.year_from, fulltext_doi=args.fulltext,
                   zotero_doi=args.zotero)


def cmd_stat(args: argparse.Namespace) -> int:
    if getattr(args, "method", None):
        from psyclaw.psych.analyze import analyze_advanced
        kw = {"model": getattr(args, "model", None), "formula": getattr(args, "formula", None),
              "group": getattr(args, "group", None),
              "items": args.items.split(",") if getattr(args, "items", None) else None}
        return analyze_advanced(args.file, args.method, **{k: v for k, v in kw.items() if v})
    from psyclaw.psych.analyze import analyze
    return analyze(args.file, args.dv, getattr(args, "group", None),
                   getattr(args, "with_var", None), getattr(args, "paired", None))


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
    pmcp.add_argument("--serve", dest="name", choices=["mne", "spss"], default=None,
                      help="作为 stdio MCP 服务器运行(mne/spss)")
    pmcp.set_defaults(func=cmd_mcp)
    sub.add_parser("gates", help="跑学术规范门禁自检").set_defaults(func=cmd_gates)

    ps = sub.add_parser("scale", help="量表库查询(DASS/PHQ-9/GAD-7/TIPI…)")
    ps.add_argument("scale_id", nargs="?", default=None, help="量表 id,留空列出全部")
    ps.set_defaults(func=cmd_scale)

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

    pcl = sub.add_parser("clarify", help="研究澄清(grill-me 式,17 槽位,不澄清完不开工)")
    pcl.add_argument("--status", action="store_true", help="只看澄清进度")
    pcl.set_defaults(func=cmd_clarify)

    pci = sub.add_parser("cite", help="方法学背书库(每个设计决策的文献支撑)")
    pci.add_argument("topic_id", nargs="?", default=None, help="决策主题,留空列出全部")
    pci.set_defaults(func=cmd_cite)

    pex = sub.add_parser("export", help="APA7 输出(Word docx + Markdown,确定性模板)")
    pex.add_argument("file", help="结构化 Markdown 草稿")
    pex.add_argument("--docx", default=None, help="docx 输出路径")
    pex.add_argument("--md", default=None, help="md 输出路径")
    pex.set_defaults(func=cmd_export)

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

    # research / research-loop → 真实 HITL 回路
    for nm in ("research", "research-loop"):
        pl = sub.add_parser(nm, help="HITL 研究回路:planner→执行→critic→修复→交付")
        pl.add_argument("topic", nargs="?", default=None, help="研究主题(可空,读 notes/goal.md)")
        pl.add_argument("--auto", action="store_true", help="跳过人工确认(CI 用,慎用)")
        pl.set_defaults(func=cmd_loop)

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
    pstat.add_argument("--method", default=None,
                       help="高级方法走 R 后端:cfa/sem/mlm/omega/invariance")
    pstat.add_argument("--model", default=None, help="lavaan 模型语法(cfa/sem/invariance)")
    pstat.add_argument("--formula", default=None, help="lme4 公式(mlm)")
    pstat.add_argument("--items", default=None, help="omega 条目列,逗号分隔")
    pstat.set_defaults(func=cmd_stat)

    pau = sub.add_parser("auth", help="机构权限(EZProxy/LibKey)配置与认证状态自检")
    pau.add_argument("--set", action="store_true", help="配置机构权限(无密码)")
    pau.add_argument("--verify", action="store_true", help="连通自检并记录认证状态")
    pau.set_defaults(func=cmd_auth)

    plit = sub.add_parser("lit", help="文献检索 + 全文获取(合法 OA;PRISMA 计数)")
    plit.add_argument("query", nargs="?", default=None, help="检索式")
    plit.add_argument("--sources", default="openalex,europepmc", help="openalex,europepmc,arxiv")
    plit.add_argument("--limit", type=int, default=10)
    plit.add_argument("--year-from", dest="year_from", type=int, default=None)
    plit.add_argument("--fulltext", default=None, help="按 DOI 取合法 OA 全文")
    plit.add_argument("--zotero", default=None, help="按 DOI 从你的 Zotero 文库取全文")
    plit.set_defaults(func=cmd_lit)

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
