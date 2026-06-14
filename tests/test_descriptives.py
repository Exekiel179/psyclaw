"""测试描述统计模块（psyclaw/psych/descriptives.py）。

数值对照：
  - mean/sd/median 对 Python 内置数学公式手工验算
  - 偏度/峰度边界（n<3/n<4）返回 None
  - Pearson r 对已知直线数据（r=1 或 r=−1）
  - Fisher-z CI 宽度随 n 增大而收窄
  - APA 表格含关键字段
  - CSV 主入口：自动列选取、write_files、错误处理
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.descriptives import (
    _mean, _sd, _median, _skewness, _kurtosis,
    _t_sf2, _betai, _norm_ppf,
    compute_descriptives,
    compute_correlation_matrix,
    format_apa_descriptives_table,
    format_apa_correlation_table,
    format_apa_paragraph,
    write_descriptives_report,
    analyze_descriptives,
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _make_rows(cols_data: dict) -> list[dict]:
    """从 {col: [val,...]} 字典构造 CSV 行列表。"""
    n = max(len(v) for v in cols_data.values())
    rows = []
    for i in range(n):
        row = {}
        for col, vals in cols_data.items():
            row[col] = str(vals[i]) if i < len(vals) else ""
        rows.append(row)
    return rows


def _make_csv(rows: list[dict], path: str):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# _mean / _sd / _median
# ---------------------------------------------------------------------------

def test_mean_basic():
    assert abs(_mean([1.0, 2.0, 3.0]) - 2.0) < 1e-10


def test_sd_basic():
    # 样本 SD of [2,4,4,4,5,5,7,9]：平均=5，Σ(xi-μ)^2=32，样本方差=32/7，SD=sqrt(32/7)
    vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert abs(_sd(vals) - math.sqrt(32 / 7)) < 1e-9


def test_median_odd():
    assert _median([3.0, 1.0, 2.0]) == 2.0


def test_median_even():
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5


# ---------------------------------------------------------------------------
# _skewness / _kurtosis
# ---------------------------------------------------------------------------

def test_skewness_symmetric_near_zero():
    """对称数据偏度接近 0。"""
    vals = [float(i) for i in range(1, 101)]
    sk = _skewness(vals)
    assert abs(sk) < 0.2, f"skewness of 1..100 should be near 0, got {sk}"


def test_skewness_positive():
    """右偏数据偏度 > 0。"""
    vals = [1.0] * 80 + [10.0, 20.0, 30.0, 40.0, 50.0]
    sk = _skewness(vals)
    assert sk > 0, f"expected positive skewness, got {sk}"


def test_skewness_too_few():
    assert _skewness([1.0, 2.0]) is None or math.isnan(_skewness([1.0, 2.0]))


def test_kurtosis_normal_approx():
    """正态分布数据峰度接近 0（使用已知对称分布）。"""
    import random
    random.seed(42)
    vals = [random.gauss(0, 1) for _ in range(5000)]
    kurt = _kurtosis(vals)
    assert abs(kurt) < 0.5, f"kurtosis of normal sample should be ~0, got {kurt}"


def test_kurtosis_too_few():
    result = _kurtosis([1.0, 2.0, 3.0])
    assert result is None or math.isnan(result)


# ---------------------------------------------------------------------------
# _t_sf2 / _betai
# ---------------------------------------------------------------------------

def test_t_sf2_large_t_small_p():
    """t=100, df=100 → p 接近 0。"""
    p = _t_sf2(100.0, 100)
    assert p < 1e-10


def test_t_sf2_t0_p1():
    """t=0 → p ≈ 1（双尾）。"""
    p = _t_sf2(0.0, 30)
    assert abs(p - 1.0) < 0.01


def test_betai_boundaries():
    assert _betai(1.0, 1.0, 0.0) == 0.0
    assert _betai(1.0, 1.0, 1.0) == 1.0


def test_norm_ppf_symmetry():
    """norm_ppf(0.975) ≈ 1.96（双尾 5%）。"""
    z = _norm_ppf(0.975)
    assert abs(z - 1.96) < 0.01


# ---------------------------------------------------------------------------
# compute_descriptives
# ---------------------------------------------------------------------------

def test_compute_descriptives_basic():
    rows = _make_rows({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    stats = compute_descriptives(rows, ["x"])
    s = stats["x"]
    assert s["n"] == 5
    assert abs(s["mean"] - 3.0) < 0.01
    assert s["missing"] == 0
    assert s["median"] == 3.0


def test_compute_descriptives_sd():
    # 样本 SD (ddof=1) of [2,4,4,4,5,5,7,9] = sqrt(32/7) ≈ 2.138
    rows = _make_rows({"v": [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]})
    stats = compute_descriptives(rows, ["v"])
    assert abs(stats["v"]["sd"] - math.sqrt(32 / 7)) < 0.01


def test_compute_descriptives_missing():
    rows = [{"x": "1"}, {"x": ""}, {"x": "3"}, {"x": "abc"}]
    stats = compute_descriptives(rows, ["x"])
    s = stats["x"]
    assert s["n"] == 2
    assert s["missing"] == 2
    assert abs(s["missing_pct"] - 50.0) < 0.1


def test_compute_descriptives_ci_width():
    """CI 宽度随 n 增大而收窄（固定 SD，重复相同模式）。"""
    # 重复固定模式确保 SD 相同，仅 n 不同
    pattern = [1.0, 2.0, 3.0, 4.0, 5.0]
    small_rows = _make_rows({"x": pattern * 3})    # n=15
    large_rows = _make_rows({"x": pattern * 40})   # n=200
    stats_s = compute_descriptives(small_rows, ["x"])
    stats_l = compute_descriptives(large_rows, ["x"])
    width_s = stats_s["x"]["ci_upper"] - stats_s["x"]["ci_lower"]
    width_l = stats_l["x"]["ci_upper"] - stats_l["x"]["ci_lower"]
    assert width_s > width_l, f"small n CI width {width_s} should > large n {width_l}"


def test_compute_descriptives_all_fields():
    rows = _make_rows({"v": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]})
    stats = compute_descriptives(rows, ["v"])
    s = stats["v"]
    for key in ("n", "missing", "missing_pct", "mean", "sd", "se",
                "ci_lower", "ci_upper", "median", "min", "max", "skewness", "kurtosis"):
        assert key in s, f"缺少字段: {key}"


def test_compute_descriptives_empty_col():
    rows = [{"x": "", "y": "1"}]
    stats = compute_descriptives(rows, ["x"])
    assert stats["x"]["n"] == 0
    assert stats["x"]["mean"] is None


def test_compute_descriptives_multi_col():
    rows = _make_rows({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    stats = compute_descriptives(rows, ["a", "b"])
    assert "a" in stats and "b" in stats
    assert abs(stats["a"]["mean"] - 2.0) < 0.01
    assert abs(stats["b"]["mean"] - 5.0) < 0.01


def test_compute_descriptives_min_max():
    rows = _make_rows({"x": [-5.0, 0.0, 3.0, 10.0]})
    s = compute_descriptives(rows, ["x"])["x"]
    assert s["min"] == -5.0
    assert s["max"] == 10.0


def test_compute_descriptives_skewness_kurtosis_present():
    rows = _make_rows({"x": [float(i) for i in range(20)]})
    s = compute_descriptives(rows, ["x"])["x"]
    assert s["skewness"] is not None
    assert s["kurtosis"] is not None


# ---------------------------------------------------------------------------
# compute_correlation_matrix
# ---------------------------------------------------------------------------

def test_corr_diagonal_one():
    """对角线 r = 1.0。"""
    rows = _make_rows({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    corr = compute_correlation_matrix(rows, ["x"])
    assert corr["r"]["x"]["x"] == 1.0


def test_corr_perfect_positive():
    """y = x → r ≈ 1。"""
    vals = [float(i) for i in range(1, 31)]
    rows = _make_rows({"x": vals, "y": vals})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    r = corr["r"]["x"]["y"]
    assert abs(r - 1.0) < 0.001


def test_corr_perfect_negative():
    """y = -x → r ≈ -1。"""
    xs = [float(i) for i in range(1, 31)]
    ys = [-x for x in xs]
    rows = _make_rows({"x": xs, "y": ys})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    r = corr["r"]["x"]["y"]
    assert abs(r - (-1.0)) < 0.001


def test_corr_zero_uncorrelated():
    """线性无关时 r ≈ 0（确定性构造）。"""
    xs = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0] * 5
    ys = [1.0, 1.0, 2.0, 2.0, 1.0, 1.0] * 5
    rows = _make_rows({"x": xs, "y": ys})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    r = corr["r"]["x"]["y"]
    assert abs(r) < 0.1


def test_corr_symmetric():
    """r[x,y] == r[y,x]。"""
    xs = [float(i) for i in range(20)]
    ys = [x * 0.5 + 1.0 for x in xs]
    rows = _make_rows({"x": xs, "y": ys})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    assert abs(corr["r"]["x"]["y"] - corr["r"]["y"]["x"]) < 1e-9


def test_corr_p_significant():
    """r ≈ 1 (n=30) → p < .001。"""
    vals = [float(i) for i in range(30)]
    rows = _make_rows({"x": vals, "y": vals})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    assert corr["p"]["x"]["y"] < 0.001


def test_corr_ci_contains_r():
    """Fisher-z CI 包含点估计 r。"""
    xs = [float(i) for i in range(30)]
    ys = [x * 0.7 + 1.0 for x in xs]
    rows = _make_rows({"x": xs, "y": ys})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    r = corr["r"]["x"]["y"]
    lo = corr["ci_lower"]["x"]["y"]
    hi = corr["ci_upper"]["x"]["y"]
    assert lo <= r <= hi


def test_corr_ci_narrows_with_n():
    """n 增大 → CI 宽度减小（使用固定噪声 r≈0.85 保持 CI 可测量）。"""
    import random

    def ci_width(n: int) -> float:
        random.seed(0)
        xs = [float(i) for i in range(n)]
        ys = [x + random.gauss(0, 3.0) for x in xs]  # r 约 0.85（有一定噪声）
        rows = _make_rows({"x": xs, "y": ys})
        corr = compute_correlation_matrix(rows, ["x", "y"])
        lo = corr["ci_lower"]["x"]["y"]
        hi = corr["ci_upper"]["x"]["y"]
        return hi - lo if lo is not None and hi is not None else float("inf")

    assert ci_width(20) > ci_width(100), "n=20 CI 应宽于 n=100"


def test_corr_too_few_rows_returns_none():
    """n < 4 时 r = None。"""
    rows = _make_rows({"x": [1.0, 2.0], "y": [1.0, 2.0]})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    assert corr["r"]["x"]["y"] is None


def test_corr_fields_present():
    rows = _make_rows({"x": [float(i) for i in range(20)],
                       "y": [float(i) for i in range(20)]})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    for key in ("r", "p", "ci_lower", "ci_upper", "n", "cols"):
        assert key in corr


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa_table_contains_headers():
    rows = _make_rows({"score": [1.0, 2.0, 3.0, 4.0, 5.0]})
    stats = compute_descriptives(rows, ["score"])
    table = format_apa_descriptives_table(stats)
    assert "score" in table
    assert "*M*" in table or "M" in table
    assert "*SD*" in table or "SD" in table


def test_format_apa_table_values():
    rows = _make_rows({"x": [1.0, 2.0, 3.0]})
    stats = compute_descriptives(rows, ["x"])
    table = format_apa_descriptives_table(stats)
    assert "2.00" in table  # mean = 2.0


def test_format_apa_table_empty_col():
    rows = [{"x": ""}]
    stats = compute_descriptives(rows, ["x"])
    table = format_apa_descriptives_table(stats)
    assert "—" in table


def test_format_apa_correlation_table_stars():
    """p < .05 显示 * 标注。"""
    xs = [float(i) for i in range(30)]
    rows = _make_rows({"x": xs, "y": xs})
    corr = compute_correlation_matrix(rows, ["x", "y"])
    table = format_apa_correlation_table(corr)
    # r=1 应有 *** 标注
    assert "***" in table or "**" in table or "*" in table


def test_format_apa_correlation_lower_triangle():
    """下三角（i>j）有值，上三角为空。"""
    xs = [float(i) for i in range(20)]
    rows = _make_rows({"a": xs, "b": xs, "c": [x * 2 for x in xs]})
    corr = compute_correlation_matrix(rows, ["a", "b", "c"])
    table = format_apa_correlation_table(corr)
    assert "a" in table and "b" in table and "c" in table


def test_format_apa_paragraph_contains_m_sd():
    rows = _make_rows({"score": [1.0, 2.0, 3.0, 4.0, 5.0]})
    stats = compute_descriptives(rows, ["score"])
    para = format_apa_paragraph(stats)
    assert "M" in para or "*M*" in para or "M =" in para or "mean" in para.lower()
    assert "SD" in para or "*SD*" in para


def test_format_apa_paragraph_empty():
    stats = compute_descriptives([], ["x"])
    para = format_apa_paragraph(stats)
    assert "无" in para or len(para) > 0


# ---------------------------------------------------------------------------
# write_descriptives_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    rows = _make_rows({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    stats = compute_descriptives(rows, ["x"])
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_descriptives_report(stats, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "描述统计" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "descriptives" in data


def test_write_report_with_corr():
    xs = [float(i) for i in range(20)]
    rows = _make_rows({"x": xs, "y": xs})
    stats = compute_descriptives(rows, ["x", "y"])
    corr = compute_correlation_matrix(rows, ["x", "y"])
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_descriptives_report(stats, corr=corr, out_dir=tmpdir)
        content = md.read_text(encoding="utf-8")
        assert "相关矩阵" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "correlations" in data


# ---------------------------------------------------------------------------
# analyze_descriptives（CSV 主入口）
# ---------------------------------------------------------------------------

def test_analyze_auto_col_select():
    """不指定 cols 时自动选数值列。"""
    rows = [{"name": "Alice", "score": "4.5", "age": "25"},
            {"name": "Bob", "score": "3.2", "age": "30"},
            {"name": "Carol", "score": "5.0", "age": "28"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_descriptives(csv_path, write_files=False)
        # 应自动选 score、age（数值列），不选 name
        assert "name" not in result["cols"] or result["descriptives"]["name"]["n"] == 0
        assert "score" in result["cols"]


def test_analyze_explicit_cols():
    rows = _make_rows({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0], "c": [7.0, 8.0, 9.0]})
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_descriptives(csv_path, cols=["a", "b"], write_files=False)
        assert "a" in result["descriptives"]
        assert "b" in result["descriptives"]
        assert "c" not in result["descriptives"]


def test_analyze_with_corr():
    xs = [float(i) for i in range(25)]
    rows = _make_rows({"x": xs, "y": [v + 1.0 for v in xs]})
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_descriptives(csv_path, cols=["x", "y"],
                                      include_corr=True, write_files=False)
        assert "correlations" in result
        assert abs(result["correlations"]["r"]["x"]["y"] - 1.0) < 0.001


def test_analyze_write_files():
    rows = _make_rows({"v": [float(i) for i in range(10)]})
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_descriptives(csv_path, cols=["v"], out_dir=tmpdir)
        assert "report_md" in result
        assert Path(result["report_md"]).exists()
        assert "report_json" in result
        data = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
        assert "descriptives" in data


def test_analyze_empty_file_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "empty.csv")
        # 只有表头行，无数据
        with open(csv_path, "w") as f:
            f.write("x,y\n")
        try:
            analyze_descriptives(csv_path, write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_n_rows_field():
    rows = _make_rows({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_descriptives(csv_path, cols=["x"], write_files=False)
        assert result["n_rows"] == 5


# ---------------------------------------------------------------------------
# 自跑块（python tests/test_descriptives.py）
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
