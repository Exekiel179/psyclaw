#!/usr/bin/env python3
"""PostToolUse check — 编辑后立即对改动的 psyclaw/*.py 做字节码编译校验。

复刻 init.sh 的 fail-fast 门禁（compileall），把它下沉到每次编辑：
语法/缩进错误在引入的瞬间就反馈给 Claude 修复，而非拖到会话末尾。

退出码 2 + stderr → Claude 会看到编译错误并修正。
只校验 psyclaw/ 下的 .py，其余一律放行。
"""
import json
import os
import py_compile
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path or not path.endswith(".py"):
        return 0
    if not os.path.exists(path):
        return 0  # 删除/移动等，无可编译对象

    cwd = payload.get("cwd") or os.getcwd()
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(cwd)).replace(os.sep, "/")
    if not rel.startswith("psyclaw/"):
        return 0

    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as exc:
        sys.stderr.write(f"[compile-check] {rel} 编译失败，请修复：\n{exc.msg}\n")
        return 2
    except SyntaxError as exc:
        sys.stderr.write(f"[compile-check] {rel} 语法错误：{exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
