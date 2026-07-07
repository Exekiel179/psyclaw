"""pystat MCP 服务器测试(v0.8 feat-049)——降级脚本路径 + 工具注册 + 协议往返。

本机通常无 pingouin,故测试聚焦「降级为可运行脚本」路径(确定性)、工具 schema、
以及经 MCP client 真实 subprocess 往返;不依赖统计库是否安装。
"""
from __future__ import annotations

from pathlib import Path

import psyclaw.mcp.servers.pystat_server as ps
from psyclaw.mcp.client import MCPClient

_CMD = f"python {Path(ps.__file__)}"


# --- 降级脚本路径(无论 pingouin 在否都应给出可运行脚本/结果,不崩、不假装) --------

def test_describe_returns_script_or_result():
    out = ps.pystat_describe({"csv_path": "data.csv", "columns": "age, score"})
    assert "pandas" in out and "pingouin" in out
    assert "'age'" in out and "'score'" in out
    assert "compute_bootci" in out          # 均值 CI


def test_ttest_independent_script():
    out = ps.pystat_ttest({"csv_path": "d.csv", "dv": "rt", "group": "cond"})
    assert "pg.ttest" in out and "cohen-d" in out.lower() or "cohen" in out.lower()
    assert "correction='auto'" in out       # Welch 稳健


def test_ttest_paired_script():
    out = ps.pystat_ttest({"csv_path": "d.csv", "dv": "pre", "paired_with": "post"})
    assert "paired=True" in out


def test_correlation_script_method_passed():
    out = ps.pystat_correlation({"csv_path": "d.csv", "x": "a", "y": "b",
                                 "method": "spearman"})
    assert "pg.corr" in out and "spearman" in out


def test_anova_script_has_effect_size():
    out = ps.pystat_anova({"csv_path": "d.csv", "dv": "y", "between": "grp"})
    assert "pg.anova" in out and ("eta" in out.lower() or "np2" in out)
    assert "pairwise_tests" in out and "holm" in out    # 事后 + 校正


def test_regression_script_lists_predictors():
    out = ps.pystat_regression({"csv_path": "d.csv", "dv": "y",
                                "predictors": "x1, x2, x3"})
    assert "linear_regression" in out
    for p in ("'x1'", "'x2'", "'x3'"):
        assert p in out


def test_guidance_no_stats_needed():
    out = ps.pystat_guidance({})
    assert "效应量" in out and "预注册" in out and "相关≠因果" in out


def test_scripts_carry_ci_rigor_note():
    """gates:效应量+CI 必报——脚本回复应带严谨性提示。"""
    out = ps.pystat_describe({"csv_path": "d.csv"})
    assert "95%" in out or "CI" in out


# --- 协议往返(经 MCPClient 真实 subprocess) ------------------------------------

def test_mcp_roundtrip_lists_all_tools():
    with MCPClient(_CMD) as c:
        names = {t["name"] for t in c.list_tools()}
    assert {"pystat_describe", "pystat_ttest", "pystat_correlation",
            "pystat_anova", "pystat_regression", "pystat_guidance"} <= names


def test_mcp_roundtrip_call_guidance():
    with MCPClient(_CMD) as c:
        out = c.call_tool("pystat_guidance", {})
    assert "选检验" in out


def test_mcp_roundtrip_call_describe_script():
    with MCPClient(_CMD) as c:
        out = c.call_tool("pystat_describe", {"csv_path": "x.csv"})
    assert "read_csv" in out


# --- 顶层不 import 统计库(铁律:统计只在工具惰性发生) --------------------------

def test_module_does_not_import_stats_at_top_level():
    import ast
    src = Path(ps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    top_imports = []
    for node in tree.body:                      # 仅模块顶层
        if isinstance(node, ast.Import):
            top_imports += [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom):
            top_imports.append(node.module or "")
    for banned in ("pingouin", "pandas", "numpy", "scipy", "statsmodels"):
        assert banned not in top_imports, f"顶层不应 import {banned}"
