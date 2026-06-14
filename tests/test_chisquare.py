"""测试卡方检验套件（psyclaw/psych/chisquare.py）。

数值对照：
  - 拟合优度：均匀分布时 χ²=0，明显不均时大
  - 独立性：独立时 χ²≈0，关联时 χ² 显著
  - Cramér's V：完全关联 2×2 = 1
  - Fisher 精确：OR=1 时 p≈1；完全关联时 p≤0.05
  - phi 在 [0,1]，Cramér's V 在 [0,1]
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.chisquare import (
    chi2_goodness_of_fit,
    chi2_independence,
    fisher_exact_2x2,
    format_apa_chi2,
    write_chi2_report,
    analyze_chi2,
)


# ---------------------------------------------------------------------------
# chi2_goodness_of_fit
# ---------------------------------------------------------------------------

def test_gof_uniform_chi2_zero():
    """所有类别相等 → χ²=0。"""
    r = chi2_goodness_of_fit([10, 10, 10, 10])
    assert r["chi2"] == 0.0
    assert r["p"] >= 0.99


def test_gof_extreme_not_significant_false():
    """极端不均匀分布 → χ² 大，p < 0.001。"""
    r = chi2_goodness_of_fit([100, 0, 0, 0], expected=[25, 25, 25, 25])
    assert r["chi2"] > 10
    assert r["p"] < 0.001


def test_gof_df_correct():
    r = chi2_goodness_of_fit([10, 20, 30])
    assert r["df"] == 2  # k - 1 = 3 - 1


def test_gof_w_in_range():
    r = chi2_goodness_of_fit([10, 20, 30])
    assert 0 <= r["w"] <= 1


def test_gof_cells_count():
    r = chi2_goodness_of_fit([5, 10, 15], labels=["A", "B", "C"])
    assert len(r["cells"]) == 3
    assert r["cells"][0]["label"] == "A"


def test_gof_expected_auto_uniform():
    """自动均匀期望：N=60，3 类 → 各 20。"""
    r = chi2_goodness_of_fit([10, 20, 30])
    expected_vals = [c["expected"] for c in r["cells"]]
    assert all(abs(e - 20.0) < 0.01 for e in expected_vals)


def test_gof_custom_expected():
    """自定义期望（以比例传入，自动缩放）。"""
    r = chi2_goodness_of_fit([15, 35], expected=[1, 3])
    # 比例 1:3 → 期望 12.5, 37.5（N=50）
    expected_vals = [c["expected"] for c in r["cells"]]
    assert abs(expected_vals[0] - 12.5) < 0.01
    assert abs(expected_vals[1] - 37.5) < 0.01


def test_gof_fields():
    r = chi2_goodness_of_fit([10, 20, 30])
    for k in ("chi2", "df", "p", "N", "w", "significant", "cells"):
        assert k in r, f"缺少字段: {k}"


def test_gof_n_correct():
    r = chi2_goodness_of_fit([10, 20, 30])
    assert r["N"] == 60


def test_gof_too_few_categories():
    try:
        chi2_goodness_of_fit([10])
        assert False
    except ValueError:
        pass


def test_gof_residuals():
    """残差 = 观测 - 期望。"""
    r = chi2_goodness_of_fit([20, 10], expected=[15, 15])
    assert abs(r["cells"][0]["residual"] - 5.0) < 0.01
    assert abs(r["cells"][1]["residual"] + 5.0) < 0.01


# ---------------------------------------------------------------------------
# chi2_independence
# ---------------------------------------------------------------------------

def _independent_table():
    """4×4 独立表：行/列比例完全一致 → χ²≈0。"""
    return [
        [10, 20, 30, 40],
        [5,  10, 15, 20],
    ]


def _associated_table():
    """2×2 强关联：只有对角线有频率。"""
    return [
        [50, 0],
        [0, 50],
    ]


def test_independence_null_chi2_near_zero():
    """完全独立的列联表 → χ²=0，p=1。"""
    r = chi2_independence(_independent_table())
    assert abs(r["chi2"]) < 1e-9
    assert r["p"] > 0.99


def test_independence_associated_significant():
    """强关联 → χ² 大，p < 0.001。"""
    r = chi2_independence(_associated_table())
    assert r["chi2"] > 50
    assert r["p"] < 0.001
    assert r["significant"]


def test_independence_phi_in_range():
    r = chi2_independence(_associated_table())
    assert 0 <= r["phi"] <= 1.0 + 1e-9


def test_independence_cramers_v_in_range():
    r = chi2_independence(_associated_table())
    assert 0 <= r["cramers_v"] <= 1.0 + 1e-9


def test_independence_perfect_association_v_1():
    """完全关联 2×2：Cramér's V ≈ 1。"""
    r = chi2_independence(_associated_table())
    assert r["cramers_v"] > 0.9


def test_independence_df_correct():
    """2×4 表：df = (2-1)*(4-1) = 3。"""
    r = chi2_independence(_independent_table())
    assert r["df"] == 3


def test_independence_expected_shape():
    r = chi2_independence(_independent_table())
    assert len(r["expected"]) == 2
    assert len(r["expected"][0]) == 4


def test_independence_row_col_sums():
    """行/列合计应与原始表一致。"""
    table = [[10, 20], [30, 40]]
    r = chi2_independence(table)
    assert r["row_sums"] == [30, 70]
    assert r["col_sums"] == [40, 60]


def test_independence_fields():
    r = chi2_independence(_associated_table())
    for k in ("chi2", "df", "p", "N", "phi", "cramers_v", "R", "C",
              "significant", "expected"):
        assert k in r


def test_independence_warn_small_expected():
    """小期望频率 > 20% 单元格时应置 warn 标志。"""
    # 总频率极小导致期望 < 5
    table = [[1, 0], [0, 1]]
    r = chi2_independence(table)
    assert r["warn_small_expected"]


def test_independence_2x2_phi_relation():
    """2×2 时 Cramér's V = phi（min(R,C)-1=1）。"""
    table = [[30, 10], [10, 30]]
    r = chi2_independence(table)
    assert abs(r["phi"] - r["cramers_v"]) < 1e-9


def test_independence_3x3():
    """3×3 表：df = 4，Cramér's V 不等于 phi。"""
    table = [[30, 5, 5], [5, 30, 5], [5, 5, 30]]
    r = chi2_independence(table)
    assert r["df"] == 4
    assert r["cramers_v"] != r["phi"]


# ---------------------------------------------------------------------------
# Fisher 精确检验
# ---------------------------------------------------------------------------

def test_fisher_or_1_not_significant():
    """OR=1（平衡表）→ p ≈ 1。"""
    table = [[10, 10], [10, 10]]
    r = fisher_exact_2x2(table)
    assert r["p"] > 0.9
    assert abs(r["OR"] - 1.0) < 0.001


def test_fisher_perfect_association():
    """完全关联（仅对角线）→ p 很小。"""
    table = [[20, 0], [0, 20]]
    r = fisher_exact_2x2(table)
    assert r["p"] < 0.001


def test_fisher_or_correct():
    """OR = (a*d)/(b*c)。"""
    table = [[8, 2], [2, 8]]
    r = fisher_exact_2x2(table)
    assert abs(r["OR"] - 16.0) < 0.01


def test_fisher_fields():
    r = fisher_exact_2x2([[5, 3], [2, 8]])
    for k in ("OR", "p", "a", "b", "c", "d", "N", "significant"):
        assert k in r


def test_fisher_n_correct():
    table = [[5, 3], [2, 8]]
    r = fisher_exact_2x2(table)
    assert r["N"] == 18


def test_fisher_non_2x2():
    try:
        fisher_exact_2x2([[1, 2, 3], [4, 5, 6]])
        assert False
    except ValueError:
        pass


def test_fisher_small_cell():
    """小样本 2×2 → Fisher 精确检验优于 chi²。"""
    table = [[3, 1], [1, 5]]
    r = fisher_exact_2x2(table)
    assert 0 <= r["p"] <= 1


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_gof_apa():
    r = chi2_goodness_of_fit([20, 10, 30])
    text = format_apa_chi2(r)
    assert "*χ*²" in text
    assert "*w*" in text
    assert "拟合优度" in text


def test_format_independence_apa():
    r = chi2_independence(_associated_table())
    text = format_apa_chi2(r)
    assert "*χ*²" in text
    assert "*V*" in text or "Cramér" in text or "φ" in text or "*φ*" in text


def test_format_fisher_apa():
    r = fisher_exact_2x2([[8, 2], [2, 8]])
    text = format_apa_chi2(r)
    assert "Fisher" in text
    assert "OR" in text


def test_format_warn_small_expected():
    table = [[1, 0], [0, 1]]
    r = chi2_independence(table)
    text = format_apa_chi2(r)
    assert "期望频率" in text


# ---------------------------------------------------------------------------
# write_chi2_report
# ---------------------------------------------------------------------------

def test_write_report_gof():
    r = chi2_goodness_of_fit([10, 20, 30], labels=["A", "B", "C"])
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_chi2_report(r, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "拟合优度" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "chi2" in data


def test_write_report_independence():
    r = chi2_independence(_associated_table())
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_chi2_report(r, out_dir=tmpdir, filename="test_indep")
        content = md.read_text(encoding="utf-8")
        assert "独立性" in content


# ---------------------------------------------------------------------------
# analyze_chi2（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_gof_csv():
    rows = [{"category": c, "count": str(n)}
            for c, n in [("A", 10), ("B", 20), ("C", 30)]]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_chi2(csv_path, test="gof", obs_col="count",
                               label_col="category", write_files=True, out_dir=tmpdir)
        assert result["N"] == 60
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_independence_csv():
    """原始数据格式：每行一个观测，含行/列因子。"""
    rows = (
        [{"row": "M", "col": "Y"} for _ in range(30)] +
        [{"row": "M", "col": "N"} for _ in range(10)] +
        [{"row": "F", "col": "Y"} for _ in range(10)] +
        [{"row": "F", "col": "N"} for _ in range(30)]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_chi2(csv_path, test="independence",
                               row_col="row", col_col="col", write_files=False)
        assert result["significant"]
        assert result["N"] == 80


def test_analyze_fisher_csv():
    rows = (
        [{"row": "T", "col": "Yes"} for _ in range(8)] +
        [{"row": "T", "col": "No"} for _ in range(2)] +
        [{"row": "C", "col": "Yes"} for _ in range(2)] +
        [{"row": "C", "col": "No"} for _ in range(8)]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_chi2(csv_path, test="fisher",
                               row_col="row", col_col="col", write_files=False)
        assert result["p"] < 0.05
        assert result["OR"] > 1


def test_analyze_unknown_test():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"x": "1"}], csv_path)
        try:
            analyze_chi2(csv_path, test="unknown", write_files=False)
            assert False
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
