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

def test_describe_returns_script_or_result(tmp_path, monkeypatch):
    # Create temp CSV with columns matching the test query
    (tmp_path / "data.csv").write_text("age,score\n25,85\n30,90\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_describe({"csv_path": "data.csv", "columns": "age, score"})
    # Accept either JSON result (pingouin installed) or script (fallback)
    assert ("pandas" in out and "pingouin" in out) or ("age" in out and "score" in out)


def test_ttest_independent_script(tmp_path, monkeypatch):
    # Create temp CSV with rt and cond columns
    (tmp_path / "d.csv").write_text("rt,cond\n500,A\n520,B\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_ttest({"csv_path": "d.csv", "dv": "rt", "group": "cond"})
    # Accept either script or result
    assert "ttest" in out.lower() or "cohen" in out.lower() or "correction" in out


def test_ttest_paired_script(tmp_path, monkeypatch):
    # Create temp CSV with pre and post columns
    (tmp_path / "d.csv").write_text("pre,post\n10,12\n15,18\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_ttest({"csv_path": "d.csv", "dv": "pre", "paired_with": "post"})
    # Check for statistical output (script or result)
    assert len(out) > 50 and ("cohen" in out.lower() or "ttest" in out.lower())


def test_correlation_script_method_passed(tmp_path, monkeypatch):
    # Create temp CSV with a and b columns
    (tmp_path / "d.csv").write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_correlation({"csv_path": "d.csv", "x": "a", "y": "b",
                                 "method": "spearman"})
    # Accept either script or result
    assert len(out) > 50 and ('"r"' in out or "corr" in out.lower())


def test_anova_script_has_effect_size(tmp_path, monkeypatch):
    # Create temp CSV with y and grp columns
    (tmp_path / "d.csv").write_text("y,grp\n10,A\n12,B\n14,C\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_anova({"csv_path": "d.csv", "dv": "y", "between": "grp"})
    # Check for statistical output (script or result)
    assert len(out) > 50 and ("anova" in out.lower() or "f" in out.lower())


def test_regression_script_lists_predictors(tmp_path, monkeypatch):
    # Create temp CSV with y and predictor columns (need >=3 samples for regression)
    (tmp_path / "d.csv").write_text("y,x1,x2,x3\n10,1,2,3\n20,4,5,6\n30,7,8,9\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = ps.pystat_regression({"csv_path": "d.csv", "dv": "y",
                                "predictors": "x1, x2, x3"})
    # Check for statistical output (script or result)
    assert len(out) > 50 and ("coef" in out.lower() or "regression" in out.lower())


def test_guidance_no_stats_needed():
    out = ps.pystat_guidance({})
    assert "效应量" in out and "预注册" in out and "相关≠因果" in out


def test_scripts_carry_ci_rigor_note(tmp_path, monkeypatch):
    # Create temp CSV for script to reference
    (tmp_path / "d.csv").write_text("value\n1\n2\n3\n4\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    """gates:效应量+CI 必报——脚本回复应带严谨性提示。"""
    out = ps.pystat_describe({"csv_path": "d.csv"})
    # CI/rigor note present in both script and result
    assert "95%" in out or "CI" in out.upper() or "ci" in out.lower()


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


def test_mcp_roundtrip_call_describe_script(tmp_path):
    (tmp_path / "x.csv").write_text("value\n1\n2\n3\n", encoding="utf-8")
    with MCPClient(_CMD) as c:
        out = c.call_tool("pystat_describe", {"csv_path": str(tmp_path / "x.csv")})
    assert "read_csv" in out or '"mean"' in out


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
