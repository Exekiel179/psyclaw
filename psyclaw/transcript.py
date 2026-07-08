"""对话导出 —— 把 REPL 当前会话渲染为 Markdown(纯函数,可单测)。

两档,差别只在「不展示的上下文」是否摊开:
- render_conversation(messages): 只导出对话本身(user↔assistant 轮),即屏幕上看到的往来。
- render_full(...): 完整上下文——额外摊开 system 提示、滚动决策备忘 memo、以及每轮
  持续注入的约定片段(键盘选择器/文件读取/命令执行)。这些模型每轮都看得见、用户从不显示,
  审计/复现/调试时需要一次性看全。

写盘的护栏(拒 data/raw 等)留在调用方(repl),本模块只负责把状态渲染成文本。
"""

from __future__ import annotations

_ROLE_LABELS = {
    "user": "🧑 用户",
    "assistant": "🤖 PsyClaw",
    "system": "⚙ 系统",
}


def _fmt_meta(meta: dict | None) -> list[str]:
    """会话元信息头(键顺序稳定,缺失项跳过)。"""
    if not meta:
        return []
    order = [
        ("session_id", "会话 ID"),
        ("session_name", "会话名"),
        ("provider", "Provider"),
        ("turns", "对话轮数"),
        ("exported_at", "导出时间"),
    ]
    lines: list[str] = []
    for key, label in order:
        val = meta.get(key)
        if val not in (None, ""):
            lines.append(f"- **{label}**:{val}")
    return lines


def _render_messages(messages: list[dict]) -> list[str]:
    """把 [{role, content}] 渲染成 Markdown 段落(content 非 str 也稳妥转字符串)。"""
    out: list[str] = []
    for m in messages or []:
        role = m.get("role", "?")
        label = _ROLE_LABELS.get(role, f"❓ {role}")
        raw = m.get("content")
        content = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        out.append(f"### {label}\n\n{content.rstrip()}")
    return out


def render_conversation(messages: list[dict], meta: dict | None = None) -> str:
    """导出当前对话(仅 user↔assistant 往来,不含隐藏上下文)。"""
    parts = ["# PsyClaw 对话导出"]
    meta_lines = _fmt_meta(meta)
    if meta_lines:
        parts.append("\n".join(meta_lines))
    body = _render_messages(messages)
    parts.append("\n\n".join(body) if body else "_（本会话暂无对话）_")
    return "\n\n".join(parts) + "\n"


def render_full(messages: list[dict], system: str = "", memo: str = "",
                conventions: str = "", meta: dict | None = None) -> str:
    """导出完整对话,含平时不展示的上下文(system 提示 / 决策备忘 / 每轮约定片段)。

    注意:每轮**动态**注入的知识/历史召回随消息即时生成、不留存,无法在此忠实重建;
    故只导出可稳定重建的持续性隐藏上下文,并如实标注这一点。
    """
    parts = ["# PsyClaw 对话导出(完整 · 含隐藏上下文)"]
    meta_lines = _fmt_meta(meta)
    if meta_lines:
        parts.append("\n".join(meta_lines))

    parts.append("## 隐藏上下文（不在对话中展示）")
    parts.append(
        "> 以下是模型每轮都能看到、但终端从不显示给用户的上下文。\n"
        "> 每轮临时注入的相关知识与历史召回随消息即时生成、不留存,无法在此重建。")
    parts.append("### 系统提示（system）\n\n"
                 + (system.strip() if system and system.strip() else "_（空）_"))
    parts.append("### 滚动决策备忘（memo）\n\n"
                 + (memo.strip() if memo and memo.strip() else "_（空）_"))
    if conventions and conventions.strip():
        parts.append("### 每轮持续注入的约定片段\n\n" + conventions.strip())

    parts.append("## 对话")
    body = _render_messages(messages)
    parts.append("\n\n".join(body) if body else "_（本会话暂无对话）_")
    return "\n\n".join(parts) + "\n"


def default_path(session_id: str, full: bool = False) -> str:
    """未指定路径时的默认导出位置(outputs/ 下,按会话 ID 命名)。"""
    suffix = ".full.md" if full else ".md"
    sid = (session_id or "session").strip() or "session"
    return f"outputs/chat_{sid}{suffix}"
