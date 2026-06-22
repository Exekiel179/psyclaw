"""测试配对/重复测量二分检验套件（psyclaw/psych/paired_categorical.py）。

数值对照（手算金标准，逐行复核）：
  - McNemar χ² = (b−c)²/(b+c)；连续性校正 χ² = (|b−c|−1)²/(b+c)
  - McNemar 精确二项：b ~ Binom(b+c, 0.5)，双尾 p = 2·P(X≤min(b,c)) 封顶 1
  - Cochran's Q = (k−1)(k·ΣC²−N²)/(k·N−ΣR²)，k=2 时退化为未校正 McNemar χ²（恒等式）
  - 全 0 / 全 1 行无被试内变异 → Q=0/p=1
  - 各条件列阳性比例正确
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.paired_categorical import (
    mcnemar_test,
    cochran_q,
    _binom_two_tailed_p,
    _coerce_binary,
    _holm_adjust,
    _chi2_sf,
    format_apa_paircat,
    write_paircat_report,
    analyze_paircat,
    paircat_cli,
)


# ---------------------------------------------------------------------------
# 分布工具
# ---------------------------------------------------------------------------

def test_chi2_sf_df1_critical():
    # χ²(1) 临界值 3.841 → p≈.05
    assert abs(_chi2_sf(3.841, 1) - 0.05) < 0.001


def test_chi2_sf_zero():
    assert _chi2_sf(0.0, 1) == 1.0


def test_binom_two_tailed_no_discordant():
    assert _binom_two_tailed_p(0, 0) == 1.0


def test_binom_two_tailed_gold():
    # n=10, k=min(2,8)=2: (1+10+45)/1024 = 56/1024; ×2 = 0.109375
    assert abs(_binom_two_tailed_p(2, 8) - 0.109375) < 1e-9


def test_binom_two_tailed_symmetric():
    assert _binom_two_tailed_p(2, 8) == _binom_two_tailed_p(8, 2)


def test_binom_two_tailed_equal_caps_at_one():
    # b=c → tail > 0.5, ×2 封顶 1.0
    assert _binom_two_tailed_p(5, 5) == 1.0


def test_binom_two_tailed_extreme():
    # 全部不一致对都在一侧 → 最显著
    p = _binom_two_tailed_p(0, 10)
    assert abs(p - 2 * (0.5 ** 10)) < 1e-12


def test_coerce_binary_valid():
    assert _coerce_binary("0", "x") == 0
    assert _coerce_binary("1", "x") == 1
    assert _coerce_binary(1.0, "x") == 1
    assert _coerce_binary(0, "x") == 0


def test_coerce_binary_rejects_nonbinary():
    try:
        _coerce_binary("2", "条件A")
        assert False, "应拒绝非二分值"
    except ValueError as e:
        assert "条件A" in str(e)


def test_coerce_binary_rejects_nonnumeric():
    try:
        _coerce_binary("abc", "x")
        assert False
    except ValueError:
        pass


def test_holm_monotone():
    adj = _holm_adjust([0.01, 0.02, 0.03])
    assert adj == sorted(adj)
    assert all(0 <= a <= 1 for a in adj)


# ---------------------------------------------------------------------------
# McNemar 检验
# ---------------------------------------------------------------------------

def test_mcnemar_uncorrected_chi2_gold():
    # b=2, c=8 → χ²=(2-8)²/10=3.6
    r = mcnemar_test([[15, 2], [8, 10]], correction=False, exact=False)
    assert abs(r["chi2"] - 3.6) < 1e-9
    assert r["statistic"] == r["chi2"]
    assert r["method"] == "chi2"
    assert abs(r["p"] - _chi2_sf(3.6, 1)) < 1e-6  # r["p"] 舍入到 6 位


def test_mcnemar_continuity_gold():
    # (|2-8|-1)²/10 = 25/10 = 2.5
    r = mcnemar_test([[15, 2], [8, 10]], correction=True, exact=False)
    assert abs(r["chi2_corrected"] - 2.5) < 1e-9
    assert r["method"] == "chi2_continuity"
    assert abs(r["p"] - _chi2_sf(2.5, 1)) < 1e-6  # r["p"] 舍入到 6 位


def test_mcnemar_exact_default_for_small_discordant():
    # n_disc=10 < 25 → 默认精确二项
    r = mcnemar_test([[15, 2], [8, 10]])
    assert r["method"] == "exact_binomial"
    assert abs(r["p"] - 0.109375) < 1e-9
    assert r["statistic"] is None


def test_mcnemar_chi2_default_for_large_discordant():
    # n_disc=25 → 默认连续性校正 χ²
    r = mcnemar_test([[5, 20], [5, 5]])
    assert r["method"] == "chi2_continuity"
    # χ²_cc=(|20-5|-1)²/25=196/25=7.84
    assert abs(r["chi2_corrected"] - 7.84) < 1e-9
    assert r["significant"] is True


def test_mcnemar_exact_threshold_boundary():
    # n_disc=24 → 精确；25 → χ²
    assert mcnemar_test([[0, 12], [12, 0]])["method"] == "exact_binomial"
    assert mcnemar_test([[0, 13], [12, 0]])["method"] == "chi2_continuity"


def test_mcnemar_no_discordant_degenerate():
    r = mcnemar_test([[10, 0], [0, 10]], exact=False, correction=False)
    assert r["chi2"] == 0.0
    assert r["p"] == 1.0
    assert r["n_discordant"] == 0
    assert r["significant"] is False


def test_mcnemar_equal_discordant_pequal1():
    r = mcnemar_test([[5, 5], [5, 5]])
    assert r["p"] == 1.0  # exact: b=c → capped 1
    assert mcnemar_test([[5, 5], [5, 5]], correction=False, exact=False)["chi2"] == 0.0


def test_mcnemar_odds_ratio():
    r = mcnemar_test([[15, 2], [8, 10]])
    assert abs(r["OR"] - 0.25) < 1e-9  # b/c = 2/8


def test_mcnemar_or_infinite_when_c_zero():
    r = mcnemar_test([[10, 5], [0, 10]])
    assert r["OR"] == "inf"


def test_mcnemar_or_nan_when_both_zero():
    r = mcnemar_test([[10, 0], [0, 10]])
    assert r["OR"] == "nan"


def test_mcnemar_marginal_proportions():
    # a=15,b=2,c=8,d=10, N=35
    r = mcnemar_test([[15, 2], [8, 10]])
    assert abs(r["prop1"] - 18 / 35) < 1e-4   # (c+d)/N
    assert abs(r["prop2"] - 12 / 35) < 1e-4   # (b+d)/N
    assert abs(r["prop_diff"] - (-6 / 35)) < 1e-4


def test_mcnemar_p_alternatives_present():
    r = mcnemar_test([[15, 2], [8, 10]])
    for key in ("p_exact", "p_chi2", "p_chi2_corrected"):
        assert key in r and 0 <= r[key] <= 1


def test_mcnemar_force_exact():
    r = mcnemar_test([[5, 20], [5, 5]], exact=True)
    assert r["method"] == "exact_binomial"


def test_mcnemar_rejects_non_2x2():
    try:
        mcnemar_test([[1, 2, 3], [4, 5, 6]])
        assert False
    except ValueError:
        pass


def test_mcnemar_rejects_negative():
    try:
        mcnemar_test([[-1, 2], [3, 4]])
        assert False
    except ValueError:
        pass


def test_mcnemar_rejects_empty_table():
    try:
        mcnemar_test([[0, 0], [0, 0]])
        assert False
    except ValueError:
        pass


def test_mcnemar_significant_field_matches_alpha():
    r = mcnemar_test([[5, 20], [5, 5]], alpha=0.001)
    assert r["significant"] == (r["p"] < 0.001)


# ---------------------------------------------------------------------------
# Cochran's Q
# ---------------------------------------------------------------------------

def test_cochran_q_gold():
    # 6 被试 3 条件，手算 Q=16/6=2.6667
    conds = {
        "A": [1, 1, 0, 1, 0, 1],
        "B": [1, 1, 1, 1, 0, 0],
        "C": [1, 0, 0, 1, 0, 0],
    }
    r = cochran_q(conds)
    assert abs(r["Q"] - 16 / 6) < 1e-3  # r["Q"] 舍入到 4 位
    assert r["df"] == 2
    # df=2 → p = exp(-Q/2)
    assert abs(r["p"] - math.exp(-(16 / 6) / 2)) < 1e-6
    assert r["N_success"] == 10


def test_cochran_q_condition_proportions():
    conds = {
        "A": [1, 1, 0, 1, 0, 1],
        "B": [1, 1, 1, 1, 0, 0],
        "C": [1, 0, 0, 1, 0, 0],
    }
    r = cochran_q(conds)
    props = {c["name"]: c["proportion"] for c in r["condition_stats"]}
    assert abs(props["A"] - 4 / 6) < 1e-4
    assert abs(props["B"] - 4 / 6) < 1e-4
    assert abs(props["C"] - 2 / 6) < 1e-4


def test_cochran_q_no_effect_equal_columns():
    # 列和全相等 → numerator=0 → Q=0/p=1
    conds = {
        "A": [1, 0, 1],
        "B": [1, 1, 0],
        "C": [0, 1, 1],
    }
    r = cochran_q(conds)
    assert r["Q"] == 0.0
    assert r["p"] == 1.0


def test_cochran_q_all_constant_rows_degenerate():
    # 所有被试全 1 → 分母 0 → 退化
    conds = {"A": [1, 1, 1], "B": [1, 1, 1], "C": [1, 1, 1]}
    r = cochran_q(conds)
    assert r["Q"] == 0.0
    assert r["p"] == 1.0


def test_cochran_q_all_zero_rows_degenerate():
    conds = {"A": [0, 0, 0], "B": [0, 0, 0], "C": [0, 0, 0]}
    r = cochran_q(conds)
    assert r["Q"] == 0.0
    assert r["p"] == 1.0


def test_cochran_q_perfect_separation_significant():
    # 条件间完全分离：A全1,B全1,C全0... 但需要被试内变异
    conds = {
        "A": [1, 1, 1, 1, 1, 1],
        "B": [1, 1, 1, 1, 1, 1],
        "C": [0, 0, 0, 0, 0, 0],
    }
    r = cochran_q(conds)
    assert r["significant"] is True
    assert r["p"] < 0.05


def test_cochran_q_reduces_to_mcnemar_k2_identity():
    # k=2 时 Cochran 公式 = 未校正 McNemar χ²（手算恒等式）
    # x=[0,0,1,1,0], y=[1,1,0,1,0]: b=2, c=1, a=1, d=1
    x = [0, 0, 1, 1, 0]
    y = [1, 1, 0, 1, 0]
    n = len(x)
    Cx, Cy = sum(x), sum(y)
    N = Cx + Cy
    sum_C2 = Cx * Cx + Cy * Cy
    R = [x[i] + y[i] for i in range(n)]
    sum_R2 = sum(ri * ri for ri in R)
    denom = 2 * N - sum_R2
    Q_k2 = 1 * (2 * sum_C2 - N * N) / denom
    # McNemar 未校正
    a = sum(1 for i in range(n) if x[i] == 0 and y[i] == 0)
    b = sum(1 for i in range(n) if x[i] == 0 and y[i] == 1)
    c = sum(1 for i in range(n) if x[i] == 1 and y[i] == 0)
    d = sum(1 for i in range(n) if x[i] == 1 and y[i] == 1)
    mc = mcnemar_test([[a, b], [c, d]], correction=False, exact=False)
    assert abs(Q_k2 - mc["chi2"]) < 1e-3  # mc["chi2"] 舍入到 4 位
    assert abs(Q_k2 - 1 / 3) < 1e-9


def test_cochran_q_rejects_lt3_conditions():
    try:
        cochran_q({"A": [0, 1], "B": [1, 0]})
        assert False
    except ValueError:
        pass


def test_cochran_q_rejects_unequal_lengths():
    try:
        cochran_q({"A": [0, 1], "B": [1, 0, 1], "C": [0, 0, 0]})
        assert False
    except ValueError:
        pass


def test_cochran_q_rejects_single_subject():
    try:
        cochran_q({"A": [1], "B": [0], "C": [1]})
        assert False
    except ValueError:
        pass


def test_cochran_q_rejects_nonbinary():
    try:
        cochran_q({"A": [1, 2], "B": [0, 1], "C": [1, 0]})
        assert False
    except ValueError:
        pass


def test_cochran_q_post_hoc_structure():
    conds = {
        "A": [1, 1, 1, 1, 1, 1],
        "B": [1, 1, 1, 1, 1, 1],
        "C": [0, 0, 0, 0, 0, 0],
    }
    r = cochran_q(conds, post_hoc=True)
    assert "post_hoc" in r
    assert len(r["post_hoc"]) == 3  # C(3,2)
    for ph in r["post_hoc"]:
        assert "p_holm" in ph and "p_raw" in ph
        assert ph["p_holm"] >= ph["p_raw"] - 1e-12


def test_cochran_q_post_hoc_holm_monotone():
    conds = {
        "A": [1, 1, 0, 1, 0, 1, 1, 0],
        "B": [0, 1, 1, 1, 0, 0, 1, 1],
        "C": [0, 0, 0, 0, 1, 0, 0, 0],
    }
    r = cochran_q(conds, post_hoc=True)
    holms = [ph["p_holm"] for ph in r["post_hoc"]]
    raws = [ph["p_raw"] for ph in r["post_hoc"]]
    # Holm 校正后按显著性排序单调非降
    order = sorted(range(len(raws)), key=lambda i: raws[i])
    sorted_holm = [holms[i] for i in order]
    assert sorted_holm == sorted(sorted_holm)


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa_mcnemar_exact():
    r = mcnemar_test([[15, 2], [8, 10]])
    txt = format_apa_paircat(r)
    assert "McNemar" in txt
    assert "精确" in txt
    assert "OR" in txt


def test_format_apa_mcnemar_chi2():
    r = mcnemar_test([[5, 20], [5, 5]])
    txt = format_apa_paircat(r)
    assert "*χ*²(1" in txt


def test_format_apa_cochran():
    conds = {"A": [1, 1, 0], "B": [1, 0, 0], "C": [0, 0, 1]}
    r = cochran_q(conds)
    txt = format_apa_paircat(r)
    assert "Cochran" in txt
    assert "*Q*(" in txt
    assert "阳性比例" in txt


# ---------------------------------------------------------------------------
# 报告写出
# ---------------------------------------------------------------------------

def test_write_paircat_report_mcnemar():
    r = mcnemar_test([[15, 2], [8, 10]])
    with tempfile.TemporaryDirectory() as d:
        md, js = write_paircat_report(r, out_dir=d, filename="t")
        assert md.exists() and js.exists()
        content = md.read_text(encoding="utf-8")
        assert "配对 2×2 列联表" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert data["test"] == "McNemar"


def test_write_paircat_report_cochran_no_nan():
    conds = {"A": [1, 1, 1], "B": [1, 1, 1], "C": [1, 1, 1]}
    r = cochran_q(conds)
    with tempfile.TemporaryDirectory() as d:
        md, js = write_paircat_report(r, out_dir=d, filename="t")
        text = js.read_text(encoding="utf-8")
        assert "NaN" not in text and "Infinity" not in text


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_analyze_paircat_mcnemar_from_csv():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        # 构造 b=2 (0,1), c=1 (1,0), a=1, d=1
        rows = [[0, 1], [0, 1], [1, 0], [1, 1], [0, 0]]
        _write_csv(p, ["pre", "post"], rows)
        r = analyze_paircat(str(p), "mcnemar", cond1_col="pre",
                            cond2_col="post", out_dir=d)
        assert r["b"] == 2 and r["c"] == 1 and r["a"] == 1 and r["d"] == 1
        assert r["n_excluded"] == 0


def test_analyze_paircat_mcnemar_excludes_bad_rows():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[0, 1], [1, 0], ["", 1], [1, "x"], [2, 1]]
        _write_csv(p, ["pre", "post"], rows)
        r = analyze_paircat(str(p), "mcnemar", cond1_col="pre",
                            cond2_col="post", out_dir=d)
        assert r["n_excluded"] == 3  # 空、非数、非二分各 1


def test_analyze_paircat_cochran_from_csv():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [
            [1, 1, 1],
            [1, 1, 0],
            [0, 1, 0],
            [1, 1, 1],
            [0, 0, 0],
            [1, 0, 0],
        ]
        _write_csv(p, ["A", "B", "C"], rows)
        r = analyze_paircat(str(p), "cochran", conditions="A,B,C", out_dir=d)
        assert abs(r["Q"] - 16 / 6) < 1e-3  # r["Q"] 舍入到 4 位
        assert r["conditions"] == ["A", "B", "C"]
        assert r["n_excluded"] == 0


def test_analyze_paircat_cochran_complete_case():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[1, 1, 1], [1, 0, ""], [0, 1, 0]]
        _write_csv(p, ["A", "B", "C"], rows)
        r = analyze_paircat(str(p), "cochran", conditions="A,B,C", out_dir=d)
        assert r["n_excluded"] == 1
        assert r["n"] == 2


def test_analyze_paircat_mcnemar_requires_cols():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["a", "b"], [[0, 1]])
        try:
            analyze_paircat(str(p), "mcnemar", out_dir=d)
            assert False
        except ValueError:
            pass


def test_analyze_paircat_cochran_requires_3_conditions():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["A", "B"], [[0, 1]])
        try:
            analyze_paircat(str(p), "cochran", conditions="A,B", out_dir=d)
            assert False
        except ValueError:
            pass


def test_analyze_paircat_unknown_test():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["a"], [[0]])
        try:
            analyze_paircat(str(p), "foo", out_dir=d)
            assert False
        except ValueError:
            pass


def test_analyze_paircat_writes_files():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[0, 1], [1, 0], [1, 1]]
        _write_csv(p, ["pre", "post"], rows)
        r = analyze_paircat(str(p), "mcnemar", cond1_col="pre",
                            cond2_col="post", out_dir=d)
        assert Path(r["report_md"]).exists()
        assert Path(r["report_json"]).exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_mcnemar(capsys):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[0, 1], [0, 1], [1, 0], [1, 1], [0, 0]]
        _write_csv(p, ["pre", "post"], rows)
        rc = paircat_cli([str(p), "--test", "mcnemar", "--cond1", "pre",
                          "--cond2", "post", "--out", d])
        assert rc == 0
        out = capsys.readouterr().out
        assert "McNemar" in out


def test_cli_cochran_json(capsys):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[1, 1, 0], [1, 0, 0], [0, 1, 1], [1, 1, 0]]
        _write_csv(p, ["A", "B", "C"], rows)
        rc = paircat_cli([str(p), "--test", "cochran", "--conditions",
                          "A,B,C", "--json", "--out", d])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["test"] == "Cochran Q"


def test_cli_missing_file_returns_1():
    rc = paircat_cli(["/nonexistent/xyz.csv", "--test", "mcnemar",
                      "--cond1", "a", "--cond2", "b"])
    assert rc == 1
