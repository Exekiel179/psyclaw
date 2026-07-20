"""psyclaw/ 下的数据文件必须被 pyproject 的 package-data 覆盖(否则不进 wheel)。

历史事故:pyproject 只配了 packages.find,没配 package-data,导致 31 个数据文件
(gates/PSYCLAW.md + rules.yaml 判据本体、agent 提示词、methods/scales 等心理学数据、
全部 skill)统统不进 wheel——`uv tool install` 装出来的 psyclaw 没有 skill、
gates 无判据,而源码跑测试全绿,完全看不出来。

本测试静态校验:每个非 .py 数据文件都能被某条 package-data glob 匹配到。
新增数据文件用了没覆盖的扩展名(如 .csv/.toml)会立刻红。
"""
from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "psyclaw"


def _patterns() -> list[str]:
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pats = cfg["tool"]["setuptools"]["package-data"]["psyclaw"]
    assert pats, "pyproject 缺 [tool.setuptools.package-data].psyclaw"
    return pats


def _data_files() -> list[Path]:
    return [p for p in PKG.rglob("*")
            if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts]


def test_every_data_file_is_covered_by_package_data():
    pats = _patterns()
    missed = []
    for f in _data_files():
        rel = f.relative_to(PKG).as_posix()
        # setuptools 的 ** 递归 glob;用 fnmatch 近似(把 **/ 视作任意层级)
        if not any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(rel, p.replace("**/", ""))
                   for p in pats):
            missed.append(rel)
    assert not missed, f"这些数据文件不会进 wheel(补 package-data glob):{missed}"


def test_critical_data_files_exist():
    """判据/技能这些「少了就残」的文件本体必须在——防误删后测试仍绿。"""
    for rel in ("gates/PSYCLAW.md", "gates/rules.yaml",
                "skills/nature-review/SKILL.md", "psych/methods.json"):
        assert (PKG / rel).is_file(), f"关键数据文件缺失:{rel}"
