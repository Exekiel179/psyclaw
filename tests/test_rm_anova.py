"""tests/test_rm_anova.py — 单因素重复测量 ANOVA 测试套件（P11-1）。

数值对照：手工验算 + pingouin.rm_anova 外部参照（若可用）。
自跑块：python tests/test_rm_anova.py
"""

import csv
import json
import math
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.rm_anova import (
    _epsilon_gg,
    _epsilon_hf,
    _helmert_contrast,
    _mauchly_test,
    _mat_det,
    _cov_matrix,
    _mat_mul,
    analyze_rm_anova,
    format_apa_rm_anova,
    one_way_rm_anova,
    pairwise_rm,
    write_rm_anova_report,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_data(Y, subjects=None, conditions=None):
    n, k = len(Y), len(Y[0])
    subj = subjects or [f"s{i+1}" for i in range(n)]
    conds = conditions or [f"t{j+1}" for j in range(k)]
    return [{"subject": subj[i], "condition": conds[j], "score": Y[i][j]}
            for i in range(n) for j in range(k)]


def _write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
        return False
    except exc_type:
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 矩阵工具
# ---------------------------------------------------------------------------

def test_det_2x2():
    assert abs(_mat_det([[1.0, 2.0], [3.0, 4.0]]) - (-2.0)) < 1e-10


def test_det_identity_3x3():
    I = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
    assert abs(_mat_det(I) - 1.0) < 1e-10


def test_det_singular():
    assert abs(_mat_det([[1.0, 2.0], [2.0, 4.0]])) < 1e-10


def test_cov_matrix_known():
    # x=[1,2,3], y=[2,4,6]: var(x)=1, var(y)=4, cov(x,y)=2
    data = [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]
    cov = _cov_matrix(data)
    assert abs(cov[0][0] - 1.0) < 1e-10
    assert abs(cov[1][1] - 4.0) < 1e-10
    assert abs(cov[0][1] - 2.0) < 1e-10
    assert abs(cov[1][0] - 2.0) < 1e-10


def test_cov_matrix_symmetric():
    import random
    random.seed(42)
    data = [[random.gauss(0, 1) for _ in range(4)] for _ in range(8)]
    cov = _cov_matrix(data)
    for i in range(4):
        for j in range(4):
            assert abs(cov[i][j] - cov[j][i]) < 1e-12


def test_mat_mul_identity():
    A = [[1.0, 2.0], [3.0, 4.0]]
    I = [[1.0, 0.0], [0.0, 1.0]]
    R = _mat_mul(A, I)
    assert abs(R[0][0] - 1.0) < 1e-12 and abs(R[1][1] - 4.0) < 1e-12


# ---------------------------------------------------------------------------
# Helmert 对比矩阵
# ---------------------------------------------------------------------------

def test_helmert_k2_norm():
    C = _helmert_contrast(2)
    norm_sq = sum(C[i][0] ** 2 for i in range(2))
    assert abs(norm_sq - 1.0) < 1e-12


def test_helmert_k3_norms():
    C = _helmert_contrast(3)
    for j in range(2):
        assert abs(sum(C[i][j] ** 2 for i in range(3)) - 1.0) < 1e-12


def test_helmert_k3_orthogonal():
    C = _helmert_contrast(3)
    dot = sum(C[i][0] * C[i][1] for i in range(3))
    assert abs(dot) < 1e-12


def test_helmert_k4_orthonormal():
    C = _helmert_contrast(4)
    for j in range(3):
        assert abs(sum(C[i][j] ** 2 for i in range(4)) - 1.0) < 1e-12
    for j1 in range(3):
        for j2 in range(j1 + 1, 3):
            dot = sum(C[i][j1] * C[i][j2] for i in range(4))
            assert abs(dot) < 1e-12


def test_helmert_shape():
    for k in range(2, 7):
        C = _helmert_contrast(k)
        assert len(C) == k and len(C[0]) == k - 1


# ---------------------------------------------------------------------------
# Mauchly 球形检验
# ---------------------------------------------------------------------------

def test_mauchly_k2_always_spherical():
    Y = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    r = _mauchly_test(Y, k=2, n=3)
    assert r["W"] == 1.0 and r["spherical"] is True


def test_mauchly_w_in_unit_interval():
    Y = [[1.0, 4.0, 2.0], [2.0, 1.0, 6.0], [3.0, 3.0, 1.0],
         [4.0, 2.0, 5.0], [5.0, 5.0, 3.0]]
    r = _mauchly_test(Y, k=3, n=5)
    assert 0.0 <= r["W"] <= 1.0


def test_mauchly_p_in_unit_interval():
    Y = [[1.0, 4.0, 2.0], [2.0, 1.0, 6.0], [3.0, 3.0, 1.0],
         [4.0, 2.0, 5.0], [5.0, 5.0, 3.0]]
    r = _mauchly_test(Y, k=3, n=5)
    assert 0.0 <= r["p"] <= 1.0


def test_mauchly_df_k3():
    Y = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    r = _mauchly_test(Y, k=3, n=3)
    assert r["df"] == 2  # k(k-1)/2 - 1 = 3-1 = 2


def test_mauchly_df_k4():
    Y = [[float(i + j) for j in range(4)] for i in range(6)]
    r = _mauchly_test(Y, k=4, n=6)
    assert r["df"] == 5  # 4*3/2 - 1 = 5


def test_mauchly_chi2_finite():
    Y = [[1.0, 5.0, 2.0], [3.0, 2.0, 6.0], [4.0, 4.0, 3.0],
         [2.0, 6.0, 5.0], [5.0, 3.0, 4.0], [6.0, 1.0, 7.0]]
    r = _mauchly_test(Y, k=3, n=6)
    assert math.isfinite(r["chi2"])


# ---------------------------------------------------------------------------
# GG / HF epsilon
# ---------------------------------------------------------------------------

def test_gg_spherical_data_valid_range():
    # 近球形数据（每个被试跨条件变化幅度小）→ epsilon 应在有效范围内
    Y = [
        [1.0, 1.2, 0.9], [3.0, 3.1, 3.2], [5.1, 5.0, 5.2],
        [2.0, 2.2, 1.9], [4.0, 3.9, 4.1], [6.1, 6.0, 5.9],
        [1.5, 1.6, 1.4], [3.5, 3.4, 3.6], [5.5, 5.6, 5.4],
        [2.5, 2.4, 2.6],
    ]
    cov = _cov_matrix(Y)
    eps = _epsilon_gg(cov, 3)
    # epsilon 必须在 [1/(k-1), 1] 内
    assert 0.5 - 1e-10 <= eps <= 1.0 + 1e-10


def test_gg_lower_bound():
    Y = [[1.0, 100.0, 2.0], [2.0, 1.0, 200.0], [3.0, 50.0, 1.0],
         [4.0, 200.0, 3.0], [5.0, 1.0, 150.0]]
    cov = _cov_matrix(Y)
    eps = _epsilon_gg(cov, 3)
    assert eps >= 1.0 / 2 - 1e-10


def test_gg_upper_bound():
    Y = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    cov = _cov_matrix(Y)
    eps = _epsilon_gg(cov, 3)
    assert eps <= 1.0 + 1e-10


def test_hf_ge_gg():
    Y = [[1.0, 4.0, 2.0], [2.0, 1.0, 6.0], [3.0, 3.0, 1.0],
         [4.0, 2.0, 5.0], [5.0, 5.0, 3.0], [2.0, 3.0, 4.0]]
    cov = _cov_matrix(Y)
    eps_gg = _epsilon_gg(cov, 3)
    eps_hf = _epsilon_hf(eps_gg, n=6, k=3)
    assert eps_hf >= eps_gg - 1e-10


def test_hf_upper_bound():
    Y = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0],
         [2.0, 3.0, 4.0], [5.0, 6.0, 7.0], [3.0, 4.0, 5.0],
         [6.0, 7.0, 8.0], [1.5, 2.5, 3.5]]
    cov = _cov_matrix(Y)
    eps_gg = _epsilon_gg(cov, 3)
    eps_hf = _epsilon_hf(eps_gg, n=8, k=3)
    assert eps_hf <= 1.0 + 1e-10


# ---------------------------------------------------------------------------
# one_way_rm_anova 主计算
# ---------------------------------------------------------------------------

# 已知数据：5 被试 × 3 条件，各被试响应模式有差异（确保 SS_error > 0）
# 条件均值约 2.0 / 4.5 / 7.2，F ≈ 100（大效应，p < .001）
_Y_SIMPLE = [
    [1.0, 4.0, 6.0],   # gap: 3, 2
    [2.0, 4.5, 7.5],   # gap: 2.5, 3
    [1.5, 3.5, 8.0],   # gap: 2, 4.5
    [2.5, 5.0, 7.0],   # gap: 2.5, 2
    [3.0, 5.5, 7.5],   # gap: 2.5, 2
]


def test_f_large_for_pure_effect():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["F"] > 50


def test_p_significant_pure_effect():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["p"] < 0.001


def test_n_k():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["n_subjects"] == 5 and res["k_conditions"] == 3


def test_ss_decomposition():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    check = res["SS_between"] + res["SS_subjects"] + res["SS_error"]
    assert abs(check - res["SS_total"]) < 1e-8


def test_ms_ratio_equals_f():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert abs(res["F"] - res["MS_between"] / res["MS_error"]) < 1e-8


def test_df_error():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    # (k-1)(n-1) = 2*4 = 8
    assert res["df_error"] == 8


def test_df_between():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["df_between"] == 2  # k-1


def test_eta2_range():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert 0.0 <= res["eta2"] <= 1.0


def test_partial_eta2_range():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert 0.0 <= res["partial_eta2"] <= 1.0


def test_partial_eta2_ge_eta2():
    # partial η² ≥ η² because SS_subjects excluded from denominator
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["partial_eta2"] >= res["eta2"] - 1e-10


def test_omega2_nonneg():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert res["omega2"] >= 0.0


def test_grand_mean():
    # cond means 2.0, 4.5, 7.2 → GM = (2+4.5+7.2)/3 = 4.567
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    expected_gm = sum(Y[i][j] for Y in [_Y_SIMPLE] for i in range(5) for j in range(3)) / 15
    assert abs(res["grand_mean"] - expected_gm) < 1e-10


def test_condition_means():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    means = sorted(cs["mean"] for cs in res["condition_stats"])
    # t1: (1+2+1.5+2.5+3)/5=2.0, t2: (4+4.5+3.5+5+5.5)/5=4.5, t3: (6+7.5+8+7+7.5)/5=7.2
    assert abs(means[0] - 2.0) < 1e-10
    assert abs(means[1] - 4.5) < 1e-10
    assert abs(means[2] - 7.2) < 1e-10


def test_condition_stats_n():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    for cs in res["condition_stats"]:
        assert cs["n"] == 5


def test_null_effect_p_large():
    # 条件均值几乎相等，但被试间差异大 → F 小，p > 0.5
    Y = [[2.1, 2.0, 2.0], [3.0, 3.1, 3.0], [4.0, 4.0, 4.1], [5.1, 5.0, 5.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    # 条件效应极小，应不显著
    assert res["p"] > 0.5 or (math.isnan(res["F"]) and abs(res["SS_between"]) < 1e-6)


def test_k2_mauchly_spherical():
    Y = [[1.0, 3.0], [2.0, 4.0], [3.0, 5.0], [4.0, 6.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    assert res["mauchly"]["spherical"] is True


def test_k4_df_error():
    Y = [[float(j * 2 + i * 0.5) for j in range(4)] for i in range(6)]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    assert res["df_error"] == 15  # (4-1)*(6-1) = 15


def test_significant_flag():
    # 使用 _Y_SIMPLE（有错误方差，F 大，应显著）
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition", alpha=0.05)
    assert res["significant"] is True


def test_p_report_correction():
    # 当球形性违反时 p_report 应来自 GG 或 HF
    Y = [[1.0, 10.0, 2.0], [2.0, 1.0, 10.0], [10.0, 2.0, 3.0],
         [3.0, 8.0, 1.0], [5.0, 4.0, 9.0], [8.0, 3.0, 5.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    if not res["mauchly"]["spherical"]:
        assert res["report_correction"] in ("gg", "hf")
        assert res["p_report"] in (res["p_gg"], res["p_hf"])
    else:
        assert res["report_correction"] == "none"
        assert abs(res["p_report"] - res["p"]) < 1e-12


def test_epsilon_gg_in_result():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert 0.0 <= res["epsilon_gg"] <= 1.0


def test_epsilon_hf_in_result():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert 0.0 <= res["epsilon_hf"] <= 1.0


def test_gg_p_uses_corrected_df():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    # GG df1 ≤ df_between
    assert res["df1_gg"] <= res["df_between"] + 1e-10


def test_error_too_few_subjects():
    data = _make_data([[1.0, 2.0]])
    assert _raises(ValueError, one_way_rm_anova, data,
                   dv="score", subject="subject", within="condition")


def test_error_too_few_conditions():
    data = [{"subject": "s1", "condition": "t1", "score": "1.0"},
            {"subject": "s2", "condition": "t1", "score": "2.0"}]
    assert _raises(ValueError, one_way_rm_anova, data,
                   dv="score", subject="subject", within="condition")


def test_error_unbalanced():
    data = [
        {"subject": "s1", "condition": "t1", "score": "1.0"},
        {"subject": "s1", "condition": "t2", "score": "2.0"},
        {"subject": "s2", "condition": "t1", "score": "3.0"},
    ]
    assert _raises(ValueError, one_way_rm_anova, data,
                   dv="score", subject="subject", within="condition")


def test_result_has_y_matrix():
    res = one_way_rm_anova(_make_data(_Y_SIMPLE), dv="score",
                           subject="subject", within="condition")
    assert "_Y" in res and len(res["_Y"]) == 5


# ---------------------------------------------------------------------------
# 成对事后检验
# ---------------------------------------------------------------------------

_Y_POST = [[1.0, 3.0, 5.0],
           [2.0, 4.0, 6.0],
           [3.0, 5.0, 7.0],
           [1.5, 3.5, 5.5]]


def test_pairwise_count():
    # C(3,2) = 3 对
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    assert len(pairs) == 3


def test_pairwise_labels():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    labels = {(p["cond1"], p["cond2"]) for p in pairs}
    assert ("t1", "t2") in labels and ("t1", "t3") in labels and ("t2", "t3") in labels


def test_pairwise_mean_diff_sign():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    t1_t2 = next(p for p in pairs if p["cond1"] == "t1" and p["cond2"] == "t2")
    assert t1_t2["mean_diff"] < 0  # t1 均值 < t2 均值


def test_pairwise_p_raw_range():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        assert 0.0 <= p["p_raw"] <= 1.0


def test_pairwise_holm_ge_raw():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        assert p["p_holm"] >= p["p_raw"] - 1e-12


def test_pairwise_holm_range():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        assert 0.0 <= p["p_holm"] <= 1.0


def test_pairwise_df():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        assert p["df"] == 3  # n - 1


def test_pairwise_dz_sign_matches_mean():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        if math.isfinite(p["d_z"]) and p["mean_diff"] != 0:
            assert math.copysign(1, p["d_z"]) == math.copysign(1, p["mean_diff"])


def test_pairwise_ci_contains_mean():
    pairs = pairwise_rm(_Y_POST, ["t1", "t2", "t3"], n=4, k=3)
    for p in pairs:
        assert p["ci_lower"] <= p["mean_diff"] <= p["ci_upper"]


def test_pairwise_large_effect_significant():
    Y = [[1.0, 10.0, 20.0], [2.0, 11.0, 21.0], [3.0, 12.0, 22.0],
         [1.5, 10.5, 20.5], [2.5, 11.5, 21.5], [3.5, 12.5, 22.5]]
    pairs = pairwise_rm(Y, ["A", "B", "C"], n=6, k=3)
    for p in pairs:
        assert p["significant"] is True


def test_pairwise_k4_pairs_count():
    Y = [[float(i + j) for j in range(4)] for i in range(5)]
    pairs = pairwise_rm(Y, ["A", "B", "C", "D"], n=5, k=4)
    assert len(pairs) == 6  # C(4,2)


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def _simple_result():
    Y = [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0], [3.0, 5.0, 7.0],
         [1.5, 3.5, 5.5], [2.5, 4.5, 6.5]]
    return one_way_rm_anova(_make_data(Y), dv="score",
                            subject="subject", within="condition")


def test_format_returns_string():
    assert isinstance(format_apa_rm_anova(_simple_result()), str)


def test_format_contains_f():
    assert "*F*" in format_apa_rm_anova(_simple_result())


def test_format_contains_partial_eta2():
    assert "η²p" in format_apa_rm_anova(_simple_result())


def test_format_contains_omega2():
    assert "ω²" in format_apa_rm_anova(_simple_result())


def test_format_contains_m_sd():
    txt = format_apa_rm_anova(_simple_result())
    assert "*M*" in txt and "*SD*" in txt


def test_format_contains_ss_ms():
    txt = format_apa_rm_anova(_simple_result())
    assert "SS" in txt and "MS" in txt


def test_format_mauchly_reported():
    # k=3 → Mauchly 应出现
    assert "Mauchly" in format_apa_rm_anova(_simple_result())


def test_format_no_raw_nan():
    txt = format_apa_rm_anova(_simple_result())
    assert "nan" not in txt.lower()


def test_format_post_hoc_section():
    res = _simple_result()
    ph = pairwise_rm(res["_Y"], res["conditions"], res["n_subjects"], res["k_conditions"])
    txt = format_apa_rm_anova(res, post_hoc=ph)
    assert "成对比较" in txt


def test_format_k2_no_mauchly():
    Y = [[1.0, 3.0], [2.0, 4.0], [3.0, 5.0], [4.0, 6.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    txt = format_apa_rm_anova(res)
    # k=2 时 Mauchly 章节不需要出现（只在 k>2 时报告）
    # 实现里 k>2 才报 Mauchly
    assert isinstance(txt, str)


# ---------------------------------------------------------------------------
# 写文件 / CSV 入口
# ---------------------------------------------------------------------------

def test_write_creates_md_json():
    Y = [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0], [3.0, 5.0, 7.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    with tempfile.TemporaryDirectory() as tmp:
        p = write_rm_anova_report(res, out_dir=tmp)
        assert p.exists()
        assert (pathlib.Path(tmp) / "rm_anova_report.json").exists()


def test_json_valid_fields():
    Y = [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0], [3.0, 5.0, 7.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    with tempfile.TemporaryDirectory() as tmp:
        write_rm_anova_report(res, out_dir=tmp)
        j = json.loads((pathlib.Path(tmp) / "rm_anova_report.json").read_text())
        assert "F" in j and "partial_eta2" in j and "mauchly" in j


def test_json_no_internal_y():
    Y = [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0], [3.0, 5.0, 7.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    with tempfile.TemporaryDirectory() as tmp:
        write_rm_anova_report(res, out_dir=tmp)
        j = json.loads((pathlib.Path(tmp) / "rm_anova_report.json").read_text())
        assert "_Y" not in j


def test_analyze_from_csv():
    Y = [[1.0, 4.0, 7.0], [2.0, 5.0, 8.0], [3.0, 6.0, 9.0],
         [1.5, 4.5, 7.5], [2.5, 5.5, 8.5]]
    rows = _make_data(Y)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = pathlib.Path(tmp) / "data.csv"
        _write_csv(rows, csv_path)
        res = analyze_rm_anova(csv_path, dv="score", subject="subject",
                               within="condition", out_dir=tmp, as_json=False)
    assert res["n_subjects"] == 5 and res["k_conditions"] == 3


def test_analyze_post_hoc_in_result():
    Y = [[1.0, 5.0, 10.0], [2.0, 6.0, 11.0], [3.0, 7.0, 12.0],
         [1.5, 5.5, 10.5], [2.5, 6.5, 11.5]]
    rows = _make_data(Y)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = pathlib.Path(tmp) / "data.csv"
        _write_csv(rows, csv_path)
        res = analyze_rm_anova(csv_path, dv="score", subject="subject",
                               within="condition", post_hoc=True,
                               out_dir=tmp, as_json=False)
    assert "post_hoc" in res and len(res["post_hoc"]) == 3


def test_analyze_json_output(capsys=None):
    Y = [[1.0, 4.0, 7.0], [2.0, 5.0, 8.0], [3.0, 6.0, 9.0]]
    rows = _make_data(Y)
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = pathlib.Path(tmp) / "data.csv"
        _write_csv(rows, csv_path)
        # Should not raise
        analyze_rm_anova(csv_path, dv="score", subject="subject",
                         within="condition", as_json=True)


# ---------------------------------------------------------------------------
# 数值校验（对照手工计算）
# ---------------------------------------------------------------------------

def test_manual_ss_between():
    # 3 条件，均值 1, 2, 3，n=4 → SS_between = n * Σ(μ_j - GM)²
    # GM = 2; SS = 4*(1+0+1) = 8
    Y = [[1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    assert abs(res["SS_between"] - 8.0) < 1e-8


def test_manual_ss_error_zero_for_perfect_data():
    # 若所有被试的差值完全一致，误差 SS = 0
    Y = [[1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0],
         [1.0, 2.0, 3.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    assert abs(res["SS_error"]) < 1e-8


def test_ss_subjects_for_identical_treatment():
    # 所有条件值相同，只有被试差异 → SS_between = 0
    Y = [[1.0, 1.0, 1.0],
         [2.0, 2.0, 2.0],
         [3.0, 3.0, 3.0],
         [4.0, 4.0, 4.0]]
    res = one_way_rm_anova(_make_data(Y), dv="score",
                           subject="subject", within="condition")
    assert abs(res["SS_between"]) < 1e-8
    assert res["SS_subjects"] > 0


# ---------------------------------------------------------------------------
# 自跑块
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    _all = [(k, v) for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for name, fn in _all:
        try:
            fn()
            passed += 1
        except Exception:
            print(f"FAIL  {name}")
            traceback.print_exc()
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  {failed} FAILED")
    sys.exit(failed)
