"""tests/test_diagnostics.py — diagnostics.py 诊断统计函数单元测试 (P5-E9)。

被测：psyclaw/psych/diagnostics.py
  - betai        : 正则化不完全 Beta I_x(a,b)
  - f_sf         : F 分布生存函数 P(F > f)
  - z_sf2        : 标准正态双尾 p 值
  - describe     : 描述统计 + 偏度/峰度矩检验
  - oneway_f     : 经典单因素 ANOVA
  - welch_f      : Welch ANOVA（不假设方差齐性）
  - levene_bf    : Brown-Forsythe Levene 方差齐性检验

对照验证依据：
  - F 表格：F(1,30)=4.171 → p≈0.05；F(1,60)=4.001 → p≈0.05；F(2,30)=3.316 → p≈0.05
  - 大 df 时 F(1,∞)≈chi²(1)/1：F=3.84 → p≈0.05
  - 标准正态：z=1.96 → 双尾 p≈0.05；z=2.576 → p≈0.01
  - Beta(1,1)=Uniform：I_0.5(1,1)=0.5；Beta(a,a) 在 x=0.5 处值=0.5

无需 LLM / API key / scipy。
"""
from __future__ import annotations

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.diagnostics import (
    betai,
    f_sf,
    z_sf2,
    describe,
    oneway_f,
    welch_f,
    levene_bf,
)


# ---------------------------------------------------------------------------
# betai — 正则化不完全 Beta I_x(a,b)
# ---------------------------------------------------------------------------

class TestBetai:
    def test_x_zero_returns_zero(self):
        assert betai(2, 3, 0.0) == 0.0

    def test_x_one_returns_one(self):
        assert betai(2, 3, 1.0) == 1.0

    def test_uniform_midpoint(self):
        # Beta(1,1) = Uniform[0,1] → I_0.5(1,1) = 0.5
        assert abs(betai(1, 1, 0.5) - 0.5) < 1e-10

    def test_symmetric_ab_midpoint(self):
        # I_0.5(a,a) = 0.5 by symmetry of the Beta distribution
        assert abs(betai(2, 2, 0.5) - 0.5) < 1e-8

    def test_range(self):
        val = betai(3, 5, 0.7)
        assert 0.0 <= val <= 1.0

    def test_monotone_increasing_in_x(self):
        # I_x(a,b) is strictly increasing in x for fixed a,b>0
        assert betai(2, 3, 0.3) < betai(2, 3, 0.7)

    def test_complement_symmetry(self):
        # I_x(a,b) + I_{1-x}(b,a) = 1
        x = 0.4
        assert abs(betai(2, 5, x) + betai(5, 2, 1 - x) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# f_sf — F 分布生存函数
# ---------------------------------------------------------------------------

class TestFSf:
    def test_f_zero_returns_one(self):
        # F=0 → p=1 (full probability mass to the right)
        assert f_sf(0, 1, 30) == 1.0

    def test_f_negative_returns_one(self):
        assert f_sf(-5, 2, 60) == 1.0

    def test_textbook_critical_df1_1_df2_30(self):
        # F(1,30) = 4.171 → p ≈ 0.050 (standard F-table)
        assert abs(f_sf(4.171, 1, 30) - 0.05) < 0.01

    def test_textbook_critical_df1_1_df2_60(self):
        # F(1,60) = 4.001 → p ≈ 0.050
        assert abs(f_sf(4.001, 1, 60) - 0.05) < 0.01

    def test_textbook_critical_df1_2_df2_30(self):
        # F(2,30) = 3.316 → p ≈ 0.050
        assert abs(f_sf(3.316, 2, 30) - 0.05) < 0.01

    def test_large_f_gives_small_p(self):
        assert f_sf(100, 1, 30) < 0.001

    def test_range(self):
        assert 0.0 <= f_sf(2.5, 3, 60) <= 1.0

    def test_decreasing_in_f(self):
        # higher F → smaller p
        assert f_sf(5.0, 2, 40) < f_sf(3.0, 2, 40)

    def test_large_df_converges_to_chi2(self):
        # F(1, ∞) = chi²(1)/1; chi²(1) = 3.84 → p ≈ 0.050
        assert abs(f_sf(3.84, 1, 10000) - 0.05) < 0.01

    def test_moderate_f_unsignificant(self):
        # F(2,30) = 2.0 → p > 0.05
        assert f_sf(2.0, 2, 30) > 0.05


# ---------------------------------------------------------------------------
# z_sf2 — 标准正态双尾 p 值
# ---------------------------------------------------------------------------

class TestZSf2:
    def test_z_zero_returns_one(self):
        # z=0 → full area, p=1
        assert z_sf2(0) == 1.0

    def test_z_1_96_approx_0_05(self):
        # well-known critical value: z=1.96 → p≈0.05
        assert abs(z_sf2(1.96) - 0.05) < 0.005

    def test_z_2_576_approx_0_01(self):
        assert abs(z_sf2(2.576) - 0.01) < 0.002

    def test_z_3_291_approx_0_001(self):
        assert abs(z_sf2(3.291) - 0.001) < 0.0005

    def test_symmetric_positive_negative(self):
        # z_sf2 uses |z|, so +1.96 and -1.96 give same p
        assert abs(z_sf2(1.96) - z_sf2(-1.96)) < 1e-12

    def test_range(self):
        assert 0.0 < z_sf2(3.0) < 1.0

    def test_decreasing_in_abs_z(self):
        assert z_sf2(3.0) < z_sf2(2.0) < z_sf2(1.0)


# ---------------------------------------------------------------------------
# describe — 描述统计 + 偏度/峰度矩检验
# ---------------------------------------------------------------------------

class TestDescribe:
    def test_required_keys_always_present(self):
        d = describe([1, 2, 3, 4, 5])
        for k in ("n", "mean", "sd", "min", "max", "median"):
            assert k in d

    def test_basic_values_linear_data(self):
        d = describe([1, 2, 3, 4, 5])
        assert d["n"] == 5
        assert d["mean"] == pytest.approx(3.0)
        assert d["median"] == pytest.approx(3.0)
        assert d["min"] == 1
        assert d["max"] == 5

    def test_sd_known_value(self):
        # [3, 5, 7]: mean=5, sum_sq=8, sample sd = sqrt(8/2) = 2.0
        d = describe([3, 5, 7])
        assert abs(d["sd"] - 2.0) < 1e-10

    def test_even_n_median_interpolated(self):
        d = describe([1, 2, 3, 4])
        assert d["median"] == pytest.approx(2.5)

    def test_skew_kurt_present_n_gt_3(self):
        xs = list(range(10))
        d = describe(xs)
        for k in ("skew", "kurt", "skew_z", "kurt_z", "skew_p", "kurt_p"):
            assert k in d

    def test_skew_kurt_absent_small_n(self):
        # n=3 → n > 3 condition fails → no moments
        d = describe([1, 2, 3])
        assert "skew" not in d

    def test_zero_variance_no_moments(self):
        # m2=0 → condition fails → no skew/kurt
        d = describe([5, 5, 5, 5, 5])
        assert "skew" not in d

    def test_symmetric_skew_near_zero(self):
        # uniform integer sequence → symmetric → skew ≈ 0
        xs = list(range(1, 21))
        d = describe(xs)
        assert abs(d["skew"]) < 0.5

    def test_right_skew_positive(self):
        # heavy right tail → positive skew
        xs = [1, 1, 1, 1, 1, 1, 1, 1, 2, 20]
        d = describe(xs)
        assert d["skew"] > 0

    def test_skew_p_in_range(self):
        xs = list(range(20))
        d = describe(xs)
        assert 0.0 <= d["skew_p"] <= 1.0

    def test_kurt_p_in_range(self):
        xs = list(range(20))
        d = describe(xs)
        assert 0.0 <= d["kurt_p"] <= 1.0

    def test_single_element(self):
        d = describe([7])
        assert d["n"] == 1
        assert d["mean"] == 7.0
        assert d["sd"] == 0.0
        assert "skew" not in d


# ---------------------------------------------------------------------------
# oneway_f — 经典单因素 ANOVA
# ---------------------------------------------------------------------------

class TestOnewayF:
    def test_required_keys(self):
        r = oneway_f([[1, 2, 3], [4, 5, 6]])
        for k in ("F", "df1", "df2", "p", "eta2"):
            assert k in r

    def test_df1_and_df2_formula(self):
        # k=3 groups of n=5 → df1=2, df2=12
        groups = [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]]
        r = oneway_f(groups)
        assert r["df1"] == 2
        assert r["df2"] == 12

    def test_equal_group_means_f_zero(self):
        # all groups share identical distribution → same mean → ss_b=0 → F=0
        groups = [[1, 2, 3], [1, 2, 3], [1, 2, 3]]
        r = oneway_f(groups)
        assert r["F"] == pytest.approx(0.0, abs=1e-10)
        assert r["eta2"] == pytest.approx(0.0, abs=1e-10)

    def test_large_effect_significant(self):
        # groups far apart, small within-group variance → large F, p < 0.001
        groups = [
            [1, 2, 3, 2, 1],
            [100, 101, 102, 101, 100],
        ]
        r = oneway_f(groups)
        assert r["p"] < 0.001

    def test_eta2_range(self):
        groups = [[1, 2, 3], [4, 5, 6], [10, 20, 30]]
        r = oneway_f(groups)
        assert 0.0 <= r["eta2"] <= 1.0

    def test_eta2_near_one_near_perfect_separation(self):
        # tiny within-group variance, huge between-group variance
        groups = [
            [10, 10.001, 9.999],
            [20, 20.001, 19.999],
            [30, 30.001, 29.999],
        ]
        r = oneway_f(groups)
        assert r["eta2"] > 0.99

    def test_p_range(self):
        groups = [[1, 2, 3], [4, 5, 6]]
        r = oneway_f(groups)
        assert 0.0 <= r["p"] <= 1.0

    def test_zero_within_variance_nan_f(self):
        # all identical values → ss_w=0 → F=NaN per code
        groups = [[5, 5, 5], [5, 5, 5]]
        r = oneway_f(groups)
        assert math.isnan(r["F"])

    def test_f_positive_for_nonzero_between_effect(self):
        groups = [[1, 2, 3], [5, 6, 7]]
        r = oneway_f(groups)
        assert r["F"] > 0


# ---------------------------------------------------------------------------
# welch_f — Welch ANOVA（不假设方差齐性）
# ---------------------------------------------------------------------------

class TestWelchF:
    def test_required_keys(self):
        r = welch_f([[1, 2, 3], [4, 5, 6]])
        for k in ("F", "df1", "df2", "p"):
            assert k in r

    def test_df1_formula_three_groups(self):
        r = welch_f([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        assert r["df1"] == 2

    def test_large_effect_significant(self):
        # groups far apart with small but non-zero within-group variance
        groups = [
            [0, 1, 0, 1, 0, 1],
            [100, 101, 100, 101, 100, 101],
        ]
        r = welch_f(groups)
        assert r["p"] < 0.001

    def test_no_effect_f_zero(self):
        # identical groups → between-group variation = 0 → F = 0
        groups = [[1, 2, 3, 4, 5], [1, 2, 3, 4, 5]]
        r = welch_f(groups)
        assert r["F"] == pytest.approx(0.0, abs=1e-8)

    def test_zero_variance_group_nan(self):
        # one group all same → variance=0 → NaN
        r = welch_f([[5, 5, 5], [1, 2, 3]])
        assert math.isnan(r["F"])

    def test_p_range(self):
        r = welch_f([[1, 2, 3, 4], [5, 6, 7, 8]])
        assert 0.0 <= r["p"] <= 1.0

    def test_unequal_variance_still_gives_valid_result(self):
        # group 1: tiny variance; group 2: large variance
        g1 = [5, 5, 5, 5, 5, 6]
        g2 = [1, 10, 20, 30, 40, 50]
        r = welch_f([g1, g2])
        assert not math.isnan(r["F"])
        assert 0.0 <= r["p"] <= 1.0


# ---------------------------------------------------------------------------
# levene_bf — Brown-Forsythe Levene 方差齐性检验
# ---------------------------------------------------------------------------

class TestLeveneBF:
    def test_required_keys(self):
        r = levene_bf([[1, 2, 3], [4, 5, 6]])
        for k in ("W", "df1", "df2", "p"):
            assert k in r

    def test_equal_variance_large_p(self):
        # two groups with same spread (different means) → p > 0.05
        g1 = [1, 2, 3, 4, 5]
        g2 = [10, 11, 12, 13, 14]
        r = levene_bf([g1, g2])
        assert r["p"] > 0.05

    def test_very_unequal_variance_small_p(self):
        # group 1: near-zero variance; group 2: huge variance
        g1 = [5.00, 5.01, 4.99, 5.00, 5.00, 5.00, 5.00, 5.00, 5.00, 5.00]
        g2 = [1.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 100.0]
        r = levene_bf([g1, g2])
        assert r["p"] < 0.05

    def test_w_nonneg(self):
        r = levene_bf([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        assert r["W"] >= 0.0

    def test_df1_formula_k_groups(self):
        # k=3 → df1 = k-1 = 2
        r = levene_bf([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        assert r["df1"] == 2

    def test_p_range(self):
        r = levene_bf([[1, 2, 3, 4, 5], [5, 6, 7, 8, 9]])
        assert 0.0 <= r["p"] <= 1.0
