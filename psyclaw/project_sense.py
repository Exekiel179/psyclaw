"""本地项目感知 —— 让模型"看得见"文件夹结构(用户实测痛点:psyclaw 感知不到本地目录)。

此前模型上下文里**没有任何项目结构**:path_ingest 只认消息里显式写出的路径,auto-loop 只认
特定输入模式——用户问"我项目里有什么/帮我看看这个文件夹",模型只能瞎猜。本模块补上:

- ``scan_tree``  有界目录扫描(限深度/条目;跳过 .git/__pycache__ 等噪声)→ 结构 dict,可单测。
- ``render_tree``  紧凑文本树(按目录聚合,同后缀多文件折叠计数,控 token)。
- ``project_brief``  拼 ``<project_structure>`` 块 → REPL 每轮注入 system(有界,~1500 字符)。

隐私纪律:**data/raw 只报文件数,不列文件名**(文件名可能含被试编号等敏感信息),内容更不读;
其余目录也只列名字与大小,从不读内容(读内容是 @file / read_file 工具的事,由用户显式发起)。
"""

from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {".git", "__pycache__", ".psyclaw", "node_modules", ".venv", "venv",
              ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "logs"}
MAX_DEPTH = 3
MAX_ENTRIES = 150
BRIEF_CHARS = 1500


def _is_raw(rel: Path) -> bool:
    parts = [p.lower() for p in rel.parts]
    return "data" in parts and "raw" in parts


def scan_tree(project_dir: str = ".", max_depth: int = MAX_DEPTH,
              max_entries: int = MAX_ENTRIES) -> dict:
    """有界扫描 → {root, dirs: {相对目录: [文件名…]}, n_dirs, n_files, truncated, raw_note}。

    data/raw 记 ``raw_note``(N 个文件)而**不列名**;超出 max_entries 置 truncated 停扫。
    """
    root = Path(project_dir).resolve()
    dirs: dict[str, list[str]] = {}
    n_files = 0
    truncated = False
    raw_count = 0

    def walk(d: Path, depth: int) -> None:
        nonlocal n_files, truncated, raw_count
        if truncated or depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        rel = d.relative_to(root)
        key = str(rel).replace("\\", "/") if str(rel) != "." else "."
        for p in entries:
            if n_files + len(dirs) >= max_entries:
                truncated = True
                return
            if p.is_dir():
                if p.name in _SKIP_DIRS or p.name.startswith("."):
                    continue
                if _is_raw(p.relative_to(root)):
                    try:
                        raw_count += sum(1 for x in p.rglob("*") if x.is_file())
                    except OSError:
                        pass
                    continue          # 受保护:不下钻、不列名
                walk(p, depth + 1)
            else:
                if _is_raw(p.relative_to(root)):
                    raw_count += 1
                    continue
                dirs.setdefault(key, []).append(p.name)
                n_files += 1

    walk(root, 1)
    return {"root": str(root), "dirs": dirs, "n_dirs": len(dirs),
            "n_files": n_files, "truncated": truncated,
            "raw_note": (f"data/raw/({raw_count} 个文件,受保护:不列名不读内容)"
                         if raw_count else "")}


def _fold(names: list[str], per_dir: int = 12) -> str:
    """同目录文件列表:超出上限按后缀折叠计数。"""
    if len(names) <= per_dir:
        return ", ".join(names)
    shown = names[:per_dir]
    from collections import Counter
    rest = Counter((Path(n).suffix or "无后缀") for n in names[per_dir:])
    tail = " ".join(f"+{c}个{s}" for s, c in rest.most_common(4))
    return ", ".join(shown) + f" …({tail})"


def render_tree(tree: dict) -> str:
    """紧凑文本树(每目录一行,文件折叠)。"""
    lines = [f"{tree['root']}/"]
    for d in sorted(tree["dirs"]):
        files = tree["dirs"][d]
        prefix = "  " if d == "." else f"  {d}/ "
        lines.append(f"{prefix}{_fold(files)}")
    if tree.get("raw_note"):
        lines.append(f"  {tree['raw_note']}")
    if tree.get("truncated"):
        lines.append(f"  …(超出 {MAX_ENTRIES} 条,已截断;用 list_dir 工具看子目录)")
    return "\n".join(lines)


def project_brief(project_dir: str = ".", budget: int = BRIEF_CHARS) -> str:
    """给 system 提示的项目结构块(有界;扫描失败返回空串,绝不阻塞对话)。"""
    try:
        tree = scan_tree(project_dir)
    except Exception:  # noqa: BLE001
        return ""
    if not tree["dirs"] and not tree.get("raw_note"):
        return ""
    body = render_tree(tree)
    if len(body) > budget:
        body = body[:budget] + "\n  …(已截断)"
    return ("# 当前项目结构(自动感知,只含名字不含内容;要读内容用 @<路径> 引用)\n"
            + body)
