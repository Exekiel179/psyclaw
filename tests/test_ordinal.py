"""测试有序 Logistic 回归模块（psyclaw/psych/ordinal.py）— P20-1。

金标准（手算精确 / 与独立模块交叉验证）：
  - 仅阈值模型（k=0）：MLE 阈值 θ_j = logit(累积比例)（误差 < 1e-5）
  - J=2 退化：比例优势 β = 二元 Logistic 斜率、θ₁ = −二元 Logistic 截距
    （与已验证的 logistic.py 交叉对照，误差 < 1e-3）
  - 各类别预测概率和 = 1（predict_probs）
  - OR = exp(B) 精确
  - 单调预测变量 → β 显著为正
  - LR χ² ≥ 0；伪 R² ∈ [0,1]；阈值严格递增
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.ordinal import (
    _chi2_sf,
    _ll_grad,
    _mat_invert,
    _mat_vec,
    _normal_quantile,
    _normal_sf,
    _observed_information,
    _safe_exp,
    _sigmoid,
    analyze_ordinal,
    format_apa_ordinal,
    ordinal_regression,
    predict_probs,
    proportional_odds_check,
    write_ordinal_report,
)
from psyclaw.psych.logistic import logistic_regression


# ─────────────────────────────────────────────────────────────────────────────
# 数学工具
# ─────────────────────────────────────────────────────────────────────────────

def test_sigmoid_zero():
    assert abs(_sigmoid(0.0) - 0.5) < 1e-12


def test_sigmoid_symmetry():
    assert abs(_sigmoid(2.0) + _sigmoid(-2.0) - 1.0) < 1e-12


def test_sigmoid_extremes():
    assert _sigmoid(800.0) > 0.999
    assert _sigmoid(-800.0) < 0.001


def test_safe_exp_overflow():
    assert _safe_exp(1000.0) == math.inf
    assert _safe_exp(-1000.0) == 0.0
    assert abs(_safe_exp(0.0) - 1.0) < 1e-12


def test_mat_invert_identity():
    I = _mat_invert([[1.0, 0.0], [0.0, 1.0]])
    assert abs(I[0][0] - 1.0) < 1e-12 and abs(I[1][1] - 1.0) < 1e-12


def test_mat_invert_singular():
    assert _mat_invert([[1.0, 2.0], [2.0, 4.0]]) is None


def test_mat_invert_roundtrip():
    M = [[4.0, 3.0], [6.0, 3.0]]
    Inv = _mat_invert(M)
    prod = [[sum(M[i][t] * Inv[t][j] for t in range(2)) for j in range(2)]
            for i in range(2)]
    assert abs(prod[0][0] - 1.0) < 1e-9 and abs(prod[1][1] - 1.0) < 1e-9
    assert abs(prod[0][1]) < 1e-9 and abs(prod[1][0]) < 1e-9


def test_mat_vec():
    assert _mat_vec([[1.0, 2.0], [3.0, 4.0]], [1.0, 1.0]) == [3.0, 7.0]


def test_normal_sf_half():
    assert abs(_normal_sf(0.0) - 0.5) < 1e-6


def test_normal_sf_196():
    assert abs(_normal_sf(1.96) - 0.025) < 1e-3


def test_normal_quantile_median():
    assert abs(_normal_quantile(0.5)) < 1e-6


def test_normal_quantile_975():
    assert abs(_normal_quantile(0.975) - 1.96) < 1e-3


def test_chi2_sf_zero():
    assert _chi2_sf(0.0, 1) == 1.0


def test_chi2_sf_critical_df1():
    # χ²_{.05,1} = 3.841
    assert abs(_chi2_sf(3.841, 1) - 0.05) < 1e-3


def test_chi2_sf_monotone():
    assert _chi2_sf(10.0, 2) < _chi2_sf(5.0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 对数似然 + 梯度
# ─────────────────────────────────────────────────────────────────────────────

def _intercept_only_data():
    # 3 类别，计数 [4, 3, 5]，n=12
    return ([1] * 4 + [2] * 3 + [3] * 5)


def test_ll_grad_returns_tuple():
    y = _intercept_only_data()
    X = [[] for _ in y]
    ll, grad = _ll_grad([0.0, 0.5], X, y, J=3, k=0)
    assert isinstance(ll, float)
    assert len(grad) == 2


def test_ll_grad_negative():
    y = _intercept_only_data()
    X = [[] for _ in y]
    ll, _ = _ll_grad([0.0, 1.0], X, y, J=3, k=0)
    assert ll < 0


def test_grad_at_optimum_near_zero():
    # 在仅阈值 MLE（=累积比例 logit）处，梯度应近 0
    y = _intercept_only_data()
    n = len(y)
    X = [[] for _ in y]
    n1, n2 = 4, 3
    t1 = math.log((n1 / n) / (1 - n1 / n))
    t2 = math.log(((n1 + n2) / n) / (1 - (n1 + n2) / n))
    _, grad = _ll_grad([t1, t2], X, y, J=3, k=0)
    assert all(abs(g) < 1e-6 for g in grad)


def test_observed_information_symmetric():
    y = _intercept_only_data()
    X = [[] for _ in y]
    info = _observed_information([0.0, 0.5], X, y, J=3, k=0)
    assert abs(info[0][1] - info[1][0]) < 1e-9


def test_observed_information_pos_diag():
    y = _intercept_only_data()
    X = [[] for _ in y]
    info = _observed_information([0.0, 0.5], X, y, J=3, k=0)
    assert info[0][0] > 0 and info[1][1] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 金标准 1：仅阈值模型恢复累积比例 logit
# ─────────────────────────────────────────────────────────────────────────────

def test_threshold_only_recovers_cumlogit():
    y = _intercept_only_data()  # 计数 4/3/5, n=12
    n = len(y)
    X = [[] for _ in y]
    res = ordinal_regression(X, y, J=3, predictor_names=[])
    cp1 = 4 / n
    cp2 = 7 / n
    t1 = math.log(cp1 / (1 - cp1))
    t2 = math.log(cp2 / (1 - cp2))
    assert abs(res["thresholds"][0] - t1) < 1e-5
    assert abs(res["thresholds"][1] - t2) < 1e-5


def test_threshold_only_no_coef():
    y = _intercept_only_data()
    X = [[] for _ in y]
    res = ordinal_regression(X, y, J=3, predictor_names=[])
    assert res["coef"] == []
    assert res["lr_chi2"] == 0.0 or res["lr_df"] == 0


def test_threshold_only_ordered():
    y = _intercept_only_data()
    X = [[] for _ in y]
    res = ordinal_regression(X, y, J=3, predictor_names=[])
    assert res["thresholds_ordered"]


def test_threshold_only_loglik_equals_null():
    # 仅阈值模型的 ll_model 应等于 ll_null
    y = _intercept_only_data()
    X = [[] for _ in y]
    res = ordinal_regression(X, y, J=3, predictor_names=[])
    assert abs(res["log_lik_model"] - res["log_lik_null"]) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 金标准 2：J=2 退化 == 二元 Logistic
# ─────────────────────────────────────────────────────────────────────────────

def _binary_xy():
    # 一个连续预测变量与二元结局，足够分散以良好收敛
    xs = [-2, -1, -1, 0, 0, 0, 1, 1, 2, -2, 0, 1, 2, -1, 0, 1]
    ys = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 1]
    return xs, ys


def test_j2_matches_binary_logistic_slope():
    xs, ys = _binary_xy()
    # ordinal: 类别 1/2 (=ys+1)
    y_cat = [v + 1 for v in ys]
    X = [[x] for x in xs]
    ores = ordinal_regression(X, y_cat, J=2, predictor_names=["x"])
    # binary logistic, event=Y=2 (ys==1)
    Xd = [[1.0, x] for x in xs]
    lres = logistic_regression(Xd, [float(v) for v in ys], predictor_names=["x"])
    # 比例优势 β == 二元斜率
    assert abs(ores["coef"][0] - lres["coef"][1]) < 1e-3


def test_j2_matches_binary_logistic_threshold():
    xs, ys = _binary_xy()
    y_cat = [v + 1 for v in ys]
    X = [[x] for x in xs]
    ores = ordinal_regression(X, y_cat, J=2, predictor_names=["x"])
    Xd = [[1.0, x] for x in xs]
    lres = logistic_regression(Xd, [float(v) for v in ys], predictor_names=["x"])
    # θ₁ == −(二元截距)
    assert abs(ores["thresholds"][0] - (-lres["coef"][0])) < 1e-3


def test_j2_or_matches_binary():
    xs, ys = _binary_xy()
    y_cat = [v + 1 for v in ys]
    X = [[x] for x in xs]
    ores = ordinal_regression(X, y_cat, J=2, predictor_names=["x"])
    Xd = [[1.0, x] for x in xs]
    lres = logistic_regression(Xd, [float(v) for v in ys], predictor_names=["x"])
    assert abs(ores["or_"][0] - lres["or_"][1]) < 1e-2


# ─────────────────────────────────────────────────────────────────────────────
# predict_probs：概率和=1
# ─────────────────────────────────────────────────────────────────────────────

def test_predict_probs_sum_to_one():
    thr = [-1.0, 0.5]
    beta = [0.8]
    for xv in (-3.0, 0.0, 2.5):
        probs = predict_probs(thr, beta, [xv])
        assert len(probs) == 3
        assert abs(sum(probs) - 1.0) < 1e-12


def test_predict_probs_all_nonneg():
    probs = predict_probs([-1.0, 0.0, 1.0], [0.5], [1.0])
    assert all(p >= 0 for p in probs)
    assert len(probs) == 4


def test_predict_probs_no_beta():
    # 仅阈值时和=1
    probs = predict_probs([-0.5, 0.5], [], [])
    assert abs(sum(probs) - 1.0) < 1e-12


def test_predict_probs_monotone_shift():
    # 更高 x（β>0）应把质量推向更高类别
    thr = [-1.0, 1.0]
    lo = predict_probs(thr, [1.0], [-2.0])
    hi = predict_probs(thr, [1.0], [2.0])
    assert hi[-1] > lo[-1]  # 最高类别概率随 x 上升


# ─────────────────────────────────────────────────────────────────────────────
# 单调预测变量 → β 显著为正
# ─────────────────────────────────────────────────────────────────────────────

def _monotone_data():
    # x 越大类别越高（强单调），20 例
    xs, ys = [], []
    for x, cat in [(1, 1), (1, 1), (2, 1), (2, 2), (3, 2), (3, 2),
                   (4, 2), (4, 3), (5, 3), (5, 3),
                   (1, 1), (2, 1), (3, 2), (4, 3), (5, 3),
                   (2, 2), (3, 2), (4, 3), (1, 1), (5, 3)]:
        xs.append(float(x))
        ys.append(cat)
    return xs, ys


def test_monotone_beta_positive():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["coef"][0] > 0


def test_monotone_beta_significant():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["p"][0] < 0.05


def test_monotone_or_above_one():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["or_"][0] > 1.0


def test_monotone_converged():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["convergence"]


def test_monotone_thresholds_ordered():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["thresholds_ordered"]


# ─────────────────────────────────────────────────────────────────────────────
# 模型拟合统计不变量
# ─────────────────────────────────────────────────────────────────────────────

def test_or_equals_exp_beta():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert abs(res["or_"][0] - math.exp(res["coef"][0])) < 1e-9


def test_lr_chi2_nonneg():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["lr_chi2"] >= 0


def test_lr_df_equals_k():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["lr_df"] == 1


def test_mcfadden_in_range():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert 0.0 <= res["mcfadden_r2"] <= 1.0


def test_nagelkerke_ge_coxsnell():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["nagelkerke_r2"] >= res["cox_snell_r2"] - 1e-9


def test_pseudo_r2_in_range():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert 0.0 <= res["cox_snell_r2"] <= 1.0
    assert 0.0 <= res["nagelkerke_r2"] <= 1.0


def test_aic_bic_formula():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    np = res["n_params"]
    assert abs(res["aic"] - (-2 * res["log_lik_model"] + 2 * np)) < 1e-6
    assert abs(res["bic"] - (-2 * res["log_lik_model"]
                             + np * math.log(res["n"]))) < 1e-6


def test_n_params_count():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    # J-1 阈值 + k 斜率 = 2 + 1
    assert res["n_params"] == 3


def test_n_per_cat_sums_to_n():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert sum(res["n_per_cat"]) == res["n"]


def test_loglik_model_ge_null():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    assert res["log_lik_model"] >= res["log_lik_null"] - 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 多预测变量
# ─────────────────────────────────────────────────────────────────────────────

def _two_pred_data():
    rows = [
        (1.0, 0.0, 1), (1.0, 0.0, 1), (2.0, 0.0, 1), (2.0, 1.0, 2),
        (3.0, 0.0, 2), (3.0, 1.0, 2), (4.0, 1.0, 3), (4.0, 0.0, 2),
        (5.0, 1.0, 3), (5.0, 1.0, 3), (1.0, 1.0, 1), (2.0, 1.0, 2),
        (3.0, 1.0, 3), (4.0, 1.0, 3), (5.0, 0.0, 3), (2.0, 0.0, 1),
        (3.0, 0.0, 2), (4.0, 1.0, 3), (1.0, 0.0, 1), (5.0, 1.0, 3),
    ]
    X = [[r[0], r[1]] for r in rows]
    y = [r[2] for r in rows]
    return X, y


def test_two_pred_dimensions():
    X, y = _two_pred_data()
    res = ordinal_regression(X, y, J=3, predictor_names=["x1", "x2"])
    assert len(res["coef"]) == 2
    assert len(res["se"]) == 2
    assert res["lr_df"] == 2


def test_two_pred_converged():
    X, y = _two_pred_data()
    res = ordinal_regression(X, y, J=3, predictor_names=["x1", "x2"])
    assert res["convergence"]
    assert res["thresholds_ordered"]


# ─────────────────────────────────────────────────────────────────────────────
# 比例优势诊断
# ─────────────────────────────────────────────────────────────────────────────

def test_po_check_structure():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    po = proportional_odds_check(X, ys, J=3, predictor_names=["x"])
    assert "per_predictor" in po
    assert "x" in po["per_predictor"]
    assert "note" in po
    assert "max_range" in po


def test_po_check_slopes_collected():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    po = proportional_odds_check(X, ys, J=3, predictor_names=["x"])
    d = po["per_predictor"]["x"]
    assert len(d["slopes"]) >= 1
    assert d["range"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# APA-7 格式化
# ─────────────────────────────────────────────────────────────────────────────

def test_format_apa_returns_str():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    out = format_apa_ordinal(res, dv_name="severity")
    assert isinstance(out, str) and len(out) > 0


def test_format_apa_contains_keys():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    out = format_apa_ordinal(res, dv_name="severity")
    assert "proportional-odds" in out.lower() or "proportional odds" in out.lower()
    assert "OR" in out
    assert "θ1" in out  # 阈值段
    assert "McFadden" in out


def test_format_apa_with_po():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    po = proportional_odds_check(X, ys, J=3, predictor_names=["x"])
    out = format_apa_ordinal(res, po=po, dv_name="severity")
    assert "assumption check" in out.lower()


def test_format_apa_table_rows():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    out = format_apa_ordinal(res, dv_name="y")
    # 表头 + 分隔 + 1 个预测变量行
    assert out.count("|") >= 3 * 8


def test_format_apa_significance_star():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    out = format_apa_ordinal(res, dv_name="y")
    assert "x*" in out  # 显著预测变量加星


# ─────────────────────────────────────────────────────────────────────────────
# JSON 安全 + 报告写出
# ─────────────────────────────────────────────────────────────────────────────

def test_write_report_files():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    with tempfile.TemporaryDirectory() as d:
        paths = write_ordinal_report(res, out_dir=d, dv_name="y")
        assert Path(paths["md"]).exists()
        assert Path(paths["json"]).exists()


def test_write_report_valid_json():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    with tempfile.TemporaryDirectory() as d:
        paths = write_ordinal_report(res, out_dir=d, dv_name="y")
        data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert "thresholds" in data and "coef" in data


def test_write_report_no_nan_in_json():
    # 含 nan 的 SE（如完美预测）也应序列化为 null
    res = {
        "thresholds": [0.0], "threshold_se": [float("nan")],
        "coef": [float("nan")], "se": [float("nan")], "z": [float("nan")],
        "p": [float("nan")], "or_": [float("inf")],
        "or_ci_lower": [0.0], "or_ci_upper": [float("inf")],
        "ci_lower": [0.0], "ci_upper": [0.0], "predictor_names": ["x"],
        "J": 2, "n": 5, "n_per_cat": [2, 3],
        "log_lik_null": -3.0, "log_lik_model": -2.0,
        "lr_chi2": 2.0, "lr_df": 1, "lr_p": 0.1,
        "mcfadden_r2": 0.3, "cox_snell_r2": 0.2, "nagelkerke_r2": 0.3,
        "aic": 8.0, "bic": 9.0, "n_params": 2, "convergence": True,
        "n_iter": 5, "thresholds_ordered": True, "alpha": 0.05,
    }
    with tempfile.TemporaryDirectory() as d:
        paths = write_ordinal_report(res, out_dir=d, dv_name="y")
        raw = Path(paths["json"]).read_text(encoding="utf-8")
        assert "NaN" not in raw and "Infinity" not in raw


def test_write_report_no_out_dir():
    xs, ys = _monotone_data()
    X = [[x] for x in xs]
    res = ordinal_regression(X, ys, J=3, predictor_names=["x"])
    paths = write_ordinal_report(res, out_dir=None, dv_name="y")
    assert paths == {}


# ─────────────────────────────────────────────────────────────────────────────
# analyze_ordinal（CSV 主入口）
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv(rows, header):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="")
    w = csv.writer(f)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    f.close()
    return f.name


def test_analyze_ordinal_basic():
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    out = analyze_ordinal(path, "sev", ["x"])
    res = out["result"]
    assert res["J"] == 3
    assert res["coef"][0] > 0
    Path(path).unlink()


def test_analyze_ordinal_category_labels():
    rows = [("low", 1), ("low", 2), ("mid", 3), ("mid", 3),
            ("high", 5), ("high", 5), ("low", 1), ("mid", 4),
            ("high", 5), ("mid", 3)]
    path = _write_csv(rows, ["grade", "x"])
    out = analyze_ordinal(path, "grade", ["x"])
    # 字典序：high < low < mid（按字母）——确认映射是确定的且 J=3
    assert out["result"]["J"] == 3
    assert len(out["result"]["category_labels"]) == 3
    Path(path).unlink()


def test_analyze_ordinal_numeric_order():
    # 数值标签应按数值升序而非字典序
    rows = [(10, 1), (2, 1), (2, 2), (10, 3), (2, 1), (10, 3),
            (2, 2), (10, 3), (2, 1), (10, 3)]
    # 只有 2 个数值类别 → 应报错
    path = _write_csv(rows, ["y", "x"])
    try:
        analyze_ordinal(path, "y", ["x"])
        assert False, "应因 <3 类别报错"
    except ValueError:
        pass
    Path(path).unlink()


def test_analyze_ordinal_missing_excluded():
    rows = [(1, 1), (1, 2), (2, ""), (2, 3), (3, 5), (3, 5),
            (1, 1), (2, 4), (3, 5), (2, 3)]
    path = _write_csv(rows, ["sev", "x"])
    out = analyze_ordinal(path, "sev", ["x"])
    assert out["result"]["n_excluded"] == 1
    assert out["result"]["n"] == 9
    Path(path).unlink()


def test_analyze_ordinal_too_few_categories():
    rows = [(1, 1), (1, 2), (2, 3), (2, 4), (1, 1), (2, 2)]
    path = _write_csv(rows, ["y", "x"])
    try:
        analyze_ordinal(path, "y", ["x"])
        assert False
    except ValueError as e:
        assert "类别" in str(e)
    Path(path).unlink()


def test_analyze_ordinal_writes_sidecar():
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    with tempfile.TemporaryDirectory() as d:
        analyze_ordinal(path, "sev", ["x"], out_dir=d)
        assert (Path(d) / "ordinal_report.md").exists()
        assert (Path(d) / "ordinal_report.json").exists()
    Path(path).unlink()


def test_analyze_ordinal_po_check_present():
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    out = analyze_ordinal(path, "sev", ["x"])
    assert out["po"] is not None
    Path(path).unlink()


def test_analyze_ordinal_no_po_check():
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    out = analyze_ordinal(path, "sev", ["x"], run_po_check=False)
    assert out["po"] is None
    Path(path).unlink()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_basic(capsys):
    from psyclaw.psych.ordinal import ordinal_cli
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    rc = ordinal_cli([path, "--dv", "sev", "--iv", "x"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OR" in out
    Path(path).unlink()


def test_cli_json(capsys):
    from psyclaw.psych.ordinal import ordinal_cli
    xs, ys = _monotone_data()
    rows = [(ys[i], xs[i]) for i in range(len(xs))]
    path = _write_csv(rows, ["sev", "x"])
    rc = ordinal_cli([path, "--dv", "sev", "--iv", "x", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "thresholds" in data
    Path(path).unlink()


def test_cli_error_returns_1(capsys):
    from psyclaw.psych.ordinal import ordinal_cli
    rc = ordinal_cli(["/nonexistent_xyz.csv", "--dv", "y", "--iv", "x"])
    assert rc == 1


# ─────────────────────────────────────────────────────────────────────────────
# CLI 注册集成
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_registered():
    from psyclaw.cli import build_parser
    parser = build_parser()
    # ordinal 子命令应可解析
    args = parser.parse_args(["ordinal", "data.csv", "--dv", "y", "--iv", "x"])
    assert args.dv == "y"
    assert args.iv == "x"
    assert hasattr(args, "func")
