"""评分者间信度测试（psyclaw/psych/irr.py）。

覆盖：
  分布工具 _norm_cdf / _norm_sf2 / _f_cdf / _f_ppf / _inv_norm（10）
  _agreement_weights（7）
  cohens_kappa — 未加权（12）
  cohens_kappa — 加权（8）
  fleiss_kappa（11）
  ratings_to_fleiss_counts（5）
  intraclass_correlation（14，含 Shrout & Fleiss 1979 金标准）
  interpret_kappa / interpret_icc（10）
  格式化 format_apa_kappa / format_apa_icc（8）
  write_irr_report（4）
  analyze_irr（10）
  边界与错误处理（7）
"""

from __future__ import annotations

import json
import math

import pytest

from psyclaw.psych import irr


# ---------------------------------------------------------------------------
# 分布工具
# ---------------------------------------------------------------------------

def test_norm_cdf_zero():
    assert abs(irr._norm_cdf(0.0) - 0.5) < 1e-9


def test_norm_cdf_symmetry():
    assert abs(irr._norm_cdf(1.5) + irr._norm_cdf(-1.5) - 1.0) < 1e-9


def test_norm_sf2_196():
    # |z|=1.96 → 双尾 p≈0.05
    assert abs(irr._norm_sf2(1.96) - 0.05) < 0.001


def test_norm_sf2_symmetric():
    assert abs(irr._norm_sf2(2.0) - irr._norm_sf2(-2.0)) < 1e-12


def test_f_cdf_zero():
    assert irr._f_cdf(0.0, 5, 15) == 0.0


def test_f_cdf_monotone():
    assert irr._f_cdf(1.0, 5, 15) < irr._f_cdf(5.0, 5, 15)


def test_f_ppf_roundtrip():
    # F_ppf(cdf(f)) ≈ f
    f = 3.5
    p = irr._f_cdf(f, 5, 15)
    assert abs(irr._f_ppf(p, 5, 15) - f) < 0.01


def test_f_ppf_critical():
    # F(1,30) 0.95 分位 ≈ 4.171（教科书）
    assert abs(irr._f_ppf(0.95, 1, 30) - 4.171) < 0.02


def test_inv_norm_median():
    assert abs(irr._inv_norm(0.5)) < 1e-9


def test_inv_norm_975():
    assert abs(irr._inv_norm(0.975) - 1.959964) < 1e-3


# ---------------------------------------------------------------------------
# _agreement_weights
# ---------------------------------------------------------------------------

def test_weights_nominal_identity():
    W = irr._agreement_weights(3, None)
    assert W == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def test_weights_diag_one():
    for scheme in (None, "linear", "quadratic"):
        W = irr._agreement_weights(4, scheme)
        for i in range(4):
            assert abs(W[i][i] - 1.0) < 1e-12


def test_weights_linear_values():
    W = irr._agreement_weights(3, "linear")
    # |i-j|/(k-1): w[0][2] = 1 - 2/2 = 0
    assert abs(W[0][2] - 0.0) < 1e-12
    assert abs(W[0][1] - 0.5) < 1e-12


def test_weights_quadratic_values():
    W = irr._agreement_weights(3, "quadratic")
    # 1-(i-j)^2/(k-1)^2: w[0][1]=1-1/4=0.75
    assert abs(W[0][1] - 0.75) < 1e-12
    assert abs(W[0][2] - 0.0) < 1e-12


def test_weights_symmetric():
    W = irr._agreement_weights(4, "quadratic")
    for i in range(4):
        for j in range(4):
            assert abs(W[i][j] - W[j][i]) < 1e-12


def test_weights_unknown_raises():
    with pytest.raises(ValueError):
        irr._agreement_weights(3, "cubic")


def test_weights_quadratic_higher_than_linear_intermediate_offdiag():
    # 一致性权重 w=1−(d/(k−1))^p：在中间距离格（d=2,k=5），二次惩罚更轻 →
    # 加权一致性值更大（原断言方向写反，二次对近失配惩罚更小）。
    Wl = irr._agreement_weights(5, "linear")
    Wq = irr._agreement_weights(5, "quadratic")
    assert Wq[0][2] > Wl[0][2]  # 0.75 > 0.5


# ---------------------------------------------------------------------------
# cohens_kappa — 未加权
# ---------------------------------------------------------------------------

def _make_2x2(a_yes_b_yes, a_yes_b_no, a_no_b_yes, a_no_b_no):
    """构造 2x2 的标签列表。"""
    a, b = [], []
    a += ["Y"] * a_yes_b_yes; b += ["Y"] * a_yes_b_yes
    a += ["Y"] * a_yes_b_no;  b += ["N"] * a_yes_b_no
    a += ["N"] * a_no_b_yes;  b += ["Y"] * a_no_b_yes
    a += ["N"] * a_no_b_no;   b += ["N"] * a_no_b_no
    return a, b


def test_kappa_textbook_value():
    # 20/5/10/15 → po=.70, pe=.50, κ=0.40
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert abs(res["kappa"] - 0.40) < 1e-6


def test_kappa_textbook_po_pe():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert abs(res["p_o"] - 0.70) < 1e-6
    assert abs(res["p_e"] - 0.50) < 1e-6


def test_kappa_textbook_se():
    # 渐近 SE ≈ 0.127（手算 Fleiss-Cohen-Everitt 1969）
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert abs(res["se"] - 0.127) < 0.002


def test_kappa_perfect_agreement():
    a = ["A", "B", "C", "A", "B"]
    res = irr.cohens_kappa(a, list(a))
    assert abs(res["kappa"] - 1.0) < 1e-9


def test_kappa_perfect_po_one():
    a = ["A", "B", "C", "A", "B"]
    res = irr.cohens_kappa(a, list(a))
    assert abs(res["p_o"] - 1.0) < 1e-9


def test_kappa_significant_when_strong():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert res["p"] < 0.05


def test_kappa_z_positive():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert res["z"] > 0


def test_kappa_ci_contains_estimate():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert res["ci_lower"] <= res["kappa"] <= res["ci_upper"]


def test_kappa_n_correct():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert res["n"] == 50


def test_kappa_categories_count():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    assert res["n_categories"] == 2


def test_kappa_chance_level_near_zero():
    # 完全独立的边际，κ 应接近 0
    a = ["Y", "Y", "N", "N"] * 10
    b = ["Y", "N", "Y", "N"] * 10
    res = irr.cohens_kappa(a, b)
    assert abs(res["kappa"]) < 1e-6


def test_kappa_length_mismatch_raises():
    with pytest.raises(ValueError):
        irr.cohens_kappa(["A", "B"], ["A"])


# ---------------------------------------------------------------------------
# cohens_kappa — 加权
# ---------------------------------------------------------------------------

def test_weighted_unweighted_equals_nominal():
    # 名义权重（None）== 显式 identity；线性加权对 2 类等于未加权
    a, b = _make_2x2(20, 5, 10, 15)
    plain = irr.cohens_kappa(a, b)
    lin = irr.cohens_kappa(a, b, weights="linear")
    # k=2 时 linear/quadratic 权重退化为名义（中间无类别）
    assert abs(plain["kappa"] - lin["kappa"]) < 1e-9


def test_weighted_quadratic_2cat_equals_plain():
    a, b = _make_2x2(20, 5, 10, 15)
    plain = irr.cohens_kappa(a, b)
    quad = irr.cohens_kappa(a, b, weights="quadratic")
    assert abs(plain["kappa"] - quad["kappa"]) < 1e-9


def test_weighted_label_set():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b, weights="linear")
    assert res["weights"] == "linear"


def test_weighted_ge_unweighted_3cat():
    # 有序数据，邻近不一致下加权 κ ≥ 未加权 κ
    a = [1, 1, 2, 2, 3, 3, 1, 2, 3, 2]
    b = [1, 2, 2, 3, 3, 2, 1, 2, 3, 1]
    plain = irr.cohens_kappa(a, b)
    quad = irr.cohens_kappa(a, b, weights="quadratic")
    assert quad["kappa"] >= plain["kappa"] - 1e-9


def test_weighted_perfect_agreement():
    a = [1, 2, 3, 2, 1]
    res = irr.cohens_kappa(a, list(a), weights="quadratic")
    assert abs(res["kappa"] - 1.0) < 1e-9


def test_weighted_custom_categories():
    a = [1, 2, 3]
    b = [1, 2, 3]
    res = irr.cohens_kappa(a, b, weights="linear", categories=[1, 2, 3])
    assert abs(res["kappa"] - 1.0) < 1e-9


def test_weighted_returns_finite_se():
    a = [1, 1, 2, 2, 3, 3, 1, 2, 3, 2]
    b = [1, 2, 2, 3, 3, 2, 1, 2, 3, 1]
    res = irr.cohens_kappa(a, b, weights="linear")
    assert math.isfinite(res["se"])


def test_weighted_interpretation_present():
    a = [1, 1, 2, 2, 3, 3]
    b = [1, 1, 2, 2, 3, 3]
    res = irr.cohens_kappa(a, b, weights="linear")
    assert "完美" in res["interpretation"]


# ---------------------------------------------------------------------------
# fleiss_kappa
# ---------------------------------------------------------------------------

def test_fleiss_perfect_agreement():
    # 2 对象，每个 2 评分者全一致 → κ=1
    counts = [[2, 0], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert abs(res["kappa"] - 1.0) < 1e-9


def test_fleiss_known_one_third():
    # 手算 κ = 1/3（见模块说明）
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert abs(res["kappa"] - 1.0 / 3.0) < 1e-6


def test_fleiss_pe():
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert abs(res["p_e"] - 0.5) < 1e-9


def test_fleiss_p_mean():
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert abs(res["p_mean"] - 2.0 / 3.0) < 1e-6


def test_fleiss_n_subjects():
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert res["n_subjects"] == 3


def test_fleiss_n_raters():
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    assert res["n_raters"] == 2


def test_fleiss_n_categories():
    counts = [[3, 0, 0], [0, 3, 0], [0, 0, 3]]
    res = irr.fleiss_kappa(counts)
    assert res["n_categories"] == 3


def test_fleiss_category_p_sums_one():
    counts = [[2, 1], [1, 2], [3, 0]]
    res = irr.fleiss_kappa(counts)
    assert abs(sum(res["category_p"]) - 1.0) < 1e-9


def test_fleiss_unequal_raters_raises():
    counts = [[2, 0], [1, 1], [0, 3]]  # 第三行总和=3
    with pytest.raises(ValueError):
        irr.fleiss_kappa(counts)


def test_fleiss_too_few_subjects_raises():
    with pytest.raises(ValueError):
        irr.fleiss_kappa([[2, 0]])


def test_fleiss_perfect_z_significant():
    counts = [[3, 0], [0, 3], [3, 0], [0, 3]]
    res = irr.fleiss_kappa(counts)
    assert res["p"] < 0.05


# ---------------------------------------------------------------------------
# ratings_to_fleiss_counts
# ---------------------------------------------------------------------------

def test_ratings_to_counts_basic():
    table = [["A", "A"], ["A", "B"], ["B", "B"]]
    counts, cats = irr.ratings_to_fleiss_counts(table)
    assert cats == ["A", "B"]
    assert counts == [[2, 0], [1, 1], [0, 2]]


def test_ratings_to_counts_ignores_missing():
    table = [["A", "A", None], ["A", "B", ""]]
    counts, cats = irr.ratings_to_fleiss_counts(table)
    assert counts[0] == [2, 0]
    assert counts[1] == [1, 1]


def test_ratings_to_counts_custom_cats():
    table = [["X", "Y"]]
    counts, cats = irr.ratings_to_fleiss_counts(table, categories=["X", "Y", "Z"])
    assert counts == [[1, 1, 0]]


def test_ratings_to_counts_three_cats():
    table = [["A", "B", "C"]]
    counts, cats = irr.ratings_to_fleiss_counts(table)
    assert counts == [[1, 1, 1]]


def test_ratings_to_counts_unknown_cat_raises():
    table = [["A", "Q"]]
    with pytest.raises(ValueError):
        irr.ratings_to_fleiss_counts(table, categories=["A", "B"])


# ---------------------------------------------------------------------------
# intraclass_correlation — Shrout & Fleiss 1979 金标准数据
# ---------------------------------------------------------------------------

SF_DATA = [
    [9, 2, 5, 8],
    [6, 1, 3, 2],
    [8, 4, 6, 8],
    [7, 1, 2, 6],
    [10, 5, 6, 9],
    [6, 2, 4, 7],
]


def test_icc_ms_msr():
    ms = irr._icc_ms(SF_DATA)
    assert abs(ms["MSR"] - 11.2417) < 0.01


def test_icc_ms_mse():
    ms = irr._icc_ms(SF_DATA)
    assert abs(ms["MSE"] - 1.0194) < 0.01


def test_icc_ms_msc():
    ms = irr._icc_ms(SF_DATA)
    assert abs(ms["MSC"] - 32.4861) < 0.01


def test_icc_ms_msw():
    ms = irr._icc_ms(SF_DATA)
    assert abs(ms["MSW"] - 6.2639) < 0.01


def test_icc_1_1_value():
    res = irr.intraclass_correlation(SF_DATA)
    assert abs(res["icc1_1"]["icc"] - 0.1657) < 0.005


def test_icc_2_1_value():
    res = irr.intraclass_correlation(SF_DATA)
    assert abs(res["icc2_1"]["icc"] - 0.2898) < 0.005


def test_icc_3_1_value():
    res = irr.intraclass_correlation(SF_DATA)
    assert abs(res["icc3_1"]["icc"] - 0.7148) < 0.005


def test_icc_3_k_value():
    res = irr.intraclass_correlation(SF_DATA)
    assert abs(res["icc3_k"]["icc"] - 0.9093) < 0.005


def test_icc_avg_ge_single():
    # 平均测度 ≥ 单次测度（Spearman-Brown）
    res = irr.intraclass_correlation(SF_DATA)
    assert res["icc3_k"]["icc"] >= res["icc3_1"]["icc"]
    assert res["icc1_k"]["icc"] >= res["icc1_1"]["icc"]


def test_icc_f_df():
    res = irr.intraclass_correlation(SF_DATA)
    assert res["icc3_1"]["df1"] == 5
    assert abs(res["icc3_1"]["df2"] - 15) < 1e-9


def test_icc_f_value():
    # F(3,1) = MSR/MSE ≈ 11.027
    res = irr.intraclass_correlation(SF_DATA)
    assert abs(res["icc3_1"]["f"] - 11.027) < 0.05


def test_icc_p_in_range():
    res = irr.intraclass_correlation(SF_DATA)
    for key in ("icc1_1", "icc2_1", "icc3_1"):
        p = res[key]["p"]
        assert 0.0 <= p <= 1.0


def test_icc_ci_brackets_point():
    res = irr.intraclass_correlation(SF_DATA)
    m = res["icc3_1"]
    assert m["ci_lower"] <= m["icc"] <= m["ci_upper"]


def test_icc_perfect_agreement():
    data = [[1, 1], [2, 2], [3, 3], [4, 4], [5, 5]]
    res = irr.intraclass_correlation(data)
    assert abs(res["icc3_1"]["icc"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# interpret
# ---------------------------------------------------------------------------

def test_interpret_kappa_nan():
    assert irr.interpret_kappa(float("nan")) == "无法计算"


def test_interpret_kappa_negative():
    assert "差" in irr.interpret_kappa(-0.1)


def test_interpret_kappa_slight():
    assert "轻微" in irr.interpret_kappa(0.15)


def test_interpret_kappa_moderate():
    assert "中等" in irr.interpret_kappa(0.50)


def test_interpret_kappa_almost_perfect():
    assert "完美" in irr.interpret_kappa(0.90)


def test_interpret_kappa_boundary_substantial():
    # 0.80 应仍为「较强」（含上界）
    assert "较强" in irr.interpret_kappa(0.80)


def test_interpret_icc_poor():
    assert "差" in irr.interpret_icc(0.40)


def test_interpret_icc_moderate():
    assert "中等" in irr.interpret_icc(0.60)


def test_interpret_icc_good():
    assert "良好" in irr.interpret_icc(0.80)


def test_interpret_icc_excellent():
    assert "优秀" in irr.interpret_icc(0.95)


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------

def test_format_kappa_str():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    out = irr.format_apa_kappa(res, method="cohen")
    assert isinstance(out, str) and "Cohen" in out


def test_format_kappa_has_reference():
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    out = irr.format_apa_kappa(res, method="cohen")
    assert "Landis" in out and "Cohen, J. (1960)" in out


def test_format_fleiss():
    counts = [[2, 0], [1, 1], [0, 2]]
    res = irr.fleiss_kappa(counts)
    out = irr.format_apa_kappa(res, method="fleiss")
    assert "Fleiss" in out


def test_format_icc_str():
    res = irr.intraclass_correlation(SF_DATA)
    out = irr.format_apa_icc(res)
    assert isinstance(out, str) and "ICC" in out


def test_format_icc_has_all_models():
    res = irr.intraclass_correlation(SF_DATA)
    out = irr.format_apa_icc(res)
    for label in ("ICC(1,1)", "ICC(2,1)", "ICC(3,1)", "ICC(3,k)"):
        assert label in out


def test_format_icc_reference():
    res = irr.intraclass_correlation(SF_DATA)
    out = irr.format_apa_icc(res)
    assert "Shrout" in out and "Koo" in out


def test_format_kappa_p_lt_001():
    # κ=0.9（近完美但非完美，避免 SE=0 退化），z≈18 → p≪.001
    a, b = _make_2x2(38, 2, 2, 38)
    res = irr.cohens_kappa(a, b)
    out = irr.format_apa_kappa(res, method="cohen")
    assert "< .001" in out


def test_format_icc_is_markdown_table():
    res = irr.intraclass_correlation(SF_DATA)
    out = irr.format_apa_icc(res)
    assert "| 模型 |" in out


# ---------------------------------------------------------------------------
# write_irr_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files(tmp_path):
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    out = irr.format_apa_kappa(res, method="cohen")
    paths = irr.write_irr_report(res, out, tmp_path)
    assert (tmp_path / "irr_report.md").exists()
    assert (tmp_path / "irr_report.json").exists()


def test_write_report_json_valid(tmp_path):
    res = irr.intraclass_correlation(SF_DATA)
    out = irr.format_apa_icc(res)
    paths = irr.write_irr_report(res, out, tmp_path)
    data = json.loads((tmp_path / "irr_report.json").read_text(encoding="utf-8"))
    assert "icc3_1" in data


def test_write_report_md_nonempty(tmp_path):
    a, b = _make_2x2(20, 5, 10, 15)
    res = irr.cohens_kappa(a, b)
    out = irr.format_apa_kappa(res, method="cohen")
    irr.write_irr_report(res, out, tmp_path)
    assert len((tmp_path / "irr_report.md").read_text(encoding="utf-8")) > 0


def test_write_report_no_nan_inf(tmp_path):
    # 全体一类 → p_e=1 → κ/se 为 nan，JSON 应转 null 不报错
    res = irr.fleiss_kappa([[2, 0], [2, 0]])
    out = irr.format_apa_kappa(res, method="fleiss")
    irr.write_irr_report(res, out, tmp_path)
    txt = (tmp_path / "irr_report.json").read_text(encoding="utf-8")
    assert "NaN" not in txt and "Infinity" not in txt


# ---------------------------------------------------------------------------
# analyze_irr（CSV 主入口）
# ---------------------------------------------------------------------------

def _write_csv(path, header, rows):
    import csv as _csv
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = _csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_analyze_kappa(tmp_path):
    csv_path = tmp_path / "k.csv"
    rows = [["Y", "Y"]] * 20 + [["Y", "N"]] * 5 + [["N", "Y"]] * 10 + [["N", "N"]] * 15
    _write_csv(csv_path, ["ra", "rb"], rows)
    res = irr.analyze_irr(str(csv_path), "kappa", rater_a="ra", rater_b="rb",
                          out_dir=str(tmp_path))
    assert abs(res["kappa"] - 0.40) < 1e-6


def test_analyze_kappa_excludes_missing(tmp_path):
    csv_path = tmp_path / "k.csv"
    rows = [["Y", "Y"], ["Y", ""], ["N", "N"]]
    _write_csv(csv_path, ["ra", "rb"], rows)
    res = irr.analyze_irr(str(csv_path), "kappa", rater_a="ra", rater_b="rb",
                          out_dir=str(tmp_path))
    assert res["n_excluded"] == 1
    assert res["n"] == 2


def test_analyze_fleiss(tmp_path):
    csv_path = tmp_path / "f.csv"
    rows = [["A", "A"], ["A", "B"], ["B", "B"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "fleiss", raters=["r1", "r2"],
                          out_dir=str(tmp_path))
    assert abs(res["kappa"] - 1.0 / 3.0) < 1e-6


def test_analyze_icc(tmp_path):
    csv_path = tmp_path / "i.csv"
    rows = [[str(v) for v in row] for row in SF_DATA]
    _write_csv(csv_path, ["r1", "r2", "r3", "r4"], rows)
    res = irr.analyze_irr(str(csv_path), "icc", raters=["r1", "r2", "r3", "r4"],
                          out_dir=str(tmp_path))
    assert abs(res["icc3_1"]["icc"] - 0.7148) < 0.005


def test_analyze_icc_excludes_nonnumeric(tmp_path):
    csv_path = tmp_path / "i.csv"
    rows = [["1", "2"], ["x", "3"], ["4", "5"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "icc", raters=["r1", "r2"],
                          out_dir=str(tmp_path))
    assert res["n_excluded"] == 1


def test_analyze_writes_sidecar(tmp_path):
    csv_path = tmp_path / "k.csv"
    rows = [["Y", "Y"], ["N", "N"]]
    _write_csv(csv_path, ["ra", "rb"], rows)
    res = irr.analyze_irr(str(csv_path), "kappa", rater_a="ra", rater_b="rb",
                          out_dir=str(tmp_path))
    assert (tmp_path / "irr_report.md").exists()


def test_analyze_return_json_clean(tmp_path):
    csv_path = tmp_path / "i.csv"
    rows = [[str(v) for v in row] for row in SF_DATA]
    _write_csv(csv_path, ["r1", "r2", "r3", "r4"], rows)
    res = irr.analyze_irr(str(csv_path), "icc", raters=["r1", "r2", "r3", "r4"],
                          out_dir=str(tmp_path), return_json=True)
    assert "_formatted" not in res
    assert "_paths" not in res


def test_analyze_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        irr.analyze_irr(str(tmp_path / "nope.csv"), "kappa",
                        rater_a="a", rater_b="b", out_dir=str(tmp_path))


def test_analyze_kappa_weighted(tmp_path):
    csv_path = tmp_path / "k.csv"
    rows = [["1", "1"], ["2", "2"], ["3", "3"], ["1", "2"], ["2", "3"]]
    _write_csv(csv_path, ["ra", "rb"], rows)
    res = irr.analyze_irr(str(csv_path), "kappa", rater_a="ra", rater_b="rb",
                          weights="quadratic", out_dir=str(tmp_path))
    assert res["weights"] == "quadratic"


def test_analyze_unknown_method_raises(tmp_path):
    csv_path = tmp_path / "k.csv"
    _write_csv(csv_path, ["a", "b"], [["1", "2"]])
    with pytest.raises(ValueError):
        irr.analyze_irr(str(csv_path), "bogus", raters=["a", "b"], out_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# 边界与错误处理
# ---------------------------------------------------------------------------

def test_kappa_empty_raises():
    with pytest.raises(ValueError):
        irr.cohens_kappa([], [])


def test_kappa_single_category_raises():
    with pytest.raises(ValueError):
        irr.cohens_kappa(["A", "A"], ["A", "A"])


def test_icc_too_few_subjects_raises():
    with pytest.raises(ValueError):
        irr.intraclass_correlation([[1, 2]])


def test_icc_too_few_raters_raises():
    with pytest.raises(ValueError):
        irr.intraclass_correlation([[1], [2], [3]])


def test_icc_unbalanced_raises():
    with pytest.raises(ValueError):
        irr.intraclass_correlation([[1, 2, 3], [4, 5]])


def test_fleiss_single_category_raises():
    with pytest.raises(ValueError):
        irr.fleiss_kappa([[2], [2], [2]])


def test_analyze_kappa_missing_column_raises(tmp_path):
    csv_path = tmp_path / "k.csv"
    _write_csv(csv_path, ["ra", "rb"], [["Y", "N"]])
    with pytest.raises(ValueError):
        irr.analyze_irr(str(csv_path), "kappa", rater_a="ra", rater_b="zz",
                        out_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Krippendorff's alpha — 差异函数 δ²
# ---------------------------------------------------------------------------

def test_kripp_delta2_nominal():
    assert irr._kripp_delta2("nominal", [1, 2, 3], 0, 1, [1, 1, 1]) == 1.0
    assert irr._kripp_delta2("nominal", [1, 2, 3], 1, 1, [1, 1, 1]) == 0.0


def test_kripp_delta2_interval():
    assert irr._kripp_delta2("interval", [1, 2, 5], 0, 2, [1, 1, 1]) == 16.0


def test_kripp_delta2_ratio():
    # ((1-3)/(1+3))² = (−2/4)² = 0.25
    assert abs(irr._kripp_delta2("ratio", [1, 3], 0, 1, [1, 1]) - 0.25) < 1e-12


def test_kripp_delta2_ratio_zero_sum():
    assert irr._kripp_delta2("ratio", [0, 0], 0, 1, [1, 1]) == 0.0


def test_kripp_delta2_ordinal():
    # vals=[1,2,3], marg=[3,4,3]; δ²(0,2) = (3+4+3 − (3+3)/2)² = (10−3)² = 49
    assert abs(irr._kripp_delta2("ordinal", [1, 2, 3], 0, 2, [3, 4, 3]) - 49.0) < 1e-9


def test_kripp_delta2_self_zero():
    assert irr._kripp_delta2("ordinal", [1, 2, 3], 2, 2, [3, 4, 3]) == 0.0


def test_kripp_delta2_unknown_raises():
    with pytest.raises(ValueError):
        irr._kripp_delta2("bogus", [1, 2], 0, 1, [1, 1])


# ---------------------------------------------------------------------------
# Krippendorff's alpha — 点估计金标准（手算）
# ---------------------------------------------------------------------------

def test_kripp_perfect_agreement_nominal():
    units = [[1, 1], [2, 2], [3, 3], [1, 1]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert abs(res["alpha"] - 1.0) < 1e-9


def test_kripp_total_swap_nominal():
    # [[1,2],[2,1]] → α = −0.5（手算）
    res = irr.krippendorff_alpha([[1, 2], [2, 1]], metric="nominal", n_boot=0)
    assert abs(res["alpha"] - (-0.5)) < 1e-9


def test_kripp_chance_level_nominal():
    # [[1,1],[1,1],[1,2]] → α = 0.0（手算：观测不一致=期望不一致）
    res = irr.krippendorff_alpha([[1, 1], [1, 1], [1, 2]], metric="nominal", n_boot=0)
    assert abs(res["alpha"] - 0.0) < 1e-9


def test_kripp_three_cat_nominal_goldstandard():
    # [[1,1],[2,2],[3,3],[1,2],[2,3]] → α = 5/11 ≈ 0.454545（手算）
    units = [[1, 1], [2, 2], [3, 3], [1, 2], [2, 3]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert abs(res["alpha"] - 5.0 / 11.0) < 1e-6


def test_kripp_three_cat_ordinal_goldstandard():
    # 同上数据，有序差异函数 → α = 0.70（手算，相邻分歧给部分信用）
    units = [[1, 1], [2, 2], [3, 3], [1, 2], [2, 3]]
    res = irr.krippendorff_alpha(units, metric="ordinal", n_boot=0)
    assert abs(res["alpha"] - 0.70) < 1e-9


def test_kripp_ordinal_beats_nominal_for_adjacent():
    # 相邻类别分歧：有序 α 应高于名义 α（有序给部分信用）
    units = [[1, 1], [2, 2], [3, 3], [1, 2], [2, 3]]
    a_nom = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)["alpha"]
    a_ord = irr.krippendorff_alpha(units, metric="ordinal", n_boot=0)["alpha"]
    assert a_ord > a_nom


def test_kripp_single_pair_interval_zero():
    # 单一可配对单位，两评分互不相同 → α = 0
    res = irr.krippendorff_alpha([[1, 2]], metric="interval", n_boot=0)
    assert abs(res["alpha"] - 0.0) < 1e-9


def test_kripp_interval_perfect():
    res = irr.krippendorff_alpha([[1, 1], [2, 2], [3, 3]], metric="interval", n_boot=0)
    assert abs(res["alpha"] - 1.0) < 1e-9


def test_kripp_ratio_perfect():
    res = irr.krippendorff_alpha([[2, 2], [4, 4], [6, 6]], metric="ratio", n_boot=0)
    assert abs(res["alpha"] - 1.0) < 1e-9


def test_kripp_alpha_at_most_one():
    units = [[1, 1, 1], [2, 2, 2], [1, 1, 2], [3, 3, 3]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert res["alpha"] <= 1.0 + 1e-12


# ---------------------------------------------------------------------------
# Krippendorff — 缺失数据 / 可配对计数 / 任意评分者数
# ---------------------------------------------------------------------------

def test_kripp_missing_skips_unpairable():
    # 仅 1 个有效值的单位不可配对，自动跳过
    units = [[1, None], [1, 1], [2, 2]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert res["n_units"] == 3
    assert res["n_units_pairable"] == 2
    assert abs(res["alpha"] - 1.0) < 1e-9


def test_kripp_variable_rater_count():
    # 评分者数可不等（缺失），仍可计算
    units = [[1, 1, 1], [2, 2, None], [3, None, 3]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert abs(res["alpha"] - 1.0) < 1e-9
    assert res["n_units_pairable"] == 3


def test_kripp_pairable_values_count():
    # n_pairable_values = Σ_u m_u（可配对单位）
    units = [[1, 1], [2, 2, 2]]  # m=2 + m=3 → 5
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=0)
    assert abs(res["n_pairable_values"] - 5.0) < 1e-9


def test_kripp_value_not_in_domain_raises():
    with pytest.raises(ValueError):
        irr.krippendorff_alpha([[1, 2], [3, 1]], metric="nominal",
                               value_domain=[1, 2], n_boot=0)


def test_kripp_unknown_metric_raises():
    with pytest.raises(ValueError):
        irr.krippendorff_alpha([[1, 1]], metric="bogus", n_boot=0)


def test_kripp_empty_raises():
    with pytest.raises(ValueError):
        irr.krippendorff_alpha([], metric="nominal", n_boot=0)


# ---------------------------------------------------------------------------
# Krippendorff — 自助法 CI
# ---------------------------------------------------------------------------

def test_kripp_bootstrap_ci_ordered():
    units = [[1, 1], [2, 2], [1, 2], [2, 1], [1, 1], [2, 2]]
    res = irr.krippendorff_alpha(units, metric="nominal", n_boot=500, seed=1)
    assert math.isfinite(res["ci_lower"])
    assert math.isfinite(res["ci_upper"])
    assert res["ci_lower"] <= res["ci_upper"]


def test_kripp_bootstrap_deterministic():
    units = [[1, 1], [2, 2], [1, 2], [2, 1], [1, 1], [2, 2]]
    r1 = irr.krippendorff_alpha(units, metric="nominal", n_boot=300, seed=7)
    r2 = irr.krippendorff_alpha(units, metric="nominal", n_boot=300, seed=7)
    assert r1["ci_lower"] == r2["ci_lower"]
    assert r1["ci_upper"] == r2["ci_upper"]


def test_kripp_no_bootstrap_nan_ci():
    res = irr.krippendorff_alpha([[1, 1], [2, 2]], metric="nominal", n_boot=0)
    assert math.isnan(res["ci_lower"])
    assert res["n_boot"] == 0


def test_kripp_percentile_helper():
    vals = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert abs(irr._percentile(vals, 0.5) - 2.0) < 1e-12
    assert math.isnan(irr._percentile([], 0.5))
    assert irr._percentile([5.0], 0.9) == 5.0


# ---------------------------------------------------------------------------
# Krippendorff — 解读 / 格式化 / CSV 入口
# ---------------------------------------------------------------------------

def test_interpret_krippendorff_thresholds():
    assert "可靠" in irr.interpret_krippendorff(0.85)
    assert "暂定" in irr.interpret_krippendorff(0.70)
    assert "不可靠" in irr.interpret_krippendorff(0.50)
    assert irr.interpret_krippendorff(float("nan")) == "无法计算"


def test_format_apa_krippendorff_contains_key_parts():
    units = [[1, 1], [2, 2], [3, 3], [1, 2], [2, 3]]
    res = irr.krippendorff_alpha(units, metric="ordinal", n_boot=200, seed=3)
    txt = irr.format_apa_krippendorff(res)
    assert isinstance(txt, str)
    assert "Krippendorff" in txt
    assert "α" in txt
    assert "有序" in txt  # metric label
    assert "2004" in txt


def test_analyze_krippendorff_nominal(tmp_path):
    csv_path = tmp_path / "kr.csv"
    rows = [["1", "1"], ["2", "2"], ["3", "3"], ["1", "2"], ["2", "3"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1", "r2"],
                          metric="nominal", n_boot=0, out_dir=str(tmp_path))
    assert abs(res["alpha"] - 5.0 / 11.0) < 1e-5
    assert res["method"] == "krippendorff"


def test_analyze_krippendorff_ordinal(tmp_path):
    csv_path = tmp_path / "kr.csv"
    rows = [["1", "1"], ["2", "2"], ["3", "3"], ["1", "2"], ["2", "3"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1", "r2"],
                          metric="ordinal", n_boot=0, out_dir=str(tmp_path))
    assert abs(res["alpha"] - 0.70) < 1e-6


def test_analyze_krippendorff_missing(tmp_path):
    csv_path = tmp_path / "kr.csv"
    rows = [["1", ""], ["1", "1"], ["2", "2"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1", "r2"],
                          metric="nominal", n_boot=0, out_dir=str(tmp_path))
    assert res["n_units_pairable"] == 2
    assert abs(res["alpha"] - 1.0) < 1e-9


def test_analyze_krippendorff_writes_sidecar(tmp_path):
    csv_path = tmp_path / "kr.csv"
    rows = [["1", "1"], ["2", "2"], ["1", "2"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1", "r2"],
                          metric="nominal", n_boot=50, out_dir=str(tmp_path))
    paths = res["_paths"]
    assert (tmp_path / "irr_report.md").exists()
    data = json.loads((tmp_path / "irr_report.json").read_text(encoding="utf-8"))
    assert "alpha" in data


def test_analyze_krippendorff_too_few_raters_raises(tmp_path):
    csv_path = tmp_path / "kr.csv"
    _write_csv(csv_path, ["r1"], [["1"], ["2"]])
    with pytest.raises(ValueError):
        irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1"],
                        out_dir=str(tmp_path))


def test_analyze_krippendorff_json_clean(tmp_path):
    csv_path = tmp_path / "kr.csv"
    rows = [["1", "1"], ["2", "2"], ["1", "2"]]
    _write_csv(csv_path, ["r1", "r2"], rows)
    res = irr.analyze_irr(str(csv_path), "krippendorff", raters=["r1", "r2"],
                          metric="nominal", n_boot=0, out_dir=str(tmp_path),
                          return_json=True)
    # NaN CI（n_boot=0）应被 _clean_json 转为 None
    assert res["ci_lower"] is None
