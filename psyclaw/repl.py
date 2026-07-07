"""PsyClaw REPL — 交互式对话终端(stdlib only)。

支持:
- 自然语言对话(流式输出,注入 PSYCLAW.md 学术规范作为 system 提示)
- slash 命令:/help /model /skills /mcp /gates /scale /clear /compact /cost /config /exit
- @<file> 文件引用:把数据/文稿拉进上下文
- **天然保存文件**:直接说「存到 X」即可——模型用 ```save 块输出,ask() 自动落盘
  (护栏:绝不写 data/raw、覆盖前确认;对齐 _capture_plan 的「解析回复→写盘」套路,provider 无关)
- 会话历史与粗略成本统计
"""

from __future__ import annotations

import re
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
    "/agent": "agent 模式开关(模型自主多步调用工具:search/read_file/save_file/kg_query/recall)",
    "/safemode": "文件读取权限:safe=一切读取须 @ 引用;open(默认)=模型可请求自动读取",
    "/plugins": "已加载插件(用户 项目/全局;可注册工具/命令/system 片段)",
    "/clarify": "研究澄清(grill-me 式,不澄清完不开工)",
    "/preregister": "预注册模板(OSF/AsPredicted 双格式;据澄清卡抽取)",
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
    "/research": "一句话研究编排:文献→设计→写作→评审→总验收(受澄清门禁约束)",
    "/research-loop": "通用 HITL 回路(planner→executor→critic)",
    "/review": "审稿模拟(EIC+3审稿人+DA;--revise 回灌修复环)",
    "/lit": "文献检索(M2+)",
    "/sessions": "列出历史会话(跨会话持久化)",
    "/resume": "续接历史会话(/resume <id>)",
    "/rename": "给当前会话改名(/rename <新名>)",
    "/search": "全文检索历史对话(/search <词>)",
    "/exit": "退出",
}


# 「天然」保存文件:提示模型用约定块输出,REPL 每轮自动扫描并落盘(对齐 _capture_plan 套路)。
_SAVE_SYSTEM = (
    "\n# 保存文件(天然支持)\n用户要求把内容保存/导出到某个文件时,**不要说你无法创建文件**。"
    "改为在回复里用下面的块输出,PsyClaw 会自动写盘(会确认覆盖、**绝不写受保护的 data/raw**):\n"
    "```save path=<文件路径>\n<文件的完整内容>\n```\n"
    "可给多个 save 块;块外照常写说明。用户没明确要求保存时,不要滥用此块。")

_SAVE_OPEN_RE = re.compile(r"^```save[ :]+(?:path=)?(?P<path>[^\n`]+)\s*$")
_FENCE_RE = re.compile(r"^```")

# 「键盘选择」:模型给选项时输出 choices 块,REPL 弹选择器并自动回传(psyclaw/choices.py)。
_CHOICES_SYSTEM = (
    "\n# 让用户选择(键盘选择器)\n需要用户在若干选项里选择时,除正文说明外,附一个块:\n"
    "```choices\n{\"question\": \"问题\", \"multi\": true, \"options\": [\"选项A\", \"选项B\"]}\n"
    "```\nPsyClaw 会弹出键盘选择器并把用户的选择自动回传给你;不要只写复选清单等用户打字。")

# 「直接跑命令」:模型输出 psyclaw/shell 块,REPL 执行并把输出自动回传(用户实测:
# 命令块没人执行,回合看着像结束了——死胡同必须消灭)。psyclaw 子命令进程内跑;
# shell 交系统终端跑。危险命令(rm -rf / git push --force / DROP TABLE…)须人工确认。
_RUN_SYSTEM = (
    "\n# 直接运行命令(会真的执行)\n要跑 PsyClaw 子命令或系统命令时,输出块(每行一条),"
    "PsyClaw 会执行并把输出回传给你,你据此继续:\n"
    "```psyclaw\nanalysis-loop data/clean/x.csv --auto\n```\n"
    "```shell\npython outputs/analysis.py\n```\n"
    "注意:**没有** describe/stat 等内置统计命令(统计已外移)——统计请生成脚本再用 shell 跑。"
    "不要输出命令块之后就当作已完成;结果会回传,等结果再下结论。")
_RUN_SAFE_NOTE = "(当前安全模式:命令块不会自动执行,会提示用户手动跑。)"

_RUN_RE = re.compile(r"```(?P<kind>psyclaw|shell|bash|sh|cmd|powershell)\s*\r?\n"
                     r"(?P<body>.*?)```", re.S)
# 危险模式标签(CLAUDE.md 红线)。v0.3 安全加固(外审 HIGH):此正则只是确认提示里的
# ⚠ 标签,**不是**安全边界——LLM 生成的 shell 命令每条都须人工确认(fail-closed),
# 拒绝清单绕过太容易(变量拼接/base64/别名),不能作为放行依据。
_DANGEROUS_RE = re.compile(
    r"rm\s+-rf|git\s+push\s+--force|git\s+reset\s+--hard|push\s+.*\b(master|main)\b"
    r"|DROP\s+TABLE|del\s+/[fsq]|rd\s+/s|format\s+[a-z]:|mkfs|shutdown", re.I)
_RUN_TIMEOUT = 180
_MAX_RUN_CMDS = 6


def parse_run_requests(reply: str) -> list[dict]:
    """从回复解析 psyclaw/shell 命令块 → [{kind, cmd}](kind ∈ psyclaw|shell)。纯函数。"""
    out: list[dict] = []
    for m in _RUN_RE.finditer(reply or ""):
        kind = "psyclaw" if m.group("kind") == "psyclaw" else "shell"
        for line in m.group("body").splitlines():
            cmd = line.strip()
            if cmd and not cmd.startswith("#"):
                out.append({"kind": kind, "cmd": cmd})
    return out


# 交互式子命令不在块里跑:stdout 被重定向时它们会隐形地等输入,看起来像卡死。
_INTERACTIVE_CMDS = {"repl", "config", "setup", "clarify", "serve", "resume"}


def _run_psyclaw_cmd(cmd: str) -> str:
    """进程内跑 psyclaw 子命令(不需要子进程;argparse 报错也如实回传)。"""
    import io as _io
    import shlex
    from contextlib import redirect_stderr, redirect_stdout
    argv = shlex.split(cmd)
    if argv and argv[0] == "psyclaw":
        argv = argv[1:]
    if argv and argv[0] in _INTERACTIVE_CMDS:
        return (f"$ psyclaw {' '.join(argv)}\n[未执行:{argv[0]} 是交互式命令,"
                "请用户自己在终端跑;非交互流程可用对应 --auto/--non-interactive 形式]")
    buf = _io.StringIO()
    try:
        from psyclaw.cli import main as _main
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = _main(argv)
    except SystemExit as exc:                 # argparse 错误等
        rc = int(exc.code or 0) if str(exc.code or 0).isdigit() else 2
    except Exception as exc:  # noqa: BLE001
        buf.write(f"\n[执行异常] {exc}")
        rc = 1
    return f"$ psyclaw {' '.join(argv)}\n(rc={rc})\n{buf.getvalue()}"


def _run_shell_cmd(cmd: str) -> str:
    """交系统 shell 跑一条命令,捕获输出(带超时)。"""
    import subprocess
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=_RUN_TIMEOUT)
        out = (res.stdout or "") + (("\n" + res.stderr) if res.stderr else "")
        return f"$ {cmd}\n(rc={res.returncode})\n{out}"
    except subprocess.TimeoutExpired:
        return f"$ {cmd}\n[超时:>{_RUN_TIMEOUT}s,已终止]"
    except OSError as exc:
        return f"$ {cmd}\n[无法执行:{exc}]"


def run_commands(reqs: list[dict], confirm=None,
                 limit: int = _MAX_RUN_CMDS) -> tuple[str, list[str]]:
    """执行命令块 → (回传消息, 终端提示行)。

    v0.3 安全加固(fail-closed):**shell 类命令每条**都须 confirm(cmd)→True 才执行——
    LLM 生成的命令交 subprocess shell=True,拒绝清单不是安全边界,人工确认才是。
    psyclaw 进程内子命令保持自动(自家 argparse 编排、无 shell,交互式命令另有守卫);
    但命中 _DANGEROUS_RE 危险模式时同样须确认(纵深防御)。confirm=None → 一律拒。
    """
    parts: list[str] = []
    notes: list[str] = []
    for r in reqs[:limit]:
        cmd = r["cmd"]
        danger = bool(_DANGEROUS_RE.search(cmd))
        if r["kind"] != "psyclaw" or danger:
            if not (confirm and confirm(cmd)):
                tag = "危险命令" if danger else "shell 命令"
                parts.append(f"$ {cmd}\n[已拒绝:{tag}未获人工确认]")
                notes.append(f"  ✗ 拒执行({tag}):{cmd[:50]}")
                continue
        notes.append(f"  ⚙ 执行:{cmd[:70]}")
        out = _run_psyclaw_cmd(cmd) if r["kind"] == "psyclaw" else _run_shell_cmd(cmd)
        parts.append(out[:6000])
    if len(reqs) > limit:
        parts.append(f"[本轮最多执行 {limit} 条命令,其余 {len(reqs) - limit} 条请下一轮]")
    return ("# 命令执行结果\n\n" + "\n\n".join(parts)) if parts else "", notes


def strip_save_blocks(reply: str) -> str:
    """去掉 save 块(含其嵌套围栏内容)——save 的内容是要写盘的文件,里面的
    read/命令/复选清单只是文件内容,绝不能被当成本轮要执行的请求。"""
    out: list[str] = []
    lines = (reply or "").splitlines()
    i, n = 0, len(lines)
    while i < n:
        if _SAVE_OPEN_RE.match(lines[i]):
            inner = False
            i += 1
            while i < n:
                ln = lines[i]
                if _FENCE_RE.match(ln):
                    if ln.strip() == "```" and not inner:
                        break
                    inner = not inner
                i += 1
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# 「自动读文件」(开放模式,默认):模型输出 read 块,REPL 自动读取注入,不必让用户 @ 引用。
_READ_OPEN_SYSTEM = (
    "\n# 读取本地文件(当前:开放模式)\n需要看本地文件内容时,**不要说你无法读取**,"
    "也不要让用户粘贴或 @ 引用。直接输出块(每行一个路径):\n"
    "```read\n<文件路径>\n```\nPsyClaw 会自动读取并把内容(数据 CSV 给结构+少量样例行;"
    "PDF 抽正文;受保护的 data/raw 会被拒绝)回传给你。")
_READ_SAFE_SYSTEM = (
    "\n# 读取本地文件(当前:安全模式)\n所有文件读取都需要用户用 @<路径> 显式引用;"
    "需要文件内容时,请求用户提供 @ 引用,不要自行读取。")

_READ_RE = re.compile(r"```read\s*\r?\n(?P<body>.*?)```", re.S)
_MAX_AUTO_READS = 4      # 每轮最多自动读的文件数
_MAX_AUTO_DEPTH = 3      # 连续自动跟进(读取/选择回传)的深度上限,防打转


def _hitl_confirm(prompt: str) -> bool:
    """真 fail-closed 的人工确认:非 TTY / EOF / Ctrl+C 一律 False。

    (评审修复:loop._ask_yn 捕获 EOFError 后返回 default=True——管道/脚本模式下
    确认会**静默放行**,与「非 TTY 不批准/不覆盖」的承诺相反。此包装先查 isatty,
    再把包括 KeyboardInterrupt 在内的一切异常都判为拒绝。)
    """
    import sys as _sys
    if not (_sys.stdin.isatty() and _sys.stdout.isatty()):
        return False
    from psyclaw.loop import _ask_yn
    try:
        return _ask_yn(prompt)
    except BaseException:  # noqa: BLE001  # KeyboardInterrupt 也算拒绝
        return False


# 敏感文件denylist:自动读取(read 块/agent read_file)绝不碰密钥类文件(铁律「不碰密钥」)。
_SECRET_NAMES = {".env", ".netrc", "credentials", "credentials.json", "id_rsa",
                 "id_ed25519", "id_ecdsa", "id_dsa"}
_SECRET_SUFFIXES = {".pem", ".key", ".ppk", ".pfx", ".p12"}


def read_denied(p: Path) -> str | None:
    """自动读取守卫:返回拒绝原因;可读返回 None。data/raw + 密钥类文件恒拒。"""
    if _save_is_protected(p):
        return "受保护的 data/raw,原始数据不入对话"
    name = p.name.lower()
    if (name in _SECRET_NAMES or p.suffix.lower() in _SECRET_SUFFIXES
            or "secret" in name or "credential" in name):
        return "疑似密钥/凭据文件,不注入对话(铁律:不碰密钥)"
    return None


def parse_read_requests(reply: str) -> list[str]:
    """从模型回复解析 ```read 块 → 路径列表(去重保序)。纯函数,可单测。"""
    paths: list[str] = []
    for m in _READ_RE.finditer(reply or ""):
        for line in m.group("body").splitlines():
            p = line.strip().strip("\"'` ")
            if p and p not in paths:
                paths.append(p)
    return paths


def gather_read_results(paths: list[str], limit: int = _MAX_AUTO_READS) -> tuple[str, list[str]]:
    """读取模型请求的文件 → (回传消息, 终端提示行)。data/raw 拒读;缺失/超限如实说明。"""
    from psyclaw.context import smart_excerpt
    parts: list[str] = []
    notes: list[str] = []
    for raw in paths[:limit]:
        p = Path(raw).expanduser()
        denial = read_denied(p)
        if denial:
            parts.append(f"[拒绝读取 {p}:{denial}]")
            notes.append(f"  ✗ 拒读:{p.name}({denial[:18]}…)")
            continue
        if not p.is_file():
            parts.append(f"[文件不存在:{p}]")
            notes.append(f"  · 未找到:{p}")
            continue
        excerpt = smart_excerpt(p)
        parts.append(excerpt)
        notes.append(f"  ✓ 已自动读取 {p.name}({len(excerpt)} 字符注入)")
    if len(paths) > limit:
        parts.append(f"[本轮最多自动读 {limit} 个文件,其余 {len(paths) - limit} 个请下一轮再请求]")
    return ("# 自动读取结果\n\n" + "\n\n".join(parts)) if parts else "", notes


def parse_save_blocks(reply: str) -> list[dict]:
    """从模型回复解析 ```save path=… 块 → [{path, content}]。纯函数,可单测。

    逐行扫描并**计数内部代码围栏**:保存的内容常含 ```python 等嵌套块,若用非贪婪正则,
    内容会在第一个 ``` 处被截断且仍报「已保存」——静默丢数据(评审修复)。规则:
    行首 ``` 开头的行在 save 块内视为围栏开/合切换;只有**不在内部围栏里**的裸 ``` 行才收尾。
    """
    out: list[dict] = []
    lines = (reply or "").splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = _SAVE_OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        path = m.group("path").strip().strip("\"'` ")
        body: list[str] = []
        inner_fence = False
        i += 1
        while i < n:
            ln = lines[i]
            if _FENCE_RE.match(ln):
                if ln.strip() == "```" and not inner_fence:
                    break                       # 真正的收尾围栏
                inner_fence = not inner_fence   # 嵌套围栏开/合
            body.append(ln)
            i += 1
        if path:
            out.append({"path": path, "content": "\n".join(body)})
        i += 1
    return out


def _save_is_protected(p: Path) -> bool:
    """目标是否落在受保护的 data/raw 下(绝不写,守铁律)。"""
    parts = [x.lower() for x in p.parts]
    return "raw" in parts and "data" in parts


def apply_save_block(blk: dict, confirm=None) -> dict:
    """写一个 save 块。护栏:拒 data/raw;文件已存在需 confirm(path)→True 才覆盖。

    返回 {status, path, ...}。status ∈ {saved, refused-raw, skipped-exists, error}。
    confirm 缺省(None)视为**不覆盖**(fail-safe:非交互不静默 clobber)。
    """
    p = Path(blk["path"]).expanduser()
    if _save_is_protected(p):
        return {"status": "refused-raw", "path": str(p)}
    if p.exists():
        if not (confirm and confirm(p)):
            return {"status": "skipped-exists", "path": str(p)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(blk["content"], encoding="utf-8")
        return {"status": "saved", "path": str(p), "chars": len(blk["content"])}
    except OSError as exc:
        return {"status": "error", "path": str(p), "error": str(exc)}


def _build_system_prompt() -> str:
    """瘦核心系统提示(长上下文优化:知识库改为按消息动态注入)。"""
    from psyclaw.context import lean_core
    parts = [lean_core()]
    parts.append(
        "\n# 强制澄清规则\n任何研究开工前必须完成澄清卡(17 槽位,/clarify)。"
        "用户提出研究想法时,你的第一动作是 grill-me 式逐项澄清(一次一个问题,"
        "带推荐答案),而不是直接给方案。设计决策必须给文献背书(/cite 查背书库)。")
    parts.append(_SAVE_SYSTEM)
    from psyclaw.memory import memory_prompt
    mem = memory_prompt()
    if mem:
        parts.append("\n" + mem)
    return "\n".join(parts)


class ReplSession:
    def __init__(self, resume_id: str | None = None) -> None:
        self.conf = cfg.load_config()
        self.provider = get_provider(self.conf)
        self.system = _build_system_prompt()
        self.messages: list[dict] = []
        self.memo = ""              # 滚动压缩的决策备忘
        self.plan_mode = False      # 规划模式:只规划不执行,产出自动抽任务
        self.audit_mode = False     # 逐轮审计(auditor agent,每轮多一次调用)
        self.agent_mode = False     # agent 模式:模型自主多步调用工具(纯工具层循环)
        # 文件读取权限:open(默认,模型 ```read 块自动读)| safe(一切读取须用户 @ 引用)
        self.file_access = str(self.conf.get("file_access", "open")).lower()
        self.session_name: str | None = None   # /rename 后的会话名(提示符可见)
        self._auto_depth = 0        # 自动跟进(读取/选择回传)深度,防打转
        from datetime import datetime
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        from psyclaw.recall import ContextArchive
        self.archive = ContextArchive(".")   # 全量上下文库(SQLite,懒建)
        self.resume_id = resume_id           # 启动时续接的会话(feat-013)
        self.chars_in = 0
        self.chars_out = 0
        try:                                 # 插件(用户项目/全局;坏插件不拖垮 REPL)
            from psyclaw.plugins import load_plugins
            self.plugins = load_plugins(".")
        except Exception:  # noqa: BLE001
            self.plugins = None

    # -- 会话续接(feat-013)-------------------------------------------------
    def _resume_session(self, sid: str) -> bool:
        """把某历史会话的轮次载回 messages,后续对话续写到同一会话。"""
        try:
            turns = self.archive.session_turns(sid)
        except Exception:  # noqa: BLE001  # 库异常不阻塞 REPL
            turns = []
        if not turns:
            print(ui.warn(f"  未找到会话 {sid};当前对话保持不变。"))
            return False
        # 验证通过才动当前状态(评审修复:先清空再验证会把在聊的对话/备忘毁掉)
        self.messages.clear()
        self.memo = ""
        self.session_id = sid
        try:                                  # 会话名带回提示符
            self.session_name = next(
                (s["name"] for s in self.archive.list_sessions(200)
                 if s["id"] == sid and s["name"] != sid), None)
        except Exception:  # noqa: BLE001
            self.session_name = None
        for t in turns:
            self.messages.append({"role": "user", "content": t["user_text"]})
            self.messages.append({"role": "assistant", "content": t["reply_text"]})
        from psyclaw.context import compact_history
        self.messages, self.memo = compact_history(self.messages, self.memo)
        print(ui.ok(f"  ⟳ 续接会话 {sid}(载入 {len(turns)} 轮,新对话续写到此会话)"))
        return True

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
    def ask(self, text: str, internal: bool = False) -> None:
        from psyclaw.context import compact_history, relevant_knowledge, render_memo
        if not internal:
            # 路径自动检测:只对**用户输入**做——自动回传消息(读取结果/命令输出)里的
            # 碎片会被误当路径,打出「未找到文件 乱码」噪音(用户实测修复)。
            from psyclaw.path_ingest import process_message
            path_ctx, path_errors = process_message(text)
            for err in path_errors:
                print(err)
            text = self._expand_files(text)
            # 若有路径注入内容,拼在用户消息前(LLM 可据此解读数据结构)
            if path_ctx:
                text = path_ctx + "\n\n用户问题：" + text
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
        # 本地项目感知:每轮注入有界目录结构(模型看得见文件夹;失败不阻塞)
        try:
            from psyclaw.project_sense import project_brief
            brief = project_brief(".")
            if brief:
                system += "\n\n" + brief
        except Exception:  # noqa: BLE001
            pass
        if self.plan_mode:
            from psyclaw.tasks import PLAN_MODE_SYSTEM
            system += "\n\n" + PLAN_MODE_SYSTEM
        # 键盘选择器约定 + 文件读取权限(随 /safemode 动态切换)+ 直接跑命令
        system += "\n" + _CHOICES_SYSTEM
        system += "\n" + (_READ_SAFE_SYSTEM if self.file_access == "safe"
                          else _READ_OPEN_SYSTEM)
        system += "\n" + _RUN_SYSTEM + ("" if self.file_access != "safe"
                                        else "\n" + _RUN_SAFE_NOTE)
        if self.plugins and self.plugins.systems:
            system += "\n\n" + "\n\n".join(self.plugins.systems)
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
        if self.agent_mode:
            reply = self._run_agent(system)
            if reply is None:            # provider 错误 → 回退用户消息
                self.messages.pop()
                return
        else:
            blk = ui.StreamBlock(f"PsyClaw · {self.provider.name}")
            reply_parts: list[str] = []
            try:
                for chunk in self.provider.chat(self.messages, system=system):
                    blk.write(chunk)
                    reply_parts.append(chunk)
            except KeyboardInterrupt:          # Ctrl+C = 取消本轮,不炸 REPL(评审修复)
                blk.write("\n[已中断本轮生成]")
                blk.close()
                self.messages.pop()
                return
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
        self._capture_saves(reply)   # 「天然」落盘:扫描 ```save 块并写文件(带护栏)
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
        # 自动跟进:模型请求读文件(开放模式自动读)/ 给出选项(弹键盘选择器)→ 回传续聊
        follow = self._auto_followup(reply)
        if follow:
            self._auto_depth += 1
            try:
                self.ask(follow, internal=True)
            finally:
                self._auto_depth -= 1

    def _auto_followup(self, reply: str) -> str | None:
        """命令执行 / 读取请求 / 选项选择 → 需要自动回传给模型的消息(无则 None)。

        统一在 **去掉 save 块之后** 的正文上解析——save 的内容是要写盘的文件,
        里面的示例命令/read/复选清单绝不能被当成本轮要执行的请求。
        """
        body = strip_save_blocks(reply)

        # ① 命令块(psyclaw/shell):执行并回传输出——命令块吐了没人跑=死胡同(用户实测)
        runs = parse_run_requests(body)
        if runs:
            if self.file_access == "safe":
                print(ui.warn(f"  [安全模式] 模型给出 {len(runs)} 条命令,未自动执行;"
                              "请手动复制运行,或 /safemode off 放开。"))
            elif self._auto_depth >= _MAX_AUTO_DEPTH:
                print(ui.dim("  (自动跟进已达深度上限,请手动继续)"))
            else:
                def _confirm_cmd(c: str) -> bool:
                    label = ("⚠ 危险命令" if _DANGEROUS_RE.search(c)
                             else "shell 命令")
                    return _hitl_confirm(f"  {label},确认执行 {c}?")
                msg, notes = run_commands(runs, confirm=_confirm_cmd)
                for n in notes:
                    print(ui.warn(n) if n.startswith("  ✗") else ui.dim(n))
                if msg:
                    return msg

        reads = parse_read_requests(body)
        if reads:
            if self.file_access == "safe":
                print(ui.warn(f"  [安全模式] 模型请求读取 {len(reads)} 个文件已被拒;"
                              "用 @<路径> 显式引用,或 /safemode off 放开。"))
            elif self._auto_depth >= _MAX_AUTO_DEPTH:
                print(ui.dim("  (自动读取跟进已达深度上限,请手动继续)"))
            else:
                msg, notes = gather_read_results(reads)
                for n in notes:
                    print(ui.dim(n) if n.startswith("  ·") else n)
                if msg:
                    return msg
        try:
            from psyclaw.choices import (format_selection_message, parse_choices,
                                         pick_interactive)
            # 规划模式的 ## TASKS 就是 - [ ] 清单——那是任务看板,不是给用户选的选项;
            # 只认显式 choices 块,复选启发式关闭(评审修复:否则每条计划回复都弹选择器)。
            choice = parse_choices(body, heuristic=not self.plan_mode)
        except Exception:  # noqa: BLE001
            choice = None
        if choice and self._auto_depth < _MAX_AUTO_DEPTH:
            chosen = pick_interactive(choice)
            if chosen:
                print(ui.ok("  → 已选:" + "、".join(c[:40] for c in chosen)))
                return format_selection_message(chosen, choice["question"])
            print(ui.dim("  (未选择;可直接输入你的回复)"))
        return None

    def _run_agent(self, system: str) -> str | None:
        """agent 模式:跑纯工具层循环(模型自主多步调工具)。返回最终答案;provider 错误返回 None。"""
        from psyclaw.toolloop import _short, run_tool_loop

        def _approve(call: dict) -> bool:
            # 真 fail-closed(非 TTY/EOF/中断不批准)+ 参数截断(save_file 的 content
            # 可能几十 KB,不能整个灌进确认提示)
            return _hitl_confirm(f"  批准副作用工具 {call['name']}"
                                 f"({_short(call.get('args') or {}, 120)})?")

        try:
            res = run_tool_loop(
                self.provider, system, self.messages, project_dir=".",
                approve=_approve, emit=lambda e: print(ui.dim(f"  ⚙ {e}")))
        except Exception as exc:  # noqa: BLE001
            print(ui.err(f"  [provider 错误] {exc}"))
            return None
        if res["trace"]:
            print(ui.dim(f"  [agent:{res['iters']} 轮 · {len(res['trace'])} 次工具调用 · "
                         f"{res['stopped']}]"))
        from psyclaw.toolloop import log_agent_run
        task_head = next((m["content"] for m in reversed(self.messages)
                          if m.get("role") == "user"), "")
        log_agent_run(".", task_head, res)   # feat-037:落运行痕迹(失败静默)
        blk = ui.StreamBlock(f"PsyClaw · {self.provider.name}")
        blk.write(res["final"])
        blk.close()
        print()
        return res["final"]

    def _capture_saves(self, reply: str) -> None:
        """扫描回复里的 ```save 块并写盘(护栏:拒 data/raw、覆盖前交互确认)。"""
        blocks = parse_save_blocks(reply)
        if not blocks:
            return

        def _confirm(p: Path) -> bool:
            # 真 fail-closed:非 TTY/EOF/中断一律不覆盖(评审修复:_ask_yn EOF 返 True)
            return _hitl_confirm(f"  文件已存在,覆盖 {p}?")

        for blk in blocks:
            r = apply_save_block(blk, confirm=_confirm)
            st = r["status"]
            if st == "saved":
                print(ui.ok(f"  ✓ 已保存 {r['path']}({r['chars']} 字符)"))
            elif st == "refused-raw":
                print(ui.err(f"  ✗ 拒绝写入受保护的 data/raw:{r['path']}"))
            elif st == "skipped-exists":
                print(ui.dim(f"  已跳过(未覆盖):{r['path']}"))
            else:
                print(ui.err(f"  ✗ 写入失败 {r['path']}:{r.get('error')}"))

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
        elif cmd == "/clarify":
            from psyclaw.psych.clarify import print_clarify_status, run_clarify_interactive
            if arg == "status":
                print_clarify_status()
            else:
                run_clarify_interactive()
                self.system = _build_system_prompt()  # 重载(惯性可能已更新)
        elif cmd in ("/preregister", "/prereg"):
            from psyclaw.psych.preregister import preregister_cli
            preregister_cli(arg.split() if arg else [])
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
        elif cmd == "/safemode":
            low = arg.lower()
            if low in ("on", "safe"):
                self.file_access = "safe"
            elif low in ("off", "open"):
                self.file_access = "open"
            else:
                self.file_access = "open" if self.file_access == "safe" else "safe"
            if self.file_access == "safe":
                print(ui.warn("  [安全模式 开] 一切文件读取须用 @<路径> 显式引用。"))
            else:
                print(ui.ok("  [开放模式] 模型可请求读取本地文件(```read 块自动读;"
                            "data/raw 恒受保护)。"))
        elif cmd == "/agent":
            low = arg.lower()
            self.agent_mode = (low == "on") if low in ("on", "off") \
                else not self.agent_mode
            if self.agent_mode:
                from psyclaw.toolloop import build_tools
                names = ", ".join(build_tools(".").keys())
                print(ui.ok("  [agent 模式 开] 模型可自主多步调用工具:") + ui.dim(names))
                print(ui.dim("    副作用工具(save_file)每次执行前问你批准;/agent off 退出。"))
            else:
                print("  [agent 模式 关] 恢复普通对话。")
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
        elif cmd == "/lit":
            from psyclaw.psych.lit_cli import lit_cli_argv
            lit_cli_argv(arg.split() if arg else [])
        elif cmd == "/sessions":
            self._cmd_sessions()
        elif cmd == "/resume":
            self._cmd_resume(arg)
        elif cmd == "/rename":
            self._cmd_rename(arg)
        elif cmd == "/search":
            self._cmd_search(arg)
        elif cmd == "/plugins":
            self._cmd_plugins()
        elif self.plugins and cmd in self.plugins.commands:
            try:                                  # 插件命令:异常不拖垮 REPL
                self.plugins.commands[cmd]["handler"](arg)
            except Exception as exc:  # noqa: BLE001
                print(ui.err(f"  [插件命令 {cmd} 出错] {exc}"))
        else:
            print(f"  未知命令 {cmd},输入 /help 查看可用命令")
        return True

    def _cmd_plugins(self) -> None:
        from psyclaw.plugins import SCOPE_LABEL
        if not self.plugins or not (self.plugins.loaded or self.plugins.errors):
            print(ui.dim("  未加载插件。放 <项目>/.psyclaw/plugins/*.py 或 "
                         "~/.psyclaw/plugins/*.py(含 register(api))即生效。"))
            return
        print(ui.accent(f"  插件({len(self.plugins.loaded)}):"))
        for p in self.plugins.loaded:
            print(f"    - {p['name']:<20} [{SCOPE_LABEL.get(p['scope'], p['scope'])}]")
        if self.plugins.commands:
            print(ui.dim("    命令:" + " ".join(self.plugins.commands)))
        if self.plugins.tools:
            print(ui.dim("    工具:" + " ".join(self.plugins.tools) + "(agent 模式可用)"))
        for e in self.plugins.errors:
            print(ui.warn(f"    ⚠ {e}"))

    # -- 会话管理 slash 命令(feat-013)------------------------------------
    def _cmd_sessions(self) -> None:
        rows = self.archive.list_sessions()
        if not rows:
            print("  (无历史会话)")
            return
        print(ui.accent("  历史会话(最近在前):"))
        for s in rows:
            cur = ui.ok("  ← 当前") if s["id"] == self.session_id else ""
            print(f"    {s['id']:<17} {s['n_turns']:>3} 轮  {s['name']}{cur}")
        print(ui.dim("  /resume <id> 续接 · /rename <新名> 命名当前 · /search <词> 全文检索"))

    def _cmd_resume(self, arg: str) -> None:
        sid = arg.strip()
        if not sid:
            print("  用法:/resume <会话id>(/sessions 看列表)")
            return
        self._resume_session(sid)   # 内部先验证会话存在,再清空并载入(误输 id 不毁现场)

    def _cmd_rename(self, arg: str) -> None:
        name = arg.strip()
        if not name:
            print("  用法:/rename <新名称>(重命名当前会话)")
            return
        self.archive.rename_session(self.session_id, name)
        self.session_name = name          # 提示符立即可见(用户实测:改了名要看得出来)
        print(ui.ok(f"  ✓ 当前会话已命名:{name}(已显示在提示符)"))

    def _cmd_search(self, arg: str) -> None:
        q = arg.strip()
        if not q:
            print("  用法:/search <关键词>(跨会话全文检索)")
            return
        hits = self.archive.search(q, limit=8)
        if not hits:
            print(f"  未检索到含「{q}」的历史轮次。")
            return
        print(ui.accent(f"  检索到 {len(hits)} 条:"))
        for h in hits:
            snippet = h["user_text"][:60].replace("\n", " ")
            print(f"    [{h['session']}] {snippet}")

    # -- 主循环 --------------------------------------------------------------
    def run(self) -> int:
        if self.resume_id:
            self._resume_session(self.resume_id)
        try:
            from psyclaw.status import collect_status
            status = collect_status(".")
        except Exception:  # noqa: BLE001
            status = None
        print(ui.startup(__version__, status=status, provider=self.provider.describe()))
        print("  " + ui.dim("输入 / 弹出命令联想(↑↓选择 Tab补全) · /exit 退出 · @<文件> 引用") + "\n")
        while True:
            base = ui.paint("psyclaw", "brcyan", "bold")
            if self.session_name:
                base += ui.dim(f"·{self.session_name[:12]}")
            modes = ("" if not self.plan_mode else ui.warn(" plan")) \
                + ("" if not self.agent_mode else ui.accent(" agent")) \
                + ("" if self.file_access != "safe" else ui.warn(" safe"))
            prompt = base + modes + ui.dim(" ❯ ")
            cmds = dict(COMMANDS)
            if self.plugins:
                cmds.update({k: v["desc"] for k, v in self.plugins.commands.items()})
            try:
                line = read_line(prompt, cmds).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            try:
                if line.startswith("/"):
                    if not self.handle_command(line):
                        break
                else:
                    self.ask(line)
            except KeyboardInterrupt:      # 深处的 Ctrl+C 也只取消本轮(评审修复)
                print(ui.dim("\n  (已中断本轮;继续对话或 /exit 退出)"))
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
  /agent      agent 模式(模型自主多步调工具:search/read_file/save_file/kg_query/recall)
  /safemode   文件读取权限(safe=一切读取须 @ 引用;默认 open=模型可请求自动读取)
  /model [m]  查看/切换模型      /provider [p]  查看/切换 provider
  /skills     列出 skills        /mcp           MCP 目录与启用状态
  /gates      门禁自检           /cost          本会话成本粗估
  /scale [s]  量表库查询(如 /scale dass-42)
  /assume [t] 前提假设知识库(如 /assume anova-rm)
  /method [m] 复杂方法目录(如 /method clpm)
  /design [d] 实验设计目录(如 /design esm-diary)
  /clarify    研究澄清(grill-me 式;不澄清完 /research 不放行)
  /preregister 预注册模板(OSF/AsPredicted;据澄清卡抽取)
  /cite [t]   方法学背书库(每个设计决策的文献支撑)
  /export f   APA7 输出(Word + Markdown,确定性模板)
  /review f   审稿模拟(EIC+3审稿人+DA;--revise 闭合写作→评审→修复)
  /memory     三层记忆(画像/决策惯性/教训卡)
  /sessions   历史会话列表       /resume <id>   续接历史会话
  /rename <名> 命名当前会话       /search <词>   跨会话全文检索
  /clear      清空上下文         /compact       压缩上下文
  /config     配置向导           /exit          退出
  /research [t]    一句话研究编排:文献→设计→写作→评审→总验收(--revise 闭环)
  /research-loop   通用 HITL 回路(planner→executor→critic→修复→交付)
  /lit [q] [-s]    文献检索(合法 OA;-s 据真实命中一键合成结构化综述)"""


def run_repl(resume_id: str | None = None) -> int:
    return ReplSession(resume_id=resume_id).run()
