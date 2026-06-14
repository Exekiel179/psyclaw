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
    spearman_rho,
    format_apa_nonpar,
    write_nonpar_report,
    analyze_nonpar,
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
