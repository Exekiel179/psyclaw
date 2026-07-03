"""交互式选项选择 —— 模型给出选项清单时,REPL 弹键盘选择器,选完自动回传。

用户实测痛点:模型回复里列了「• [ ] 研究1a …」这样的复选清单,但 REPL 只是打印文本,
不支持键盘选择。沿用本项目「约定块 + 自动捕获」的既有套路(save 块 / tool 块同款):

- 首选约定块(system 提示教模型输出,机器可靠解析):
    ```choices
    {"question": "要复现哪些实验?", "multi": true, "options": ["研究1a …", "研究1b …"]}
    ```
- 兜底启发式:模型自发写的复选清单行(``• [ ] xxx`` / ``- [ ] xxx``)≥2 条也自动识别
  (multi=True;问题取清单前最近的一行正文)。

选择器三级降级(对齐 ui_input 的纪律):prompt_toolkit 对话框(方向键+空格勾选+回车)
→ 编号输入(``1,3`` / ``全部`` / 回车跳过)→ 非 TTY 不弹(打印提示,不阻塞脚本)。
解析与选择解析均为纯函数,可单测;交互层薄壳。
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


# ---------------------------------------------------------------------------
# 交互层(薄壳,三级降级)
# ---------------------------------------------------------------------------

def _pick_ptk(choice: dict):
    """prompt_toolkit 对话框:方向键移动 + 空格勾选(多选)/回车选定。失败抛异常→兜底。"""
    from prompt_toolkit.shortcuts import checkboxlist_dialog, radiolist_dialog
    values = [(o, o[:76]) for o in choice["options"]]
    if choice["multi"]:
        res = checkboxlist_dialog(
            title="键盘选择(空格勾选 · 回车确认 · Tab 到确定)",
            text=choice["question"], values=values).run()
        return list(res) if res else []
    res = radiolist_dialog(title="键盘选择(方向键 · 回车确认)",
                           text=choice["question"], values=values).run()
    return [res] if res else []


def _pick_numbered(choice: dict) -> list[str]:
    """编号输入兜底:打印编号清单,输入 1,3 / 全部 / 回车跳过。"""
    from psyclaw import ui
    print(ui.accent(f"  {choice['question']}"))
    for i, o in enumerate(choice["options"], 1):
        print(f"    {ui.ok(str(i)):>4}. {o[:90]}")
    tip = "编号(可多选,如 1,3)或 全部" if choice["multi"] else "编号(单选)"
    try:
        raw = input(f"  选择 [{tip};回车跳过]: ")
    except (EOFError, KeyboardInterrupt):
        return []
    return resolve_selection(raw, choice["options"], choice["multi"])


def pick_interactive(choice: dict) -> list[str]:
    """弹键盘选择器。prompt_toolkit 可用走对话框,否则编号输入。返回选中项([]=跳过)。"""
    import sys
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return []          # 非 TTY(脚本/管道)不弹,不阻塞
    try:
        return _pick_ptk(choice)
    except Exception:  # noqa: BLE001  # 未装 ptk / 对话框失败 → 编号兜底
        return _pick_numbered(choice)
