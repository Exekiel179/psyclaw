"""feat(method/样本量):生成委托 statsmodels 的功效分析脚本——统计外移。

守铁律:psyclaw 不算样本量(功效分析是统计),而是据检验类型+效应量+α+power 生成
一个委托 statsmodels.stats.power 的可复现脚本,由用户(或 MCP)跑,解出所需 N。
"""
from __future__ import annotations

from psyclaw.psych.power_script import generate_power_script


def test_returns_script_text():
    s = generate_power_script("t-ind", effect=0.5)
    assert isinstance(s, str) and len(s) > 100


def test_delegates_to_statsmodels_not_inline():
    s = generate_power_script("t-ind", effect=0.5)
    assert "statsmodels" in s and "solve_power" in s
    import psyclaw.psych.power_script as M
    import inspect
    src = inspect.getsource(M)
    for banned in ("import statsmodels", "import scipy", "import numpy"):
        assert banned not in src, f"生成器自身不该 import 统计库:{banned}"


def test_t_independent_uses_ttestpower():
    s = generate_power_script("t-ind", effect=0.5, alpha=0.05, power=0.8)
    assert "TTestIndPower" in s
    assert "0.5" in s and "0.05" in s and "0.8" in s


def test_anova_uses_ftest_with_groups():
    s = generate_power_script("anova", effect=0.25, groups=4)
    assert "FTestAnovaPower" in s
    assert "4" in s                       # k_groups


def test_correlation_supported():
    s = generate_power_script("correlation", effect=0.3)
    assert "0.3" in s and ("NormalIndPower" in s or "correlation" in s.lower())


def test_script_is_valid_python():
    for t in ("t-ind", "anova", "correlation"):
        compile(generate_power_script(t, effect=0.4), "<gen>", "exec")


def test_sensitivity_table_present():
    """脚本应给敏感性:不同效应量下的 N，避免只报一个点估计。"""
    s = generate_power_script("t-ind", effect=0.5)
    assert "敏感" in s or "sensitivity" in s.lower() or "for " in s


def test_unknown_test():
    s = generate_power_script("no-such-test", effect=0.5)
    assert s == "" or "未知" in s or "支持" in s
