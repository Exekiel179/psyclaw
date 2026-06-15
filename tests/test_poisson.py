"""测试泊松回归模块（psyclaw/psych/poisson.py）— P18-1。

金标准（手算精确）：
  - 单二元预测变量饱和模型：logμ = β0 + β1·x（x∈{0,1}）
    MLE 给出 exp(β0) = ȳ(x=0)，exp(β0+β1) = ȳ(x=1)
    取 x=0 组 y=[1,2,3]（ȳ=2），x=1 组 y=[4,6,8]（ȳ=6）
    → β0 = log 2 ≈ 0.693147，β1 = log 3 ≈ 1.098612，IRR(β1) = 3.0
  - 仅截距模型：β0 = log(ȳ)
  - IRR = exp(B) 精确
  - 偏差 ≥ 0；null_deviance − deviance = lr_chi2
  - chi2_sf(0, df) = 1；normal_quantile(0.975) ≈ 1.96
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.poisson import (
    _chi2_sf,
    _mat_invert,
    _normal_quantile,
    _normal_sf,
    _poisson_deviance,
    _poisson_loglik,
    _safe_exp,
    _json_safe,
    poisson_regression,
    format_apa_poisson,
    write_poisson_report,
    analyze_poisson,
    poisson_cli,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _binary_data():
    """x=0 组 y=[1,2,3]，x=1 组 y=[4,6,8]（饱和模型金标准）。"""
    xs = [0, 0, 0, 1, 1, 1]
    ys = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
    X = [[1.0, float(x)] for x in xs]
    return X, ys


# ---------------------------------------------------------------------------
# 数学工具
# ---------------------------------------------------------------------------

def test_safe_exp_normal():
    assert abs(_safe_exp(0.0) - 1.0) < 1e-12
    assert abs(_safe_exp(1.0) - math.e) < 1e-12


def test_safe_exp_overflow():
    assert _safe_exp(1000.0) == math.inf
    assert _safe_exp(-1000.0) == 0.0


def test_normal_sf_zero():
    assert abs(_normal_sf(0.0) - 0.5) < 1e-6


def test_normal_sf_196():
    # P(Z > 1.96) ≈ 0.025
    assert abs(_normal_sf(1.96) - 0.025) < 1e-3


def test_normal_sf_symmetry():
    assert abs(_normal_sf(1.5) - _normal_sf(-1.5)) < 1e-12


def test_normal_quantile_median():
    assert abs(_normal_quantile(0.5)) < 1e-6


def test_normal_quantile_975():
    assert abs(_normal_quantile(0.975) - 1.96) < 1e-2


def test_normal_quantile_monotone():
    assert _normal_quantile(0.1) < _normal_quantile(0.9)


def test_chi2_sf_zero():
    assert _chi2_sf(0.0, 1) == 1.0
    assert _chi2_sf(-5.0, 3) == 1.0


def test_chi2_sf_critical_df1():
    # χ²(1) 临界值 3.841 → p ≈ 0.05
    assert abs(_chi2_sf(3.841, 1) - 0.05) < 1e-3


def test_chi2_sf_critical_df2():
    # χ²(2) 临界值 5.991 → p ≈ 0.05
    assert abs(_chi2_sf(5.991, 2) - 0.05) < 1e-3


def test_chi2_sf_monotone():
    assert _chi2_sf(2.0, 2) > _chi2_sf(8.0, 2)


def test_chi2_sf_range():
    p = _chi2_sf(4.0, 3)
    assert 0.0 <= p <= 1.0


def test_mat_invert_identity():
    M = [[2.0, 0.0], [0.0, 4.0]]
    inv = _mat_invert(M)
    assert abs(inv[0][0] - 0.5) < 1e-12
    assert abs(inv[1][1] - 0.25) < 1e-12


def test_mat_invert_singular():
    M = [[1.0, 2.0], [2.0, 4.0]]
    assert _mat_invert(M) is None


# ---------------------------------------------------------------------------
# 泊松偏差与对数似然
# ---------------------------------------------------------------------------

def test_loglik_perfect_fit_handles_zero():
    # 含 y=0 不应崩溃
    ll = _poisson_loglik([0.0, 1.0, 2.0], [1.0, 1.0, 1.0])
    assert math.isfinite(ll)


def test_deviance_nonnegative():
    d = _poisson_deviance([1.0, 2.0, 3.0], [1.5, 2.0, 2.5])
    assert d >= 0.0


def test_deviance_zero_when_mu_equals_y():
    # μ = y → 完美拟合 → 偏差 = 0
    d = _poisson_deviance([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert abs(d) < 1e-9


def test_deviance_zero_y_term():
    # y=0 时 y·log(y/μ) → 0，偏差应只剩 2μ
    d = _poisson_deviance([0.0], [2.0])
    assert abs(d - 4.0) < 1e-9   # 2 * (-(0-2)) = 4


# ---------------------------------------------------------------------------
# 核心：饱和二元模型金标准
# ---------------------------------------------------------------------------

def test_binary_intercept_recovers_log2():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["coef"][0] - math.log(2.0)) < 1e-6


def test_binary_slope_recovers_log3():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["coef"][1] - math.log(3.0)) < 1e-6


def test_binary_irr_is_3():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["irr"][1] - 3.0) < 1e-5


def test_binary_intercept_irr_is_2():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["irr"][0] - 2.0) < 1e-5


def test_binary_converges():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["convergence"] is True


def test_irr_equals_exp_coef():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for j in range(len(r["coef"])):
        assert abs(r["irr"][j] - math.exp(r["coef"][j])) < 1e-9


def test_irr_ci_brackets_irr():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for j in range(len(r["coef"])):
        assert r["irr_ci_lower"][j] <= r["irr"][j] <= r["irr_ci_upper"][j]


def test_ci_brackets_coef():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for j in range(len(r["coef"])):
        assert r["ci_lower"][j] <= r["coef"][j] <= r["ci_upper"][j]


# ---------------------------------------------------------------------------
# 仅截距模型
# ---------------------------------------------------------------------------

def test_intercept_only_recovers_log_mean():
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    X = [[1.0] for _ in y]
    r = poisson_regression(X, y, predictor_names=[])
    assert abs(r["coef"][0] - math.log(3.0)) < 1e-6   # ȳ=3


def test_intercept_only_lr_df_zero():
    y = [1.0, 2.0, 3.0]
    X = [[1.0] for _ in y]
    r = poisson_regression(X, y, predictor_names=[])
    assert r["lr_df"] == 0
    assert math.isnan(r["lr_p"])


def test_intercept_only_lr_chi2_zero():
    y = [2.0, 2.0, 2.0, 2.0]
    X = [[1.0] for _ in y]
    r = poisson_regression(X, y, predictor_names=[])
    assert abs(r["lr_chi2"]) < 1e-6


# ---------------------------------------------------------------------------
# 模型拟合统计
# ---------------------------------------------------------------------------

def test_deviance_nonneg_model():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["deviance"] >= 0.0
    assert r["null_deviance"] >= 0.0


def test_lr_chi2_equals_dev_difference():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["lr_chi2"] - (r["null_deviance"] - r["deviance"])) < 1e-6


def test_lr_chi2_nonnegative():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["lr_chi2"] >= 0.0


def test_lr_df_equals_predictors():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["lr_df"] == 1


def test_mcfadden_range():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert 0.0 <= r["mcfadden_r2"] <= 1.0


def test_aic_bic_formula():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    k = 2
    assert abs(r["aic"] - (-2.0 * r["log_lik_model"] + 2.0 * k)) < 1e-9
    assert abs(r["bic"] - (-2.0 * r["log_lik_model"] + k * math.log(r["n"]))) < 1e-9


def test_ll_model_geq_ll_null():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["log_lik_model"] >= r["log_lik_null"] - 1e-9


def test_z_equals_coef_over_se():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for j in range(len(r["coef"])):
        if r["se"][j] > 0 and math.isfinite(r["se"][j]):
            assert abs(r["z"][j] - r["coef"][j] / r["se"][j]) < 1e-9


def test_p_two_sided():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for j in range(len(r["coef"])):
        if math.isfinite(r["p"][j]):
            assert 0.0 <= r["p"][j] <= 1.0


def test_result_keys_present():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    for key in ("term_names", "coef", "se", "z", "p", "irr", "deviance",
                "null_deviance", "lr_chi2", "aic", "bic", "dispersion",
                "overdispersed", "pearson_chi2", "mean_y", "sum_y"):
        assert key in r


def test_term_names_include_intercept():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    assert r["term_names"] == ["(Intercept)", "grp"]


def test_mean_and_sum_y():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert abs(r["sum_y"] - 24.0) < 1e-9
    assert abs(r["mean_y"] - 4.0) < 1e-9


# ---------------------------------------------------------------------------
# 过度离散诊断
# ---------------------------------------------------------------------------

def test_overdispersion_detected():
    # 极端聚集计数 → φ >> 1.5
    y = [0.0, 0.0, 0.0, 0.0, 0.0, 30.0, 0.0, 0.0, 0.0, 0.0]
    X = [[1.0] for _ in y]
    r = poisson_regression(X, y, predictor_names=[])
    assert r["dispersion"] > 1.5
    assert r["overdispersed"] is True


def test_dispersion_formula():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    df = r["n"] - len(r["coef"])
    assert abs(r["dispersion"] - r["pearson_chi2"] / df) < 1e-9


def test_dispersion_finite():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert math.isfinite(r["dispersion"])


def test_pearson_chi2_nonnegative():
    X, y = _binary_data()
    r = poisson_regression(X, y)
    assert r["pearson_chi2"] >= 0.0


# ---------------------------------------------------------------------------
# 显著性方向（强信号）
# ---------------------------------------------------------------------------

def test_strong_positive_effect_significant():
    # 大样本强信号，β1 应显著为正
    xs = [0.0] * 50 + [1.0] * 50
    ys = [2.0] * 50 + [10.0] * 50
    X = [[1.0, x] for x in xs]
    r = poisson_regression(X, ys, predictor_names=["grp"])
    assert r["coef"][1] > 0
    assert r["p"][1] < 0.05


def test_no_effect_not_significant():
    # 两组计数相同 → β1 ≈ 0
    xs = [0.0] * 30 + [1.0] * 30
    ys = [3.0] * 30 + [3.0] * 30
    X = [[1.0, x] for x in xs]
    r = poisson_regression(X, ys, predictor_names=["grp"])
    assert abs(r["coef"][1]) < 1e-4


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def test_format_returns_str():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    out = format_apa_poisson(r, dv_name="errors")
    assert isinstance(out, str) and len(out) > 0


def test_format_contains_irr_header():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    out = format_apa_poisson(r)
    assert "IRR" in out


def test_format_contains_dv_name():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    out = format_apa_poisson(r, dv_name="symptom_count")
    assert "symptom_count" in out


def test_format_contains_model_fit():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    out = format_apa_poisson(r)
    assert "McFadden" in out and "AIC" in out


def test_format_overdispersion_warning():
    y = [0.0, 0.0, 0.0, 0.0, 0.0, 30.0, 0.0, 0.0, 0.0, 0.0]
    X = [[1.0] for _ in y]
    r = poisson_regression(X, y, predictor_names=[])
    out = format_apa_poisson(r)
    assert "overdispersion" in out.lower()


def test_format_dispersion_ok_text():
    xs = [0.0] * 30 + [1.0] * 30
    ys = [3.0] * 30 + [3.0] * 30
    X = [[1.0, x] for x in xs]
    r = poisson_regression(X, ys, predictor_names=["grp"])
    out = format_apa_poisson(r)
    assert "equidispersion" in out.lower()


def test_format_significant_predictor_text():
    xs = [0.0] * 50 + [1.0] * 50
    ys = [2.0] * 50 + [10.0] * 50
    X = [[1.0, x] for x in xs]
    r = poisson_regression(X, ys, predictor_names=["grp"])
    out = format_apa_poisson(r, dv_name="count")
    assert "grp" in out and "IRR" in out


# ---------------------------------------------------------------------------
# JSON 安全 + 报告写出
# ---------------------------------------------------------------------------

def test_json_safe_replaces_nan_inf():
    obj = {"a": float("nan"), "b": float("inf"), "c": [1.0, float("-inf")]}
    safe = _json_safe(obj)
    assert safe["a"] is None
    assert safe["b"] is None
    assert safe["c"][1] is None
    assert safe["c"][0] == 1.0


def test_write_report_creates_files():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    with tempfile.TemporaryDirectory() as d:
        paths = write_poisson_report(r, out_dir=d, dv_name="errors")
        assert Path(paths["md"]).exists()
        assert Path(paths["json"]).exists()


def test_write_report_valid_json():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    with tempfile.TemporaryDirectory() as d:
        paths = write_poisson_report(r, out_dir=d)
        data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert "coef" in data
        assert "mu" not in data   # mu 不写入 sidecar


def test_write_report_no_dir_returns_empty():
    X, y = _binary_data()
    r = poisson_regression(X, y, predictor_names=["grp"])
    paths = write_poisson_report(r, out_dir=None)
    assert paths == {}


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def test_analyze_basic():
    rows = [
        {"errs": 1, "grp": 0}, {"errs": 2, "grp": 0}, {"errs": 3, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1}, {"errs": 8, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        out = analyze_poisson(str(csv_path), "errs", ["grp"])
        r = out["result"]
        assert abs(r["coef"][1] - math.log(3.0)) < 1e-6
        assert r["dv"] == "errs"


def test_analyze_excludes_missing():
    rows = [
        {"errs": 1, "grp": 0}, {"errs": 2, "grp": 0},
        {"errs": "", "grp": 1}, {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        out = analyze_poisson(str(csv_path), "errs", ["grp"])
        assert out["result"]["n_excluded"] == 1
        assert out["result"]["n"] == 4


def test_analyze_rejects_negative():
    rows = [
        {"errs": -1, "grp": 0}, {"errs": 2, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        try:
            analyze_poisson(str(csv_path), "errs", ["grp"])
            assert False, "应对负值报错"
        except ValueError as e:
            assert "负值" in str(e)


def test_analyze_rejects_non_integer():
    rows = [
        {"errs": 1.5, "grp": 0}, {"errs": 2, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        try:
            analyze_poisson(str(csv_path), "errs", ["grp"])
            assert False, "应对非整数报错"
        except ValueError as e:
            assert "整数" in str(e)


def test_analyze_rejects_all_zero():
    rows = [
        {"errs": 0, "grp": 0}, {"errs": 0, "grp": 0},
        {"errs": 0, "grp": 1}, {"errs": 0, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        try:
            analyze_poisson(str(csv_path), "errs", ["grp"])
            assert False, "应对全 0 报错"
        except ValueError as e:
            assert "全为 0" in str(e)


def test_analyze_too_few_cases():
    rows = [{"errs": 5, "grp": 0}]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        try:
            analyze_poisson(str(csv_path), "errs", ["grp"])
            assert False, "应对样本不足报错"
        except ValueError as e:
            assert "完整案例不足" in str(e)


def test_analyze_writes_sidecar():
    rows = [
        {"errs": 1, "grp": 0}, {"errs": 2, "grp": 0}, {"errs": 3, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1}, {"errs": 8, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        analyze_poisson(str(csv_path), "errs", ["grp"], out_dir=d)
        assert (Path(d) / "poisson_report.md").exists()
        assert (Path(d) / "poisson_report.json").exists()


def test_analyze_multiple_predictors():
    rows = [
        {"y": 1, "a": 0, "b": 1}, {"y": 2, "a": 0, "b": 2},
        {"y": 3, "a": 1, "b": 1}, {"y": 5, "a": 1, "b": 2},
        {"y": 2, "a": 0, "b": 3}, {"y": 6, "a": 1, "b": 3},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        out = analyze_poisson(str(csv_path), "y", ["a", "b"])
        r = out["result"]
        assert len(r["coef"]) == 3
        assert r["term_names"] == ["(Intercept)", "a", "b"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_runs(capsys):
    rows = [
        {"errs": 1, "grp": 0}, {"errs": 2, "grp": 0}, {"errs": 3, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1}, {"errs": 8, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        rc = poisson_cli([str(csv_path), "--dv", "errs", "--iv", "grp"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "IRR" in out


def test_cli_json(capsys):
    rows = [
        {"errs": 1, "grp": 0}, {"errs": 2, "grp": 0}, {"errs": 3, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1}, {"errs": 8, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        rc = poisson_cli([str(csv_path), "--dv", "errs", "--iv", "grp", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "coef" in data


def test_cli_bad_dv_returns_1(capsys):
    rows = [
        {"errs": -1, "grp": 0}, {"errs": 2, "grp": 0},
        {"errs": 4, "grp": 1}, {"errs": 6, "grp": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "data.csv"
        _make_csv(rows, csv_path)
        rc = poisson_cli([str(csv_path), "--dv", "errs", "--iv", "grp"])
        assert rc == 1
