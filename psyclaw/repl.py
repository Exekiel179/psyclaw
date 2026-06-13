"""PsyClaw REPL — 交互式对话终端(stdlib only)。

支持:
- 自然语言对话(流式输出,注入 PSYCLAW.md 学术规范作为 system 提示)
- slash 命令:/help /model /skills /mcp /gates /scale /screen /clear /compact /cost /config /exit
- @<file> 文件引用:把数据/文稿拉进上下文
- 会话历史与粗略成本统计
"""

from __future__ import annotations

import sys
from pathlib import Path

from psyclaw import __version__, config as cfg
from psyclaw.gates.checker import GATES_DIR, run_gates_selfcheck
from psyclaw.mcp.manager import list_mcp_catalog
from psyclaw.providers import get_provider
from psyclaw.skills.loader import list_skills

from psyclaw import ui
from psyclaw.ui_input import read_line

MAX_FILE_CHARS = 30_000
PROMPT = ui.paint("psyclaw", "brcyan", "bold") + ui.dim(" ❯ ")

# slash 命令注册表(联想弹出用:命令 → 一句话描述)
COMMANDS = {
    "/help": "命令总览",
    "/plan": "规划模式开关(只规划不执行;/plan <目标> 设目标并开启;off 退出)",
    "/goal": "查看/设定研究目标(notes/goal.md)",
    "/tasks": "任务看板(自动从计划抽取;start/done/add/sync)",
    "/recall": "手动召回历史上下文(/recall <查询>;库状态留空查看)",
    "/audit": "逐轮审计开关(on/off;每轮多一次 LLM 调用)",
    "/clarify": "研究澄清(grill-me 式,不澄清完不开工)",
    "/check": "可运行假设诊断(正态/Levene/经典F+Welch)",
    "/screen": "草率作答筛查(longstring/IRV/直线)",
    "/scale": "量表库(DASS/PHQ-9/GAD-7/TIPI…)",
    "/assume": "前提假设知识库(16 检验族)",
    "/method": "复杂方法目录(SEM/MLM/LPA/网络…)",
    "/design": "实验设计目录(12 设计卡)",
    "/cite": "方法学背书库(决策→文献)",
    "/export": "APA7 输出(Word docx + Markdown)",
    "/memory": "三层记忆(画像/惯性/教训卡)",
    "/gates": "学术门禁自检(13 条)",
    "/skills": "已注册 skills",
    "/mcp": "MCP 目录与启用状态",
    "/model": "查看/切换模型",
    "/provider": "查看/切换 provider",
    "/cost": "本会话成本粗估",
    "/clear": "清空上下文",
    "/compact": "压缩上下文",
    "/config": "配置向导",
    "/research": "一句话端到端流水线:文献→设计→统计→写作→评审→门禁(受澄清门禁约束)",
    "/research-loop": "通用 HITL 回路(planner→executor→critic)",
    "/review": "审稿模拟(EIC+3审稿人+DA;--revise 回灌修复环)",
    "/lit": "文献检索(M2+)",
    "/stat": "ARS-Stat 统计分析(M2+)",
    "/write": "APA JARS 写作(M2+)",
    "/exit": "退出",
}


def _build_system_prompt() -> str:
    """瘦核心系统提示(长上下文优化:知识库改为按消息动态注入)。"""
    from psyclaw.context import lean_core
    parts = [lean_core()]
    parts.append(
        "\n# 强制澄清规则\n任何研究开工前必须完成澄清卡(17 槽位,/clarify)。"
        "用户提出研究想法时,你的第一动作是 grill-me 式逐项澄清(一次一个问题,"
        "带推荐答案),而不是直接给方案。设计决策必须给文献背书(/cite 查背书库)。")
    from psyclaw.memory import memory_prompt
    mem = memory_prompt()
    if mem:
        parts.append("\n" + mem)
    return "\n".join(parts)


class ReplSession:
    def __init__(self) -> None:
        self.conf = cfg.load_config()
        self.provider = get_provider(self.conf)
        self.system = _build_system_prompt()
        self.messages: list[dict] = []
        self.memo = ""              # 滚动压缩的决策备忘
        self.plan_mode = False      # 规划模式:只规划不执行,产出自动抽任务
        self.audit_mode = False     # 逐轮审计(auditor agent,每轮多一次调用)
        from datetime import datetime
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        from psyclaw.recall import ContextArchive
        self.archive = ContextArchive(".")   # 全量上下文库(SQLite,懒建)
        self.chars_in = 0
        self.chars_out = 0

    # -- 文件引用 ----------------------------------------------------------
    def _expand_files(self, text: str) -> str:
        """把 @path 替换为文件内容块。"""
        out_parts = []
        for token in text.split():
            if token.startswith("@") and len(token) > 1:
                p = Path(token[1:]).expanduser()
                if p.exists() and p.is_file():
                    from psyclaw.context import smart_excerpt
                    excerpt = smart_excerpt(p)
                    out_parts.append("\n" + excerpt + "\n")
                    print(f"  [智能摘录 {p}({len(excerpt)} 字符进上下文)]")
                    continue
                print(f"  [未找到文件 {token[1:]},按原文发送]")
            out_parts.append(token)
        return " ".join(out_parts)

    # -- 对话 --------------------------------------------------------------
    def ask(self, text: str) -> None:
        from psyclaw.context import compact_history, relevant_knowledge, render_memo
        text = self._expand_files(text)
        self.messages.append({"role": "user", "content": text})
        self.messages, self.memo = compact_history(self.messages, self.memo)
        # 动态系统提示:瘦核心 + 决策备忘 + 按需知识
        system = self.system
        memo_part = render_memo(self.memo)
        if memo_part:
            system += "\n\n" + memo_part
        knowledge = relevant_knowledge(text)
        if knowledge:
            system += "\n\n" + knowledge
        if self.plan_mode:
            from psyclaw.tasks import PLAN_MODE_SYSTEM
            system += "\n\n" + PLAN_MODE_SYSTEM
        # 历史上下文召回:关键词定位 + 相关度门控(不达标不注入)
        try:
            from psyclaw.recall import render_recall
            hits = self.archive.recall(text, exclude_session=self.session_id)
            if hits:
                system += "\n\n" + render_recall(hits)
                print(ui.dim(f"  [召回 {len(hits)} 条历史上下文,相关度 "
                             + "/".join(f"{h['score']:.0%}" for h in hits) + "]"))
        except Exception:  # noqa: BLE001  # 召回失败不阻塞对话
            pass
        self.chars_in += len(text) + len(system)
        print()
        blk = ui.StreamBlock(f"PsyClaw · {self.provider.name}")
        reply_parts: list[str] = []
        try:
            for chunk in self.provider.chat(self.messages, system=system):
                blk.write(chunk)
                reply_parts.append(chunk)
        except Exception as exc:  # noqa: BLE001
            blk.write(f"\n[provider 错误] {exc}")
            blk.close()
            self.messages.pop()
            return
        blk.close()
        print()
        reply = "".join(reply_parts)
        self.messages.append({"role": "assistant", "content": reply})
        self.chars_out += len(reply)
        if self.plan_mode:
            self._capture_plan(reply)
        # 全量储存本轮上下文(写入失败不阻塞对话)
        try:
            self.archive.record(self.session_id, text, reply)
        except Exception:  # noqa: BLE001
            pass
        # 逐轮审计(显式开启时)
        if self.audit_mode and reply.strip():
            from psyclaw.audit import render_verdict, run_audit
            result = run_audit(self.provider, text, reply)
            print(render_verdict(result))

    def _capture_plan(self, reply: str) -> None:
        """规划模式产物落盘:存 notes/plan.md 并自动抽任务(auto-write task)。"""
        from psyclaw.tasks import TaskStore, parse_plan_tasks
        if not parse_plan_tasks(reply):
            return
        plan_p = Path("notes") / "plan.md"
        plan_p.parent.mkdir(parents=True, exist_ok=True)
        plan_p.write_text(reply, encoding="utf-8")
        store = TaskStore(".")
        n = store.sync_from_plan(reply)
        done, total = store.progress()
        print(ui.ok(f"  ✓ 计划已存 notes/plan.md · 自动写入 {n} 条新任务"
                    f"(进度 {done}/{total})"))
        print(ui.dim("    /tasks 查看看板 · /plan off 退出规划模式开始执行"))

    # -- slash 命令 ---------------------------------------------------------
    def handle_command(self, line: str) -> bool:
        """处理 slash 命令。返回 False 表示退出 REPL。"""
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()

        if cmd in ("/exit", "/quit", "/q"):
            return False

        if cmd == "/help":
            print(HELP_TEXT)
        elif cmd == "/model":
            if arg:
                self.conf["model"] = arg
                self.provider = get_provider(self.conf)
            print(f"  provider: {self.provider.describe()}")
        elif cmd == "/provider":
            if arg:
                self.conf["provider"] = arg
                self.provider = get_provider(self.conf)
            print(f"  provider: {self.provider.describe()}")
        elif cmd == "/skills":
            for s in list_skills():
                print(f"  - {s['name']:<14} [{s['category']}] {s['description'][:60]}")
        elif cmd == "/mcp":
            for m in list_mcp_catalog():
                state = "✓" if m["enabled"] else "·"
                print(f"  {state} {m['name']:<14} [{m['category']}] {m['enable_when']}")
        elif cmd == "/gates":
            run_gates_selfcheck(verbose=True)
        elif cmd == "/scale":
            from psyclaw.psych.scales import print_scale
            print_scale(arg or None)
        elif cmd == "/assume":
            from psyclaw.psych.knowledge import print_assumptions
            print_assumptions(arg or None)
        elif cmd == "/method":
            from psyclaw.psych.knowledge import print_method
            print_method(arg or None)
        elif cmd == "/design":
            from psyclaw.psych.knowledge import print_design
            print_design(arg or None)
        elif cmd == "/check":
            from psyclaw.psych.diagnostics import check_cli_args
            if not arg:
                print("  用法:/check <data.csv> --dv <列名> [--group <列名>]")
            else:
                check_cli_args(arg.split())
        elif cmd == "/clarify":
            from psyclaw.psych.clarify import print_clarify_status, run_clarify_interactive
            if arg == "status":
                print_clarify_status()
            else:
                run_clarify_interactive()
                self.system = _build_system_prompt()  # 重载(惯性可能已更新)
        elif cmd == "/cite":
            from psyclaw.psych.knowledge import print_evidence
            print_evidence(arg or None)
        elif cmd == "/export":
            from psyclaw.output.apa7 import export_cli
            if not arg:
                print("  用法:/export <draft.md> [--docx out.docx] [--md out.md]")
            else:
                export_cli(arg.split())
        elif cmd == "/memory":
            from psyclaw.memory import memory_cli
            memory_cli(arg.split() if arg else ["list"])
        elif cmd == "/plan":
            from psyclaw.tasks import set_goal
            low = arg.lower()
            if low in ("off", "exit", "quit"):
                self.plan_mode = False
                print("  [规划模式 关] 对话恢复正常。/tasks 查看待办,逐条执行。")
            elif arg and low != "on":
                set_goal(arg)
                self.plan_mode = True
                print(ui.ok(f"  ✓ 目标已写 notes/goal.md:{arg[:60]}"))
                print("  [规划模式 开] 直接对话生成计划,末尾 TASKS 自动抽取为任务看板。")
            else:
                self.plan_mode = True if low == "on" else not self.plan_mode
                print(f"  [规划模式 {'开' if self.plan_mode else '关'}]"
                      + ("只规划不执行;/plan off 退出。" if self.plan_mode else ""))
        elif cmd == "/goal":
            from psyclaw.tasks import get_goal, set_goal
            if arg:
                set_goal(arg)
                print(ui.ok("  ✓ 研究目标已写 notes/goal.md"))
            else:
                g = get_goal()
                print(f"  目标:{g}" if g else
                      "  (未设定)/goal <文本> 设定;/plan <文本> 可顺带开启规划模式。")
        elif cmd == "/tasks":
            from psyclaw.tasks import tasks_cli
            tasks_cli(arg.split() if arg else ["list"])
        elif cmd == "/recall":
            from psyclaw.recall import RECALL_THRESHOLD
            if not arg:
                n_turns, n_kws = self.archive.stats()
                emb = self.archive.embedder
                print(f"  上下文库:{n_turns} 轮对话 · {n_kws} 条关键词索引"
                      f" · 关键词门槛 {RECALL_THRESHOLD:.0%}")
                print(f"  向量后端:{emb.name} · 语义门槛 {emb.default_threshold:.0%}"
                      + ("" if emb.name.startswith("model2vec") else
                         ui.dim("(哈希兜底;psyclaw setup --groups embed 升级真模型)")))
                print(ui.dim("  /recall <查询> 手动召回 · /recall reindex 重建向量索引"))
            elif arg.lower() == "reindex":
                n = self.archive.reindex()
                print(ui.ok(f"  ✓ 已为 {n} 轮补建向量(后端 {self.archive.embedder.name})"))
            else:
                hits = self.archive.recall(arg)
                if not hits:
                    print(ui.dim("  无相关度达标的历史上下文(门槛 "
                                 f"{RECALL_THRESHOLD:.0%},不达标不注入)。"))
                for h in hits:
                    print(ui.accent(f"  ◆ {h['ts']} · 相关度 {h['score']:.0%}"))
                    print(ui.dim(f"    问:{h['user_text'][:80]}"))
                    print(ui.dim(f"    答:{h['reply_text'][:80]}"))
        elif cmd == "/audit":
            low = arg.lower()
            if low == "on":
                self.audit_mode = True
            elif low == "off":
                self.audit_mode = False
            elif low == "log":
                logp = Path(".psyclaw/audits/audit_log.md")
                print(logp.read_text(encoding="utf-8")[-2000:]
                      if logp.exists() else "  (暂无审计记录)")
                return True
            else:
                self.audit_mode = not self.audit_mode
            print(f"  [逐轮审计 {'开' if self.audit_mode else '关'}]"
                  + (" 每轮回答后 auditor 评分,SCORE<80 草拟教训卡;"
                     "注意每轮多一次 LLM 调用。" if self.audit_mode else ""))
        elif cmd == "/screen":
            from psyclaw.psych.careless import screen_csv_cli
            if not arg:
                print("  用法:/screen <data.csv> [--prefix Q] [--suffix A]")
            else:
                screen_csv_cli(arg.split())
        elif cmd == "/clear":
            self.messages.clear()
            print("  [上下文已清空]")
        elif cmd == "/compact":
            keep = self.messages[-4:]
            dropped = len(self.messages) - len(keep)
            self.messages = keep
            print(f"  [已压缩:丢弃 {max(dropped, 0)} 条早期消息,保留最近 {len(keep)} 条]")
        elif cmd == "/cost":
            tok_in, tok_out = self.chars_in // 4, self.chars_out // 4
            print(f"  约 {tok_in} input tokens / {tok_out} output tokens(按字符/4 粗估)")
        elif cmd == "/config":
            cfg.run_config_wizard()
            self.conf = cfg.load_config()
            self.provider = get_provider(self.conf)
        elif cmd == "/review":
            from psyclaw.review import review_cli
            review_cli(arg.split() if arg else [])
        elif cmd == "/research":
            from psyclaw.pipeline import pipeline_cli
            pipeline_cli(arg.split() if arg else [])
        elif cmd == "/research-loop":
            from psyclaw.loop import run_loop
            run_loop(topic=arg or None)
        elif cmd in ("/lit", "/stat", "/write", "/init"):
            print(f"  [{cmd}] M2+ 实现(见 DESIGN.md 路线图)。当前可直接用自然语言询问,ARS 规范已注入。")
        else:
            print(f"  未知命令 {cmd},输入 /help 查看可用命令")
        return True

    # -- 主循环 --------------------------------------------------------------
    def run(self) -> int:
        print("  " + ui.accent("⚙ provider ") + self.provider.describe())
        print("  " + ui.dim("输入 / 弹出命令联想(↑↓选择 Tab补全) · /exit 退出 · @<文件> 引用") + "\n")
        while True:
            prompt = PROMPT if not self.plan_mode else (
                ui.paint("psyclaw", "brcyan", "bold")
                + ui.warn(" plan") + ui.dim(" ❯ "))
            try:
                line = read_line(prompt, COMMANDS).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.startswith("/"):
                if not self.handle_command(line):
                    break
            else:
                self.ask(line)
        print(ui.dim("再见。研究顺利!"))
        return 0


HELP_TEXT = """\
  对话        直接输入问题(流式回复,PSYCLAW 学术规范已注入)
  @<file>     在消息中引用文件内容(如:帮我看看 @data.csv 的结构)
  /plan [g]   规划模式(只规划不执行;带文本=设目标并开启;off 退出)
  /goal [g]   查看/设定研究目标(notes/goal.md)
  /tasks      任务看板(list|add|start|done|block|sync;计划自动抽取)
  /recall [q] 历史上下文召回(全量存库+关键词索引,相关度≥80%才注入)
  /audit      逐轮审计开关(auditor 评分;on/off/log)
  /model [m]  查看/切换模型      /provider [p]  查看/切换 provider
  /skills     列出 skills        /mcp           MCP 目录与启用状态
  /gates      门禁自检           /cost          本会话成本粗估
  /scale [s]  量表库查询(如 /scale dass-42)
  /assume [t] 前提假设知识库(如 /assume anova-rm)
  /method [m] 复杂方法目录(如 /method clpm)
  /design [d] 实验设计目录(如 /design esm-diary)
  /check f    可运行假设诊断(/check data.csv --dv 分数 --group 组别)
  /screen f   数据草率作答筛查
  /clarify    研究澄清(grill-me 式;不澄清完 /research 不放行)
  /cite [t]   方法学背书库(每个设计决策的文献支撑)
  /export f   APA7 输出(Word + Markdown,确定性模板)
  /review f   审稿模拟(EIC+3审稿人+DA;--revise 闭合写作→评审→修复)
  /memory     三层记忆(画像/决策惯性/教训卡)
  /clear      清空上下文         /compact       压缩上下文
  /config     配置向导           /exit          退出
  /research [t]    一句话端到端流水线:文献→设计→统计→写作→评审→门禁(--revise 闭环)
  /research-loop   通用 HITL 回路(planner→executor→critic→修复→交付)
  /lit /stat /write  → M2+ 实现"""


def run_repl() -> int:
    return ReplSession().run()
