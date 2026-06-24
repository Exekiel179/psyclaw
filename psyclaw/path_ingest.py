"""REPL 本地文件路径检测与路由 (R-5)。

① 自动识别消息中的本地路径（绝对/相对/~展开/带引号/Windows 反斜杠）
② 数据文件（csv/tsv/xlsx/sav）→ 仅注入结构元数据，原始数据永不进入 LLM 上下文
   （守住「原始数据不入对话」隐私铁律 + 大文件不灌上下文）
③ 文本文件（md/txt/py 等）→ smart_excerpt 摘录入上下文
④ 只读，不改写原始文件；路径不存在/无权限给清晰报错
"""

from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

DATA_SUFFIXES: frozenset[str] = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".sav"})
TEXT_SUFFIXES: frozenset[str] = frozenset({
    ".md", ".txt", ".py", ".json", ".yaml", ".yml",
    ".pdf", ".r", ".do", ".tex", ".rst", ".log",
})


def _build_path_re() -> re.Pattern[str]:
    # 引号内允许反斜杠：Windows 绝对路径 "C:\dir\my file.csv" 必须能整段匹配
    quoted = r'"([^"]{3,250})"'
    single = r"'([^']{3,250})'"
    win_abs = r'([A-Za-z]:[/\\][^\s,;()\[\]"\'<>]{2,250})'
    unix_abs = r'(/(?:[^\s,;()\[\]"\'<>]{1,249}))'
    tilde = r'(~[^\s,;()\[\]"\'<>@\n]{1,250})'
    rel = r'(\.\.?/[^\s,;()\[\]"\'<>]{1,250})'
    return re.compile(
        r'(?:' + quoted + r'|' + single + r'|' + win_abs
        + r'|' + unix_abs + r'|' + tilde + r'|' + rel + r')',
        re.UNICODE,
    )


_PATH_RE = _build_path_re()
# 剥掉路径尾部的 ASCII 标点 + 常见中文标点
_STRIP_TRAIL = re.compile(r'[.,;:!?)\'\"。！？、，：；「」『』【】〔〕]+$')


def _expand_user(raw: str) -> Path:
    """展开前导 ~。优先用 $HOME(跨平台一致);否则退回 Path.expanduser()。

    Windows 的 Path.expanduser() 只认 USERPROFILE 而忽略 HOME,显式优先 HOME
    可让行为在三大平台一致(真实 Windows 用户通常无 HOME,自然退回 USERPROFILE)。
    """
    if raw == "~" or raw.startswith(("~/", "~\\")):
        home = os.environ.get("HOME")
        if home:
            rest = raw[1:].lstrip("/\\")
            return Path(home, rest) if rest else Path(home)
    return Path(raw).expanduser()


def extract_paths(text: str, cwd: Path | None = None) -> list[Path]:
    """从文本中提取所有候选本地文件路径（去重，按首次出现顺序）。

    只返回磁盘上实际存在的文件路径；不存在的候选路径不在此返回，
    但调用方可通过 process_message 获取带扩展名的不存在路径的错误。
    """
    base = cwd or Path.cwd()
    seen: set[Path] = set()
    result: list[Path] = []
    for match in _PATH_RE.finditer(text):
        raw = next(g for g in match.groups() if g is not None)
        raw = _STRIP_TRAIL.sub("", raw).strip()
        if not raw:
            continue
        p = _expand_user(raw)
        if not p.is_absolute():
            p = (base / p).resolve()
        if p in seen or not p.exists():
            continue
        seen.add(p)
        result.append(p)
    return result


def classify(path: Path) -> str:
    """路径分类。返回 'data' | 'text' | 'unknown'。"""
    s = path.suffix.lower()
    if s in DATA_SUFFIXES:
        return "data"
    if s in TEXT_SUFFIXES:
        return "text"
    return "unknown"


def _is_num(s: str) -> bool:
    # 'nan'/'inf' 虽能被 float() 解析，但在数据列类型判定里应视为非数值文本
    if s.strip().lower().lstrip("+-") in ("nan", "inf", "infinity"):
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _data_metadata(path: Path) -> str:
    """CSV/TSV 结构元数据摘要（仅列名+类型+行数，不含原始数据行）。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return f'<data_file path="{path}" error="权限拒绝"/>'
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    headers = list(reader.fieldnames or [])
    samples: list[dict] = []
    for i, row in enumerate(reader):
        if i >= 3:
            break
        samples.append(row)
    n_rows = raw.count("\n")

    col_info_parts: list[str] = []
    for h in headers[:20]:
        vals = [r.get(h, "").strip() for r in samples if r.get(h, "").strip()]
        typ = "数值" if vals and all(_is_num(v) for v in vals) else "文本"
        col_info_parts.append(f"{h}({typ})")
    col_info = ", ".join(col_info_parts)
    if len(headers) > 20:
        col_info += f" … 共 {len(headers)} 列"

    lines = [
        f'<data_file path="{path}" rows≈{n_rows} cols={len(headers)}>',
        f"列: {col_info}",
        "[⚠ 原始数据行未进入对话，数据隐私受保护]",
        f'[📊 全量分析: psyclaw describe "{path}" / '
        f'psyclaw stat "{path}" --dv <列> [--group <列>]]',
        "</data_file>",
    ]
    return "\n".join(lines)


def process_message(
    text: str, cwd: Path | None = None
) -> tuple[str, list[str]]:
    """检测消息中的本地路径并分类路由。

    Returns:
        (injected_context, user_errors)
        injected_context — 额外注入 LLM 上下文的字符串
        user_errors — 用户可见的错误/警告消息列表
    """
    from psyclaw.context import smart_excerpt

    base = cwd or Path.cwd()
    candidates = extract_paths(text, base)

    # 另收集候选路径中有已知后缀但不存在的路径（用于友好报错）
    missing_with_ext: list[Path] = []
    for match in _PATH_RE.finditer(text):
        raw = next(g for g in match.groups() if g is not None)
        raw = _STRIP_TRAIL.sub("", raw).strip()
        if not raw:
            continue
        p = _expand_user(raw)
        if not p.is_absolute():
            p = (base / p).resolve()
        if not p.exists() and p.suffix.lower() in DATA_SUFFIXES | TEXT_SUFFIXES:
            if p not in missing_with_ext:
                missing_with_ext.append(p)

    context_parts: list[str] = []
    errors: list[str] = []

    for path in candidates:
        if not path.is_file():
            continue
        kind = classify(path)
        if kind == "data":
            try:
                meta = _data_metadata(path)
                context_parts.append(meta)
                print(f"  [数据文件: {path.name} → 结构元数据注入上下文，原始数据受保护]")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"  [无法读取 {path}: {exc}]")
        elif kind == "text":
            try:
                excerpt = smart_excerpt(path)
                context_parts.append(excerpt)
                print(f"  [文本文件: {path.name}({len(excerpt)} 字符进上下文)]")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"  [无法读取 {path}: {exc}]")
        else:
            size = path.stat().st_size
            if size < 500_000:
                try:
                    excerpt = smart_excerpt(path)
                    context_parts.append(excerpt)
                    print(f"  [文件: {path.name}({len(excerpt)} 字符进上下文)]")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"  [无法读取 {path}: {exc}]")

    for mp in missing_with_ext:
        errors.append(f"  [文件未找到: {mp}]")

    injected = "\n\n".join(context_parts)
    return injected, errors
