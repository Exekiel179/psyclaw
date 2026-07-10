#!/usr/bin/env python3
"""PreToolUse guard — 保护 harness 真源与规范门禁不被误改。

拦截对以下路径的 Edit/Write，改为要求人工确认（permissionDecision: ask），
而非静默放行：
  - psyclaw/gates/**        学术规范门禁（rules.yaml / PSYCLAW.md / checker.py …）
  - feature_list.json       harness 状态真源
  - .claude/settings.json   权限与 hook 配置本身

CLAUDE.md 铁律：门禁只增不偷偷删；feature_list.json 是状态真源。
误改这些文件会静默破坏 harness 契约，所以走确认而不是硬拒绝——
显式想改时人工点通过即可。
"""
import json
import os
import sys

# 相对仓库根的受保护前缀 / 精确文件
PROTECTED_PREFIXES = ("psyclaw/gates/",)
PROTECTED_FILES = ("feature_list.json", ".claude/settings.json")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # 输入异常不阻断正常流程

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not path:
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(cwd))
    except Exception:
        rel = path
    rel = rel.replace(os.sep, "/")

    hit = rel in PROTECTED_FILES or any(rel.startswith(p) for p in PROTECTED_PREFIXES)
    if not hit:
        return 0

    reason = (
        f"'{rel}' 是 harness 真源/规范门禁文件（CLAUDE.md：门禁只增不偷偷删、"
        f"feature_list.json 为状态真源）。确认这是有意的改动吗？"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
