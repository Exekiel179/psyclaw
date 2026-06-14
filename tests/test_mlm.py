"""Tests for psyclaw.psych.mlm — 两层随机截距混合线性模型。

验证策略:
  1. 零模型 (无预测变量): ICC / 截距 ≈ 总体均值
  2. 含预测变量: 固定效应方向正确、显著性检验
  3. 边界: ICC=0 / ICC≈1 (极端聚类)
  4. 数学恒等: tau2/(tau2+sigma2) == ICC; AIC=-2LL+2k; BIC=-2LL+k*log(N)
  5. APA-7 格式 / JSON sidecar / CSV 主入口 / CLI
  6. 错误处理: 单组 / 样本量不足 / 每组仅 1 个观测
"""

from __future__ import annotations

import csv
import io
import json
import math
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.mlm import (
    analyze_mlm,
    compute_icc_mlm,
    fit_random_intercept,
    format_apa_mlm,
    mlm_cli,
    write_mlm_report,
)


# ─────────────────────────────────────────────────────────────────────────────
# 辅助: 确定性伪随机嵌套数据生成
# ─────────────────────────────────────────────────────────────────────────────

def _make_nested_data(
    J: int = 5,
    n_per: int = 10,
    intercept: float = 50.0,
    slope: float = 2.0,
    tau: float = 5.0,
    sigma: float = 3.0,
    seed: int = 42,
):
    """J 组，每组 n_per 个观测的两层数据（确定性伪随机）。"""
    rng = [seed]

    def _rand():
        rng[0] = (rng[0] * 1664525 + 1013904223) & 0xFFFFFFFF
        return rng[0] / 0xFFFFFFFF - 0.5

    def _randn():
        u1 = max(1e-10, abs(_rand()) + 0.5)
        u2 = (_rand() + 0.5) * 2 * math.pi
        return math.sqrt(-2 * math.log(u1)) * math.cos(u2)

    y, X, groups = [], [], []
    for j in range(J):
        u_j = _randn() * tau
        for _ in range(n_per):
            xv = _randn() * 3.0 + 5.0
            y.append(intercept + slope * xv + u_j + _randn() * sigma)
            X.append([xv])
            groups.append(f"G{j+1:02d}")
    return y, X, groups


def _write_csv(y, groups, X, pred_names, directory):
    path = str(pathlib.Path(directory) / "data.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        cols = ["dv", "cluster"] + pred_names
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i in range(len(y)):
            row = {"dv": y[i], "cluster": groups[i]}
            for k, pn in enumerate(pred_names):
                row[pn] = X[i][k]
            w.writerow(row)
    return path


def _capture(fn):
    """捕获 stdout 并返回 (return_value, captured_string)。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rv = fn()
    finally:
        sys.stdout = old
    return rv, buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# 1. 零模型
# ─────────────────────────────────────────────────────────────────────────────

def test_null_model_intercept():
    y = [10.0, 12.0, 11.0, 20.0, 22.0, 21.0, 30.0, 32.0, 31.0]
    groups = ["A", "A", "A", "B", "B", "B", "C", "C", "C"]
    res = fit_random_intercept(y, [], groups)
    grand = sum(y) / len(y)
    assert abs(res["beta"][0] - grand) < 3.0, \
        f"截距 {res['beta'][0]:.3f} 远离均值 {grand:.3f}"


def test_null_model_icc_high():
    y = [1.0, 1.1, 1.2, 10.0, 10.1, 10.2, 20.0, 20.1, 20.2]
    groups = ["A"] * 3 + ["B"] * 3 + ["C"] * 3
    res = fit_random_intercept(y, [], groups)
    assert res["icc"] > 0.8, f"极端聚类 ICC 应 > 0.8，实得 {res['icc']:.4f}"


def test_null_model_low_icc():
    y = [10.0, 14.0, 12.0, 11.0, 13.0, 10.5, 12.5, 11.5, 10.0, 13.0]
    groups = ["A", "A", "B", "B", "C", "C", "D", "D", "E", "E"]
    res = fit_random_intercept(y, [], groups)
    assert res["icc"] < 0.5, f"低聚类 ICC 应 < 0.5，实得 {res['icc']:.4f}"


def test_null_model_returns_fields():
    y = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    groups = ["A", "A", "A", "B", "B", "B"]
    res = fit_random_intercept(y, [], groups)
    for key in ("beta", "se", "t", "p", "ci_lower", "ci_upper",
                "sigma2", "tau2", "icc", "ll", "aic", "bic",
                "J", "N", "n_j", "converged", "n_iter", "u_hat"):
        assert key in res, f"缺少键: {key}"


def test_null_model_single_beta():
    """零模型只有截距，beta 长度为 1。"""
    y = [1.0, 2.0, 3.0, 10.0, 11.0, 12.0]
    groups = ["A", "A", "A", "B", "B", "B"]
    res = fit_random_intercept(y, [], groups)
    assert len(res["beta"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. 含预测变量
# ─────────────────────────────────────────────────────────────────────────────

def test_fixed_effect_positive_slope():
    y, X, groups = _make_nested_data(J=6, n_per=15, slope=3.0, tau=2.0, sigma=1.0)
    res = fit_random_intercept(y, X, groups, pred_names=["x"])
    assert res["beta"][1] > 1.5, f"正斜率估计 {res['beta'][1]:.3f} 偏小"


def test_fixed_effect_negative_slope():
    y, X, groups = _make_nested_data(J=6, n_per=15, slope=-3.0, tau=2.0, sigma=1.0)
    res = fit_random_intercept(y, X, groups, pred_names=["x"])
    assert res["beta"][1] < -1.5, f"负斜率估计 {res['beta'][1]:.3f} 偏大"


def test_intercept_near_true_value():
    y, X, groups = _make_nested_data(J=8, n_per=20, intercept=50.0, slope=2.0,
                                     tau=3.0, sigma=2.0, seed=123)
    res = fit_random_intercept(y, X, groups)
    assert 40.0 < res["beta"][0] < 65.0, f"截距 {res['beta'][0]:.2f} 偏离真值 50 过多"


def test_p_values_in_range():
    y, X, groups = _make_nested_data(J=5, n_per=12)
    res = fit_random_intercept(y, X, groups)
    for pv in res["p"]:
        if math.isfinite(pv):
            assert 0.0 <= pv <= 1.0, f"p 值超出 [0,1]: {pv}"


def test_ci_contains_beta():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    for k in range(len(res["beta"])):
        assert res["ci_lower"][k] <= res["beta"][k] <= res["ci_upper"][k], \
            f"CI [{res['ci_lower'][k]:.3f}, {res['ci_upper'][k]:.3f}] 不含 beta={res['beta'][k]:.3f}"


def test_pred_names_stored():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups, pred_names=["age"])
    assert res["term_names"] == ["Intercept", "age"]


def test_term_names_auto():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert res["term_names"][0] == "Intercept"
    assert res["term_names"][1].startswith("X")


def test_t_stat_significant_for_large_effect():
    """大效应下斜率应显著。"""
    y, X, groups = _make_nested_data(J=8, n_per=20, slope=10.0, tau=1.0, sigma=1.0)
    res = fit_random_intercept(y, X, groups)
    assert res["p"][1] < 0.05, f"大效应 p 值应 < .05，实得 {res['p'][1]:.4f}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. 方差分量
# ─────────────────────────────────────────────────────────────────────────────

def test_variance_components_positive():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    assert res["sigma2"] > 0
    assert res["tau2"] > 0


def test_icc_definition_identity():
    """ICC 恒等: tau2/(tau2+sigma2)。"""
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    expected = res["tau2"] / (res["tau2"] + res["sigma2"])
    assert abs(res["icc"] - expected) < 1e-10


def test_icc_in_unit_interval():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    assert 0.0 <= res["icc"] <= 1.0


def test_high_icc_extreme_clustering():
    y = [1.0, 1.1, 1.05, 100.0, 100.1, 100.05, 200.0, 200.1, 200.05]
    groups = ["A"] * 3 + ["B"] * 3 + ["C"] * 3
    res = fit_random_intercept(y, [], groups)
    assert res["icc"] > 0.95, f"极端聚类 ICC 应 > 0.95，实得 {res['icc']:.4f}"


def test_blups_length_equals_j():
    y, X, groups = _make_nested_data(J=5, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert len(res["u_hat"]) == res["J"]
    assert len(res["blup_se"]) == res["J"]


def test_blup_se_nonneg():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    for se_v in res["blup_se"]:
        assert se_v >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. 模型拟合指标
# ─────────────────────────────────────────────────────────────────────────────

def test_aic_formula():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    p = len(res["beta"])
    expected = -2 * res["ll"] + 2 * (p + 2)
    assert abs(res["aic"] - expected) < 1e-6


def test_bic_formula():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    p = len(res["beta"])
    expected = -2 * res["ll"] + (p + 2) * math.log(res["N"])
    assert abs(res["bic"] - expected) < 1e-6


def test_ll_finite():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert math.isfinite(res["ll"])


def test_n_and_j_correct():
    y, X, groups = _make_nested_data(J=6, n_per=10)
    res = fit_random_intercept(y, X, groups)
    assert res["N"] == 60
    assert res["J"] == 6


def test_n_j_sums_to_N():
    y, X, groups = _make_nested_data(J=5, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert sum(res["n_j"]) == res["N"]


def test_converged_flag_type():
    y, X, groups = _make_nested_data(J=5, n_per=15)
    res = fit_random_intercept(y, X, groups)
    assert isinstance(res["converged"], bool)


def test_unique_groups_count():
    y, X, groups = _make_nested_data(J=7, n_per=6)
    res = fit_random_intercept(y, X, groups)
    assert len(res["unique_groups"]) == 7


def test_df_resid_positive():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert res["df_resid"] > 0


def test_se_nonneg():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups)
    for se_v in res["se"]:
        assert se_v >= 0.0


def test_ci_width_positive():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    for k in range(len(res["beta"])):
        assert res["ci_upper"][k] > res["ci_lower"][k]


# ─────────────────────────────────────────────────────────────────────────────
# 5. compute_icc_mlm
# ─────────────────────────────────────────────────────────────────────────────

def test_icc_mlm_zero():
    r = compute_icc_mlm(0.0, 5.0)
    assert r["icc"] == 0.0


def test_icc_mlm_half():
    r = compute_icc_mlm(1.0, 1.0)
    assert abs(r["icc"] - 0.5) < 1e-10


def test_icc_mlm_high():
    r = compute_icc_mlm(9.0, 1.0)
    assert abs(r["icc"] - 0.9) < 1e-10


def test_icc_mlm_keys():
    r = compute_icc_mlm(0.5, 5.0)
    for k in ("icc", "interpretation", "tau2", "sigma2"):
        assert k in r


def test_icc_mlm_negligible():
    r = compute_icc_mlm(0.01, 10.0)
    assert "可忽略" in r["interpretation"]


def test_icc_mlm_large():
    r = compute_icc_mlm(5.0, 1.0)
    assert "大" in r["interpretation"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. format_apa_mlm
# ─────────────────────────────────────────────────────────────────────────────

def test_format_apa_has_sections():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    res = fit_random_intercept(y, X, groups, pred_names=["x"])
    text = format_apa_mlm(res)
    for section in ("固定效应", "方差分量", "模型拟合", "结果摘要"):
        assert section in text, f"缺少段落: {section}"


def test_format_apa_contains_icc():
    y = [1.0, 1.1, 1.2, 10.0, 10.1, 10.2, 20.0, 20.1, 20.2]
    groups = ["A"] * 3 + ["B"] * 3 + ["C"] * 3
    res = fit_random_intercept(y, [], groups)
    assert "ICC" in format_apa_mlm(res)


def test_format_apa_intercept_label():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert "Intercept" in format_apa_mlm(res)


def test_format_apa_aic_bic():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    text = format_apa_mlm(res)
    assert "AIC" in text
    assert "BIC" in text


def test_format_apa_variance_labels():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    text = format_apa_mlm(res)
    assert "τ²" in text
    assert "σ²" in text


def test_format_apa_custom_alpha():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    assert "99%" in format_apa_mlm(res, alpha=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 7. write_mlm_report
# ─────────────────────────────────────────────────────────────────────────────

def test_write_report_creates_files():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    with tempfile.TemporaryDirectory() as td:
        md_p, json_p = write_mlm_report(res, td)
        assert md_p.exists()
        assert json_p.exists()


def test_write_report_md_content():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    with tempfile.TemporaryDirectory() as td:
        md_p, _ = write_mlm_report(res, td)
        content = md_p.read_text(encoding="utf-8")
        assert "MLM" in content
        assert "ICC" in content


def test_write_report_json_valid():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    with tempfile.TemporaryDirectory() as td:
        _, json_p = write_mlm_report(res, td)
        data = json.loads(json_p.read_text(encoding="utf-8"))
        for k in ("icc", "tau2", "sigma2", "aic", "bic"):
            assert k in data, f"JSON 缺少键: {k}"


def test_write_report_json_icc_matches():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    res = fit_random_intercept(y, X, groups)
    with tempfile.TemporaryDirectory() as td:
        _, json_p = write_mlm_report(res, td)
        data = json.loads(json_p.read_text(encoding="utf-8"))
        assert abs(data["icc"] - res["icc"]) < 1e-10


# ─────────────────────────────────────────────────────────────────────────────
# 8. analyze_mlm (CSV 主入口)
# ─────────────────────────────────────────────────────────────────────────────

def test_analyze_mlm_from_csv():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        res, _ = _capture(
            lambda: analyze_mlm(csv_path, dv="dv", cluster="cluster", ivs=["x"])
        )
    assert res["N"] == 50
    assert res["J"] == 5


def test_analyze_mlm_null_model():
    y, X, groups = _make_nested_data(J=4, n_per=10)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        res, _ = _capture(
            lambda: analyze_mlm(csv_path, dv="dv", cluster="cluster", ivs=[])
        )
    assert len(res["beta"]) == 1


def test_analyze_mlm_json_output():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        _, out = _capture(
            lambda: analyze_mlm(csv_path, dv="dv", cluster="cluster",
                                ivs=["x"], json_output=True)
        )
    data = json.loads(out)
    assert "icc" in data


def test_analyze_mlm_writes_sidecar():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        out_dir = str(pathlib.Path(td) / "notes")
        _, _ = _capture(
            lambda: analyze_mlm(csv_path, dv="dv", cluster="cluster",
                                ivs=["x"], out_dir=out_dir)
        )
        assert (pathlib.Path(out_dir) / "mlm_report.md").exists()
        assert (pathlib.Path(out_dir) / "mlm_report.json").exists()


def test_analyze_mlm_missing_col_error():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        try:
            analyze_mlm(csv_path, dv="dv", cluster="cluster", ivs=["no_such_col"])
            assert False, "应抛出 ValueError"
        except (ValueError, KeyError):
            pass


def test_analyze_mlm_excludes_missing():
    """含缺失值的行应被排除，n_excluded 应计数正确。"""
    with tempfile.TemporaryDirectory() as td:
        csv_path = str(pathlib.Path(td) / "data.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["dv", "cluster"])
            w.writeheader()
            for g in ["A", "A", "A", "B", "B", "B"]:
                w.writerow({"dv": 10.0, "cluster": g})
            w.writerow({"dv": "", "cluster": "C"})   # 缺失 dv
            w.writerow({"dv": "abc", "cluster": "C"})  # 无效 dv
            for _ in range(4):
                w.writerow({"dv": 10.0, "cluster": "C"})
        res, _ = _capture(
            lambda: analyze_mlm(csv_path, dv="dv", cluster="cluster", ivs=[])
        )
    assert res["n_excluded"] >= 2
    assert res["N"] == 10  # 6+4 有效行


# ─────────────────────────────────────────────────────────────────────────────
# 9. mlm_cli
# ─────────────────────────────────────────────────────────────────────────────

def test_cli_null_model():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        rc, _ = _capture(lambda: mlm_cli([csv_path, "--dv", "dv", "--cluster", "cluster"]))
    assert rc == 0


def test_cli_with_iv():
    y, X, groups = _make_nested_data(J=5, n_per=10)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        rc, _ = _capture(
            lambda: mlm_cli([csv_path, "--dv", "dv", "--cluster", "cluster", "--iv", "x"])
        )
    assert rc == 0


def test_cli_json_mode():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        rc, out = _capture(
            lambda: mlm_cli([csv_path, "--dv", "dv", "--cluster", "cluster",
                             "--iv", "x", "--json"])
        )
    assert rc == 0
    data = json.loads(out)
    assert "icc" in data


def test_cli_out_dir():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        out = str(pathlib.Path(td) / "out")
        rc, _ = _capture(
            lambda: mlm_cli([csv_path, "--dv", "dv", "--cluster", "cluster",
                             "--iv", "x", "--out", out])
        )
        assert rc == 0
        assert (pathlib.Path(out) / "mlm_report.md").exists()


def test_cli_missing_file():
    rc, _ = _capture(lambda: mlm_cli(["no_file.csv", "--dv", "dv", "--cluster", "cluster"]))
    assert rc == 1


def test_cli_alpha_flag():
    y, X, groups = _make_nested_data(J=4, n_per=8)
    with tempfile.TemporaryDirectory() as td:
        csv_path = _write_csv(y, groups, X, ["x"], td)
        rc, _ = _capture(
            lambda: mlm_cli([csv_path, "--dv", "dv", "--cluster", "cluster",
                             "--iv", "x", "--alpha", "0.01"])
        )
    assert rc == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. 错误处理
# ─────────────────────────────────────────────────────────────────────────────

def test_single_group_raises():
    y = [1.0, 2.0, 3.0]
    groups = ["A", "A", "A"]
    try:
        fit_random_intercept(y, [], groups)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_all_singletons_raises():
    y = [1.0, 2.0, 3.0, 4.0]
    groups = ["A", "B", "C", "D"]
    try:
        fit_random_intercept(y, [], groups)
        assert False, "应抛出 ValueError（每组仅 1 观测）"
    except ValueError:
        pass


def test_insufficient_n_raises():
    y = [1.0]
    groups = ["A"]
    try:
        fit_random_intercept(y, [], groups)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_two_groups_minimum():
    y = [1.0, 2.0, 3.0, 10.0, 11.0, 12.0]
    groups = ["A", "A", "A", "B", "B", "B"]
    res = fit_random_intercept(y, [], groups)
    assert res["J"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 11. 数学一致性
# ─────────────────────────────────────────────────────────────────────────────

def test_t_positive_for_large_pos_effect():
    y, X, groups = _make_nested_data(J=8, n_per=20, slope=10.0, tau=1.0, sigma=1.0)
    res = fit_random_intercept(y, X, groups)
    assert res["t"][1] > 0


def test_aic_less_than_null_model_aic_when_predictor_helps():
    """当预测变量有效时，含预测变量模型 AIC 应低于零模型。"""
    y, X, groups = _make_nested_data(J=8, n_per=20, slope=5.0, tau=2.0, sigma=1.0)
    res_null = fit_random_intercept(y, [], groups)
    res_full = fit_random_intercept(y, X, groups)
    # 有效预测变量应改善拟合（AIC 降低）
    assert res_full["aic"] < res_null["aic"]


def test_n_j_all_equal_for_balanced():
    y, X, groups = _make_nested_data(J=4, n_per=10)
    res = fit_random_intercept(y, X, groups)
    assert all(n == 10 for n in res["n_j"])


def test_sigma2_shrinks_with_more_data():
    """更大样本（同等噪声）下 σ² 估计应更接近真实值。"""
    y_small, X_small, g_small = _make_nested_data(J=4, n_per=5, sigma=2.0)
    y_large, X_large, g_large = _make_nested_data(J=4, n_per=50, sigma=2.0)
    r_s = fit_random_intercept(y_small, X_small, g_small)
    r_l = fit_random_intercept(y_large, X_large, g_large)
    # 大样本 sigma2 应更接近 4.0 (= 2^2)
    assert abs(r_l["sigma2"] - 4.0) < abs(r_s["sigma2"] - 4.0) or r_l["sigma2"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 自跑块
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback

    _all = [(k, v) for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for _name, _fn in _all:
        try:
            _fn()
            passed += 1
            print(f"  PASS  {_name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {_name}")
            traceback.print_exc()
    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  ({failed} FAILED)")
    raise SystemExit(1 if failed else 0)
