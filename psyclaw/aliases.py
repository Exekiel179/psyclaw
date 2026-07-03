"""用户自定义命令别名 —— 机制可以复杂,命令要简单(v0.2)。

用户把常用长命令缩成自己的词,一行一条:

    # ~/.psyclaw/aliases.yaml(全局)或 <项目>/.psyclaw/aliases.yaml(项目级,覆盖全局)
    qc: check --journal xinlixuebao
    起跑: auto-loop --auto
    综述: lit-loop --skip-gates

之后 ``psyclaw qc 稿件.md`` == ``psyclaw check --journal xinlixuebao 稿件.md``
(别名展开后,余下参数原样追加)。

纪律:**内置命令优先**——别名不得覆盖真实子命令(与 plugins/skills 的防劫持一致);
文件坏了 fail-safe 当没有;解析用 shlex(带引号的参数正确切分)。纯函数,可单测。
"""

from __future__ import annotations

import shlex
from pathlib import Path


def alias_files(project_dir: str = ".") -> list[Path]:
    """别名文件(存在才返回):全局在前、项目在后(后者覆盖前者)。"""
    cands = [Path.home() / ".psyclaw" / "aliases.yaml",
             Path(project_dir) / ".psyclaw" / "aliases.yaml"]
    return [p for p in cands if p.is_file()]


def _parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        # errors="replace":文件编码坏了当没有,绝不阻塞 CLI(与 skills loader 同款)
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                out[k] = v
    except OSError:
        pass
    return out


def load_aliases(project_dir: str = ".") -> dict[str, str]:
    """合并全局 + 项目别名(项目覆盖全局)。失败返回 {},绝不阻塞 CLI。"""
    merged: dict[str, str] = {}
    for p in alias_files(project_dir):
        merged.update(_parse(p))
    return merged


def expand_alias(argv: list[str], aliases: dict[str, str],
                 builtin: set[str] | frozenset = frozenset()) -> list[str]:
    """若 argv[0] 是别名(且**不是**内置命令)→ 展开;余下参数原样追加。纯函数。"""
    if not argv or not aliases:
        return argv
    head = argv[0]
    if head in builtin or head.startswith("-"):
        return argv                      # 内置优先,别名不得劫持真实子命令
    target = aliases.get(head)
    if not target:
        return argv
    try:
        expanded = shlex.split(target)
    except ValueError:
        return argv                      # 别名定义坏了 → 原样(fail-safe)
    return expanded + argv[1:]
