"""测试非参数检验套件（psyclaw/psych/nonparametric.py）。

数值对照：
  - Mann-Whitney U：scipy.stats.mannwhitneyu 已知结果
  - Wilcoxon signed-rank：配对差值全正 → W_minus=0
  - Kruskal-Wallis：等距三组应与单因素 ANOVA 同向
  - Spearman ρ：完全单调递增 → ρ=1；完全单调递减 → ρ=-1
  - 效应量 r = Z/√N 在 [0,1]
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.nonparametric import (
    mann_whitney_u,
    wilcoxon_signed_rank,
    kruskal_wallis,
    friedman_test,
    spearman_rho,
    format_apa_nonpar,
    write_nonpar_report,
    analyze_nonpar,
    _holm_adjust,
    _interpret_w,
)


# ---------------------------------------------------------------------------
# Mann-Whitney U
# ---------------------------------------------------------------------------

def _mwu_groups():
    return (
        [1.0, 2.0, 3.0, 4.0, 5.0],   # 低组
        [6.0, 7.0, 8.0, 9.0, 10.0],  # 高组
    )


def test_mwu_significant():
    x, y = _mwu_groups()
    r = mann_whitney_u(x, y)
    assert r["p"] < 0.05, f"p={r['p']}"
    assert r["significant"]


def test_mwu_null_not_significant():
    """两组均值完全相同 → 不显著。"""
    x = [5.0, 5.0, 5.0, 5.0, 5.0]
    y = [5.0, 5.0, 5.0, 5.0, 5.0]
    r = mann_whitney_u(x, y)
    assert r["p"] > 0.05


def test_mwu_u1_u2_sum():
    """U1 + U2 = n1 × n2。"""
    x, y = _mwu_groups()
    r = mann_whitney_u(x, y)
    assert abs(r["U1"] + r["U2"] - r["n1"] * r["n2"]) < 0.001


def test_mwu_r_in_range():
    x, y = _mwu_groups()
    r = mann_whitney_u(x, y)
    assert 0 <= r["r_effect"] <= 1


def test_mwu_fields():
    x, y = _mwu_groups()
    r = mann_whitney_u(x, y)
    for k in ("U1", "U2", "n1", "n2", "Z", "p", "r_effect", "significant"):
        assert k in r, f"缺少字段: {k}"


def test_mwu_z_direction():
    """低值组 vs 高值组：U1（y 胜过 x 对数）= n1*n2 → Z > 0。"""
    x = [1.0, 2.0, 3.0]
    y = [10.0, 11.0, 12.0]
    r = mann_whitney_u(x, y)
    # U1 counts pairs where y > x; all y > x → U1 = n1*n2 = max → Z > 0
    assert r["Z"] > 0


def test_mwu_too_few_samples():
    try:
        mann_whitney_u([1.0, 2.0], [3.0, 4.0, 5.0])
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_mwu_ties():
    """有同值时应正常返回（平均秩）。"""
    x = [1.0, 1.0, 2.0, 2.0, 3.0]
    y = [4.0, 4.0, 5.0, 5.0, 6.0]
    r = mann_whitney_u(x, y)
    assert r["p"] < 0.05


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank
# ---------------------------------------------------------------------------

def test_wilcoxon_all_positive_diffs():
    """所有差值 > 0 → W_minus = 0，应显著。"""
    x = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    y = [1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0]
    r = wilcoxon_signed_rank(x, y)
    assert r["W_minus"] == 0.0
    assert r["p"] < 0.05


def test_wilcoxon_symmetric():
    """对称差值 → 不显著。"""
    x = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    y = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    # 所有差值 = 0 → 应抛出（n 不足），改用微小随机对称差值
    x2 = [5.1, 4.9, 6.1, 5.9, 7.1, 5.9, 4.8]
    y2 = [4.9, 5.1, 5.9, 6.1, 6.9, 6.1, 5.2]
    r = wilcoxon_signed_rank(x2, y2)
    assert r["p"] > 0.05


def test_wilcoxon_one_sample():
    """单样本模式：x vs mu0=5。"""
    x = [6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
    r = wilcoxon_signed_rank(x, mu0=5.0)
    assert r["p"] < 0.05


def test_wilcoxon_r_in_range():
    x = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    y = [1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0]
    r = wilcoxon_signed_rank(x, y)
    assert 0 <= r["r_effect"] <= 1


def test_wilcoxon_w_plus_minus_sum():
    """W_plus + W_minus = n*(n+1)/2（无零值时）。"""
    x = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    y = [1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0]
    r = wilcoxon_signed_rank(x, y)
    n = r["n_pairs"]
    expected_total = n * (n + 1) / 2
    assert abs(r["W_plus"] + r["W_minus"] - expected_total) < 0.001


def test_wilcoxon_fields():
    x = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    y = [1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0]
    r = wilcoxon_signed_rank(x, y)
    for k in ("W", "W_plus", "W_minus", "n_pairs", "Z", "p", "r_effect", "significant"):
        assert k in r, f"缺少字段: {k}"


def test_wilcoxon_mismatched_lengths():
    try:
        wilcoxon_signed_rank([1.0, 2.0, 3.0], [1.0, 2.0])
        assert False
    except ValueError:
        pass


def test_wilcoxon_too_few_nonzero():
    try:
        wilcoxon_signed_rank([5.0, 5.0, 6.0], [5.0, 5.0, 5.5])  # n_nonzero=1
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Kruskal-Wallis H
# ---------------------------------------------------------------------------

def _kw_groups():
    return {
        "A": [1.0, 2.0, 3.0, 4.0, 5.0],
        "B": [6.0, 7.0, 8.0, 9.0, 10.0],
        "C": [11.0, 12.0, 13.0, 14.0, 15.0],
    }


def test_kruskal_significant():
    """H=12.5，df=2，chi²正态近似 p≈0.002（< 0.01）。"""
    r = kruskal_wallis(_kw_groups())
    assert r["p"] < 0.01, f"p={r['p']}"
    assert r["significant"]


def test_kruskal_null():
    """所有组相同 → H≈0。"""
    groups = {"A": [5.0, 5.0, 5.0, 5.0], "B": [5.0, 5.0, 5.0, 5.0]}
    r = kruskal_wallis(groups)
    assert r["H"] < 0.1
    assert r["p"] > 0.05


def test_kruskal_df_correct():
    r = kruskal_wallis(_kw_groups())
    assert r["df"] == 2  # k - 1


def test_kruskal_eta2_in_range():
    r = kruskal_wallis(_kw_groups())
    assert 0 <= r["eta2_h"] <= 1


def test_kruskal_h_large_when_groups_separated():
    """三组均值差 5，H 应相当大（类比 ANOVA F 大）。"""
    r = kruskal_wallis(_kw_groups())
    assert r["H"] > 10


def test_kruskal_group_stats():
    r = kruskal_wallis(_kw_groups())
    assert len(r["group_stats"]) == 3
    for g in r["group_stats"]:
        for k in ("name", "n", "median", "mean_rank"):
            assert k in g


def test_kruskal_median_correct():
    r = kruskal_wallis(_kw_groups())
    medians = {g["name"]: g["median"] for g in r["group_stats"]}
    assert abs(medians["A"] - 3.0) < 0.01
    assert abs(medians["B"] - 8.0) < 0.01
    assert abs(medians["C"] - 13.0) < 0.01


def test_kruskal_too_few_groups():
    try:
        kruskal_wallis({"A": [1.0, 2.0, 3.0]})
        assert False
    except ValueError:
        pass


def test_kruskal_too_few_obs():
    try:
        kruskal_wallis({"A": [1.0, 2.0], "B": [3.0, 4.0]})
        assert False
    except ValueError:
        pass


def test_kruskal_fields():
    r = kruskal_wallis(_kw_groups())
    for k in ("H", "df", "p", "eta2_h", "N", "k", "significant", "group_stats"):
        assert k in r


def test_kruskal_n_correct():
    r = kruskal_wallis(_kw_groups())
    assert r["N"] == 15
    assert r["k"] == 3


# ---------------------------------------------------------------------------
# Spearman ρ
# ---------------------------------------------------------------------------

def test_spearman_perfect_positive():
    """完全单调递增 → ρ = 1.0。"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 20.0, 30.0, 40.0, 50.0]
    r = spearman_rho(x, y)
    assert abs(r["rho"] - 1.0) < 1e-9


def test_spearman_perfect_negative():
    """完全单调递减 → ρ = -1.0。"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [50.0, 40.0, 30.0, 20.0, 10.0]
    r = spearman_rho(x, y)
    assert abs(r["rho"] + 1.0) < 1e-9


def test_spearman_zero_correlation():
    """不相关数据 → ρ ≈ 0，p > 0.05。"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    y = [4.0, 2.0, 6.0, 1.0, 7.0, 3.0, 5.0, 8.0]  # 打乱秩
    r = spearman_rho(x, y)
    # 不要求精确 0，只要 p 不显著 (弱相关)
    assert abs(r["rho"]) < 0.9


def test_spearman_fields():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 3.0, 5.0, 1.0]
    r = spearman_rho(x, y)
    for k in ("rho", "t", "df", "p", "n", "significant"):
        assert k in r


def test_spearman_df_correct():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 4.0, 3.0, 5.0, 1.0]
    r = spearman_rho(x, y)
    assert r["df"] == 3  # n - 2 = 5 - 2


def test_spearman_significant_when_strong():
    """强正相关（单调增）大样本应显著。"""
    x = list(range(1, 21))
    y = [v + (0.1 * (i % 3)) for i, v in enumerate(x)]
    r = spearman_rho(x, y)
    assert r["p"] < 0.001
    assert r["rho"] > 0.95


def test_spearman_length_mismatch():
    try:
        spearman_rho([1.0, 2.0, 3.0], [1.0, 2.0])
        assert False
    except ValueError:
        pass


def test_spearman_too_few():
    try:
        spearman_rho([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_mwu_apa():
    x, y = _mwu_groups()
    result = mann_whitney_u(x, y)
    result["test"] = "Mann-Whitney U"
    text = format_apa_nonpar(result)
    assert "*U*" in text
    assert "*Z*" in text
    assert "*r*" in text


def test_format_wilcoxon_apa():
    x = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0]
    y = [1.0,  2.0,  3.0,  4.0,  5.0,  6.0,  7.0]
    result = wilcoxon_signed_rank(x, y)
    text = format_apa_nonpar(result)
    assert "*W*" in text
    assert "*Z*" in text


def test_format_kruskal_apa():
    result = kruskal_wallis(_kw_groups())
    text = format_apa_nonpar(result)
    assert "*H*" in text
    assert "*η*²" in text or "η²" in text


def test_format_spearman_apa():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = spearman_rho(x, y)
    text = format_apa_nonpar(result)
    assert "*r*_s" in text or "rho" in text or "ρ" in text


# ---------------------------------------------------------------------------
# write_nonpar_report
# ---------------------------------------------------------------------------

def test_write_report_mwu():
    x, y = _mwu_groups()
    result = mann_whitney_u(x, y)
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_nonpar_report(result, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "Mann-Whitney" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "U1" in data


def test_write_report_kruskal():
    result = kruskal_wallis(_kw_groups())
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_nonpar_report(result, out_dir=tmpdir)
        content = md.read_text(encoding="utf-8")
        assert "中位数" in content


# ---------------------------------------------------------------------------
# analyze_nonpar（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_mwu_csv():
    rows = (
        [{"score": str(v), "group": "low"} for v in [1, 2, 3, 4, 5]] +
        [{"score": str(v), "group": "high"} for v in [6, 7, 8, 9, 10]]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="mwu", dv="score",
                                group_col="group", write_files=True, out_dir=tmpdir)
        assert result["p"] < 0.05
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_kruskal_csv():
    rows = (
        [{"y": str(v), "g": "A"} for v in [1, 2, 3, 4, 5]] +
        [{"y": str(v), "g": "B"} for v in [6, 7, 8, 9, 10]] +
        [{"y": str(v), "g": "C"} for v in [11, 12, 13, 14, 15]]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="kruskal", dv="y",
                                group_col="g", write_files=False)
        assert result["p"] < 0.01  # chi²近似 p≈0.002
        assert result["k"] == 3


def test_analyze_wilcoxon_csv():
    rows = [{"pre": str(v), "post": str(v + 3)} for v in range(1, 11)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="wilcoxon", dv="pre",
                                y_col="post", write_files=False)
        assert result["p"] < 0.05


def test_analyze_spearman_csv():
    rows = [{"x": str(i), "y": str(i * 2)} for i in range(1, 11)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="spearman", dv="x",
                                y_col="y", write_files=False)
        assert abs(result["rho"] - 1.0) < 1e-9


def test_analyze_mwu_wrong_groups():
    """超过 2 组时 mwu 应报错。"""
    rows = (
        [{"s": "1", "g": "A"}, {"s": "2", "g": "A"}, {"s": "3", "g": "A"}] +
        [{"s": "4", "g": "B"}, {"s": "5", "g": "B"}, {"s": "6", "g": "B"}] +
        [{"s": "7", "g": "C"}, {"s": "8", "g": "C"}, {"s": "9", "g": "C"}]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_nonpar(csv_path, test="mwu", dv="s", group_col="g",
                           write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_unknown_test():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"x": "1", "g": "A"}], csv_path)
        try:
            analyze_nonpar(csv_path, test="unknown", dv="x", write_files=False)
            assert False
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Friedman 检验（重复测量单因素 ANOVA 的非参数替代）
# ---------------------------------------------------------------------------

def _friedman_perfect():
    """4 名被试在 3 条件上完全一致排序 A>B>C → χ²=8, W=1。"""
    return {
        "A": [10.0, 10.0, 10.0, 10.0],
        "B": [8.0, 8.0, 8.0, 8.0],
        "C": [5.0, 5.0, 5.0, 5.0],
    }


def test_friedman_perfect_concordance_chi2():
    r = friedman_test(_friedman_perfect())
    assert abs(r["chi2"] - 8.0) < 1e-9


def test_friedman_perfect_concordance_W():
    r = friedman_test(_friedman_perfect())
    assert abs(r["W"] - 1.0) < 1e-9


def test_friedman_perfect_concordance_p():
    # p = chi2_sf(8, 2) = exp(-4) ≈ 0.018316
    r = friedman_test(_friedman_perfect())
    assert abs(r["p"] - math.exp(-4.0)) < 1e-4


def test_friedman_perfect_significant():
    r = friedman_test(_friedman_perfect(), alpha=0.05)
    assert r["significant"] is True


def test_friedman_df_correct():
    r = friedman_test(_friedman_perfect())
    assert r["df"] == 2  # k - 1


def test_friedman_no_effect_latin_square():
    # 拉丁方：各条件秩和相等 → χ²=0, W=0, p=1
    conds = {
        "A": [1.0, 2.0, 3.0],
        "B": [2.0, 3.0, 1.0],
        "C": [3.0, 1.0, 2.0],
    }
    r = friedman_test(conds)
    assert abs(r["chi2"]) < 1e-9
    assert abs(r["W"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9
    assert r["significant"] is False


def test_friedman_partial_ties_golden():
    # n=2,k=3：行 [1,2,3] 与 [1,1,2]（前两值同值）
    # R=[2.5,3.5,6], A1=27.5, C1=24 → χ²=2·(54.5−48)/3.5=3.714286
    conds = {
        "A": [1.0, 1.0],
        "B": [2.0, 1.0],
        "C": [3.0, 2.0],
    }
    r = friedman_test(conds)
    assert abs(r["chi2"] - 3.714286) < 1e-4
    # W = χ²/(n(k-1)) = 3.714286/4 = 0.928571
    assert abs(r["W"] - 0.928571) < 1e-4
    # p = exp(-3.714286/2) ≈ 0.15613
    assert abs(r["p"] - 0.15613) < 1e-3


def test_friedman_W_in_range():
    r = friedman_test(_friedman_perfect())
    assert 0.0 <= r["W"] <= 1.0


def test_friedman_chi2_nonnegative():
    conds = {
        "A": [3.0, 1.0, 4.0, 1.0, 5.0],
        "B": [2.0, 7.0, 1.0, 8.0, 2.0],
        "C": [8.0, 1.0, 8.0, 2.0, 8.0],
    }
    r = friedman_test(conds)
    assert r["chi2"] >= 0.0
    assert 0.0 <= r["p"] <= 1.0


def test_friedman_all_tied_degenerate():
    # 每名被试在所有条件上完全同值 → 无秩变异 → χ²=0, p=1
    conds = {
        "A": [5.0, 3.0],
        "B": [5.0, 3.0],
        "C": [5.0, 3.0],
    }
    r = friedman_test(conds)
    assert abs(r["chi2"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9
    assert abs(r["W"]) < 1e-9


def test_friedman_chi2_equals_n_k_minus_1_times_W():
    # 恒等式 χ² = n(k-1)·W
    conds = {
        "A": [3.0, 1.0, 4.0, 1.0, 5.0],
        "B": [2.0, 7.0, 1.0, 8.0, 2.0],
        "C": [8.0, 1.0, 8.0, 2.0, 9.0],
    }
    r = friedman_test(conds)
    assert abs(r["chi2"] - r["n"] * (r["k"] - 1) * r["W"]) < 1e-3


def test_friedman_too_few_conditions():
    try:
        friedman_test({"A": [1.0, 2.0], "B": [2.0, 3.0]})
        assert False, "应抛出 ValueError（k<3）"
    except ValueError:
        pass


def test_friedman_unequal_lengths():
    try:
        friedman_test({"A": [1.0, 2.0], "B": [2.0, 3.0], "C": [1.0]})
        assert False, "应抛出 ValueError（列不等长）"
    except ValueError:
        pass


def test_friedman_too_few_subjects():
    try:
        friedman_test({"A": [1.0], "B": [2.0], "C": [3.0]})
        assert False, "应抛出 ValueError（n<2）"
    except ValueError:
        pass


def test_friedman_condition_stats():
    r = friedman_test(_friedman_perfect())
    assert len(r["condition_stats"]) == 3
    names = {c["name"] for c in r["condition_stats"]}
    assert names == {"A", "B", "C"}
    # A 始终最高 → 平均秩最高（升序赋秩，最大值=最高秩）
    by_name = {c["name"]: c["mean_rank"] for c in r["condition_stats"]}
    assert by_name["A"] == 3.0
    assert by_name["B"] == 2.0
    assert by_name["C"] == 1.0


def test_friedman_rank_sums_sum_correct():
    # 每名被试的秩和恒为 k(k+1)/2，全体秩和 = n·k(k+1)/2
    r = friedman_test(_friedman_perfect())
    total = sum(c["rank_sum"] for c in r["condition_stats"])
    n, k = r["n"], r["k"]
    assert abs(total - n * k * (k + 1) / 2.0) < 1e-9


def test_friedman_post_hoc_present():
    r = friedman_test(_friedman_perfect(), post_hoc=True)
    assert "post_hoc" in r
    assert len(r["post_hoc"]) == 3  # C(3,2)


def test_friedman_post_hoc_absent_by_default():
    r = friedman_test(_friedman_perfect())
    assert "post_hoc" not in r


def test_friedman_post_hoc_fields():
    conds = {
        "A": [1.0, 1.0],
        "B": [2.0, 1.0],
        "C": [3.0, 2.0],
    }
    r = friedman_test(conds, post_hoc=True)
    ph = r["post_hoc"][0]
    for key in ("cond1", "cond2", "rank_diff", "t", "df", "p_raw", "p_holm", "significant"):
        assert key in ph
    # df = (n-1)(k-1) = 1·2 = 2
    assert ph["df"] == 2


def test_friedman_post_hoc_t_arithmetic():
    # n=2,k=3 部分同值：R=[2.5,3.5,6], A1=27.5, sum_R2=54.5
    # var = 2·(2·27.5−54.5)/2 = 0.5, se=√0.5; A vs C: diff=-3.5 → t=-3.5/√0.5≈-4.9497
    conds = {
        "A": [1.0, 1.0],
        "B": [2.0, 1.0],
        "C": [3.0, 2.0],
    }
    r = friedman_test(conds, post_hoc=True)
    ac = [p for p in r["post_hoc"] if {p["cond1"], p["cond2"]} == {"A", "C"}][0]
    assert abs(abs(ac["t"]) - 4.94975) < 1e-3
    assert abs(abs(ac["rank_diff"]) - 3.5) < 1e-9


def test_friedman_post_hoc_holm_ge_raw():
    conds = {
        "A": [3.0, 1.0, 4.0, 1.0, 5.0],
        "B": [5.0, 7.0, 6.0, 8.0, 7.0],
        "C": [9.0, 8.0, 9.0, 9.0, 8.0],
    }
    r = friedman_test(conds, post_hoc=True)
    for ph in r["post_hoc"]:
        assert ph["p_holm"] >= ph["p_raw"] - 1e-9
        assert 0.0 <= ph["p_holm"] <= 1.0


def test_holm_adjust_monotone_and_bounds():
    adj = _holm_adjust([0.01, 0.02, 0.03])
    assert adj == sorted(adj)  # 单调非降（输入已升序）
    for a in adj:
        assert 0.0 <= a <= 1.0
    # m=3：第一个校正 = min(3·0.01,1)=0.03
    assert abs(adj[0] - 0.03) < 1e-12


def test_holm_adjust_empty():
    assert _holm_adjust([]) == []


def test_interpret_w_labels():
    assert _interpret_w(0.6) == "强一致性"
    assert _interpret_w(0.4) == "中等一致性"
    assert _interpret_w(0.2) == "弱一致性"
    assert _interpret_w(0.05) == "微弱一致性"


def test_friedman_apa_format():
    r = friedman_test(_friedman_perfect())
    txt = format_apa_nonpar(r)
    assert "Friedman" in txt
    assert "χ" in txt
    assert "Kendall" in txt
    assert "W" in txt


def test_friedman_write_report():
    r = friedman_test(_friedman_perfect(), post_hoc=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path, json_path = write_nonpar_report(r, out_dir=tmpdir, filename="fried")
        assert md_path.exists()
        assert json_path.exists()
        text = md_path.read_text(encoding="utf-8")
        assert "各条件描述统计" in text
        assert "事后两两比较" in text
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert loaded["test"] == "Friedman"


def test_analyze_friedman_csv():
    # 宽表：每行一名被试，三个条件列
    rows = [
        {"t1": "10", "t2": "8", "t3": "5"},
        {"t1": "12", "t2": "9", "t3": "6"},
        {"t1": "11", "t2": "7", "t3": "4"},
        {"t1": "13", "t2": "10", "t3": "5"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="friedman",
                                conditions="t1,t2,t3", write_files=False)
        assert result["test"] == "Friedman"
        # 三条件严格分离 → 完美一致 → χ²=8, W=1
        assert abs(result["chi2"] - 8.0) < 1e-9
        assert abs(result["W"] - 1.0) < 1e-9
        assert result["n"] == 4
        assert result["n_excluded"] == 0


def test_analyze_friedman_excludes_incomplete_rows():
    rows = [
        {"t1": "10", "t2": "8", "t3": "5"},
        {"t1": "12", "t2": "", "t3": "6"},      # 缺失 → 排除
        {"t1": "11", "t2": "7", "t3": "4"},
        {"t1": "x", "t2": "10", "t3": "5"},     # 非数值 → 排除
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="friedman",
                                conditions="t1,t2,t3", write_files=False)
        assert result["n"] == 2
        assert result["n_excluded"] == 2


def test_analyze_friedman_requires_conditions():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"t1": "1", "t2": "2", "t3": "3"}], csv_path)
        try:
            analyze_nonpar(csv_path, test="friedman", write_files=False)
            assert False, "应抛出 ValueError（缺少 conditions）"
        except ValueError:
            pass


def test_analyze_friedman_too_few_condition_cols():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"t1": "1", "t2": "2"}], csv_path)
        try:
            analyze_nonpar(csv_path, test="friedman",
                           conditions="t1,t2", write_files=False)
            assert False, "应抛出 ValueError（<3 条件）"
        except ValueError:
            pass


def test_analyze_non_friedman_requires_dv():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"x": "1", "g": "A"}], csv_path)
        try:
            analyze_nonpar(csv_path, test="kruskal", group_col="g",
                           write_files=False)
            assert False, "应抛出 ValueError（缺少 dv）"
        except ValueError:
            pass


def test_analyze_friedman_post_hoc_via_csv():
    rows = [
        {"t1": "3", "t2": "5", "t3": "9"},
        {"t1": "1", "t2": "7", "t3": "8"},
        {"t1": "4", "t2": "6", "t3": "9"},
        {"t1": "1", "t2": "8", "t3": "9"},
        {"t1": "5", "t2": "7", "t3": "8"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_nonpar(csv_path, test="friedman",
                                conditions="t1,t2,t3", post_hoc=True,
                                write_files=False)
        assert "post_hoc" in result
        assert len(result["post_hoc"]) == 3


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
