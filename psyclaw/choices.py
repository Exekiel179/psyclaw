"""交互式选项选择 —— 模型给出选项清单时,REPL 弹键盘选择器,选完自动回传。

用户实测痛点:模型回复里列了「• [ ] 研究1a …」这样的复选清单,但 REPL 只是打印文本,
不支持键盘选择。沿用本项目「约定块 + 自动捕获」的既有套路(save 块 / tool 块同款):

- 首选约定块(system 提示教模型输出,机器可靠解析):
    ```choices
    {"question": "要复现哪些实验?", "multi": true, "options": ["研究1a …", "研究1b …"]}
    ```
- 兜底启发式:模型自发写的复选清单行(``• [ ] xxx`` / ``- [ ] xxx``)≥2 条也自动识别
  (multi=True;问题取清单前最近的一行正文)。

选择器三级降级(对齐 ui_input 的纪律):**原地内联选择器**(↑↓ 移动 · 空格勾选 ·
回车确认 · 打字=自由作答;只用 ANSI 行控制,不清屏不进备用屏——v0.12 feat-068,
用户实测:prompt_toolkit 全屏对话框在 Windows 上是突兀的蓝色独立屏幕,已弃用)
→ 编号输入(``1,3`` / ``全部`` / 回车跳过)→ 非 TTY 不弹(打印提示,不阻塞脚本)。
解析与选择解析均为纯函数,可单测;内联选择器的键流与行读取可注入,同样可单测。
"""

from __future__ import annotations

import json
import re

_BLOCK_RE = re.compile(r"```choices\s*\r?\n(?P<body>.*?)```", re.S)
# 复选清单行:• / - / * 可选前缀 + [ ] + 文本
_CHECKBOX_RE = re.compile(r"^\s*(?:[-•*·]\s*)?\[\s?\]\s*(?P<opt>.+?)\s*$")
MAX_OPTIONS = 20


def parse_choices(reply: str, heuristic: bool = True) -> dict | None:
    """从模型回复解析选项集 → {question, multi, options} 或 None。纯函数。

    优先 ```choices JSON 块;无块且 ``heuristic=True`` 时启发式识别 ``[ ]`` 复选清单
    (≥2 条才算;**代码围栏内的行不算**——save 块/示例代码里的清单不是给用户选的)。
    规划模式等场景可传 ``heuristic=False`` 只认显式块(- [ ] 任务清单不该弹选择器)。
    """
    m = _BLOCK_RE.search(reply or "")
    if m:
        try:
            obj = json.loads(m.group("body").strip())
            opts = [str(o).strip() for o in obj.get("options", []) if str(o).strip()]
            if len(opts) >= 2:
                return {"question": str(obj.get("question", "")).strip() or "请选择",
                        "multi": bool(obj.get("multi", True)),
                        "options": opts[:MAX_OPTIONS]}
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass  # 块坏了 → 走启发式
    if not heuristic:
        return None

    lines = (reply or "").splitlines()
    opts: list[str] = []
    first_idx = None
    in_fence = False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cm = _CHECKBOX_RE.match(ln)
        if cm:
            if first_idx is None:
                first_idx = i
            opts.append(cm.group("opt"))
    if len(opts) < 2:
        return None
    # 问题 = 清单前最近的非空正文行
    question = "请选择"
    for j in range((first_idx or 0) - 1, -1, -1):
        t = lines[j].strip().strip(":：")
        if t:
            question = t[:80]
            break
    return {"question": question, "multi": True, "options": opts[:MAX_OPTIONS]}


def resolve_selection(raw: str, options: list[str], multi: bool = True) -> list[str]:
    """把用户输入解析成选中的选项列表。纯函数。

    支持:``1,3`` / ``1 3`` 编号(1 基)· ``全部``/``all``/``a`` · 选项原文精确匹配 ·
    空串=取消([])。单选(multi=False)只留第一个。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.lower() in ("全部", "all", "a", "所有"):
        return list(options) if multi else options[:1]
    chosen: list[str] = []
    for tok in re.split(r"[,，;；\s]+", raw):
        if not tok:
            continue
        if tok.isdigit():
            i = int(tok)
            if 1 <= i <= len(options) and options[i - 1] not in chosen:
                chosen.append(options[i - 1])
        elif tok in options and tok not in chosen:
            chosen.append(tok)
    return chosen[:1] if (chosen and not multi) else chosen


def format_selection_message(chosen: list[str], question: str = "") -> str:
    """选中项 → 自动回传给模型的用户消息。"""
    head = f"(针对「{question}」)" if question and question != "请选择" else ""
    return f"我的选择{head}:" + "、".join(chosen)


def format_free_answer(text: str, question: str = "") -> str:
    """用户没选编号、而是直接打字作答 → 带上问题上下文回传给模型(别把输入吞掉)。"""
    head = f"(针对「{question}」)" if question and question != "请选择" else ""
    return f"{head}{text}".strip()


# ---------------------------------------------------------------------------
# 交互层(薄壳,三级降级)
# ---------------------------------------------------------------------------

def _pick_inline(choice: dict, get_key=None, read_rest=None) -> tuple[list[str], str | None]:
    """原地内联选择器(Claude Code 式,feat-068)。返回 (选中项, 自由文本)。

    键位:↑↓ 移动高亮 · 数字键跳选 · 空格勾选(多选) · 回车确认 · Esc/Ctrl+C 跳过 ·
    其它可打印字符 = 自由作答(转入行输入,首字符保留,feat-060 的「不吞输入」延续)。
    渲染只用 ANSI 行控制(\\033[K + 光标上移)在对话流里原地重画——不清屏、
    不进备用屏(prompt_toolkit 全屏对话框在 Windows 上是蓝色独立屏幕,弃用)。
    get_key / read_rest 可注入假键流与行读取,离线可单测。
    """
    import shutil
    import sys
    from psyclaw import ui
    from psyclaw.ui_input import _get_key
    keyf = get_key or _get_key
    readf = read_rest or input
    opts = choice["options"]
    multi = bool(choice["multi"])
    n = len(opts)
    sel = 0
    checked: set[int] = set()
    hint = ("↑↓ 移动 · 空格勾选 · 回车确认 · Esc 跳过 · 直接打字作答" if multi
            else "↑↓ 移动 · 回车/空格选定 · Esc 跳过 · 直接打字作答")
    out = sys.stdout
    out.write(ui.accent(f"  {choice['question']}") + ui.dim(f"  ({hint})") + "\n")
    # 按终端宽度截断,高亮项被截断时在下方详情区给全文(feat-071,用户反馈:
    # 选项框出来时看不见选项所说的方案)。详情区固定 2 行占位,重画几何稳定。
    width = max(40, shutil.get_terminal_size((100, 24)).columns)
    avail = width - 12
    detail_rows = 2

    def _draw(first: bool = False) -> None:
        if not first:
            out.write(f"\033[{n + detail_rows}A")   # 光标回菜单首行,原地重画
        for i, o in enumerate(opts):
            box = ("[x] " if i in checked else "[ ] ") if multi else ""
            cut = o[:avail] + ("…" if len(o) > avail else "")
            line = f"{box}{i + 1}. {cut}"
            if i == sel:
                out.write("\033[K  " + ui.paint("▸ " + line, "brcyan", "bold") + "\n")
            else:
                out.write("\033[K    " + line + "\n")
        full = opts[sel]
        detail: list[str] = []
        if len(full) > avail:                       # 高亮项截断了 → 详情区给全文
            body, w = full, max(20, width - 8)
            while body and len(detail) < detail_rows:
                detail.append(body[:w])
                body = body[w:]
            if body:
                detail[-1] = detail[-1][:-1] + "…"
        for r in range(detail_rows):
            txt = detail[r] if r < len(detail) else ""
            out.write("\033[K" + (ui.dim("    ▏" + txt) if txt else "") + "\n")
        out.flush()

    _draw(first=True)
    empty_streak = 0
    try:
        while True:
            key = keyf()
            if not key:
                # feat-080:空键不重画;连续空 = 流已死(EOF/句柄失效),跳过而非
                # 100% CPU 忙等重画(此前 '' 不命中任何分支直落 _draw 热转)。
                empty_streak += 1
                if empty_streak >= 8:
                    return [], None
                continue
            empty_streak = 0
            if key == "UP":
                sel = (sel - 1) % n
            elif key in ("DOWN", "TAB"):
                sel = (sel + 1) % n
            elif key == " ":
                if multi:
                    checked.symmetric_difference_update({sel})
                else:                          # feat-080:单选空格=选定高亮项
                    _draw()                    # (旧 radiolist 肌肉记忆;此前落进
                    return [opts[sel]], None   # 自由作答,空回车把选择吞成跳过)
            elif key == "ENTER":
                if multi and checked:
                    return [opts[i] for i in sorted(checked)], None
                return [opts[sel]], None       # 多选没勾任何项=选高亮那个;单选同
            elif key in ("ESC", "EOF"):
                return [], None
            elif (key.isascii() and key.isdigit()   # isascii 防 '²'.isdigit() 过而
                  and key != "0" and int(key) <= n):  # int() 崩(isdigit≠可 int)
                sel = int(key) - 1
                if not multi:
                    _draw()
                    return [opts[sel]], None   # 单选:数字即选定(同编号输入的心智)
                checked.symmetric_difference_update({sel})
            elif key and len(key) == 1 and key.isprintable():
                # 自由作答:不吞输入——退出菜单转行输入,首字符保留
                out.write(ui.dim("  作答: ") + key)
                out.flush()
                rest = readf("")
                text = (key + rest).strip()
                return [], (text or None)
            _draw()
    except KeyboardInterrupt:
        out.write("\n")
        return [], None


def _pick_numbered(choice: dict) -> tuple[list[str], str | None]:
    """编号输入兜底。返回 (选中项, 自由文本)。

    输入是有效编号/全部/原文 → (选中项, None);空(回车)→ ([], None);
    **非空但不是有效编号 → ([], 原文)**:别把输入吞掉(用户实测:打 `y` 直接消失)——
    当作对该问题的自由作答回传给模型继续,而不是「未选择」死胡同。
    """
    from psyclaw import ui
    print(ui.accent(f"  {choice['question']}"))
    for i, o in enumerate(choice["options"], 1):
        print(f"    {ui.ok(str(i)):>4}. {o[:90]}")
    tip = "编号(可多选,如 1,3)或 全部" if choice["multi"] else "编号(单选)"
    try:
        raw = input(f"  选择 [{tip};或直接打字作答;回车跳过]: ")
    except (EOFError, KeyboardInterrupt):
        return [], None
    chosen = resolve_selection(raw, choice["options"], choice["multi"])
    if chosen:
        return chosen, None
    return [], (raw.strip() or None)


def pick_interactive(choice: dict) -> tuple[list[str], str | None]:
    """弹键盘选择器。返回 (选中项, 自由文本):

    - (选中项, None):用户选了编号/选项;
    - ([], 自由文本):用户没选编号、直接打字作答(转发给模型,不丢);
    - ([], None):跳过(回车 / 非 TTY / 对话框取消)。
    """
    import sys
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return [], None          # 非 TTY(脚本/管道)不弹,不阻塞
    try:
        return _pick_inline(choice)       # 原地内联(feat-068);含自由作答
    except Exception:  # noqa: BLE001  # 终端不支持读键/ANSI → 编号兜底
        return _pick_numbered(choice)
