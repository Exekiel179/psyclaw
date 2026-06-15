"""相关系数差异检验测试（psyclaw/psych/compare_corr.py）— 约 60 例。

覆盖：
  分布工具 _norm_cdf / _norm_sf2 / _norm_ppf / _t_sf2 / _betai（10）
  _fisher_z_ci / _pearson_r / _f3（9）
  compare_independent_corrs 含手算金标准（11）
  compare_dependent_overlapping（Williams）含手算金标准（10）
  compare_dependent_nonoverlapping（Steiger）含退化金标准（9）
  interpret_compare（4）
  format_apa_compare_corr（6）
  write_compare_corr_report（3）
  analyze_compare_corr CSV（8）
  边界与错误处理（7）
"""

from __future__ import annotations

import csv
import json
import math
import pathlib

import pytest

from psyclaw.psych.compare_corr import (
    _norm_cdf,
    _norm_sf2,
    _norm_ppf,
    _t_sf2,
    _betai,
    _fisher_z_ci,
    _pearson_r,
    _f3,
    compare_independent_corrs,
    compare_dependent_overlapping,
    compare_dependent_nonoverlapping,
    interpret_compare,
    format_apa_compare_corr,
    write_compare_corr_report,
    analyze_compare_corr,
)


# ---------------------------------------------------------------------------
# 分布工具
# ---------------------------------------------------------------------------

def test_norm_cdf_zero():
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-12


def test_norm_cdf_196():
    assert abs(_norm_cdf(1.959964) - 0.975) < 1e-4


def test_norm_cdf_symmetry():
    assert abs(_norm_cdf(1.3) + _norm_cdf(-1.3) - 1.0) < 1e-12


def test_norm_sf2_zero_is_one():
    assert abs(_norm_sf2(0.0) - 1.0) < 1e-12


def test_norm_sf2_196():
    assert abs(_norm_sf2(1.959964) - 0.05) < 1e-4


def test_norm_sf2_symmetry():
    assert abs(_norm_sf2(2.1) - _norm_sf2(-2.1)) < 1e-12


def test_norm_ppf_median():
    assert abs(_norm_ppf(0.5)) < 1e-6


def test_norm_ppf_975():
    assert abs(_norm_ppf(0.975) - 1.959964) < 1e-4


def test_betai_complement():
    # I_x(a,b) + I_{1-x}(b,a) = 1
    assert abs(_betai(2.0, 3.0, 0.4) + _betai(3.0, 2.0, 0.6) - 1.0) < 1e-9


def test_t_sf2_known():
    # t=2.042, df=30 → 双尾 p ≈ 0.05
    assert abs(_t_sf2(2.042, 30) - 0.05) < 1e-3


# ---------------------------------------------------------------------------
# _fisher_z_ci / _pearson_r / _f3
# ---------------------------------------------------------------------------

def test_fisher_z_ci_brackets_r():
    lo, hi = _fisher_z_ci(0.5, 53, 0.05)
    assert lo < 0.5 < hi


def test_fisher_z_ci_width_shrinks_with_n():
    lo1, hi1 = _fisher_z_ci(0.5, 20, 0.05)
    lo2, hi2 = _fisher_z_ci(0.5, 200, 0.05)
    assert (hi2 - lo2) < (hi1 - lo1)


def test_fisher_z_ci_small_n_nan():
    lo, hi = _fisher_z_ci(0.5, 3, 0.05)
    assert math.isnan(lo) and math.isnan(hi)


def test_fisher_z_ci_r_one_nan():
    lo, hi = _fisher_z_ci(1.0, 50, 0.05)
    assert math.isnan(lo) and math.isnan(hi)


def test_pearson_r_perfect_positive():
    assert abs(_pearson_r([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-12


def test_pearson_r_perfect_negative():
    assert abs(_pearson_r([1, 2, 3, 4], [4, 3, 2, 1]) + 1.0) < 1e-12


def test_pearson_r_zero_variance_nan():
    assert math.isnan(_pearson_r([1, 1, 1], [1, 2, 3]))


def test_f3_removes_leading_zero():
    assert _f3(0.318) == ".318"


def test_f3_negative_removes_leading_zero():
    assert _f3(-0.2) == "-.200"


def test_f3_ge_one_keeps_integer():
    assert _f3(2.249) == "2.249"


def test_f3_none():
    assert _f3(None) == "—"


# ---------------------------------------------------------------------------
# compare_independent_corrs
# ---------------------------------------------------------------------------

def test_indep_equal_corrs_z_zero():
    r = compare_independent_corrs(0.5, 60, 0.5, 60)
    assert abs(r["z"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9
    assert abs(r["diff"]) < 1e-12


def test_indep_gold_standard_z():
    # r1=.7 n1=103, r2=.5 n2=103 → z ≈ 2.2486（手算）
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert abs(r["z"] - 2.2486) < 0.01


def test_indep_gold_standard_p():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert 0.02 < r["p"] < 0.03


def test_indep_significant_flag():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert r["significant"] is True


def test_indep_equal_not_significant():
    r = compare_independent_corrs(0.5, 60, 0.5, 60)
    assert r["significant"] is False


def test_indep_diff_sign():
    r = compare_independent_corrs(0.3, 80, 0.6, 80)
    assert r["diff"] < 0


def test_indep_ci_brackets_diff():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert r["ci_lower"] <= r["diff"] <= r["ci_upper"]


def test_indep_kind_label():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert r["kind"] == "independent"


def test_indep_keys_present():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    for k in ("r1", "n1", "r2", "n2", "diff", "z", "p",
              "ci_lower", "ci_upper", "alpha", "significant"):
        assert k in r


def test_indep_z_antisymmetry():
    a = compare_independent_corrs(0.7, 103, 0.5, 103)
    b = compare_independent_corrs(0.5, 103, 0.7, 103)
    assert abs(a["z"] + b["z"]) < 1e-9


def test_indep_small_n_raises():
    with pytest.raises(ValueError):
        compare_independent_corrs(0.5, 3, 0.5, 50)


# ---------------------------------------------------------------------------
# compare_dependent_overlapping (Williams)
# ---------------------------------------------------------------------------

def test_overlap_equal_corrs_t_zero():
    r = compare_dependent_overlapping(0.5, 0.5, 0.3, 100)
    assert abs(r["t"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9


def test_overlap_gold_standard_t():
    # rjk=.6 rjh=.4 rkh=.5 n=103 → Williams t ≈ 2.4863（手算）
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert abs(r["t"] - 2.4863) < 0.01


def test_overlap_gold_standard_df():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert r["df"] == 100


def test_overlap_gold_standard_p():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert 0.01 < r["p"] < 0.02


def test_overlap_significant_flag():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert r["significant"] is True


def test_overlap_diff():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert abs(r["diff"] - 0.2) < 1e-9


def test_overlap_ci_brackets_diff():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert r["ci_lower"] <= r["diff"] <= r["ci_upper"]


def test_overlap_kind_label():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    assert r["kind"] == "overlapping"


def test_overlap_t_antisymmetry():
    a = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    b = compare_dependent_overlapping(0.4, 0.6, 0.5, 103)
    assert abs(a["t"] + b["t"]) < 1e-9


def test_overlap_small_n_raises():
    with pytest.raises(ValueError):
        compare_dependent_overlapping(0.6, 0.4, 0.5, 3)


# ---------------------------------------------------------------------------
# compare_dependent_nonoverlapping (Steiger)
# ---------------------------------------------------------------------------

def test_nonoverlap_degenerate_gold_standard():
    # 全交叉相关=0：rjk=.5 rhm=.2 n=103 → Z ≈ 2.4507（手算）
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 103)
    assert abs(r["z"] - 2.4507) < 0.01


def test_nonoverlap_degenerate_p():
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 103)
    assert 0.01 < r["p"] < 0.02


def test_nonoverlap_equal_corrs_z_zero():
    r = compare_dependent_nonoverlapping(0.4, 0.4, 0.2, 0.1, 0.15, 0.25, 100)
    assert abs(r["z"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9


def test_nonoverlap_diff():
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0.1, 0.1, 0.1, 0.1, 100)
    assert abs(r["diff"] - 0.3) < 1e-9


def test_nonoverlap_ci_brackets_diff():
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0.1, 0.1, 0.1, 0.1, 100)
    assert r["ci_lower"] <= r["diff"] <= r["ci_upper"]


def test_nonoverlap_kind_label():
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 103)
    assert r["kind"] == "nonoverlapping"


def test_nonoverlap_positive_cross_reduces_se():
    # 正交叉相关 → 估计量正相关 c>0 → 2-2c 减小 → |z| 增大（相对退化情形）
    base = compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 103)
    pos = compare_dependent_nonoverlapping(0.5, 0.2, 0.5, 0.5, 0.5, 0.5, 103)
    assert abs(pos["z"]) > abs(base["z"])


def test_nonoverlap_z_antisymmetry():
    a = compare_dependent_nonoverlapping(0.5, 0.2, 0.1, 0.1, 0.1, 0.1, 100)
    b = compare_dependent_nonoverlapping(0.2, 0.5, 0.1, 0.1, 0.1, 0.1, 100)
    assert abs(a["z"] + b["z"]) < 1e-9


def test_nonoverlap_small_n_raises():
    with pytest.raises(ValueError):
        compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 3)


# ---------------------------------------------------------------------------
# interpret_compare
# ---------------------------------------------------------------------------

def test_interpret_significant_first_stronger():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    txt = interpret_compare(r)
    assert "显著差异" in txt and "前一个" in txt


def test_interpret_significant_second_stronger():
    r = compare_independent_corrs(0.3, 103, 0.7, 103)
    txt = interpret_compare(r)
    assert "显著差异" in txt and "后一个" in txt


def test_interpret_not_significant():
    r = compare_independent_corrs(0.5, 60, 0.5, 60)
    assert "无显著差异" in interpret_compare(r)


def test_interpret_nan_p():
    assert "无法判定" in interpret_compare({"p": float("nan"), "alpha": 0.05, "diff": 0.1})


# ---------------------------------------------------------------------------
# format_apa_compare_corr
# ---------------------------------------------------------------------------

def test_format_independent_contains_fisher():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    out = format_apa_compare_corr(r)
    assert "Fisher" in out and "相关系数差异检验" in out


def test_format_overlapping_contains_williams():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    out = format_apa_compare_corr(r)
    assert "Williams" in out


def test_format_nonoverlapping_contains_steiger():
    r = compare_dependent_nonoverlapping(0.5, 0.2, 0, 0, 0, 0, 103)
    out = format_apa_compare_corr(r)
    assert "Steiger" in out


def test_format_contains_references():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    out = format_apa_compare_corr(r)
    assert "参考文献" in out and "Zou" in out


def test_format_uses_custom_labels():
    r = compare_dependent_overlapping(0.6, 0.4, 0.5, 103)
    out = format_apa_compare_corr(r, labels={"j": "焦虑", "k": "成绩", "h": "睡眠"})
    assert "焦虑" in out


def test_format_returns_str():
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    assert isinstance(format_apa_compare_corr(r), str)


# ---------------------------------------------------------------------------
# write_compare_corr_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files(tmp_path):
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    out = format_apa_compare_corr(r)
    paths = write_compare_corr_report(r, out, tmp_path)
    assert pathlib.Path(paths["md"]).exists()
    assert pathlib.Path(paths["json"]).exists()


def test_write_report_json_valid(tmp_path):
    r = compare_independent_corrs(0.7, 103, 0.5, 103)
    out = format_apa_compare_corr(r)
    paths = write_compare_corr_report(r, out, tmp_path)
    data = json.loads(pathlib.Path(paths["json"]).read_text(encoding="utf-8"))
    assert data["kind"] == "independent"


def test_write_report_no_nan_inf(tmp_path):
    # 退化情形可能产生 nan CI；sidecar 应转为 null
    r = compare_dependent_overlapping(0.95, 0.95, 0.99, 100)
    out = format_apa_compare_corr(r)
    paths = write_compare_corr_report(r, out, tmp_path)
    txt = pathlib.Path(paths["json"]).read_text(encoding="utf-8")
    assert "NaN" not in txt and "Infinity" not in txt


# ---------------------------------------------------------------------------
# analyze_compare_corr CSV
# ---------------------------------------------------------------------------

def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_analyze_independent_csv(tmp_path):
    p = tmp_path / "d.csv"
    rows = []
    for i in range(20):
        rows.append([i, i + (i % 3), 0])      # group 0（正相关，|r|<1）
    for i in range(20):
        rows.append([i, (19 - i) + (i % 5), 1])  # group 1（负相关，|r|<1）
    _write_csv(p, ["x", "y", "g"], rows)
    r = analyze_compare_corr("independent", str(p), x_col="x", y_col="y",
                             group_col="g", out_dir=str(tmp_path))
    assert r["kind"] == "independent"
    assert r["n1"] == 20 and r["n2"] == 20
    assert 0.0 <= r["p"] <= 1.0


def test_analyze_independent_csv_three_groups_raises(tmp_path):
    p = tmp_path / "d.csv"
    _write_csv(p, ["x", "y", "g"],
               [[1, 2, 0], [2, 3, 1], [3, 4, 2], [4, 5, 0]])
    with pytest.raises(ValueError):
        analyze_compare_corr("independent", str(p), x_col="x", y_col="y",
                             group_col="g", out_dir=str(tmp_path))


def test_analyze_overlapping_csv_matches_pearson(tmp_path):
    p = tmp_path / "d.csv"
    rows = [[i, i + (i % 4), (i * 2) % 7] for i in range(30)]
    _write_csv(p, ["x", "y", "z"], rows)
    r = analyze_compare_corr("overlapping", str(p), x_col="x", y_col="y",
                             z_col="z", out_dir=str(tmp_path))
    xs = [row[0] for row in rows]
    ys = [row[1] for row in rows]
    assert abs(r["r_jk"] - round(_pearson_r(xs, ys), 6)) < 1e-6
    assert r["kind"] == "overlapping"


def test_analyze_nonoverlapping_csv(tmp_path):
    p = tmp_path / "d.csv"
    rows = [[i, (i * 3) % 11, (i * 2) % 7, (i + 5) % 9] for i in range(40)]
    _write_csv(p, ["a", "b", "c", "d"], rows)
    r = analyze_compare_corr("nonoverlapping", str(p), var_cols=["a", "b", "c", "d"],
                             out_dir=str(tmp_path))
    assert r["kind"] == "nonoverlapping"
    assert r["n"] == 40


def test_analyze_excludes_missing_rows(tmp_path):
    p = tmp_path / "d.csv"
    rows = [[i, i + 1, i + 2] for i in range(20)]
    rows.append(["", "5", "6"])      # 缺失行
    _write_csv(p, ["x", "y", "z"], rows)
    r = analyze_compare_corr("overlapping", str(p), x_col="x", y_col="y",
                             z_col="z", out_dir=str(tmp_path))
    assert r["n_excluded"] == 1
    assert r["n"] == 20


def test_analyze_return_json_clean(tmp_path):
    p = tmp_path / "d.csv"
    rows = [[i, i + (i % 4), (i * 2) % 7] for i in range(30)]
    _write_csv(p, ["x", "y", "z"], rows)
    out = analyze_compare_corr("overlapping", str(p), x_col="x", y_col="y",
                               z_col="z", out_dir=str(tmp_path), return_json=True)
    assert "_formatted" not in out
    assert out["kind"] == "overlapping"


def test_analyze_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        analyze_compare_corr("overlapping", str(tmp_path / "nope.csv"),
                             x_col="x", y_col="y", z_col="z", out_dir=str(tmp_path))


def test_analyze_overlapping_writes_report(tmp_path):
    p = tmp_path / "d.csv"
    rows = [[i, i + (i % 4), (i * 2) % 7] for i in range(30)]
    _write_csv(p, ["x", "y", "z"], rows)
    r = analyze_compare_corr("overlapping", str(p), x_col="x", y_col="y",
                             z_col="z", out_dir=str(tmp_path))
    assert pathlib.Path(r["_paths"]["md"]).exists()


# ---------------------------------------------------------------------------
# 边界与错误处理
# ---------------------------------------------------------------------------

def test_invalid_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        analyze_compare_corr("bogus", out_dir=str(tmp_path))


def test_r_out_of_range_raises():
    with pytest.raises(ValueError):
        compare_independent_corrs(1.5, 50, 0.3, 50)


def test_indep_r_equals_one_raises():
    with pytest.raises(ValueError):
        compare_independent_corrs(1.0, 50, 0.3, 50)


def test_overlap_singular_denominator_raises():
    # 接近完全相关矩阵 → denom 可能非正
    with pytest.raises(ValueError):
        compare_dependent_overlapping(0.99, -0.99, 0.99, 50)


def test_independent_manual_requires_all_args(tmp_path):
    with pytest.raises(ValueError):
        analyze_compare_corr("independent", None, r1=0.5, n1=50,
                             out_dir=str(tmp_path))


def test_nonoverlapping_manual_via_analyze_raises(tmp_path):
    with pytest.raises(ValueError):
        analyze_compare_corr("nonoverlapping", None, out_dir=str(tmp_path))


def test_alpha_affects_ci_width():
    wide = compare_independent_corrs(0.7, 103, 0.5, 103, alpha=0.01)
    narrow = compare_independent_corrs(0.7, 103, 0.5, 103, alpha=0.10)
    w_wide = wide["ci_upper"] - wide["ci_lower"]
    w_narrow = narrow["ci_upper"] - narrow["ci_lower"]
    assert w_wide > w_narrow
