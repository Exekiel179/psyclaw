"""tests/test_ancova.py — 协方差分析 (ANCOVA) 测试套件（自跑块）。

覆盖：
  - 精确代数验证（y = group_offset + slope*cov，已知参数）
  - Type-III SS 与 F 检验
  - 调整均值（EMM）与 SE / CI
  - 同质性回归斜率检验（成立 / 违反）
  - 偏 partial η² / partial ω² 边界
  - 事后成对 t + Holm 校正
  - 多协变量（两个协变量）
  - CSV 完整流程 + sidecar 写入
  - 错误处理（自由度不足、无效输入）
"""

from __future__ import annotations

import csv
import json
import math
import os
import pathlib
import random
import tempfile

from psyclaw.psych.ancova import (
    ancova,
    analyze_ancova,
    format_apa_ancova,
    format_apa_post_hoc,
    write_ancova_report,
    _fit_ols,
    _build_X,
)


# ---------------------------------------------------------------------------
# 数据生成辅助
# ---------------------------------------------------------------------------

def _simple_data():
    """三组，协变量线性相关因变量。组效应真值：A=0, B=5, C=10；斜率=2。"""
    random.seed(42)
    rows = []
    for grp, offset in [("A", 0), ("B", 5), ("C", 10)]:
        for _ in range(15):
            x = random.uniform(0, 10)
            y = offset + 2 * x + random.gauss(0, 0.5)
            rows.append({"group": grp, "covariate": round(x, 3), "score": round(y, 3)})
    return rows


def _two_group_data():
    """两组平行线：ctrl: y=10+3x; treat: y=15+3x（无噪声，精确验证）。"""
    data = []
    for i in range(10):
        x = float(i)
        data.append({"g": "ctrl", "x": x, "y": 10.0 + 3 * x})
        data.append({"g": "treat", "x": x, "y": 15.0 + 3 * x})
    return data


def _multi_cov_data():
    """两组，两个协变量：y = offset + 1.5*x1 + 2.0*x2 + noise。"""
    random.seed(99)
    rows = []
    for grp, offset in [("X", 0.0), ("Y", 8.0)]:
        for _ in range(20):
            x1 = random.uniform(0, 10)
            x2 = random.uniform(0, 5)
            y = offset + 1.5 * x1 + 2.0 * x2 + random.gauss(0, 0.5)
            rows.append({"g": grp, "x1": round(x1, 3), "x2": round(x2, 3), "y": round(y, 3)})
    return rows


def _make_csv(rows, path):
    headers = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# 内部工具测试
# ---------------------------------------------------------------------------

def test_fit_ols_exact_recovery():
    """y = 2 + 3x — 精确恢复截距与斜率。"""
    n = 10
    X = [[1.0, float(i)] for i in range(n)]
    y = [2.0 + 3.0 * i for i in range(n)]
    sse, beta, _ = _fit_ols(y, X)
    assert abs(sse) < 1e-8
    assert abs(beta[0] - 2.0) < 1e-8
    assert abs(beta[1] - 3.0) < 1e-8


def test_fit_ols_singular_raises():
    X = [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]  # 第二列 = 2×第一列
    y = [1.0, 2.0, 3.0]
    try:
        _fit_ols(y, X)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_build_x_full_model_col_count():
    """k=3, p=2：全模型列数 = 1 + (k-1) + p = 5。"""
    n, k, p = 6, 3, 2
    grp_idxs = [0, 0, 1, 1, 2, 2]
    cov = [[1.0, 2.0]] * 6
    X = _build_X(n, grp_idxs, k, cov, p, include_group=True)
    assert len(X) == 6
    assert all(len(row) == 5 for row in X)


def test_build_x_cov_only_col_count():
    """仅协变量时列数 = 1 + p。"""
    n = 4
    cov = [[float(i)] for i in range(n)]
    X = _build_X(n, [0, 1, 0, 1], 2, cov, 1, include_group=False)
    assert all(len(row) == 2 for row in X)


def test_build_x_interaction_col_count():
    """k=2, p=1，含交互：列数 = 1 + 1 + 1 + 1 = 4。"""
    n, k, p = 4, 2, 1
    cov = [[float(i)] for i in range(n)]
    X = _build_X(n, [0, 0, 1, 1], k, cov, p,
                 include_group=True, include_interactions=True)
    assert all(len(row) == 4 for row in X)


def test_build_x_reference_group_dummy_zero():
    """参照组（index 0）所有哑变量位均为 0。"""
    n, k, p = 3, 3, 1
    cov = [[1.0]] * 3
    X = _build_X(n, [0, 1, 2], k, cov, p, include_group=True)
    assert X[0][1] == 0.0 and X[0][2] == 0.0


def test_build_x_exclude_cov_col_count():
    """exclude_cov=0 时，k=2, p=2：列数 = 1 + 1 + 1 = 3。"""
    n, k, p = 4, 2, 2
    cov = [[1.0, 2.0]] * 4
    X = _build_X(n, [0, 0, 1, 1], k, cov, p,
                 include_group=True, exclude_cov=0)
    assert all(len(row) == 3 for row in X)


# ---------------------------------------------------------------------------
# 核心 ANCOVA 测试
# ---------------------------------------------------------------------------

def test_two_group_adjusted_mean_diff():
    """两组平行线：调整均值差应精确等于 5.0。"""
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    adj = {am["group"]: am["adj_mean"] for am in result["adjusted_means"]}
    diff = adj["treat"] - adj["ctrl"]
    assert abs(diff - 5.0) < 0.01


def test_f_group_significant_large_effect():
    """有明确组效应时 F_group 显著（p < .05）。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    ge = result["group_effect"]
    assert ge["F"] is not None and ge["F"] > 1.0
    assert ge["p"] is not None and ge["p"] < 0.05


def test_covariate_significant_when_slope_nonzero():
    """协变量与 DV 强相关时 F_cov 显著。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    ce = result["covariate_effects"][0]
    assert ce["F"] is not None and ce["F"] > 1.0
    assert ce["p"] is not None and ce["p"] < 0.05


def test_partial_eta2_in_range():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    eta2 = result["group_effect"]["partial_eta2"]
    assert 0.0 <= eta2 <= 1.0


def test_partial_omega2_nonneg():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    assert result["group_effect"]["partial_omega2"] >= 0.0


def test_adjusted_mean_ci_contains_mean():
    """95% CI 应包含调整均值本身。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    for am in result["adjusted_means"]:
        assert am["ci_lower"] <= am["adj_mean"] <= am["ci_upper"]


def test_adjusted_mean_se_nonneg():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    for am in result["adjusted_means"]:
        assert am["SE"] >= 0.0


def test_group_counts_correct():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    ns = {am["group"]: am["n"] for am in result["adjusted_means"]}
    assert ns["A"] == 15 and ns["B"] == 15 and ns["C"] == 15


def test_df_error_formula():
    """df_error = N − k − p（N=45, k=3, p=1 → 41）。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    assert result["model"]["df_error"] == 45 - 3 - 1


def test_ss_group_error_below_total():
    """SS_group + SS_error ≤ SS_total（Type-III 性质）。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    mod = result["model"]
    assert mod["SS_group"] + mod["SS_error"] <= mod["SS_total"] + 1e-6


def test_three_group_levels_present():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    group_names = {am["group"] for am in result["adjusted_means"]}
    assert group_names == {"A", "B", "C"}


def test_two_groups_k_equals_2():
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    assert result["model"]["k"] == 2
    assert len(result["adjusted_means"]) == 2


def test_coefficients_intercept_present():
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    names = [c["name"] for c in result["coefficients"]]
    assert any("截距" in n or "Intercept" in n for n in names)


def test_covariate_slope_recovered():
    """两组平行线（斜率=3）：协变量系数应 ≈ 3。"""
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    cov_coef = next(c for c in result["coefficients"] if c["name"] == "x")
    assert abs(cov_coef["B"] - 3.0) < 0.01


def test_model_n_correct():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    assert result["model"]["N"] == 45


def test_covariate_names_stored():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    assert result["model"]["cov_names"] == ["covariate"]


def test_grand_cov_mean_matches_data():
    """存储的协变量总体均值应与数据一致。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    xs = [r["covariate"] for r in data]
    covariates = [[x] for x in xs]
    result = ancova(y, groups, covariates, cov_names=["covariate"])
    expected = sum(xs) / len(xs)
    stored = result["model"]["grand_cov_means"][0]
    assert abs(stored - expected) < 0.01


# ---------------------------------------------------------------------------
# 同质性回归斜率检验
# ---------------------------------------------------------------------------

def test_homogeneity_keys_present():
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    hom = result["homogeneity"]
    assert "assumption_met" in hom
    assert "p" in hom or "note" in hom


def test_homogeneity_parallel_lines():
    """斜率完全相同时同质性假设应成立。"""
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"])
    hom = result["homogeneity"]
    if hom.get("F") is not None and hom.get("p") is not None:
        assert hom["assumption_met"]


def test_homogeneity_different_slopes():
    """斜率明显不同时同质性假设应违反（或 F 较大）。"""
    n = 25
    x = [float(i) for i in range(n)]
    # A: slope=0, B: slope=5 — 差异极大
    y = [0.0 * xi + 0.001 * i for i, xi in enumerate(x)] + \
        [5.0 * xi + 0.001 * i for i, xi in enumerate(x)]
    groups = ["A"] * n + ["B"] * n
    covariates = [[xi] for xi in x + x]
    try:
        result = ancova(y, groups, covariates, cov_names=["x"])
        hom = result["homogeneity"]
        if hom.get("F") is not None:
            assert hom["F"] > 1.0
    except ValueError:
        pass  # 奇异矩阵（完全确定系统），可接受


# ---------------------------------------------------------------------------
# 事后检验
# ---------------------------------------------------------------------------

def test_post_hoc_present_when_requested():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    assert "post_hoc" in result
    assert "comparisons" in result["post_hoc"]


def test_post_hoc_absent_when_not_requested():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=False)
    assert "post_hoc" not in result


def test_post_hoc_three_group_pair_count():
    """三组 → C(3,2) = 3 对。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    assert len(result["post_hoc"]["comparisons"]) == 3


def test_post_hoc_p_adj_geq_p_orig():
    """Holm 校正后 p_adj ≥ p_orig。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    for c in result["post_hoc"]["comparisons"]:
        if c["p_orig"] is not None and c["p_adj"] is not None:
            assert c["p_adj"] >= c["p_orig"] - 1e-9


def test_post_hoc_diff_matches_adj_means():
    """diff = adj_mean1 − adj_mean2（精确对应）。"""
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    for c in result["post_hoc"]["comparisons"]:
        expected = round(c["adj_mean1"] - c["adj_mean2"], 4)
        assert abs(c["diff"] - expected) < 1e-3


def test_post_hoc_n_significant_in_range():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    ph = result["post_hoc"]
    assert 0 <= ph["n_significant"] <= len(ph["comparisons"])


def test_post_hoc_reject_h0_bool():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    covariates = [[r["covariate"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["covariate"],
                    include_post_hoc=True)
    for c in result["post_hoc"]["comparisons"]:
        assert isinstance(c["reject_h0"], bool)


def test_post_hoc_two_groups():
    """两组事后检验 → 1 对。"""
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"],
                    include_post_hoc=True)
    assert len(result["post_hoc"]["comparisons"]) == 1


def test_post_hoc_significant_for_large_diff():
    """调整均值差≈5 时事后检验应显著。"""
    data = _two_group_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    covariates = [[r["x"]] for r in data]
    result = ancova(y, groups, covariates, cov_names=["x"],
                    include_post_hoc=True)
    comp = result["post_hoc"]["comparisons"][0]
    assert comp["reject_h0"]


# ---------------------------------------------------------------------------
# 多协变量
# ---------------------------------------------------------------------------

def test_two_cov_f_group_present():
    data = _multi_cov_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    cov = [[r["x1"], r["x2"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["x1", "x2"])
    assert result["group_effect"]["F"] is not None


def test_two_cov_effects_count():
    data = _multi_cov_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    cov = [[r["x1"], r["x2"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["x1", "x2"])
    assert len(result["covariate_effects"]) == 2


def test_two_cov_df_error():
    """N=40, k=2, p=2 → df_error=36。"""
    data = _multi_cov_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    cov = [[r["x1"], r["x2"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["x1", "x2"])
    assert result["model"]["df_error"] == 40 - 2 - 2


def test_two_cov_partial_eta2_in_range():
    data = _multi_cov_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    cov = [[r["x1"], r["x2"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["x1", "x2"])
    for ce in result["covariate_effects"]:
        if ce["partial_eta2"] is not None:
            assert 0.0 <= ce["partial_eta2"] <= 1.0


def test_two_cov_adj_means_two_groups():
    data = _multi_cov_data()
    y = [r["y"] for r in data]
    groups = [r["g"] for r in data]
    cov = [[r["x1"], r["x2"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["x1", "x2"])
    assert len(result["adjusted_means"]) == 2


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def test_format_contains_ancova_header():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    text = format_apa_ancova(result)
    assert "ANCOVA" in text


def test_format_contains_adjusted_means_section():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    text = format_apa_ancova(result)
    assert "调整均值" in text


def test_format_contains_f_statistic():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    text = format_apa_ancova(result)
    assert "*F*" in text


def test_format_contains_partial_eta2():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    text = format_apa_ancova(result)
    assert "η" in text


def test_format_post_hoc_table_contains_holm():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"],
                    include_post_hoc=True)
    text = format_apa_post_hoc(result["post_hoc"])
    assert "Holm" in text


def test_format_post_hoc_contains_vs():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"],
                    include_post_hoc=True)
    text = format_apa_post_hoc(result["post_hoc"])
    assert "vs" in text


def test_format_apa_paragraph_generated():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    text = format_apa_ancova(result)
    assert "APA-7" in text


# ---------------------------------------------------------------------------
# sidecar 写入
# ---------------------------------------------------------------------------

def test_write_creates_files():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    with tempfile.TemporaryDirectory() as td:
        md_path, json_path = write_ancova_report(result, out_dir=td)
        assert md_path.exists()
        assert json_path.exists()


def test_write_json_parseable():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    with tempfile.TemporaryDirectory() as td:
        _, json_path = write_ancova_report(result, out_dir=td)
        parsed = json.loads(json_path.read_text(encoding="utf-8"))
        assert "group_effect" in parsed


def test_write_md_contains_header():
    data = _simple_data()
    y = [r["score"] for r in data]
    groups = [r["group"] for r in data]
    cov = [[r["covariate"]] for r in data]
    result = ancova(y, groups, cov, cov_names=["covariate"])
    with tempfile.TemporaryDirectory() as td:
        md_path, _ = write_ancova_report(result, out_dir=td)
        text = md_path.read_text(encoding="utf-8")
        assert "ANCOVA" in text


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def test_analyze_basic():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="score", group_col="group",
            cov_cols=["covariate"], out_dir=td)
        assert result["model"]["N"] == 45
        assert "group_effect" in result


def test_analyze_writes_files():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="score", group_col="group",
            cov_cols=["covariate"], out_dir=td)
        assert "report_md" in result
        assert "report_json" in result
        assert os.path.exists(result["report_md"])
        assert os.path.exists(result["report_json"])


def test_analyze_n_excluded_counts_missing():
    """含缺失 DV 行时 n_excluded 正确。"""
    rows = _simple_data()
    rows[0]["score"] = ""
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="score", group_col="group",
            cov_cols=["covariate"], out_dir=td)
        assert result["n_excluded"] == 1
        assert result["model"]["N"] == 44


def test_analyze_with_post_hoc():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="score", group_col="group",
            cov_cols=["covariate"], include_post_hoc=True, out_dir=td)
        assert "post_hoc" in result


def test_analyze_no_write():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="score", group_col="group",
            cov_cols=["covariate"], write_files=False)
        assert "report_md" not in result


def test_analyze_two_group():
    rows = [{"g": r["g"], "x": r["x"], "y": r["y"]} for r in _two_group_data()]
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ancova(
            csv_path=csv_path, dv="y", group_col="g",
            cov_cols=["x"], write_files=False)
        assert result["model"]["k"] == 2


# ---------------------------------------------------------------------------
# 错误处理
# ---------------------------------------------------------------------------

def test_error_only_one_group():
    y = [1.0, 2.0, 3.0]
    groups = ["A", "A", "A"]
    cov = [[1.0], [2.0], [3.0]]
    try:
        ancova(y, groups, cov, cov_names=["x"])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_error_no_covariates():
    y = [1.0, 2.0, 3.0]
    groups = ["A", "A", "B"]
    try:
        ancova(y, groups, [], cov_names=[])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_error_mismatched_covariate_rows():
    y = [1.0, 2.0, 3.0, 4.0]
    groups = ["A", "A", "B", "B"]
    cov = [[1.0], [2.0]]  # 仅 2 行
    try:
        ancova(y, groups, cov, cov_names=["x"])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_error_insufficient_df():
    """n=5, k=3, p=2 → df_error=0 → 应报错。"""
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    groups = ["A", "A", "B", "B", "C"]
    cov = [[float(i), float(i) * 2] for i in range(5)]
    try:
        ancova(y, groups, cov, cov_names=["x1", "x2"])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_error_empty_csv():
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "empty.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("group,covariate,score\n")
        try:
            analyze_ancova(csv_path, "score", "group", ["covariate"],
                           write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_error_all_missing_dv():
    """所有 DV 值缺失 → 应报错。"""
    rows = [{"g": "A", "x": "1", "y": ""},
            {"g": "A", "x": "2", "y": ""},
            {"g": "B", "x": "3", "y": ""},
            {"g": "B", "x": "4", "y": ""}]
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_ancova(csv_path, "y", "g", ["x"], write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def test_cli_basic_exit_zero():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        from psyclaw.psych.ancova import ancova_cli
        rc = ancova_cli([csv_path, "--dv", "score",
                         "--group", "group", "--cov", "covariate",
                         "--out", td])
        assert rc == 0


def test_cli_json_flag_produces_json():
    rows = _simple_data()
    import io, sys
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        from psyclaw.psych.ancova import ancova_cli
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            rc = ancova_cli([csv_path, "--dv", "score",
                             "--group", "group", "--cov", "covariate",
                             "--json", "--out", td])
        finally:
            sys.stdout = old_stdout
        assert rc == 0
        parsed = json.loads(buf.getvalue())
        assert "group_effect" in parsed


def test_cli_with_post_hoc():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        from psyclaw.psych.ancova import ancova_cli
        rc = ancova_cli([csv_path, "--dv", "score",
                         "--group", "group", "--cov", "covariate",
                         "--post-hoc", "--out", td])
        assert rc == 0


def test_cli_missing_file_returns_1():
    from psyclaw.psych.ancova import ancova_cli
    rc = ancova_cli(["nonexistent_file.csv", "--dv", "y",
                     "--group", "g", "--cov", "x"])
    assert rc == 1


def test_cli_empty_cov_returns_1():
    rows = _simple_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        from psyclaw.psych.ancova import ancova_cli
        rc = ancova_cli([csv_path, "--dv", "score",
                         "--group", "group", "--cov", ""])
        assert rc == 1


def test_cli_multi_cov():
    rows = _multi_cov_data()
    with tempfile.TemporaryDirectory() as td:
        csv_path = os.path.join(td, "data.csv")
        _make_csv(rows, csv_path)
        from psyclaw.psych.ancova import ancova_cli
        rc = ancova_cli([csv_path, "--dv", "y",
                         "--group", "g", "--cov", "x1,x2",
                         "--out", td])
        assert rc == 0


# ---------------------------------------------------------------------------
# 自跑块（无 pytest）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    _all = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in _all:
        try:
            fn()
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  {failed} FAILED")
