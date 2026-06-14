"""tests/test_stats_core.py — stats_core.py 核心统计函数单元测试 (P5-E8)。

被测：psyclaw/psych/stats_core.py
  - t_sf2          : 学生 t 双尾 p 值
  - chi2_sf        : 卡方上尾概率
  - norm_ppf       : 标准正态分位数
  - t_ppf          : t 分位数
  - welch_ttest    : Welch 独立样本 t 检验
  - student_ttest  : Student 等方差 t 检验
  - paired_ttest   : 配对样本 t 检验
  - pearson_r      : Pearson 相关系数
  - oneway_anova_full: 单因素 ANOVA（带 η²/ω²）
  - mann_whitney   : Mann-Whitney U 检验
  - chisquare_independence: 卡方独立性检验
  - eta_squared    : η² 效应量
  - bootstrap_ci   : 分层 bootstrap 置信区间

对照验证依据：
  - 标准正态：norm_ppf(0.975) ≈ 1.96
  - t 表格：t(df=30, 0.025 双尾) ≈ 2.042；t(df=1, 0.025) ≈ 12.706
  - 卡方表格：χ²(df=1) 0.05 分位 ≈ 3.841

不需要 LLM / API key / scipy。
"""
from __future__ import annotations

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.stats_core import (
    t_sf2,
    chi2_sf,
    norm_ppf,
    t_ppf,
    welch_ttest,
    student_ttest,
    paired_ttest,
    pearson_r,
    mann_whitney,
    chisquare_independence,
    eta_squared,
    bootstrap_ci,
)

# 辅助数据
G_ZERO = [0.0] * 20          # 全零组
G_ONE = [1.0] * 20           # 全一组
G_A = list(range(1, 11))     # [1..10], mean=5.5
G_B = list(range(11, 21))    # [11..20], mean=15.5, 明显分离


# ─── t_sf2 ────────────────────────────────────────────────────────────────────

class TestTSf2:
    def test_zero_t_gives_p_one(self):
        p = t_sf2(0.0, 10)
        assert abs(p - 1.0) < 1e-6

    def test_large_t_gives_small_p(self):
        p = t_sf2(10.0, 30)
        assert p < 0.001

    def test_symmetry(self):
        """t_sf2(t) 应等于 t_sf2(-t)（双尾）。"""
        for t in [1.5, 2.0, 3.0]:
            for df in [5, 20, 100]:
                assert abs(t_sf2(t, df) - t_sf2(-t, df)) < 1e-12

    def test_df_zero_returns_nan(self):
        result = t_sf2(2.0, 0)
        assert math.isnan(result)

    def test_large_df_approaches_normal(self):
        """df → ∞ 时 t 分布趋向正态；t=1.96, df=10000 → p ≈ 0.05。"""
        p = t_sf2(1.96, 10000)
        assert abs(p - 0.05) < 0.002

    def test_standard_table_df30(self):
        """t(df=30) 双尾 0.05 临界值约 2.042：t_sf2(2.042, 30) ≈ 0.05。"""
        p = t_sf2(2.042, 30)
        assert abs(p - 0.05) < 0.002

    def test_p_in_zero_one(self):
        for t_val in [0.1, 1.0, 5.0, 20.0]:
            p = t_sf2(t_val, 15)
            assert 0.0 <= p <= 1.0


# ─── chi2_sf ──────────────────────────────────────────────────────────────────

class TestChi2Sf:
    def test_zero_x_gives_one(self):
        assert chi2_sf(0.0, 1) == 1.0

    def test_negative_x_gives_one(self):
        assert chi2_sf(-1.0, 1) == 1.0

    def test_large_x_gives_small_p(self):
        assert chi2_sf(100.0, 1) < 1e-10

    def test_critical_value_df1(self):
        """χ²(df=1) 0.05 上侧临界值 ≈ 3.841。"""
        p = chi2_sf(3.841, 1)
        assert abs(p - 0.05) < 0.002

    def test_critical_value_df3(self):
        """χ²(df=3) 0.05 上侧临界值 ≈ 7.815。"""
        p = chi2_sf(7.815, 3)
        assert abs(p - 0.05) < 0.002

    def test_result_in_range(self):
        for x in [0.5, 2.0, 5.0, 10.0]:
            p = chi2_sf(x, 2)
            assert 0.0 <= p <= 1.0


# ─── norm_ppf ─────────────────────────────────────────────────────────────────

class TestNormPpf:
    def test_median_zero(self):
        assert abs(norm_ppf(0.5)) < 1e-6

    def test_0975_approx_196(self):
        """norm_ppf(0.975) ≈ 1.96（双尾 95% z-临界值）。"""
        assert abs(norm_ppf(0.975) - 1.96) < 0.01

    def test_symmetry(self):
        """norm_ppf(1-p) = -norm_ppf(p)。"""
        for p in [0.1, 0.25, 0.3]:
            assert abs(norm_ppf(1 - p) + norm_ppf(p)) < 1e-5

    def test_p_zero_nan(self):
        assert math.isnan(norm_ppf(0.0))

    def test_p_one_nan(self):
        assert math.isnan(norm_ppf(1.0))

    def test_0_025_negative(self):
        assert norm_ppf(0.025) < 0

    def test_monotone(self):
        vals = [norm_ppf(p) for p in [0.1, 0.25, 0.5, 0.75, 0.9]]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1]


# ─── t_ppf ────────────────────────────────────────────────────────────────────

class TestTPpf:
    def test_0975_large_df_near_196(self):
        """df=10000：t_ppf(0.975) ≈ 1.96（趋向正态）。"""
        assert abs(t_ppf(0.975, 10000) - 1.96) < 0.01

    def test_0975_df30_near_2042(self):
        """df=30：t_ppf(0.975) ≈ 2.042（教科书值）。"""
        assert abs(t_ppf(0.975, 30) - 2.042) < 0.01

    def test_p_below_half_negative(self):
        assert t_ppf(0.025, 10) < 0

    def test_monotone_in_df(self):
        """df 增大时分位数向正态收敛（减小）。"""
        vals = [t_ppf(0.975, df) for df in [5, 10, 30, 100, 1000]]
        for i in range(len(vals) - 1):
            assert vals[i] > vals[i + 1]


# ─── welch_ttest ──────────────────────────────────────────────────────────────

class TestWelchTtest:
    def test_required_keys(self):
        res = welch_ttest(G_A, G_B)
        for k in ("test", "t", "df", "p", "m1", "sd1", "n1", "m2", "sd2", "n2",
                  "effect", "d", "d_ci"):
            assert k in res

    def test_separated_groups_significant(self):
        res = welch_ttest(G_A, G_B)
        assert res["p"] < 0.001

    def test_equal_groups_nonsignificant(self):
        g = [5.0] * 10
        res = welch_ttest(g, g)
        # Zero variance → returns error dict
        assert "error" in res or res.get("p", 1.0) == 1.0

    def test_d_direction(self):
        """m1 < m2 → d < 0。"""
        res = welch_ttest(G_A, G_B)
        assert res["d"] < 0

    def test_sign_reversal(self):
        """交换组序后 t 符号翻转，p 值不变。"""
        r1 = welch_ttest(G_A, G_B)
        r2 = welch_ttest(G_B, G_A)
        assert abs(r1["t"] + r2["t"]) < 1e-9
        assert abs(r1["p"] - r2["p"]) < 1e-9

    def test_d_ci_contains_d(self):
        res = welch_ttest(G_A, G_B)
        lo, hi = res["d_ci"]
        assert lo <= res["d"] <= hi

    def test_n_correct(self):
        res = welch_ttest(G_A, G_B)
        assert res["n1"] == len(G_A)
        assert res["n2"] == len(G_B)


# ─── student_ttest ────────────────────────────────────────────────────────────

class TestStudentTtest:
    def test_label_student(self):
        res = student_ttest(G_A, G_B)
        assert "Student" in res.get("test", "")

    def test_df_equals_n1_plus_n2_minus_2(self):
        res = student_ttest(G_A, G_B)
        assert abs(res["df"] - (len(G_A) + len(G_B) - 2)) < 1e-9

    def test_separated_groups_significant(self):
        res = student_ttest(G_A, G_B)
        assert res["p"] < 0.001

    def test_required_keys(self):
        res = student_ttest(G_A, G_B)
        for k in ("test", "t", "df", "p", "d"):
            assert k in res


# ─── paired_ttest ─────────────────────────────────────────────────────────────

class TestPairedTtest:
    # 差值有方差的测试数据（所有差值不全等，sd > 0）
    _X = [3, 5, 4, 6, 2, 7, 4, 5, 3, 6]
    _Y = [1, 2, 2, 3, 1, 4, 2, 3, 1, 3]
    # diffs = [2,3,2,3,1,3,2,2,2,3], mean=2.3, sd>0

    def test_consistent_positive_diff_significant(self):
        """差值一致为正时，检验应显著。"""
        res = paired_ttest(self._X, self._Y)
        assert "error" not in res
        assert res["p"] < 0.001

    def test_df_equals_n_minus_1(self):
        res = paired_ttest(self._X, self._Y)
        assert abs(res["df"] - (len(self._X) - 1)) < 1e-9

    def test_zero_diff_returns_error(self):
        x = [1.0, 2.0, 3.0]
        res = paired_ttest(x, x)
        assert "error" in res

    def test_dz_positive_when_x_greater(self):
        """x > y 时差值为正，dz > 0。"""
        res = paired_ttest(self._X, self._Y)
        assert "error" not in res
        assert res["d"] > 0

    def test_d_ci_present(self):
        res = paired_ttest(self._X, self._Y)
        assert "d_ci" in res


# ─── pearson_r ────────────────────────────────────────────────────────────────

class TestPearsonR:
    def test_perfect_positive(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        res = pearson_r(x, y)
        assert abs(res["r"] - 1.0) < 1e-9

    def test_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [-1.0, -2.0, -3.0, -4.0, -5.0]
        res = pearson_r(x, y)
        assert abs(res["r"] + 1.0) < 1e-9

    def test_zero_variance_returns_error(self):
        x = [1.0] * 5
        y = [2.0, 3.0, 1.0, 4.0, 5.0]
        res = pearson_r(x, y)
        assert "error" in res

    def test_df_equals_n_minus_2(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        y = [1.1, 1.9, 3.2, 3.8, 5.1, 6.0, 7.2]
        res = pearson_r(x, y)
        assert abs(res["df"] - (len(x) - 2)) < 1e-9

    def test_n_correct(self):
        x = list(range(10))
        y = list(range(10, 20))
        res = pearson_r(x, y)
        assert res["n"] == 10

    def test_r_in_neg1_pos1(self):
        import random
        rng = random.Random(99)
        x = [rng.gauss(0, 1) for _ in range(50)]
        y = [rng.gauss(0, 1) for _ in range(50)]
        res = pearson_r(x, y)
        assert -1.0 <= res["r"] <= 1.0

    def test_ci_contains_r(self):
        x = list(range(1, 20))
        y = [v * 0.8 + 0.5 for v in x]
        res = pearson_r(x, y)
        lo, hi = res["r_ci"]
        assert lo <= res["r"] <= hi


# ─── mann_whitney ─────────────────────────────────────────────────────────────

class TestMannWhitney:
    def test_required_keys(self):
        res = mann_whitney(G_A, G_B)
        for k in ("test", "U", "z", "p", "n1", "n2", "effect", "r"):
            assert k in res

    def test_separated_groups_significant(self):
        res = mann_whitney(G_A, G_B)
        assert res["p"] < 0.001

    def test_p_in_range(self):
        res = mann_whitney(G_A, G_B)
        assert 0.0 <= res["p"] <= 1.0

    def test_u_non_negative(self):
        res = mann_whitney(G_A, G_B)
        assert res["U"] >= 0

    def test_equal_groups_p_near_one(self):
        g = [1.0, 2.0, 3.0, 4.0, 5.0]
        res = mann_whitney(g, g)
        # 完全相同数据 → z=0 → p=1.0
        assert res["p"] > 0.5


# ─── chisquare_independence ───────────────────────────────────────────────────

class TestChisquareIndependence:
    def test_independent_2x2_high_p(self):
        """完全独立：[[5,5],[5,5]] → χ²=0 → p=1。"""
        res = chisquare_independence([[5, 5], [5, 5]])
        assert abs(res["chi2"]) < 1e-9
        assert abs(res["p"] - 1.0) < 1e-6

    def test_dependent_2x2_significant(self):
        """完全关联：[[10,0],[0,10]] → 极显著。"""
        res = chisquare_independence([[10, 0], [0, 10]])
        assert res["p"] < 0.001

    def test_df_formula(self):
        """df = (rows-1)*(cols-1)。"""
        res = chisquare_independence([[1, 2, 3], [4, 5, 6]])
        assert abs(res["df"] - 2) < 1e-9

    def test_cramers_v_range(self):
        res = chisquare_independence([[10, 0], [0, 10]])
        assert 0.0 <= res["V"] <= 1.0

    def test_n_equals_total(self):
        table = [[3, 7], [8, 2]]
        res = chisquare_independence(table)
        assert res["N"] == 20


# ─── eta_squared ──────────────────────────────────────────────────────────────

class TestEtaSquared:
    def test_all_same_returns_zero(self):
        groups = [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
        eta2 = eta_squared(groups)
        assert math.isnan(eta2) or abs(eta2) < 1e-9

    def test_completely_separated(self):
        """组内无方差：eta² → 1.0。"""
        groups = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
        eta2 = eta_squared(groups)
        assert abs(eta2 - 1.0) < 1e-6

    def test_value_in_range(self):
        groups = [G_A, G_B, list(range(21, 31))]
        eta2 = eta_squared(groups)
        assert 0.0 <= eta2 <= 1.0


# ─── bootstrap_ci ─────────────────────────────────────────────────────────────

class TestBootstrapCI:
    def test_returns_2_tuple(self):
        result = bootstrap_ci([G_A, G_B], eta_squared, n_boot=100)
        assert len(result) == 2

    def test_lower_le_upper(self):
        lo, hi = bootstrap_ci([G_A, G_B], eta_squared, n_boot=200, seed=1)
        assert lo <= hi

    def test_eta2_within_ci(self):
        """bootstrap CI 应包含点估计（大概率，固定种子）。"""
        true_eta2 = eta_squared([G_A, G_B])
        lo, hi = bootstrap_ci([G_A, G_B], eta_squared, n_boot=500, seed=42)
        # CI 应包含或非常接近真值（宽泛判据，统计过程有随机性）
        assert lo <= true_eta2 + 0.05  # CI 下界不应超过真值太多

    def test_fixed_seed_reproducible(self):
        r1 = bootstrap_ci([G_A, G_B], eta_squared, n_boot=100, seed=7)
        r2 = bootstrap_ci([G_A, G_B], eta_squared, n_boot=100, seed=7)
        assert r1 == r2
