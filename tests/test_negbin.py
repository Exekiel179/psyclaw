"""测试负二项回归模块（psyclaw/psych/negbin.py）— P19-1。

金标准（手算精确，与 θ 无关——饱和模型的均值由 score 方程唯一确定）：
  - 单二元预测变量饱和模型：logμ = β0 + β1·x（x∈{0,1}）
    score 方程给出 exp(β0) = ȳ(x=0)，exp(β0+β1) = ȳ(x=1)
    取 x=0 组 y=[1,2,3]（ȳ=2），x=1 组 y=[4,6,8]（ȳ=6）
    → β0 = log 2，β1 = log 3，IRR(β1) = 3.0
  - 仅截距模型：β0 = log(ȳ)
  - IRR = exp(B) 精确
  - NB 嵌套泊松（θ→∞）：ll_NB ≥ ll_Poisson，故 α=0 边界 LR ≥ 0
  - 过度离散数据：θ 有限、α=1/θ>0、α=0 LR 检验显著
  - 偏差 ≥ 0
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.negbin import (
    _chi2_sf,
    _mat_invert,
    _mat_vec,
    _normal_quantile,
    _normal_sf,
    _safe_exp,
    _nb_loglik,
    _poisson_loglik,
    _nb_deviance,
    _fit_beta,
    _fit_theta,
    _eval_mu,
    _json_safe,
    negbin_regression,
    format_apa_negbin,
    write_negbin_report,
    analyze_negbin,
    negbin_cli,
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


def _overdispersed_data():
    """多数为 0、少数极大的强过度离散计数 + 一个连续预测变量。"""
    ys = [0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 0.0, 15.0, 0.0, 20.0, 0.0, 1.0]
    xs = [0.0, 1.0, 2.0, 0.0, 3.0, 1.0, 0.0, 9.0, 1.0, 10.0, 0.0, 2.0]
    X = [[1.0, x] for x in xs]
    return X, ys


def _overdispersed_intercept_data():
    """仅截距、极强过度离散（大量 0 + 两个极大值）——过度离散无歧义。"""
    ys = [0.0] * 14 + [30.0, 40.0]
    X = [[1.0]] * len(ys)
    return X, ys


# ---------------------------------------------------------------------------
# 数学工具（复用 poisson 同款，确认无回归）
# ---------------------------------------------------------------------------

def test_safe_exp_normal():
    assert abs(_safe_exp(0.0) - 1.0) < 1e-12
    assert abs(_safe_exp(1.0) - math.e) < 1e-9


def test_safe_exp_overflow_guard():
    assert _safe_exp(1000.0) == math.inf
    assert _safe_exp(-1000.0) == 0.0


def test_normal_sf_half_at_zero():
    assert abs(_normal_sf(0.0) - 0.5) < 1e-6


def test_normal_sf_196():
    # 双尾 0.05 → 单尾 0.025
    assert abs(_normal_sf(1.96) - 0.025) < 1e-3


def test_normal_quantile_975():
    assert abs(_normal_quantile(0.975) - 1.96) < 1e-3


def test_normal_quantile_median():
    assert abs(_normal_quantile(0.5)) < 1e-6


def test_chi2_sf_zero():
    assert _chi2_sf(0.0, 1) == 1.0
    assert _chi2_sf(-5.0, 2) == 1.0


def test_chi2_sf_critical_df1():
    # χ²(1) 临界值 3.841 → p ≈ 0.05
    assert abs(_chi2_sf(3.841, 1) - 0.05) < 1e-3


def test_chi2_sf_monotone():
    assert _chi2_sf(10.0, 1) < _chi2_sf(1.0, 1)


def test_mat_invert_identity():
    inv = _mat_invert([[1.0, 0.0], [0.0, 1.0]])
    assert abs(inv[0][0] - 1.0) < 1e-12
    assert abs(inv[1][1] - 1.0) < 1e-12


def test_mat_invert_singular():
    assert _mat_invert([[1.0, 2.0], [2.0, 4.0]]) is None


def test_mat_invert_known():
    inv = _mat_invert([[4.0, 7.0], [2.0, 6.0]])  # det=10
    assert abs(inv[0][0] - 0.6) < 1e-9
    assert abs(inv[0][1] + 0.7) < 1e-9
    assert abs(inv[1][0] + 0.2) < 1e-9
    assert abs(inv[1][1] - 0.4) < 1e-9


def test_mat_vec():
    out = _mat_vec([[1.0, 2.0], [3.0, 4.0]], [1.0, 1.0])
    assert out == [3.0, 7.0]


# ---------------------------------------------------------------------------
# 对数似然 / 偏差
# ---------------------------------------------------------------------------

def test_nb_loglik_finite():
    y = [1.0, 2.0, 3.0]
    mu = [2.0, 2.0, 2.0]
    assert math.isfinite(_nb_loglik(y, mu, 5.0))


def test_nb_approaches_poisson_large_theta():
    # θ→∞ 时 NB 对数似然趋近泊松对数似然
    y = [0.0, 1.0, 2.0, 3.0, 4.0]
    mu = [2.0, 2.0, 2.0, 2.0, 2.0]
    ll_nb = _nb_loglik(y, mu, 1e8)
    ll_pois = _poisson_loglik(y, mu)
    assert abs(ll_nb - ll_pois) < 1e-2


def test_nb_loglik_decreases_with_overdispersion_for_clustered_data():
    # 数据强过度离散时，较小 θ（更大方差）给更高似然
    y = [0.0, 0.0, 0.0, 10.0]
    mu = [2.5, 2.5, 2.5, 2.5]
    assert _nb_loglik(y, mu, 0.5) > _nb_loglik(y, mu, 100.0)


def test_poisson_loglik_handles_zero():
    assert math.isfinite(_poisson_loglik([0.0, 0.0], [1.0, 1.0]))


def test_nb_deviance_nonnegative():
    assert _nb_deviance([0.0, 1.0, 5.0], [1.0, 2.0, 3.0], 2.0) >= 0.0


def test_nb_deviance_zero_at_saturation():
    # μ = y（饱和）时偏差为 0
    y = [1.0, 2.0, 3.0]
    assert _nb_deviance(y, y, 4.0) < 1e-9


# ---------------------------------------------------------------------------
# θ 拟合（黄金分割）
# ---------------------------------------------------------------------------

def test_fit_theta_returns_positive():
    y = [0.0, 0.0, 1.0, 10.0]
    mu = [2.75, 2.75, 2.75, 2.75]
    th = _fit_theta(y, mu)
    assert th > 0


def test_fit_theta_maximizes_loglik():
    y = [0.0, 0.0, 1.0, 10.0]
    mu = [2.75, 2.75, 2.75, 2.75]
    th = _fit_theta(y, mu)
    # MLE 处似然不低于附近点
    assert _nb_loglik(y, mu, th) >= _nb_loglik(y, mu, th * 2) - 1e-6
    assert _nb_loglik(y, mu, th) >= _nb_loglik(y, mu, th / 2) - 1e-6


def test_fit_theta_large_for_equidispersed():
    # 近泊松（均值≈方差）数据 θ 应趋向上界
    y = [3.0, 3.0, 3.0, 3.0]
    mu = [3.0, 3.0, 3.0, 3.0]
    th = _fit_theta(y, mu)
    assert th > 100.0


# ---------------------------------------------------------------------------
# _fit_beta（给定 θ 的 Fisher scoring）
# ---------------------------------------------------------------------------

def test_fit_beta_intercept_recovers_mean():
    y = [1.0, 2.0, 3.0, 4.0, 6.0, 8.0]
    X = [[1.0]] * len(y)
    beta, conv = _fit_beta(X, y, 5.0, [0.0])
    assert abs(math.exp(beta[0]) - sum(y) / len(y)) < 1e-6


def test_fit_beta_independent_of_theta_for_saturated():
    # 饱和模型的 β 与 θ 无关
    X, y = _binary_data()
    b1, _ = _fit_beta(X, y, 0.5, [0.0, 0.0])
    b2, _ = _fit_beta(X, y, 50.0, [0.0, 0.0])
    assert abs(b1[0] - b2[0]) < 1e-6
    assert abs(b1[1] - b2[1]) < 1e-6


# ---------------------------------------------------------------------------
# 饱和二元金标准
# ---------------------------------------------------------------------------

def test_saturated_intercept_log2():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert abs(r["coef"][0] - math.log(2.0)) < 1e-6


def test_saturated_slope_log3():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert abs(r["coef"][1] - math.log(3.0)) < 1e-6


def test_saturated_irr_3():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert abs(r["irr"][1] - 3.0) < 1e-5


def test_saturated_intercept_irr_2():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert abs(r["irr"][0] - 2.0) < 1e-5


def test_saturated_irr_equals_exp_coef():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    for j in range(len(r["coef"])):
        assert abs(r["irr"][j] - math.exp(r["coef"][j])) < 1e-9


def test_saturated_fitted_means_match_group_means():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    mu = r["mu"]
    assert abs(sum(mu[:3]) / 3 - 2.0) < 1e-5
    assert abs(sum(mu[3:]) / 3 - 6.0) < 1e-5


# ---------------------------------------------------------------------------
# 仅截距模型
# ---------------------------------------------------------------------------

def test_intercept_only_beta_log_mean():
    y = [2.0, 4.0, 6.0, 8.0]
    X = [[1.0]] * len(y)
    r = negbin_regression(X, y, predictor_names=[])
    assert abs(r["coef"][0] - math.log(5.0)) < 1e-6


def test_intercept_only_lr_df_zero():
    y = [2.0, 4.0, 6.0, 8.0]
    X = [[1.0]] * len(y)
    r = negbin_regression(X, y, predictor_names=[])
    assert r["lr_df"] == 0


def test_intercept_only_n_terms():
    y = [2.0, 4.0, 6.0, 8.0]
    X = [[1.0]] * len(y)
    r = negbin_regression(X, y, predictor_names=[])
    assert r["term_names"] == ["(Intercept)"]


# ---------------------------------------------------------------------------
# 模型拟合统计
# ---------------------------------------------------------------------------

def test_result_keys_present():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    for key in ("coef", "se", "z", "p", "irr", "theta", "alpha_dispersion",
                "log_lik_model", "log_lik_poisson", "deviance", "null_deviance",
                "lr_chi2", "lr_df", "lr_p", "mcfadden_r2", "aic", "bic",
                "lr_alpha_chi2", "lr_alpha_p", "pearson_chi2", "df_resid"):
        assert key in r


def test_deviance_nonnegative():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert r["deviance"] >= 0.0
    assert r["null_deviance"] >= 0.0


def test_lr_chi2_nonnegative():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["lr_chi2"] >= 0.0


def test_lr_df_equals_predictor_count():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert r["lr_df"] == 1


def test_aic_bic_param_count_includes_theta():
    # AIC = -2ll + 2(k+1)，BIC = -2ll + (k+1)ln n
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    k = len(r["coef"])
    expected_aic = -2.0 * r["log_lik_model"] + 2.0 * (k + 1)
    expected_bic = -2.0 * r["log_lik_model"] + (k + 1) * math.log(r["n"])
    assert abs(r["aic"] - expected_aic) < 1e-9
    assert abs(r["bic"] - expected_bic) < 1e-9


def test_mcfadden_in_range():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["mcfadden_r2"] <= 1.0


def test_df_resid_formula():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["df_resid"] == r["n"] - len(r["coef"])


def test_n_and_mean():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert r["n"] == 6
    assert abs(r["mean_y"] - sum(y) / len(y)) < 1e-12


def test_alpha_dispersion_is_inverse_theta():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert abs(r["alpha_dispersion"] - 1.0 / r["theta"]) < 1e-9


def test_theta_positive():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["theta"] > 0.0


def test_convergence_flag_bool():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert isinstance(r["convergence"], bool)


def test_mu_length():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert len(r["mu"]) == len(y)


# ---------------------------------------------------------------------------
# NB 嵌套泊松 & α=0 边界检验
# ---------------------------------------------------------------------------

def test_nb_loglik_ge_poisson():
    # NB 嵌套泊松：ll_NB ≥ ll_Poisson
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["log_lik_model"] >= r["log_lik_poisson"] - 1e-6


def test_lr_alpha_nonnegative():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["lr_alpha_chi2"] >= 0.0


def test_overdispersion_detected_significant():
    # 极强过度离散数据 → α=0 检验显著、θ 有限、α>0
    X, y = _overdispersed_intercept_data()
    r = negbin_regression(X, y, predictor_names=[])
    assert r["theta"] < 1e6           # θ 有限
    assert r["alpha_dispersion"] > 0.0
    assert r["lr_alpha_chi2"] > 2.706  # χ̄²(1) 单尾 .05 临界
    assert r["lr_alpha_p"] < 0.05     # 拒绝 α=0


def test_lr_alpha_p_boundary_half():
    # 边界校正 p = ½·χ²₁ 生存函数（lr>0 时）
    X, y = _overdispersed_intercept_data()
    r = negbin_regression(X, y, predictor_names=[])
    assert r["lr_alpha_chi2"] > 0.0
    expected = 0.5 * _chi2_sf(r["lr_alpha_chi2"], 1)
    assert abs(r["lr_alpha_p"] - expected) < 1e-9


def test_equidispersed_alpha_not_significant():
    # 近泊松数据 → α=0 检验不显著
    y = [3.0, 2.0, 4.0, 3.0, 2.0, 4.0, 3.0, 3.0, 2.0, 4.0]
    X = [[1.0]] * len(y)
    r = negbin_regression(X, y, predictor_names=[])
    assert r["lr_alpha_p"] > 0.05


# ---------------------------------------------------------------------------
# 显著性方向
# ---------------------------------------------------------------------------

def test_positive_predictor_positive_coef():
    # 计数随 x 增大 → β1 > 0
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    assert r["coef"][1] > 0.0


def test_se_nonnegative():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    for s in r["se"]:
        assert (not math.isfinite(s)) or s >= 0.0


# ---------------------------------------------------------------------------
# format_apa_negbin
# ---------------------------------------------------------------------------

def test_format_returns_str():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    out = format_apa_negbin(r, dv_name="errors")
    assert isinstance(out, str) and len(out) > 0


def test_format_contains_table_header():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    out = format_apa_negbin(r)
    assert "Predictor" in out and "IRR" in out


def test_format_contains_dispersion():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    out = format_apa_negbin(r)
    assert "θ" in out and "α" in out


def test_format_contains_overdispersion_test():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    out = format_apa_negbin(r)
    assert "overdispersion" in out.lower()


def test_format_mentions_negative_binomial():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    out = format_apa_negbin(r, dv_name="errors")
    assert "egative binomial" in out
    assert "errors" in out


def test_format_significant_predictor_text():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    out = format_apa_negbin(r, dv_name="symptoms")
    # 表内含变量名
    assert "x" in out


# ---------------------------------------------------------------------------
# JSON 安全 + 报告写出
# ---------------------------------------------------------------------------

def test_json_safe_replaces_nan_inf():
    obj = {"a": float("nan"), "b": float("inf"), "c": [1.0, float("-inf")], "d": "x"}
    safe = _json_safe(obj)
    assert safe["a"] is None
    assert safe["b"] is None
    assert safe["c"] == [1.0, None]
    assert safe["d"] == "x"


def test_json_safe_roundtrip():
    X, y = _overdispersed_data()
    r = negbin_regression(X, y, predictor_names=["x"])
    payload = _json_safe({k: v for k, v in r.items() if k != "mu"})
    # 严格 JSON 合法（无 NaN/Inf）
    json.dumps(payload, allow_nan=False)


def test_write_report_creates_files():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    with tempfile.TemporaryDirectory() as d:
        paths = write_negbin_report(r, out_dir=d, dv_name="errors")
        assert Path(paths["md"]).exists()
        assert Path(paths["json"]).exists()
        # JSON 可解析
        json.loads(Path(paths["json"]).read_text(encoding="utf-8"))


def test_write_report_no_dir_returns_empty():
    X, y = _binary_data()
    r = negbin_regression(X, y, predictor_names=["grp"])
    assert write_negbin_report(r, out_dir=None) == {}


# ---------------------------------------------------------------------------
# analyze_negbin（CSV 主入口）
# ---------------------------------------------------------------------------

def test_analyze_basic():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": 3, "x": 0},
        {"y": 4, "x": 1}, {"y": 6, "x": 1}, {"y": 8, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        out = analyze_negbin(str(p), "y", ["x"])
        r = out["result"]
        assert abs(r["coef"][0] - math.log(2.0)) < 1e-6
        assert abs(r["irr"][1] - 3.0) < 1e-5


def test_analyze_excludes_missing():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": "", "x": 1},
        {"y": 4, "x": 1}, {"y": 6, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        out = analyze_negbin(str(p), "y", ["x"])
        assert out["result"]["n_excluded"] == 1
        assert out["result"]["n"] == 4


def test_analyze_rejects_negative():
    rows = [{"y": -1, "x": 0}, {"y": 2, "x": 1}, {"y": 3, "x": 1}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        try:
            analyze_negbin(str(p), "y", ["x"])
            assert False, "应对负值报错"
        except ValueError as e:
            assert "负值" in str(e)


def test_analyze_rejects_noninteger():
    rows = [{"y": 1.5, "x": 0}, {"y": 2, "x": 1}, {"y": 3, "x": 1}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        try:
            analyze_negbin(str(p), "y", ["x"])
            assert False, "应对非整数报错"
        except ValueError as e:
            assert "非整数" in str(e)


def test_analyze_rejects_all_zero():
    rows = [{"y": 0, "x": 0}, {"y": 0, "x": 1}, {"y": 0, "x": 1}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        try:
            analyze_negbin(str(p), "y", ["x"])
            assert False, "应对全 0 报错"
        except ValueError as e:
            assert "全为 0" in str(e)


def test_analyze_insufficient_rows():
    rows = [{"y": 5, "x": 0}]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        try:
            analyze_negbin(str(p), "y", ["x"])
            assert False, "应对样本不足报错"
        except ValueError as e:
            assert "完整案例不足" in str(e)


def test_analyze_writes_sidecar():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": 3, "x": 0},
        {"y": 4, "x": 1}, {"y": 6, "x": 1}, {"y": 8, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        analyze_negbin(str(p), "y", ["x"], out_dir=d)
        assert (Path(d) / "negbin_report.md").exists()
        assert (Path(d) / "negbin_report.json").exists()


def test_analyze_records_dv():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": 3, "x": 0},
        {"y": 4, "x": 1}, {"y": 6, "x": 1}, {"y": 8, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        out = analyze_negbin(str(p), "y", ["x"])
        assert out["result"]["dv"] == "y"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_basic_returns_zero():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": 3, "x": 0},
        {"y": 4, "x": 1}, {"y": 6, "x": 1}, {"y": 8, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        assert negbin_cli([str(p), "--dv", "y", "--iv", "x"]) == 0


def test_cli_json_returns_zero():
    rows = [
        {"y": 1, "x": 0}, {"y": 2, "x": 0}, {"y": 3, "x": 0},
        {"y": 4, "x": 1}, {"y": 6, "x": 1}, {"y": 8, "x": 1},
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _make_csv(rows, p)
        assert negbin_cli([str(p), "--dv", "y", "--iv", "x", "--json"]) == 0


def test_cli_bad_file_returns_one():
    assert negbin_cli(["/nonexistent/path.csv", "--dv", "y", "--iv", "x"]) == 1
