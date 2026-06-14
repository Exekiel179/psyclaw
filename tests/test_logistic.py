"""测试二元 Logistic 回归模块（psyclaw/psych/logistic.py）— P7-1。

数值对照：
  - sigmoid(0) = 0.5 精确
  - 正相关数据 β₁ > 0
  - OR = exp(B) 精确
  - Nagelkerke R² ≥ Cox-Snell R²
  - LR chi² ≥ 0，df = k-1
  - HL chi² ≥ 0，df = g-2
  - chi2_sf(0, df) = 1
  - normal_quantile(0.975) ≈ 1.96
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.logistic import (
    _chi2_sf,
    _normal_quantile,
    _normal_sf,
    _sigmoid,
    format_apa_logistic,
    hosmer_lemeshow,
    logistic_regression,
    logistic_cli,
    write_logistic_report,
    analyze_logistic,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _simple_data(n=100):
    """确定性**非完全分离**数据：x 均匀分布 [-2, 2]，y 按 sigmoid(x) 概率通过 LCG 采样。

    刻意使用弱信号（coefficient≈1）+ 伪随机采样，避免完全线性分离导致 beta→∞。
    """
    xs, ys = [], []
    lcg = 12345  # 线性同余伪随机种子
    for i in range(n):
        x = (i / max(n - 1, 1) - 0.5) * 4
        p = _sigmoid(x)  # 弱信号：系数 = 1（非 2）
        lcg = (lcg * 1103515245 + 12345) & 0x7fffffff
        threshold = (lcg % 10000) / 10000.0
        y = 1.0 if threshold < p else 0.0
        xs.append(x)
        ys.append(y)
    return xs, ys


def _build_X(xs):
    return [[1.0, x] for x in xs]


# ---------------------------------------------------------------------------
# 数学工具
# ---------------------------------------------------------------------------

def test_sigmoid_zero():
    assert abs(_sigmoid(0.0) - 0.5) < 1e-10


def test_sigmoid_large_pos():
    assert abs(_sigmoid(100.0) - 1.0) < 1e-10


def test_sigmoid_large_neg():
    assert abs(_sigmoid(-100.0)) < 1e-10


def test_normal_sf_symmetry():
    assert abs(_normal_sf(1.96) - _normal_sf(-1.96)) < 1e-8


def test_normal_sf_zero():
    assert abs(_normal_sf(0.0) - 0.5) < 1e-4


def test_normal_quantile_median():
    assert abs(_normal_quantile(0.5)) < 1e-5


def test_normal_quantile_97_5():
    assert abs(_normal_quantile(0.975) - 1.96) < 0.01


def test_chi2_sf_zero_x():
    for df in [1, 2, 5]:
        assert abs(_chi2_sf(0.0, df) - 1.0) < 1e-8


def test_chi2_sf_large_x():
    assert _chi2_sf(1000.0, 2) < 1e-6


def test_chi2_sf_known_value():
    # χ²(2) 上 5% 临界值约 5.991
    assert abs(_chi2_sf(5.991, 2) - 0.05) < 0.003


# ---------------------------------------------------------------------------
# logistic_regression 核心
# ---------------------------------------------------------------------------

def test_convergence():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    assert r["convergence"] is True


def test_coef_length():
    xs, ys = _simple_data(50)
    r = logistic_regression(_build_X(xs), ys)
    assert len(r["coef"]) == 2  # 截距 + 1 预测变量


def test_predictor_positive():
    """x 与 y 正相关（sigmoid(x) 生成），β₁ 估计应 > 0。"""
    # 使用较大样本提高稳定性
    xs, ys = _simple_data(150)
    r = logistic_regression(_build_X(xs), ys, predictor_names=["x"])
    # 信号方向正确即可（LCG 随机但样本量足够时方向稳健）
    assert r["coef"][1] > 0


def test_or_eq_exp_beta():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for j in range(len(r["coef"])):
        assert abs(r["or_"][j] - math.exp(r["coef"][j])) < 1e-8


def test_or_reciprocal():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for j in range(1, len(r["coef"])):
        assert abs(r["or_"][j] * (1.0 / r["or_"][j]) - 1.0) < 1e-8


def test_se_positive():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for s in r["se"]:
        assert s > 0


def test_p_in_unit_interval():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for pv in r["p"]:
        if math.isfinite(pv):
            assert 0.0 <= pv <= 1.0


def test_z_from_coef_se():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for j in range(len(r["coef"])):
        expected = r["coef"][j] / r["se"][j]
        assert abs(r["z"][j] - expected) < 1e-6


def test_ci_contains_coef():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    for j in range(len(r["coef"])):
        assert r["ci_lower"][j] < r["coef"][j] < r["ci_upper"][j]


def test_cox_snell_in_range():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert 0.0 <= r["cox_snell_r2"] <= 1.0


def test_nagelkerke_in_range():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert 0.0 <= r["nagelkerke_r2"] <= 1.0


def test_nagelkerke_geq_cox_snell():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert r["nagelkerke_r2"] >= r["cox_snell_r2"] - 1e-8


def test_lr_chi2_nonneg():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert r["lr_chi2"] >= 0.0


def test_lr_df_single_predictor():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert r["lr_df"] == 1


def test_lr_p_in_range():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert 0.0 <= r["lr_p"] <= 1.0


def test_n_counts():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    assert r["n"] == 100
    assert r["n_pos"] + r["n_neg"] == 100


def test_mu_in_unit_interval():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert all(0.0 < m < 1.0 for m in r["mu"])


def test_null_ll_formula():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    n_pos = sum(ys)
    n = len(ys)
    p0 = n_pos / n
    expected = n_pos * math.log(p0) + (n - n_pos) * math.log(1.0 - p0)
    assert abs(r["log_lik_null"] - expected) < 1e-6


def test_model_ll_geq_null():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert r["log_lik_model"] >= r["log_lik_null"] - 1e-6


def test_term_names_custom():
    xs, ys = _simple_data(40)
    r = logistic_regression(_build_X(xs), ys, predictor_names=["score"])
    assert r["term_names"] == ["(Intercept)", "score"]


def test_default_predictor_names():
    xs, ys = _simple_data(40)
    r = logistic_regression(_build_X(xs), ys)
    assert r["predictor_names"] == ["X1"]


def test_two_predictors():
    n = 100
    lcg = 54321
    rows = []
    for i in range(n):
        x1 = (i / (n - 1) - 0.5) * 4
        x2 = ((i * 7 % n) / n - 0.5) * 2
        p = _sigmoid(x1 + 0.5 * x2)
        lcg = (lcg * 1103515245 + 12345) & 0x7fffffff
        y = 1.0 if (lcg % 10000) / 10000.0 < p else 0.0
        rows.append([x1, x2, y])
    X = [[1.0, r[0], r[1]] for r in rows]
    y_list = [r[2] for r in rows]
    r = logistic_regression(X, y_list)
    assert len(r["coef"]) == 3
    assert r["lr_df"] == 2


def test_two_predictors_positive_r2():
    n = 100
    lcg = 54321
    rows = []
    for i in range(n):
        x1 = (i / (n - 1) - 0.5) * 4
        x2 = ((i * 7 % n) / n - 0.5) * 2
        p = _sigmoid(x1 + 0.5 * x2)
        lcg = (lcg * 1103515245 + 12345) & 0x7fffffff
        y = 1.0 if (lcg % 10000) / 10000.0 < p else 0.0
        rows.append([x1, x2, y])
    X = [[1.0, r[0], r[1]] for r in rows]
    y_list = [r[2] for r in rows]
    r = logistic_regression(X, y_list)
    assert r["nagelkerke_r2"] > 0.0


# ---------------------------------------------------------------------------
# Hosmer-Lemeshow
# ---------------------------------------------------------------------------

def test_hl_df():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"], g=10)
    assert hl["hl_df"] == 8


def test_hl_p_in_range():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"])
    assert 0.0 <= hl["hl_p"] <= 1.0


def test_hl_chi2_nonneg():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"])
    assert hl["hl_chi2"] >= 0.0


def test_hl_g_auto_adjust_small_n():
    y = [0.0, 1.0, 0.0, 1.0, 0.0]
    pred = [0.2, 0.8, 0.3, 0.7, 0.4]
    hl = hosmer_lemeshow(y, pred, g=10)
    assert hl["g"] <= len(y)


def test_hl_groups_count():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"], g=5)
    assert len(hl["groups"]) == 5


def test_hl_total_n():
    xs, ys = _simple_data(100)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"])
    assert sum(g["n"] for g in hl["groups"]) == 100


# ---------------------------------------------------------------------------
# format_apa_logistic
# ---------------------------------------------------------------------------

def test_apa_contains_or():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys, predictor_names=["score"])
    assert "OR" in format_apa_logistic(r)


def test_apa_contains_ci():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert "CI" in format_apa_logistic(r)


def test_apa_contains_predictor_name():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys, predictor_names=["score"])
    assert "score" in format_apa_logistic(r)


def test_apa_contains_intercept():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    assert "Intercept" in format_apa_logistic(r)


def test_apa_contains_nagelkerke():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    text = format_apa_logistic(r)
    assert "Nagelkerke" in text or "R²" in text


def test_apa_contains_lr_chi2():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    text = format_apa_logistic(r)
    assert "χ²" in text or "chi" in text.lower()


def test_apa_hl_text():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    hl = hosmer_lemeshow(ys, r["mu"])
    text = format_apa_logistic(r, hl=hl)
    assert "Hosmer" in text


def test_apa_no_hl_no_hosmer():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    text = format_apa_logistic(r, hl=None)
    assert "Hosmer" not in text


def test_apa_no_sig_predictors_message():
    # 使用 alpha=0.0 → 所有 p > alpha（因为 p >= 0），所以 0.0 不行
    # 使用极严苛 alpha 而且小数据 → p 不会小于 alpha
    xs, ys = _simple_data(10)
    # 人工将 p 设为 nan 值通过构造结果
    r = logistic_regression(_build_X(xs), ys, alpha=0.05)
    # 改 p 为大于 alpha 的值
    r2 = dict(r)
    r2["p"] = [0.9, 0.9]  # 截距和预测变量都不显著
    text = format_apa_logistic(r2, dv_name="response")
    assert "No predictors" in text or "significant" in text.lower()


def test_apa_dv_name_in_output():
    xs, ys = _simple_data(60)
    r = logistic_regression(_build_X(xs), ys)
    text = format_apa_logistic(r, dv_name="diagnosis")
    assert "diagnosis" in text


def test_apa_n_in_output():
    xs, ys = _simple_data(80)
    r = logistic_regression(_build_X(xs), ys)
    text = format_apa_logistic(r)
    assert "80" in text


# ---------------------------------------------------------------------------
# write_logistic_report
# ---------------------------------------------------------------------------

def test_write_md_and_json():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        r = logistic_regression(_build_X(xs), ys, predictor_names=["x"])
        hl = hosmer_lemeshow(ys, r["mu"])
        paths = write_logistic_report(r, hl=hl, out_dir=tmp)
        assert Path(paths["md"]).exists()
        assert Path(paths["json"]).exists()


def test_write_json_valid():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        r = logistic_regression(_build_X(xs), ys, predictor_names=["x"])
        paths = write_logistic_report(r, out_dir=tmp)
        with open(paths["json"], encoding="utf-8") as f:
            data = json.load(f)
        assert "coef" in data
        assert "nagelkerke_r2" in data


def test_write_json_no_mu_key():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        r = logistic_regression(_build_X(xs), ys)
        paths = write_logistic_report(r, out_dir=tmp)
        with open(paths["json"], encoding="utf-8") as f:
            data = json.load(f)
        assert "mu" not in data


def test_write_no_outdir():
    xs, ys = _simple_data(20)
    r = logistic_regression(_build_X(xs), ys)
    paths = write_logistic_report(r, out_dir=None)
    assert paths == {}


# ---------------------------------------------------------------------------
# analyze_logistic（CSV 主入口）
# ---------------------------------------------------------------------------

def test_analyze_basic():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(80)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(80)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out = analyze_logistic(path, "y", ["x"])
        assert out["result"]["convergence"] is True


def test_analyze_hl_returned():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(80)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(80)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out = analyze_logistic(path, "y", ["x"])
        assert out["hl"] is not None


def test_analyze_no_hl():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(80)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(80)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out = analyze_logistic(path, "y", ["x"], run_hl=False)
        assert out["hl"] is None


def test_analyze_missing_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(50)
        rows = [{"x": xs[i], "y": ys[i]} for i in range(50)]
        rows[5]["x"] = ""
        rows[10]["y"] = ""
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out = analyze_logistic(path, "y", ["x"])
        assert out["result"]["n_excluded"] == 2


def test_analyze_non_binary_dv_raises():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"x": float(i), "y": i % 3} for i in range(30)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        try:
            analyze_logistic(path, "y", ["x"])
            assert False, "应该抛 ValueError"
        except ValueError:
            pass


def test_analyze_single_class_raises():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"x": float(i), "y": 1.0} for i in range(20)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        try:
            analyze_logistic(path, "y", ["x"])
            assert False, "应该抛 ValueError"
        except ValueError:
            pass


def test_analyze_sidecar_written():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(60)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out_dir = os.path.join(tmp, "out")
        analyze_logistic(path, "y", ["x"], out_dir=out_dir)
        assert Path(out_dir, "logistic_report.md").exists()
        assert Path(out_dir, "logistic_report.json").exists()


def test_analyze_dv_stored():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(60)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out = analyze_logistic(path, "y", ["x"])
        assert out["result"]["dv"] == "y"


# ---------------------------------------------------------------------------
# logistic_cli
# ---------------------------------------------------------------------------

def test_cli_exit_0(capsys=None):
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(80)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(80)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        rc = logistic_cli([path, "--dv", "y", "--iv", "x"])
        assert rc == 0


def test_cli_json_mode():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(80)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(80)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        rc = logistic_cli([path, "--dv", "y", "--iv", "x", "--json"])
        out = sys.stdout.getvalue()
        sys.stdout = old_stdout
        assert rc == 0
        data = json.loads(out)
        assert "coef" in data
        assert "nagelkerke_r2" in data


def test_cli_invalid_csv():
    rc = logistic_cli(["/no/such/file.csv", "--dv", "y", "--iv", "x"])
    assert rc != 0


def test_cli_no_hl_flag():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(60)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        rc = logistic_cli([path, "--dv", "y", "--iv", "x", "--no-hl"])
        assert rc == 0


def test_cli_out_flag():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(60)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        out_dir = os.path.join(tmp, "rpt")
        rc = logistic_cli([path, "--dv", "y", "--iv", "x", "--out", out_dir])
        assert rc == 0
        assert Path(out_dir, "logistic_report.md").exists()


def test_cli_alpha_flag():
    with tempfile.TemporaryDirectory() as tmp:
        xs, ys = _simple_data(60)
        rows = [{"x": xs[i], "y": int(ys[i])} for i in range(60)]
        path = os.path.join(tmp, "d.csv")
        _make_csv(rows, path)
        rc = logistic_cli([path, "--dv", "y", "--iv", "x", "--alpha", "0.01"])
        assert rc == 0


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
