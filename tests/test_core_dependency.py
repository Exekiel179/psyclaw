"""守护:prompt_toolkit 是唯一内置第三方核心依赖(用户拍板)。

防未来会话按旧铁律「纯 stdlib 核」把它从 dependencies 误删——那会让实时命令下拉 +
中文输入退回 readline 降级(用户实测过的两个 bug 复发)。统计库仍不得进 dependencies。
"""
from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _deps() -> list[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"].get("dependencies", [])


def test_prompt_toolkit_is_core_dependency():
    deps = " ".join(_deps()).lower()
    assert "prompt_toolkit" in deps or "prompt-toolkit" in deps


def test_no_stats_lib_in_core_deps():
    # 统计库铁律:不得进核心 dependencies(只能在 [stats] extra)
    joined = " ".join(_deps()).lower()
    for banned in ("pingouin", "scipy", "statsmodels", "numpy", "pandas", "lifelines"):
        assert banned not in joined, f"统计库 {banned} 不该进核心依赖(应在 [stats] extra)"
