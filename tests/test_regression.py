"""测试 OLS 回归模块（psyclaw/psych/regression.py）。

数值对照：
  - 简单线性回归（y=2x+1）：截距=1，斜率=2，R²=1
  - 完全拟合时 R²=1，SSE=0
  - 多元回归：正交预测变量时系数独立
  - SE / t / p 对已知结果校验
  - β（标准化）= b * sd_x / sd_y
  - Fisher-z CI 宽度随 n 增大收窄
  - 错误处理：奇异矩阵、数据不足
  - APA 表格含关键字段
  - CSV 主入口：完整案例过滤、write_files
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.regression import (
    _mat_transpose, _mat_mult, _mat_invert,
    _t_sf2, _f_sf,
    compute_ols,
    format_apa_regression_table,
    format_apa_paragraph,
    write_regression_report,
    analyze_regression,
)


# ---------------------------------------------------------------------------
# 矩阵工具
# ---------------------------------------------------------------------------

def test_mat_transpose():
    A = [[1, 2, 3], [4, 5, 6]]
    T = _mat_transpose(A)
    assert T[0] == [1, 4]
    assert T[1] == [2, 5]
    assert T[2] == [3, 6]


def test_mat_mult_identity():
    I = [[1, 0], [0, 1]]
    A = [[3, 4], [5, 6]]
    assert _mat_mult(I, A) == A


def test_mat_invert_2x2():
    """[[2,0],[0,4]]^{-1} = [[0.5,0],[0,0.25]]。"""
    M = [[2.0, 0.0], [0.0, 4.0]]
    inv = _mat_invert(M)
    assert inv is not None
    assert abs(inv[0][0] - 0.5) < 1e-9
    assert abs(inv[1][1] - 0.25) < 1e-9


def test_mat_invert_singular():
    """奇异矩阵返回 None。"""
    M = [[1.0, 2.0], [2.0, 4.0]]
    assert _mat_invert(M) is None


def test_mat_invert_roundtrip():
    """A × A^{-1} ≈ I。"""
    A = [[4.0, 3.0], [3.0, 2.0]]
    Ainv = _mat_invert(A)
    assert Ainv is not None
    prod = _mat_mult(A, Ainv)
    for i in range(2):
        for j in range(2):
            expected = 1.0 if i == j else 0.0
            assert abs(prod[i][j] - expected) < 1e-9


# ---------------------------------------------------------------------------
# _t_sf2 / _f_sf
# ---------------------------------------------------------------------------

def test_t_sf2_known():
    """t=2, df=10 → p ≈ 0.074（双尾，课本值）。"""
    p = _t_sf2(2.0, 10)
    assert 0.06 < p < 0.09, f"got {p}"


def test_f_sf_large():
    """F 很大 → p 很小。"""
    p = _f_sf(100.0, 5, 100)
    assert p < 1e-10


def test_f_sf_zero():
    """F=0 → p=1。"""
    p = _f_sf(0.0, 1, 10)
    assert math.isnan(p) or p >= 0.99


# ---------------------------------------------------------------------------
# compute_ols 简单线性回归
# ---------------------------------------------------------------------------

def _simple_ols(slope: float = 2.0, intercept: float = 1.0, n: int = 30):
    """生成 y = slope*x + intercept 的完美数据。"""
    xs = [float(i) for i in range(n)]
    ys = [slope * x + intercept for x in xs]
    X = [[x] for x in xs]
    return xs, ys, X


def test_ols_perfect_fit_r2():
    """完美线性关系 R²=1，SSE≈0。"""
    _, y, X = _simple_ols()
    result = compute_ols(y, X, iv_names=["x"])
    assert abs(result["R2"] - 1.0) < 1e-6
    assert result["SSE"] < 1e-6


def test_ols_coefficients_simple():
    """y = 2x + 1 → 截距≈1，斜率≈2。"""
    _, y, X = _simple_ols(slope=2.0, intercept=1.0)
    result = compute_ols(y, X, iv_names=["x"])
    coefs = {c["name"]: c for c in result["coefficients"]}
    assert abs(coefs["截距 (Intercept)"]["B"] - 1.0) < 0.01
    assert abs(coefs["x"]["B"] - 2.0) < 0.01


def test_ols_r2_adj_le_r2():
    """调整 R² ≤ R²。"""
    _, y, X = _simple_ols()
    result = compute_ols(y, X, iv_names=["x"])
    assert result["R2_adj"] <= result["R2"]


def test_ols_f_test_significant():
    """R²=1 时 F 应极大，p < .001。"""
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    assert result["F"] is not None and result["F"] > 100
    assert result["F_p"] is not None and result["F_p"] < 0.001


def test_ols_se_positive():
    """所有系数 SE > 0（非完全拟合时）。"""
    import random
    random.seed(1)
    xs = [float(i) for i in range(30)]
    ys = [2.0 * x + 1.0 + random.gauss(0, 1) for x in xs]
    X = [[x] for x in xs]
    result = compute_ols(ys, X, iv_names=["x"])
    for c in result["coefficients"]:
        assert c["SE"] > 0, f"{c['name']} SE={c['SE']}"


def test_ols_t_p_consistent():
    """t = B/SE，p 双尾；|t| 大时 p 小。"""
    import random
    random.seed(2)
    xs = [float(i) for i in range(40)]
    ys = [3.0 * x + random.gauss(0, 1) for x in xs]
    X = [[x] for x in xs]
    result = compute_ols(ys, X, iv_names=["x"])
    coef = [c for c in result["coefficients"] if c["name"] == "x"][0]
    assert coef["t"] > 10  # slope=3, n=40 → t 很大
    assert coef["p"] < 0.001


def test_ols_ci_contains_true_value():
    """95% CI 应包含真实斜率（足够大 n 下大概率成立）。"""
    import random
    random.seed(3)
    xs = [float(i) for i in range(50)]
    ys = [2.0 * x + 1.0 + random.gauss(0, 3) for x in xs]
    X = [[x] for x in xs]
    result = compute_ols(ys, X, iv_names=["x"])
    coef = [c for c in result["coefficients"] if c["name"] == "x"][0]
    assert coef["ci_lower"] < 2.0 < coef["ci_upper"]


def test_ols_beta_standardized():
    """β = B * sd_x / sd_y（手工验证）。"""
    import random
    random.seed(4)
    xs = [float(i) for i in range(30)]
    ys = [1.5 * x + random.gauss(0, 2) for x in xs]
    X = [[x] for x in xs]

    def sd(vals):
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))

    result = compute_ols(ys, X, iv_names=["x"])
    coef = [c for c in result["coefficients"] if c["name"] == "x"][0]
    expected_beta = coef["B"] * sd(xs) / sd(ys)
    assert abs(coef["beta"] - expected_beta) < 0.001


# ---------------------------------------------------------------------------
# 多元回归
# ---------------------------------------------------------------------------

def test_ols_multiple_coefficients():
    """y = 2x1 + 3x2 + 1：正交预测变量，系数独立恢复。"""
    n = 40
    # x1 = 0..n-1; x2 = alternating ±1（与 x1 正交）
    xs1 = [float(i) for i in range(n)]
    xs2 = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    ys = [2.0 * xs1[i] + 3.0 * xs2[i] + 1.0 for i in range(n)]
    X = [[xs1[i], xs2[i]] for i in range(n)]
    result = compute_ols(ys, X, iv_names=["x1", "x2"])
    coefs = {c["name"]: c for c in result["coefficients"]}
    assert abs(coefs["x1"]["B"] - 2.0) < 0.01, f"x1 B={coefs['x1']['B']}"
    assert abs(coefs["x2"]["B"] - 3.0) < 0.01, f"x2 B={coefs['x2']['B']}"


def test_ols_r2_multiple_ge_simple():
    """多元 R² ≥ 简单 R²（添加有效预测变量只会增大 R²）。"""
    import random
    random.seed(5)
    n = 50
    xs1 = [float(i) for i in range(n)]
    xs2 = [random.gauss(0, 1) for _ in range(n)]
    ys = [2 * xs1[i] + 0.5 * xs2[i] + random.gauss(0, 1) for i in range(n)]
    result_simple = compute_ols(ys, [[x] for x in xs1], iv_names=["x1"])
    result_multi = compute_ols(ys, [[xs1[i], xs2[i]] for i in range(n)], iv_names=["x1", "x2"])
    assert result_multi["R2"] >= result_simple["R2"]


def test_ols_too_few_rows_raises():
    """有效行数不足时抛出 ValueError。"""
    X = [[1.0], [2.0]]
    y = [1.0, 2.0]
    try:
        compute_ols(y, X, iv_names=["x"])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_ols_singular_raises():
    """完全多重共线（x2=2*x1）时应抛出 ValueError。"""
    xs1 = [float(i) for i in range(20)]
    xs2 = [x * 2 for x in xs1]
    ys = [3.0 * x + 1.0 for x in xs1]
    X = [[xs1[i], xs2[i]] for i in range(20)]
    try:
        compute_ols(ys, X, iv_names=["x1", "x2"])
        assert False, "应抛出 ValueError（奇异矩阵）"
    except ValueError:
        pass


def test_ols_fields_present():
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    for key in ("n", "k", "df_model", "df_resid", "coefficients",
                "R2", "R2_adj", "F", "F_p", "SSE", "SSR", "SST", "MSE", "RMSE"):
        assert key in result, f"缺少字段: {key}"


def test_ols_df_correct():
    _, y, X = _simple_ols(n=25)
    result = compute_ols(y, X, iv_names=["x"])
    assert result["df_model"] == 1
    assert result["df_resid"] == 23  # n - k - 1 = 25 - 1 - 1 = 23


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa_table_headers():
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    table = format_apa_regression_table(result)
    assert "*B*" in table
    assert "*β*" in table
    assert "*SE*" in table
    assert "*t*" in table
    assert "*p*" in table
    assert "95% CI" in table


def test_format_apa_table_has_intercept():
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    table = format_apa_regression_table(result)
    assert "截距" in table or "Intercept" in table


def test_format_apa_table_r2():
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    table = format_apa_regression_table(result)
    assert "R" in table and "²" in table


def test_format_apa_paragraph_contains_key_info():
    import random
    random.seed(6)
    xs = [float(i) for i in range(30)]
    ys = [2.0 * x + random.gauss(0, 1) for x in xs]
    result = compute_ols(ys, [[x] for x in xs], iv_names=["age"],
                          dv_name="score")
    para = format_apa_paragraph(result)
    assert "score" in para
    assert "age" in para
    assert "R" in para


def test_format_apa_paragraph_significant():
    """显著预测变量应出现在段落中。"""
    import random
    random.seed(7)
    xs = [float(i) for i in range(40)]
    ys = [5.0 * x + random.gauss(0, 1) for x in xs]
    result = compute_ols(ys, [[x] for x in xs], iv_names=["x"], dv_name="y")
    para = format_apa_paragraph(result)
    # x 应为显著预测变量（slope=5, n=40）
    assert "x" in para and ("显著" in para or "p" in para)


# ---------------------------------------------------------------------------
# write_regression_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    _, y, X = _simple_ols(n=20)
    result = compute_ols(y, X, iv_names=["x"])
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_regression_report(result, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "OLS" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "R2" in data
        assert "coefficients" in data


# ---------------------------------------------------------------------------
# analyze_regression（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows: list[dict], path: str):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_regression_simple():
    """y = 2x + 1 从 CSV 恢复斜率≈2，截距≈1。"""
    rows = [{"x": str(float(i)), "y": str(2.0 * i + 1.0)} for i in range(30)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_regression(csv_path, dv="y", ivs=["x"],
                                    out_dir=tmpdir, write_files=True)
        assert abs(result["R2"] - 1.0) < 1e-6
        coefs = {c["name"]: c for c in result["coefficients"]}
        assert abs(coefs["x"]["B"] - 2.0) < 0.01
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_regression_missing_data():
    """含缺失值的行被过滤，完整案例分析。"""
    rows = [{"x": str(float(i)), "y": str(2.0 * i + 1.0)} for i in range(25)]
    rows[5]["y"] = ""  # 缺失值
    rows[10]["x"] = "nan"  # 非数值
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_regression(csv_path, dv="y", ivs=["x"],
                                    out_dir=tmpdir, write_files=False)
        assert result["n"] == 23  # 25 - 2 缺失行
        assert result["n_excluded"] == 2


def test_analyze_regression_json_output():
    """write_files=True 时 report_json 含必要字段。"""
    rows = [{"x": str(float(i)), "y": str(1.5 * i)} for i in range(20)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_regression(csv_path, dv="y", ivs=["x"],
                                    out_dir=tmpdir, write_files=True)
        data = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
        for key in ("R2", "F", "F_p", "coefficients", "n", "dv_name", "iv_names"):
            assert key in data


def test_analyze_regression_too_few_rows():
    """有效行数不足时抛出 ValueError。"""
    rows = [{"x": "1", "y": "2"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_regression(csv_path, dv="y", ivs=["x"], write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 自跑块
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
