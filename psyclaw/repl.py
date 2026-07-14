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
import shutil
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
_MAX_GOAL_CONTEXT_CHARS = 8_000
_MAX_EMPTY_REPLY_RETRIES = 2
_EMPTY_REPLY_NUDGE = (
    "上一轮模型回复为空,但前一条工具或命令结果仍待处理。请直接检查上一条结果:"
    "若失败,说明原因并修正后继续;若成功,解释结果并推进剩余任务。不要等待用户再说『继续』。"
)
PROMPT = ui.paint("psyclaw", "brcyan", "bold") + ui.dim(" ❯ ")

# slash 命令注册表(联想弹出用:命令 → 一句话描述)
COMMANDS = {
    "/help": "命令总览",
    "/goal": "查看研究目标;带文本时写入 notes/goal.md 并立即开始执行",
    "/run": "运行明确流程:analysis|meta|literature|qualitative",
    "/auto": "按项目状态自主推进;强制检查和不可逆决策仍会暂停",
    "/approval": "审批策略:ask(默认)|auto;危险操作始终确认",
    "/access": "文件访问策略:open(默认)|safe",
    "/tasks": "任务看板(自动从计划抽取;start/done/add/sync)",
    "/recall": "手动召回历史上下文(/recall <查询>;库状态留空查看)",
    "/plugins": "已加载插件(用户 项目/全局;可注册工具/命令/system 片段)",
    "/prepare": "完成研究准备清单(17 个研究准备项)",
    "/preregister": "预注册模板(OSF/AsPredicted 双格式;据研究准备清单抽取)",
    "/scale": "量表库(DASS/PHQ-9/GAD-7/TIPI…)",
    "/assume": "前提假设知识库(16 检验族)",
    "/method": "复杂方法目录(SEM/MLM/LPA/网络…)",
    "/design": "实验设计目录(12 设计卡)",
    "/cite": "方法学背书库(决策→文献)",
    "/export": "APA7 输出(Word docx + Markdown)",
    "/memory": "三层记忆(画像/惯性/教训卡);/memory verify 再验证环境教训、已恢复的自动失效",
    "/gates": "研究质量检查",
    "/skills": "已注册 skills",
    "/mcp": "MCP 目录与启用状态",
    "/model": "查看/切换模型",
    "/provider": "查看/切换 provider",
    "/cost": "本会话成本粗估",
    "/clear": "清空上下文",
    "/compact": "压缩上下文",
    "/config": "配置向导",
    "/review": "审稿模拟(EIC+3审稿人+DA;--revise 回灌修复环)",
    "/lit": "文献检索(M2+)",
    "/sessions": "列出历史会话(跨会话持久化)",
    "/resume": "续接历史会话(/resume <id>)",
    "/rename": "给当前会话改名(/rename <新名>)",
    "/search": "全文检索历史对话(/search <词>)",
    "/dump": "导出当前对话为 Markdown(--full 连同不展示的隐藏上下文一并导出)",
    "/img": "在终端内联渲染图片(/img <路径>;iTerm2/WezTerm/VSCode/Warp/kitty;命令出图会自动显示)",
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
    "```\nPsyClaw 会弹出键盘选择器并把用户的选择自动回传给你;不要只写复选清单等用户打字。"
    "**先在正文把各方案的内容/取舍写清楚**,选项文字要自包含且简短(一行说清是什么),"
    "不要写「方案A」这种脱离正文就看不懂的标签。")

# 「直接跑命令」:模型输出 psyclaw/shell 块,REPL 执行并把输出自动回传(用户实测:
# 命令块没人执行,回合看着像结束了——死胡同必须消灭)。psyclaw 子命令进程内跑;
# shell 交系统终端跑。危险命令(rm -rf / git push --force / DROP TABLE…)须人工确认。
_RUN_SYSTEM = (
    "\n# 直接运行命令(会真的执行)\n要跑 PsyClaw 子命令或系统命令时,输出块(每行一条),"
    "PsyClaw 会执行并把输出回传给你,你据此继续:\n"
    "```psyclaw\nrun analysis data/clean/x.csv\n```\n"
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


_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
_CONTINUATION_ENDS = ("\\", "&&", "||", "|")


def _quotes_balanced(s: str) -> bool:
    """简易 shell 引号状态机:单/双引号是否全部闭合(双引号内 \\ 转义生效)。"""
    in_s = in_d = esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\" and not in_s:      # 单引号内反斜杠是字面量
            esc = True
            continue
        if in_s:
            in_s = ch != "'"
        elif in_d:
            in_d = ch != '"'
        elif ch == "'":
            in_s = True
        elif ch == '"':
            in_d = True
    return not (in_s or in_d)


def group_shell_commands(body: str) -> list[str]:
    """把 shell 块正文分组成**完整命令**(feat-101)。纯函数。

    第三轮评估实测:模型发多行 `python3 -c "…"`,旧实现逐行拆成 5 条"命令"
    分别审批/执行(`import pandas as pd` 单独一条、结尾 `\"` 也算一条),
    逐行执行必然全废。延续条件:引号未闭合 / 行尾 \\ && || | / heredoc 未终结。
    局限:引号**内**的 `<< WORD` 字面量会被误判为 heredoc(罕见,宁并不拆)。
    """
    cmds: list[str] = []
    cur: list[str] = []
    heredoc: str | None = None
    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if heredoc is not None:
            cur.append(raw)
            if line.strip() == heredoc:
                heredoc = None
                cmds.append("\n".join(cur).strip())
                cur = []
            continue
        if not cur and (not line.strip() or line.strip().startswith("#")):
            continue
        cur.append(raw)
        joined = "\n".join(cur)
        if not _quotes_balanced(joined):
            continue
        if line.endswith(_CONTINUATION_ENDS):
            continue
        hm = _HEREDOC_RE.search(joined)
        if hm:
            heredoc = hm.group(1)
            continue
        cmds.append(joined.strip())
        cur = []
    if cur:                    # 引号/heredoc 未闭合的残尾也如实交出,不静默丢
        cmds.append("\n".join(cur).strip())
    return cmds


def cmd_display(cmd: str) -> str:
    """多行命令的单行显示形态:首行 + (+N 行)。纯函数(feat-101)。"""
    lines = (cmd or "").splitlines() or [""]
    if len(lines) == 1:
        return lines[0]
    return f"{lines[0]}  (+{len(lines) - 1} 行)"


def parse_run_requests(reply: str) -> list[dict]:
    """从回复解析 psyclaw/shell 命令块 → [{kind, cmd}](kind ∈ psyclaw|shell)。纯函数。

    shell 块按 `group_shell_commands` 分组(多行引号/续行/heredoc 是一条命令,
    feat-101);psyclaw 子命令天然单行,保持逐行。
    """
    out: list[dict] = []
    for m in _RUN_RE.finditer(reply or ""):
        kind = "psyclaw" if m.group("kind") == "psyclaw" else "shell"
        if kind == "shell":
            for cmd in group_shell_commands(m.group("body")):
                out.append({"kind": kind, "cmd": cmd})
            continue
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
    # feat-127:启用沙箱时,执行前过代码执行面裁决(恶意硬拒,快速失败)
    timeout = _RUN_TIMEOUT
    try:
        from psyclaw import sandbox as _sb
        pol = _sb.load_policy(".")
        if pol.get("enabled"):
            v = _sb.sandbox_check("exec", "run", {"cmd": cmd}, project_dir=".")
            if not v["allow"]:
                return f"$ {cmd}\n[沙箱拒绝执行:{v['reason']}]"
            timeout = _sb.exec_limits(pol)["timeout_s"]
    except Exception:  # noqa: BLE001  # 沙箱异常不阻断(既有 _DANGEROUS_RE 仍兜底)
        pass
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=timeout)
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
        shown = cmd_display(cmd)               # feat-101:多行命令单行化显示
        if r["kind"] != "psyclaw" or danger:
            if not (confirm and confirm(cmd)):
                tag = "危险命令" if danger else "shell 命令"
                parts.append(f"$ {cmd}\n[已拒绝:{tag}未获人工确认]")
                notes.append(f"  ✗ 拒执行({tag}):{shown[:50]}")
                continue
        notes.append(f"  ⚙ 执行:{shown[:70]}")
        out = _run_psyclaw_cmd(cmd) if r["kind"] == "psyclaw" else _run_shell_cmd(cmd)
        parts.append(out[:6000])
    if len(reqs) > limit:
        parts.append(f"[本轮最多执行 {limit} 条命令,其余 {len(reqs) - limit} 条请下一轮]")
    return ("# 命令执行结果\n\n" + "\n\n".join(parts)) if parts else "", notes


# ---------------------------------------------------------------------------
# 错误学习:从命令输出蒸馏「可复用的环境教训」(纯函数,可单测)。
# 只认高信号、可泛化的失败——命令不存在 / 模块未装 / 属性(版本改名):正是用户实测里
# 反复重踩的坑(python→python3、系统 Python 无 mne、mne.datasets.erpcore→erp_core)。
# 蒸馏出的教训进「本会话记忆」(每轮注入,当场止损)+ 落 memory 待确认卡(跨会话复用)。
# ---------------------------------------------------------------------------
_CMD_NOTFOUND_RES = [
    re.compile(r"command not found:\s*(?P<c>[\w.\-]+)", re.I),        # zsh
    re.compile(r"(?P<c>[\w.\-]+):\s*command not found", re.I),        # bash
    re.compile(r"(?P<c>[\w.\-]+):\s*not found", re.I),               # sh/dash
    re.compile(r"[‘'\"](?P<c>[\w.\-]+)[’'\"]\s*不是内部或外部命令"),   # windows cmd
    re.compile(r"未找到命令[::]\s*(?P<c>[\w.\-]+)"),
]
_MODULE_NOTFOUND_RE = re.compile(r"No module named ['\"]?(?P<m>[\w.]+)['\"]?", re.I)
_ATTR_ERR_RE = re.compile(
    r"module ['\"](?P<mod>[\w.]+)['\"] has no attribute ['\"](?P<attr>[\w.]+)['\"]")
_CMD_ALT = {"python": "python3", "pip": "pip3", "py": "python3"}
# shell 名会被「X: command not found」误当成缺失命令(zsh 格式 `zsh: command not found: python`
# 里 zsh 只是报错前缀,不是缺的命令)——一律排除。
_SHELL_NAMES = {"bash", "zsh", "sh", "dash", "fish", "ksh", "csh", "tcsh",
                "cmd", "powershell", "pwsh", "not", "command"}


def distill_env_lessons(output: str) -> list[dict]:
    """从命令输出蒸馏环境教训 → [{trigger, lesson}](去重保序)。纯函数。"""
    out: list[dict] = []
    seen: set = set()
    text = output or ""

    def add(trigger: str, lesson: str, kind: str) -> None:
        key = (trigger, lesson)
        if key not in seen:
            seen.add(key)
            out.append({"trigger": trigger, "lesson": lesson, "kind": kind})

    for rx in _CMD_NOTFOUND_RES:
        for m in rx.finditer(text):
            c = m.group("c")
            if not c or c in _SHELL_NAMES or c.isdigit():   # shell 前缀/行号等误匹配保护
                continue
            alt = _CMD_ALT.get(c)
            hint = f",改用 `{alt}`" if alt else ",换等价命令,或先确认它已安装且在 PATH"
            add(c, f"本机没有 `{c}` 命令{hint};下次别再直接调 `{c}`", "cmd")
    for m in _MODULE_NOTFOUND_RE.finditer(text):
        mod = m.group("m").split(".")[0]
        add(mod, f"当前 Python 未安装模块 `{mod}`;需要时先 `pip3 install --user {mod}`,"
                 f"或改用装有它的解释器/环境,别默认能 import", "module")
    for m in _ATTR_ERR_RE.finditer(text):
        mod, attr = m.group("mod"), m.group("attr")
        add(f"{mod}.{attr}", f"`{mod}` 在本机版本里没有 `{attr}`(可能已改名/移除);"
                             f"调用前先查该版本实际可用的 API,别照旧写", "attr")
    return out


def probe_env_card_stale(card: dict) -> bool | None:
    """再验证一张环境教训卡:它说的『不可用』现在是否已可用(→ 该归档)。

    返回 True=卡已过时(该失效归档)/ False=仍成立(环境依旧缺)/ None=无法判定(跳过)。
    - cmd:  shutil.which(命令) 是否找得到——**秒回、无子进程、注入安全**,startup 也能用。
    - module/attr: 用 python3(退 python)真跑 `import`/取属性,退出码 0 即已恢复——
      子进程 list 参数(非 shell)、触发词经 [\\w.] 校验,注入安全;导入较慢,仅 /memory verify 用。
    只处理带 kind 的卡(本版之后蒸馏的);无 kind 的老卡返回 None 不动它。
    """
    kind = card.get("kind")
    trig = str(card.get("trigger", ""))
    if kind == "cmd":
        if not re.fullmatch(r"[\w.\-]+", trig):
            return None
        return shutil.which(trig) is not None
    if kind in ("module", "attr"):
        interp = shutil.which("python3") or shutil.which("python")
        if not interp:
            return None
        if kind == "module":
            if not re.fullmatch(r"[\w.]+", trig):
                return None
            code = f"import {trig}"
        else:
            if "." not in trig or not re.fullmatch(r"[\w.]+", trig):
                return None
            mod, _, attr = trig.rpartition(".")
            code = f"import {mod}; getattr({mod}, {attr!r})"
        import subprocess
        try:
            rc = subprocess.run([interp, "-c", code], capture_output=True,
                                timeout=8).returncode
        except (OSError, subprocess.TimeoutExpired):
            return None
        return rc == 0
    return None


# 「全部同意」的命令前缀分类(feat-070):这些程序的行为由第一个参数决定
# (git status ≠ git push),范围要带上它;其余程序按程序名归类即可(pytest、ls…)。
_SUBCMD_TOOLS = frozenset({
    "git", "uv", "uvx", "npm", "pnpm", "yarn", "pip", "pip3", "conda", "brew",
    "docker", "kubectl", "cargo", "make", "python", "python3", "py", "node",
    "ruby", "perl", "bash", "sh", "zsh", "Rscript",
})

# feat-081(v0.12 评审修复):包装/提权/延迟执行类程序——真正跑什么由后面的参数
# 决定,任何前缀键都无法圈住行为 → 一律不泛化(范围=整条原文,逐条同意)。
_WRAPPER_TOOLS = frozenset({
    "sudo", "doas", "env", "nohup", "time", "nice", "timeout", "xargs",
    "watch", "uvx", "npx", "bunx", "setsid", "stdbuf", "caffeinate",
})

# 「程序+子命令」仍等于任意代码执行的组合(uv run X 可跑任何脚本)→ 不泛化。
_NO_GENERALIZE_PAIRS = frozenset({
    ("uv", "run"), ("npm", "exec"), ("npm", "x"), ("pnpm", "dlx"),
    ("yarn", "dlx"), ("pip", "download"), ("conda", "run"),
})


def cmd_approval_scope(cmd: str) -> str:
    """把一条 shell 命令归类成「全部同意」的范围键。纯函数,可单测。

    - 一般程序 → 程序名(`pytest -q` → `pytest`):同意 pytest 不放行 rm;
    - 子命令型/解释器型程序 → 程序名+第二个词(`git status`、`python3 analyze.py`):
      同意 `git status` 不放行 `git push`;Windows 的 `git.exe` 剥后缀同样归类
      (feat-081:此前 .exe 绕过子命令区分,status 的同意会放行 push);
    - **不泛化**(范围=整条原文,逐条同意;feat-081 收紧):复合命令(| && ; > 等,
      不再截断 80 字防前缀碰撞)、环境变量前缀(`FOO=1 …` 可改写任意程序行为)、
      包装/提权程序(sudo/env/nohup/uvx/npx…)、解释器直跑代码的 flag 形
      (`python -c/-m`、`bash -c`、`node -e`…——同意一条=放行任意代码,必须逐条)、
      以及 `uv run` 这类「子命令仍是任意执行」的组合;
    - 危险命令另有红线,永远逐条问,不进这里。
    """
    raw = (cmd or "").strip()
    if not raw:
        return "空命令"
    if any(t in raw for t in ("|", "&&", "||", ";", ">", "<", "`", "$(", "&")):
        return raw                           # 复合/后台命令:范围=整条,不泛化
    toks = raw.split()
    if "=" in toks[0]:                       # 环境变量赋值前缀:不泛化
        return raw
    head = toks[0].replace("\\", "/").rsplit("/", 1)[-1]   # 剥路径取程序名
    if head.lower().endswith((".exe", ".bat", ".cmd")):    # Windows 后缀剥掉
        head = head[:-4]
    if head in _WRAPPER_TOOLS:
        return raw
    if head in _SUBCMD_TOOLS and len(toks) > 1:
        sub = toks[1]
        if sub.startswith("-"):              # flag ≠ 子命令(-c/-m/-e 直跑代码)
            return raw
        if (head, sub) in _NO_GENERALIZE_PAIRS:
            return raw
        return f"{head} {sub}"
    return head


def render_image_file(path, force: str | None = None) -> bool:
    """内联渲染**已知**图片文件(feat-086):路径已在手,不做正则再发现。

    @图片 引用此前把已知路径回环进 find_image_paths 的正则重新提取——
    含 '('、')'、'+'、':'(Windows 盘符)的文件名匹配不到,0 张渲染还向
    用户与模型谎报「终端不支持」。直接渲染,不回环。
    """
    from psyclaw import imgview
    if not imgview.supports_inline(force):
        return False
    p = Path(path).expanduser()
    esc = imgview.render_escape(p, force=force)
    if not esc:
        return False
    print(ui.dim(f"  🖼 {p.name}"))
    sys.stdout.write(esc)
    sys.stdout.flush()
    return True


def render_images_in_text(text: str, force: str | None = None, limit: int = 3) -> int:
    """文本里提到的图片文件,若存在且终端支持,内联渲染;返回渲染张数。

    REPL(命令输出/agent 结果)与 `psyclaw agent` CLI 共用(feat-065);
    终端不支持 / 文件不存在 / 超限一律静默跳过,由调用方回退打印路径。
    """
    from psyclaw import imgview
    if not imgview.supports_inline(force):
        return 0
    shown = 0
    for raw in imgview.find_image_paths(text):
        if shown >= limit:
            break
        p = Path(raw).expanduser()
        if not p.is_file():
            continue
        if render_image_file(p, force=force):
            shown += 1
    return shown


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
# 自动跟进(命令/读取)的停机判据 = **no-progress 检测**(下方),不再靠低深度上限。
# 原来 3 步的硬上限会掐断合法多步分析(下载→装依赖→跑→报错→修→重跑,十几步很正常);
# 现改为:连续重复相同的命令/读取请求即判「原地打转」而停(与 toolloop feat-044 一致)。
# 深度上限只留一个**高位安全兜底**(防「每轮都换不同请求、永不收敛」的极端空转烧 token,
# 与 toolloop 仍保留 max_iters 兜底同理),合法任务几乎永远碰不到;可经 config max_auto_depth 调。
_MAX_AUTO_DEPTH = 100
_MAX_FOLLOWUP_REPEAT = 2   # 命令/读取请求连续重复 ≥ 此值即判无进展停(同 toolloop _MAX_NOPROGRESS)


def _followup_signature(runs: list[dict], reads: list[str]):
    """命令+读取请求的规范签名(排序去序)——连续两轮相同即模型在原地打转。纯函数,可单测。

    只签**自动生成**的跟进(命令/读取);choices 由用户逐次交互驱动,不计入 no-progress。
    无任何命令/读取时返回 None(该轮不参与判重)。
    """
    cmds = tuple(sorted((r.get("kind", ""), r.get("cmd", "")) for r in runs))
    rds = tuple(sorted(reads))
    if not cmds and not rds:
        return None
    return (cmds, rds)


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


def _hitl_confirm_all(prompt: str) -> str:
    """三态人工确认:返回 "yes" / "no" / "all"。

    all = 本会话此类不再逐条问(用户实测:「确认一次,同类就统一,别一直问」)。
    fail-closed:非 TTY / EOF / Ctrl+C 一律 "no"。空(回车)沿用原默认=yes。
    提示逐项写明含义(feat-067,用户实测:`[Y/n/a=…]` 缩写看不懂 a 是什么)。
    """
    import sys as _sys
    if not (_sys.stdin.isatty() and _sys.stdout.isatty()):
        return "no"
    from psyclaw.ui_input import safe_prompt
    try:
        v = input(safe_prompt(ui.warn(
            f"{prompt} [回车=同意 / n=拒绝 / a=同意且本会话此类不再问]: "))).strip().lower()
    except BaseException:  # noqa: BLE001
        return "no"
    if v in ("a", "all", "全部", "都", "always", "都同意"):
        return "all"
    if not v or v.startswith("y") or v in ("是", "好", "ok"):
        return "yes"
    return "no"


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


def _is_exit_word(line: str) -> bool:
    """裸退出词:quit / exit(不带斜杠也认,feat-090 用户实测反馈)。纯函数可单测。

    只认整行精确词(小写归一)——「exit code 怎么看」这类正常提问不受影响。
    """
    return (line or "").strip().lower() in ("quit", "exit")


def _build_system_prompt() -> str:
    """瘦核心系统提示(长上下文优化:知识库改为按消息动态注入)。"""
    from psyclaw.context import lean_core
    parts = [lean_core()]
    parts.append(
        "\n# 研究准备规则\n正式研究开始前必须完成研究准备清单(17 个研究准备项,/prepare)。"
        "用户提出研究想法时,你的第一动作是 grill-me 式逐项澄清(一次一个问题,"
        "带推荐答案),而不是直接给方案。设计决策必须给文献背书(/cite 查背书库)。")
    parts.append(_SAVE_SYSTEM)
    from psyclaw.memory import memory_prompt
    mem = memory_prompt(include_lessons=False)   # feat-111:教训改逐消息相关性注入
    if mem:
        parts.append("\n" + mem)
    return "\n".join(parts)


def _goal_context(goal: str) -> str:
    """把持久化目标变成每轮可见的有界上下文,避免用户只说『继续』时丢任务。"""
    text = (goal or "").strip()
    if not text:
        return ""
    if len(text) > _MAX_GOAL_CONTEXT_CHARS:
        text = text[:_MAX_GOAL_CONTEXT_CHARS] + "\n...(目标过长,已截断)"
    return "# 当前研究目标(notes/goal.md)\n" + text


def _goal_execution_prompt(goal: str) -> str:
    """`/goal <文本>` 写盘后发送给模型的顶层任务。"""
    return (_goal_context(goal)
            + "\n\n目标已由用户明确设定。请保留其中全部约束并立即开始执行;"
              "信息确实不足时再提出最少量澄清,不要只复述目标或等待用户说『开始/继续』。")


class ReplSession:
    def __init__(self, resume_id: str | None = None,
                 approval: str | None = None) -> None:
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
        # 审批模式:default(shell/危险命令、文件覆盖、工具副作用逐条人工确认)
        # | yolo(非危险副作用自动放行,只有红线危险命令仍问;/yolo 切换,config approval=yolo 设默认)。
        # 可自定义:config 里 approval=yolo|default 或 yolo=true。
        self.yolo = (str(self.conf.get("approval", "")).lower() in ("yolo", "auto")
                     or bool(self.conf.get("yolo", False)))
        if approval:
            self.yolo = approval.lower() == "auto"  # suggest 是 ask 的兼容名
        # 自动跟进停机靠 no-progress 检测;深度只是高位安全兜底(可 config 调,合法任务碰不到)
        try:
            self.max_auto_depth = int(self.conf.get("max_auto_depth", _MAX_AUTO_DEPTH))
        except (TypeError, ValueError):
            self.max_auto_depth = _MAX_AUTO_DEPTH
        self._followup_prev_sig = None   # 上一轮命令/读取请求签名(no-progress 判重)
        self._followup_repeat = 0        # 连续重复次数
        self._empty_reply_streak = 0     # 命令结果后 provider 空回复的有限自动恢复
        # 错误学习:本会话从命令失败蒸馏的环境教训(每轮注入,当场止损);跨会话见 memory 待确认卡
        self._tool_idle: dict = {"idle": {}}   # feat-133:工具组闲置计数(跨消息)
        self.session_lessons: list[dict] = []
        self._session_lesson_keys: set = set()
        # 「全部同意」:用户对某类副作用(执行 shell/覆盖文件/工具)说过 a 后,本会话该类不再逐条问
        self._auto_approve_labels: set = set()
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
        """把 @path 替换为文件内容块;@图片 则内联渲染(feat-069)。"""
        out_parts = []
        for token in text.split():
            if token.startswith("@") and len(token) > 1:
                p = Path(token[1:]).expanduser()
                if p.exists() and p.is_file():
                    from psyclaw import imgview
                    if imgview.is_image(p):
                        # 图片:终端支持则内联显示给用户;上下文只注入元信息——
                        # 二进制像素既不该灌给模型,smart_excerpt 也只会摘出乱码。
                        # feat-086:路径已知,直接渲染(不再回环正则,含括号/盘符
                        # 的文件名此前渲染不出还谎报「终端不支持」)
                        n = render_image_file(
                            p, force=self.conf.get("image_protocol"))
                        note = "已在终端内联显示" if n else "当前终端不支持内联显示"
                        out_parts.append(
                            f"(用户引用了图片 {p}({p.stat().st_size // 1024} KB),"
                            f"{note}。其像素内容你不可见;如需数值请引导用户跑分析或描述图内容)")
                        if not n:
                            print(ui.dim(f"  [图片 {p.name}:终端不支持内联,"
                                         "config image_protocol 可强制]"))
                        continue
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
            # 新的顶层轮次:重置 no-progress 判重(上一轮的重复计数不跨用户消息累加)
            self._followup_prev_sig = None
            self._followup_repeat = 0
            self._empty_reply_streak = 0
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
        # feat-041:传 provider 做结构化 LLM 蒸馏(无 key/异常自动回落规则蒸馏)
        self.messages, self.memo = compact_history(self.messages, self.memo,
                                                   provider=self.provider)
        # 动态系统提示:瘦核心 + 决策备忘 + 按需知识
        system = self.system
        # `/goal` 是持久状态,不是只写盘的旁路。每轮都注入,让“继续”也能承接完整任务。
        try:
            from psyclaw.tasks import get_goal
            goal_part = _goal_context(get_goal())
            if goal_part:
                system += "\n\n" + goal_part
        except Exception:  # noqa: BLE001  # 目标读取失败不阻断对话
            pass
        memo_part = render_memo(self.memo)
        if memo_part:
            system += "\n\n" + memo_part
        # 错误学习:本会话已踩过的环境坑,每轮注入,防止再犯(python→python3、缺模块、API 改名…)
        if self.session_lessons:
            system += ("\n\n# 本会话已知环境限制(命令失败教训,务必遵守别重复踩)\n"
                       + "\n".join(f"- [{le['trigger']}] {le['lesson']}"
                                   for le in self.session_lessons[-12:]))
        # feat-111:跨会话教训卡按**当前消息相关性**检索注入(强度前 2 张保底),
        # 不再全量常驻 system——治「用得越久注入越多」的上下文膨胀
        try:
            from psyclaw.memory import relevant_lessons, render_lesson_block
            block = render_lesson_block(relevant_lessons(text))
            if block:
                system += "\n\n" + block
        except Exception:  # noqa: BLE001  # 记忆读取失败不阻断对话
            pass
        # feat-114:语义记忆(研究语境概念/约定)同方检索注入,冲突卡如实带出
        try:
            from psyclaw.memory import recall_facts, render_fact_block
            fblock = render_fact_block(recall_facts(text))
            if fblock:
                system += "\n\n" + fblock
        except Exception:  # noqa: BLE001
            pass
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
        # 键盘选择器约定 + 文件读取权限(随 /access 动态切换)+ 直接跑命令
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
                from psyclaw.ui_input import EscapeWatch, stream_interruptible
                with EscapeWatch() as esc:     # feat-090:生成中按 ESC 也能取消本轮
                    for chunk in stream_interruptible(
                            self.provider.chat(self.messages, system=system), esc):
                        blk.write(chunk)
                        reply_parts.append(chunk)
            except KeyboardInterrupt:          # Ctrl+C / ESC = 取消本轮,不炸 REPL
                blk.write("\n[已中断本轮生成(ESC/Ctrl+C)]")
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
            from psyclaw.providers import get_role_provider
            auditor_p = get_role_provider(self.conf, "auditor", self.provider)
            result = run_audit(auditor_p, text, reply)
            print(render_verdict(result))
        # 自动跟进:模型请求读文件(开放模式自动读)/ 给出选项(弹键盘选择器)→ 回传续聊
        follow = self._recover_empty_reply(reply, internal, self._auto_followup(reply))
        if follow:
            self._auto_depth += 1
            try:
                self.ask(follow, internal=True)
            finally:
                self._auto_depth -= 1

    # -- 副作用审批(YOLO / 「全部同意」/ 默认逐条确认)----------------------
    def _side_effect_ok(self, detail: str, *, dangerous: bool = False,
                        label: str = "副作用") -> bool:
        """统一的副作用确认门。

        - 命中红线的**危险**操作(rm -rf / push --force / DROP TABLE…):永远逐条问,
          **不给「全部同意」**,即使 YOLO / 之前说过 a 也照问(红线不放松)。
        - 非危险:① YOLO 全放行 ② 本会话已对该类说过「全部同意(a)」→ 自动放行
          ③ 否则三态确认 Y/n/a——选 a 则**本会话该类不再逐条问**(用户实测:确认一次同类就统一)。

        待确认内容单独打在上一行(短提示,免与回显 y 串行);data/raw 与密钥是更上层硬拒。
        """
        if dangerous:
            print(ui.dim(f"  ┆ 待确认{label}:{detail[:200]}"))
            return _hitl_confirm("  确认⚠ 危险操作?")
        if self.yolo or label in self._auto_approve_labels:
            why = "YOLO" if self.yolo else "本会话已同意此类"
            print(ui.dim(f"  ⚡ 自动放行({why}·{label}):{detail[:60]}"))
            return True
        print(ui.dim(f"  ┆ 待确认{label}:{detail[:200]}"))
        ans = _hitl_confirm_all(f"  确认{label}?")
        if ans == "all":
            self._auto_approve_labels.add(label)
            print(ui.ok(f"    ✓ 本会话起「{label}」不再逐条确认(/approval auto 可统一放行)"))
            return True
        return ans == "yes"

    def _confirm_cmd(self, cmd: str) -> bool:
        """命令执行确认:危险命令自动识别(YOLO 也问),其余按模式放行/确认。

        「全部同意(a)」的范围按 cmd_approval_scope 限定到命令前缀(feat-070,
        用户反馈:放行所有 shell 命令范围太大)——同意 `git status` 不放行 `rm`。
        """
        if "\n" in cmd:                # feat-101:多行命令整体展示后确认(引号块=一条命令)
            lines = cmd.splitlines()
            print(ui.dim("  ┆ 多行命令内容:"))
            for ln in lines[:20]:
                print(ui.dim(f"  ┆   {ln[:120]}"))
            if len(lines) > 20:
                print(ui.dim(f"  ┆   …(共 {len(lines)} 行)"))
            return self._side_effect_ok(
                cmd_display(cmd), dangerous=bool(_DANGEROUS_RE.search(cmd)),
                label=f"执行 shell 命令(多行:{cmd_display(cmd)[:60]})")
        return self._side_effect_ok(cmd, dangerous=bool(_DANGEROUS_RE.search(cmd)),
                                    label=f"执行 shell 命令({cmd_approval_scope(cmd)})")

    def _learn_from_output(self, output: str) -> None:
        """错误学习:从命令输出蒸馏环境教训 → 本会话记忆(每轮注入)+ memory 待确认卡(跨会话)。

        本会话记忆当场生效止损;跨会话的卡是 pending(经 /memory confirm 才转生效),
        避免把「装了 mne 之后就过时」的环境事实自动固化——沿用既有教训卡的 HITL 纪律。
        """
        self._ingest_lessons(distill_env_lessons(output))

    def _ingest_lessons(self, lessons: list[dict]) -> None:
        """把已蒸馏的教训并入会话记忆 + 落待确认卡(agent 循环产出的 lessons 也走这里,feat-065)。"""
        for les in lessons:
            key = (les["trigger"], les["lesson"])
            if key in self._session_lesson_keys:
                continue
            self._session_lesson_keys.add(key)
            self.session_lessons.append(les)
            print(ui.accent(f"  📎 记下环境教训:{les['lesson'][:72]}"))
            # 落持久待确认卡(best-effort,失败不阻塞;feat-087 与 CLI 共用)
            from psyclaw.memory import draft_lessons
            draft_lessons([les])

    # -- 图片内联渲染(终端支持时把分析出的图显示在对话里)---------------------
    def _cmd_img(self, arg: str) -> None:
        """/img <路径>:在终端内联渲染一张图片(不支持则打印路径)。"""
        from psyclaw import imgview
        if not arg.strip():
            print("  用法:/img <图片路径>(png/jpg/gif/webp/bmp;支持的终端内联显示)")
            return
        p = Path(arg.strip().strip("\"'")).expanduser()
        if not p.is_file():
            print(ui.warn(f"  未找到:{p}"))
            return
        if not imgview.is_image(p):
            print(ui.warn(f"  不是可渲染的图片类型:{p.suffix}"))
            return
        force = self.conf.get("image_protocol")
        esc = imgview.render_escape(p, force=force)
        if esc:
            print(ui.dim(f"  🖼 {p.name}({p.stat().st_size // 1024} KB)"))
            sys.stdout.write(esc)
            sys.stdout.flush()
        else:
            proto = imgview.supports_inline(force)
            if not proto:
                print(ui.dim("  当前终端不支持内联图片(iTerm2/WezTerm/VSCode/Warp/kitty 可;"
                             "config image_protocol 可强制)。文件在:" + str(p)))
            else:
                print(ui.warn(f"  渲染失败(可能超过 {imgview.MAX_IMG_BYTES // 1024 // 1024}MB"
                              f" 上限或格式受限)。文件在:{p}"))

    def _render_images_in(self, text: str) -> None:
        """命令输出里提到的图片文件,若存在且终端支持,自动内联渲染(最多 3 张)。"""
        render_images_in_text(text, force=self.conf.get("image_protocol"))

    def _reprobe_env_lessons(self, include_slow: bool = False) -> int:
        """自动失效:再验证已生效的环境教训卡,现在能用了的自动归档(active→archived)。

        include_slow=False:只查 cmd 类(shutil.which 秒回,startup 用,零延迟);
        include_slow=True:连 module/attr 一起真跑 import(子进程,/memory verify 用)。
        只碰 source=error 的机器生成卡——用户/审计的方法学教训绝不因命令成功而失效。返回归档数。
        """
        from psyclaw import memory
        try:
            cards = [c for c in memory.active_lessons() if c.get("source") == "error"]
        except Exception:  # noqa: BLE001
            return 0
        archived = 0
        for c in cards:
            if not include_slow and c.get("kind") != "cmd":
                continue
            if probe_env_card_stale(c) is not True:   # 仅在**确证已恢复**时才失效(防误删)
                continue
            if memory.archive_lesson(c["trigger"], c["lesson"],
                                     reason="环境已恢复(再验证通过),自动失效"):
                archived += 1
                self.session_lessons = [le for le in self.session_lessons
                                        if le.get("trigger") != c["trigger"]]
                print(ui.ok(f"  ♻ 环境教训自动失效:[{c['trigger']}] 现在可用了,已归档"))
        return archived

    def _round_is_autonomous(self, runs: list[dict], reads: list[str]) -> bool:
        """这一轮跟进会不会**不问人**就执行?

        会逐条问人(用户打 y 确认)= 用户在亲手推进,不是模型自主空转——no-progress 不该管。
        - shell / 危险命令:非 YOLO 要人确认 → 非自主;YOLO 且非危险自动跑 → 自主。
        - psyclaw 子命令、开放模式自动读文件:不问人 → 自主。
        no-progress 只在自主回合计数,免得用户逐条确认被误判成「原地打转」而掐断(用户实测)。
        """
        for r in runs:
            danger = bool(_DANGEROUS_RE.search(r.get("cmd", "")))
            if r.get("kind") != "psyclaw" or danger:      # 需要确认的命令
                if not (self.yolo and not danger):        # 非 YOLO、或危险 → 会问人
                    return False
        return True

    def _noprogress_stop(self, runs: list[dict], reads: list[str]) -> bool:
        """no-progress 检测:命令/读取请求连续重复 ≥ 阈值 → 判原地打转,停自动跟进。

        滚动更新 self._followup_prev_sig / _followup_repeat(每个顶层轮次开头已重置)。
        与 toolloop 的 _calls_signature 判重同理——这是流式路径的停机主判据(替代低深度上限)。
        """
        sig = _followup_signature(runs, reads)
        if sig is None:
            return False
        if sig == self._followup_prev_sig:
            self._followup_repeat += 1
        else:
            self._followup_prev_sig = sig
            self._followup_repeat = 0
        if self._followup_repeat >= _MAX_FOLLOWUP_REPEAT:
            print(ui.warn(f"  (检测到连续 {self._followup_repeat + 1} 轮重复相同的命令/读取请求且"
                          "无新进展,已停自动跟进以免空转;请换思路,或说「继续」再试)"))
            return True
        return False

    def _recover_empty_reply(self, reply: str, internal: bool,
                             follow: str | None) -> str | None:
        """命令/读取回传后模型空回复时有限自愈,保留现有 follow 的优先级。"""
        if reply.strip():
            self._empty_reply_streak = 0
            return follow
        if not internal or follow is not None:
            return follow
        self._empty_reply_streak += 1
        if self._empty_reply_streak <= _MAX_EMPTY_REPLY_RETRIES:
            print(ui.warn(f"  (模型回复为空,自动恢复 "
                          f"{self._empty_reply_streak}/{_MAX_EMPTY_REPLY_RETRIES})"))
            return _EMPTY_REPLY_NUDGE
        print(ui.warn("  (模型连续空回复,已停止自动恢复;上下文仍保留,可继续对话)"))
        return None

    def _auto_followup(self, reply: str) -> str | None:
        """命令执行 / 读取请求 / 选项选择 → 需要自动回传给模型的消息(无则 None)。

        统一在 **去掉 save 块之后** 的正文上解析——save 的内容是要写盘的文件,
        里面的示例命令/read/复选清单绝不能被当成本轮要执行的请求。

        停机:命令/读取的自动跟进不再靠低深度上限,而是 **no-progress 检测**(连续重复
        相同请求即停);深度只留高位安全兜底,防极端空转。choices 由用户逐次交互,不设限。
        """
        body = strip_save_blocks(reply)
        runs = parse_run_requests(body)
        reads = parse_read_requests(body)

        # 自动跟进可能空转,两道闸拦——但 no-progress 只针对**自主**回合(YOLO 自动跑 / 自动读):
        # 用户在逐条确认(打 y)本身就是在推进,不该被判「原地打转」而掐断(用户实测)。
        if (runs or reads) and self.file_access != "safe":
            if self._auto_depth >= self.max_auto_depth:   # ① 高位安全兜底,始终生效
                print(ui.dim(f"  (自动跟进已达安全上限 {self.max_auto_depth},请说「继续」再续)"))
                return None
            if self._round_is_autonomous(runs, reads):
                if self._noprogress_stop(runs, reads):    # ② no-progress 只管自主空转
                    return None
            else:                                          # 人在逐条确认 → 不算空转,重置判重
                self._followup_prev_sig = None
                self._followup_repeat = 0

        # ① 命令块(psyclaw/shell):执行并回传输出——命令块吐了没人跑=死胡同(用户实测)
        if runs:
            if self.file_access == "safe":
                print(ui.warn(f"  [访问:safe] 模型给出 {len(runs)} 条命令,未自动执行;"
                              "请手动复制运行,或 /access open 放开。"))
            else:
                msg, notes = run_commands(runs, confirm=self._confirm_cmd)
                for n in notes:
                    print(ui.warn(n) if n.startswith("  ✗") else ui.dim(n))
                if msg:
                    self._learn_from_output(msg)   # 错误学习:命令失败 → 蒸馏环境教训
                    self._render_images_in(msg)    # 命令出图 → 终端内联渲染(支持时)
                    return msg

        if reads:
            if self.file_access == "safe":
                print(ui.warn(f"  [访问:safe] 模型请求读取 {len(reads)} 个文件已被拒;"
                              "用 @<路径> 显式引用,或 /access open 放开。"))
            else:
                msg, notes = gather_read_results(reads)
                for n in notes:
                    print(ui.dim(n) if n.startswith("  ·") else n)
                if msg:
                    return msg
        try:
            from psyclaw.choices import (format_free_answer, format_selection_message,
                                         parse_choices, pick_interactive)
            # 规划模式的 ## TASKS 就是 - [ ] 清单——那是任务看板,不是给用户选的选项;
            # 只认显式 choices 块,复选启发式关闭(评审修复:否则每条计划回复都弹选择器)。
            choice = parse_choices(body, heuristic=not self.plan_mode)
        except Exception:  # noqa: BLE001
            choice = None
        if choice and self._auto_depth < self.max_auto_depth:
            chosen, free = pick_interactive(choice)
            if chosen:
                print(ui.ok("  → 已选:" + "、".join(c[:40] for c in chosen)))
                return format_selection_message(chosen, choice["question"])
            if free:   # 用户没选编号、直接打字(如 y)→ 当自由作答转发给模型,别吞掉(用户实测)
                print(ui.dim(f"  → 「{free[:40]}」不是编号,已作为你的回复发给模型继续"))
                return format_free_answer(free, choice["question"])
            print(ui.dim("  (跳过选择;可直接输入你的回复)"))
        return None

    def _run_agent(self, system: str) -> str | None:
        """agent 模式:跑纯工具层循环(模型自主多步调工具)。返回最终答案;provider 错误返回 None。"""
        from psyclaw.toolloop import _short, run_tool_loop

        def _approve(call: dict) -> bool:
            # YOLO 自动放行工具副作用;否则人工确认。参数截断(save_file 的 content
            # 可能几十 KB,不整个灌进提示);非 TTY/EOF/中断仍 fail-closed(在 _hitl_confirm)。
            return self._side_effect_ok(
                f"{call['name']}({_short(call.get('args') or {}, 120)})", label="工具副作用")

        try:
            res = run_tool_loop(
                self.provider, system, self.messages, project_dir=".",
                approve=_approve, emit=lambda e: print(ui.dim(f"  ⚙ {e}")),
                idle_state=self._tool_idle)   # feat-133:跨消息累积工具组闲置,长期不用清走
        except KeyboardInterrupt:              # feat-090:ESC/Ctrl+C 取消本轮,不炸 REPL
            print(ui.warn("  [已中断本轮生成(ESC/Ctrl+C)]"))
            return None
        except Exception as exc:  # noqa: BLE001
            print(ui.err(f"  [provider 错误] {exc}"))
            return None
        if res["trace"]:
            print(ui.dim(f"  [agent:{res['iters']} 轮 · {len(res['trace'])} 次工具调用 · "
                         f"{res['stopped']}]"))
        # feat-065:循环内蒸馏的环境教训并入会话记忆(每轮注入)+ 落跨会话待确认卡
        self._ingest_lessons(res.get("lessons") or [])
        from psyclaw.toolloop import log_agent_run
        task_head = next((m["content"] for m in reversed(self.messages)
                          if m.get("role") == "user"), "")
        log_agent_run(".", task_head, res)   # feat-037:落运行痕迹(失败静默)
        blk = ui.StreamBlock(f"PsyClaw · {self.provider.name}")
        blk.write(res["final"])
        blk.close()
        print()
        # feat-065:最终答案与工具输出里提到的图,终端支持时内联渲染(分析出图即见)
        self._render_images_in("\n".join(
            [res["final"]] + [str(t.get("output", "")) for t in res["trace"]]))
        return res["final"]

    def _capture_saves(self, reply: str) -> None:
        """扫描回复里的 ```save 块并写盘(护栏:拒 data/raw、覆盖前交互确认)。"""
        blocks = parse_save_blocks(reply)
        if not blocks:
            return

        def _confirm(p: Path) -> bool:
            # YOLO 自动覆盖(data/raw 另有硬拒);否则 fail-closed 人工确认(非 TTY/EOF 不覆盖)
            return self._side_effect_ok(str(p), label="覆盖已存在文件")

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
        elif cmd in ("/prepare", "/clarify"):
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
            if arg.strip().lower() == "verify":
                print(ui.dim("  正在再验证环境教训卡(命令 / 模块 / 属性)…"))
                n = self._reprobe_env_lessons(include_slow=True)
                print(ui.ok(f"  ✓ 完成:{n} 条已恢复并归档。") if n else
                      ui.dim("  没有已恢复的环境教训(都仍成立,或无法判定)。"))
            else:
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
                print(ui.ok("  ✓ 研究目标已写 notes/goal.md,并发送给模型开始执行"))
                self.ask(_goal_execution_prompt(arg))
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
        elif cmd == "/access":
            self._cmd_access(arg, toggle=False)
        elif cmd == "/safemode":             # 兼容别名;不再进入主帮助/联想
            self._cmd_access(arg, toggle=True)
        elif cmd == "/approval":
            self._cmd_approval(arg, toggle=False)
        elif cmd == "/yolo":
            self._cmd_approval(arg, toggle=True)  # 兼容别名
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
            print(ui.dim("  [兼容别名] 通用任务请直接在 Chat 中说明"))
            run_loop(topic=arg or None)
        elif cmd == "/run":
            self._cmd_run_mode(arg)
        elif cmd == "/auto":
            self._cmd_auto_mode(arg)
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
        elif cmd == "/dump":
            self._cmd_dump(arg)
        elif cmd in ("/img", "/show"):
            self._cmd_img(arg)
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

    def _cmd_approval(self, arg: str, *, toggle: bool = False) -> None:
        """审批策略:ask|auto。旧 `/yolo` 用 toggle=True 保留原切换语义。"""
        low = arg.strip().lower()
        if low in ("auto", "on", "yolo"):
            self.yolo = True
        elif low in ("ask", "off", "default", "suggest"):
            self.yolo = False
        elif toggle:
            self.yolo = not self.yolo
        elif not low:
            print(f"  approval:{'auto' if self.yolo else 'ask'}"
                  "  (/approval ask|auto)")
            return
        else:
            print(ui.warn("  用法:/approval ask|auto"))
            return
        if self.yolo:
            print(ui.err("  [审批:auto] 命令 / 文件覆盖 / 工具副作用自动放行——"
                         "只有命中红线的危险命令(rm -rf、push --force、DROP TABLE…)仍会问你。"))
            print(ui.dim("    多步分析一口气跑完(靠 no-progress 检测停,不再中途卡深度上限)。"
                         "受保护的 data/raw 与密钥始终硬拒。/approval ask 恢复逐条确认。"))
        else:
            print(ui.ok("  [审批:ask] shell / 覆盖 / 工具副作用逐条人工确认。"))

    def _cmd_yolo(self, arg: str) -> None:
        """旧内部调用兼容层;新界面使用 `/approval ask|auto`。"""
        self._cmd_approval(arg, toggle=True)

    def _cmd_access(self, arg: str, *, toggle: bool = False) -> None:
        """文件访问策略:open|safe。旧 `/safemode` 保留切换语义。"""
        low = arg.strip().lower()
        if low in ("safe", "on"):
            self.file_access = "safe"
        elif low in ("open", "off"):
            self.file_access = "open"
        elif toggle:
            self.file_access = "open" if self.file_access == "safe" else "safe"
        elif not low:
            print(f"  access:{self.file_access}  (/access open|safe)")
            return
        else:
            print(ui.warn("  用法:/access open|safe"))
            return
        if self.file_access == "safe":
            print(ui.warn("  [访问:safe] 一切文件读取须用 @<路径> 显式引用。"))
        else:
            print(ui.ok("  [访问:open] 模型可请求读取本地文件;data/raw 恒受保护。"))

    def _record_mode_run(self, command: str, rc: int) -> None:
        """把 slash 模式运行记进对话,使后续自然语言能承接发生过的操作。"""
        self.messages.append({"role": "user", "content": f"[运行命令] {command}"})
        self.messages.append({"role": "assistant", "content":
                              f"[运行完成] 退出码 {rc};产物见 notes/ 与 outputs/。"})

    def _cmd_run_mode(self, arg: str) -> None:
        """/run <类型> <目标>:聊天内调用与 CLI 相同的共享模式路由。"""
        import shlex
        from psyclaw.modes import RUN_TYPES, run_mode
        try:
            toks = shlex.split(arg)
        except ValueError as exc:
            print(ui.warn(f"  参数解析失败:{exc}"))
            return
        if not toks:
            print("  用法:/run <类型> <路径或主题>  类型:" + "|".join(RUN_TYPES))
            return
        kind, rest = toks[0], toks[1:]
        confirm_each = "--confirm-each" in rest
        exploratory = "--exploratory" in rest or "--skip-gates" in rest
        resume = "--resume" in rest
        flags = {"--confirm-each", "--exploratory", "--resume", "--yes", "--skip-gates"}
        rest = [x for x in rest if x not in flags]
        target = " ".join(rest).strip() or None
        try:
            rc = run_mode(kind, target, confirm_each=confirm_each,
                          exploratory=exploratory, resume=resume)
        except ValueError as exc:
            print(ui.warn(f"  {exc}"))
            return
        self._record_mode_run(f"/run {arg}", rc)

    def _cmd_auto_mode(self, arg: str) -> None:
        """/auto:聊天内启动自主项目推进。"""
        import shlex
        from psyclaw.modes import run_auto
        try:
            toks = shlex.split(arg)
        except ValueError as exc:
            print(ui.warn(f"  参数解析失败:{exc}"))
            return
        confirm = "--confirm-each" in toks
        exploratory = "--exploratory" in toks or "--skip-gates" in toks
        max_iters = 6
        if "--max-iters" in toks:
            try:
                max_iters = int(toks[toks.index("--max-iters") + 1])
            except (ValueError, IndexError):
                print(ui.warn("  --max-iters 需要整数"))
                return
        rc = run_auto(max_iters=max_iters, confirm_each=confirm,
                      exploratory=exploratory)
        self._record_mode_run(f"/auto {arg}".rstrip(), rc)

    # -- 导出对话(feat:导出当前对话 / 完整含隐藏上下文)---------------------
    def _standing_conventions(self) -> str:
        """每轮持续注入、但从不在对话中展示的约定片段(键盘选择/文件读取/命令执行)。

        随 file_access 与 plan_mode 确定性重建——与 ask() 里拼进 system 的口径一致。
        每轮临时注入的相关知识/历史召回随消息即时生成、不留存,故不在此重建。
        """
        parts = [_CHOICES_SYSTEM,
                 _READ_SAFE_SYSTEM if self.file_access == "safe" else _READ_OPEN_SYSTEM,
                 _RUN_SYSTEM + ("\n" + _RUN_SAFE_NOTE if self.file_access == "safe" else "")]
        if self.plan_mode:
            from psyclaw.tasks import PLAN_MODE_SYSTEM
            parts.append(PLAN_MODE_SYSTEM)
        return "\n".join(p for p in parts if p)

    def _cmd_dump(self, arg: str) -> None:
        """/dump [--full] [路径]:导出当前对话;--full 连同不展示的隐藏上下文一并导出。"""
        from psyclaw import transcript
        from psyclaw.context import render_memo
        toks = arg.split()
        full = False
        rest: list[str] = []
        for t in toks:
            if t in ("--full", "-f", "full"):
                full = True
            else:
                rest.append(t)
        if not self.messages:
            print(ui.dim("  (当前会话暂无对话可导出)"))
            return
        from datetime import datetime
        meta = {
            "session_id": self.session_id,
            "session_name": self.session_name or "",
            "provider": self.provider.describe(),
            "turns": sum(1 for m in self.messages if m.get("role") == "user"),
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if full:
            from psyclaw.tasks import get_goal
            text = transcript.render_full(
                self.messages, system=self.system, memo=render_memo(self.memo),
                conventions=self._standing_conventions(), current_goal=get_goal(),
                meta=meta)
        else:
            text = transcript.render_conversation(self.messages, meta=meta)
        target = rest[0] if rest else transcript.default_path(self.session_id, full)
        p = Path(target).expanduser()
        if _save_is_protected(p):
            print(ui.err(f"  ✗ 拒绝写入受保护的 data/raw:{p}"))
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(ui.err(f"  ✗ 导出失败 {p}:{exc}"))
            return
        kind = "完整对话(含隐藏上下文)" if full else "当前对话"
        print(ui.ok(f"  ✓ 已导出{kind} → {p}({len(text)} 字符)"))
        if not full:
            print(ui.dim("    /dump --full 连同 system 提示/决策备忘等不展示的上下文一并导出"))

    # -- 主循环 --------------------------------------------------------------
    def run(self) -> int:
        if self.resume_id:
            self._resume_session(self.resume_id)
        try:
            from psyclaw.status import collect_status
            status = collect_status(".")
        except Exception:  # noqa: BLE001
            status = None
        print(ui.startup(__version__, status=status, provider=self.provider.describe(),
                         approval="auto" if self.yolo else "default"))
        # 自动失效(轻量):启动时秒验证 cmd 类环境教训——上次说「没有 python」但现在装上了,
        # 就自动归档,别再用过时的坑误导模型。只 shutil.which、零子进程、无卡则零成本;
        # 模块/属性类较慢,留给 /memory verify 手动跑。config verify_env_lessons=false 可关。
        if self.conf.get("verify_env_lessons", True):
            try:
                self._reprobe_env_lessons(include_slow=False)
            except Exception:  # noqa: BLE001  # 再验证失败绝不阻塞启动
                pass
        print("  " + ui.dim("输入 / 弹出命令联想(↑↓选择 Tab补全) · /exit 退出 · @<文件> 引用") + "\n")
        while True:
            base = ui.paint("psyclaw", "brcyan", "bold")
            if self.session_name:
                base += ui.dim(f"·{self.session_name[:12]}")
            modes = ("" if not self.plan_mode else ui.warn(" plan")) \
                + ("" if not self.agent_mode else ui.accent(" advanced")) \
                + ("" if self.file_access != "safe" else ui.warn(" access:safe")) \
                + ("" if not self.yolo else ui.err(" approval:auto"))
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
            if _is_exit_word(line):        # feat-090:裸 quit/exit 也认(用户实测反馈)
                break
            try:
                if line.startswith("/"):
                    if not self.handle_command(line):
                        break
                else:
                    self.ask(line)
            except KeyboardInterrupt:      # 深处的 Ctrl+C 也只取消本轮(评审修复)
                print(ui.dim("\n  (已中断本轮;继续对话或 /exit 退出)"))
        # feat-116:会话结束自动睡眠(自上次睡眠新增 ≥20 轮才触发,轻量不扰人)
        try:
            from psyclaw.sleep import render_report, run_sleep, sleep_due
            if sleep_due("."):
                print(ui.dim("  " + render_report(run_sleep(".", provider=self.provider))))
        except Exception:  # noqa: BLE001  # 睡眠失败绝不影响退出
            pass
        print(ui.dim("再见。研究顺利!"))
        return 0


HELP_TEXT = """\
  三种工作方式
  对话         直接输入问题;工具按需使用,关键操作按 approval 策略确认
  /run TYPE X  执行明确流程:analysis|meta|literature|qualitative
               默认连续执行;可加 --confirm-each / --exploratory / --resume
  /auto         据项目状态持续推进(--confirm-each 可逐任务确认)

  当前任务
  @<file>     在消息中引用文件内容(如:帮我看看 @data.csv 的结构)
  /goal [g]   查看目标;带文本时写 notes/goal.md 并立即发送模型执行
  /prepare    完成研究准备清单       /clarify 是兼容别名
  /tasks      任务看板(list|add|start|done|block|sync;计划自动抽取)
  /recall [q] 历史上下文召回(全量存库+关键词索引,相关度≥80%才注入)

  安全策略
  /approval ask|auto  ask=副作用逐条确认;auto=自动放行非危险操作
  /access open|safe   open=模型可请求读文件;safe=只能用 @ 显式引用

  会话与输出
  /model [m]  查看/切换模型      /provider [p]  查看/切换 provider
  /sessions   历史会话列表       /resume <id>   续接历史会话
  /rename <名> 命名当前会话       /search <词>   跨会话全文检索
  /dump [--full] [路径]  导出当前对话为 Markdown(--full 含 system/备忘等隐藏上下文)
  /clear      清空上下文           /compact       压缩上下文
  /exit       退出

  其他能力仍可直接调用;输入 / 后看联想。旧 /agent /research-loop /yolo /safemode 保持兼容。"""


def run_repl(resume_id: str | None = None, approval: str | None = None) -> int:
    return ReplSession(resume_id=resume_id, approval=approval).run()
