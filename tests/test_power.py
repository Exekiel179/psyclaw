"""先验功效分析红队测试 —— 无 scipy 环境下的三重校验。

校验策略(本机无 scipy/numpy):
  1. 闭式自检:非中心 χ²(df=1) 有正态闭式;λ=0 退回中心分布;密度积分=1;
     df→∞ 的非中心 t 退回 Φ(t−ncp);分位数往返一致。
  2. 文献锚点:G*Power / Cohen(1988) 公认数值(t/ANOVA/相关/回归)。
  3. 互证:同一两尾 t 功效用"非中心 t 积分"与"非中心 F 级数"两条独立代码路径必须吻合。

运行:python -m pytest tests/ 或 python tests/test_power.py
原则:统计数值错误不可接受 —— 任一锚点偏出容差即失败。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.stats_core import _norm_cdf, _gammainc  # noqa: E402
from psyclaw.psych import power as P  # noqa: E402


def _close(a, b, tol=1e-3):
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# 1. 分布闭式自检
# ---------------------------------------------------------------------------

def test_chi_scaled_density_integrates_to_one():
    for df in (1, 5, 30, 126, 400):
        mass = P._chi_scaled_mass(df)
        assert _close(mass, 1.0, 2e-3), f"df={df} 密度积分={mass}"


def test_ncf_sf_lambda0_equals_central():
    # λ=0 时非中心 F 生存 = 中心 F 生存 = 1 − I_x
    for f, d1, d2 in [(2.0, 3, 40), (3.9163, 1, 126), (2.655, 3, 176)]:
        central = 1.0 - P._f_cdf_central(f, d1, d2)
        assert _close(P.ncf_sf(f, d1, d2, 0.0), central, 1e-9)


def test_ncx2_sf_lambda0_equals_central():
    for x, df in [(3.84, 1), (18.31, 10), (43.77, 30)]:
        central = 1.0 - _gammainc(df / 2.0, x / 2.0)
        assert _close(P.ncx2_sf(x, df, 0.0), central, 1e-9)


def test_ncx2_sf_df1_closed_form():
    # df=1:X=(Z+√λ)² → P(X>x)=1−[Φ(√x−√λ)−Φ(−√x−√λ)]
    for x, lam in [(3.84, 0.0), (3.84, 10.0), (6.0, 5.0), (1.0, 3.0)]:
        sx, sl = math.sqrt(x), math.sqrt(lam)
        closed = 1.0 - (_norm_cdf(sx - sl) - _norm_cdf(-sx - sl))
        assert _close(P.ncx2_sf(x, 1, lam), closed, 1e-3), f"x={x} λ={lam}"


def test_nct_cdf_large_df_to_normal():
    # df→∞ 时非中心 t 退回 N(ncp,1):CDF(t) → Φ(t−ncp)
    for t, ncp in [(1.0, 0.5), (0.0, 1.0), (-0.5, 0.3), (2.0, 1.5)]:
        approx = P.nct_cdf(t, 100000, ncp)
        assert _close(approx, _norm_cdf(t - ncp), 2e-3), f"t={t} ncp={ncp}"


def test_f_ppf_roundtrip():
    for p, d1, d2 in [(0.95, 1, 126), (0.95, 3, 176), (0.99, 5, 86)]:
        fc = P.f_ppf(p, d1, d2)
        assert _close(P._f_cdf_central(fc, d1, d2), p, 1e-4)


def test_ncx2_ppf_roundtrip():
    for p, df, lam in [(0.95, 20, 0.0), (0.95, 20, 10.0), (0.05, 30, 12.0)]:
        crit = P.ncx2_ppf(p, df, lam)
        assert _close(P.ncx2_sf(crit, df, lam), 1.0 - p, 1e-4)


# ---------------------------------------------------------------------------
# 2. t 检验:文献锚点 + 互证
# ---------------------------------------------------------------------------

def test_ttest_two_sample_gpower_anchor():
    # G*Power: d=0.5, 双尾 α=.05, n=64/组 → power ≈ 0.8015
    pw = P.power_ttest(0.5, 64, 64, alpha=0.05, tails=2, kind="two-sample")
    assert _close(pw, 0.8015, 6e-3), pw


def test_ttest_nct_matches_ncf_two_sided():
    # 两尾 t 功效:非中心 t 积分 vs 非中心 F 级数(两条独立路径)
    d, n = 0.5, 64
    df = 2 * n - 2
    nct_power = P.power_ttest(d, n, n, alpha=0.05, tails=2, kind="two-sample")
    fc = P.f_ppf(0.95, 1, df)
    ncp_f = (d * math.sqrt(n * n / (2.0 * n))) ** 2
    ncf_power = P.ncf_sf(fc, 1, df, ncp_f)
    assert _close(nct_power, ncf_power, 3e-3), (nct_power, ncf_power)


def test_ttest_required_n_classic():
    # Cohen/G*Power 经典:d=0.5 双尾 power=.80 → 每组 64
    n = P.n_for_ttest(0.5, power=0.80, alpha=0.05, tails=2, kind="two-sample")
    assert n == 64, n


def test_ttest_one_sided_more_powerful():
    p2 = P.power_ttest(0.5, 40, 40, tails=2, kind="two-sample")
    p1 = P.power_ttest(0.5, 40, 40, tails=1, kind="two-sample")
    assert p1 > p2


def test_ttest_paired_monotone_in_n():
    lo = P.power_ttest(0.4, 20, kind="paired")
    hi = P.power_ttest(0.4, 60, kind="paired")
    assert 0.0 < lo < hi < 1.0


# ---------------------------------------------------------------------------
# 3. ANOVA
# ---------------------------------------------------------------------------

def test_anova_gpower_anchor():
    # G*Power: f=0.25, 4 组, α=.05, n=45/组(N=180) → power ≈ 0.799
    pw = P.power_anova(0.25, 4, 45, alpha=0.05)
    assert _close(pw, 0.799, 1.2e-2), pw


def test_anova_required_n():
    n = P.n_for_anova(0.25, 4, power=0.80, alpha=0.05)
    assert 43 <= n <= 47, n


def test_anova_monotone_in_n():
    assert P.power_anova(0.25, 4, 20) < P.power_anova(0.25, 4, 60)


# ---------------------------------------------------------------------------
# 4. 相关(Fisher z)
# ---------------------------------------------------------------------------

def test_correlation_fisher_z_anchor():
    # 手算:r=.3, n=85, 双尾 → power ≈ 0.8004
    pw = P.power_correlation(0.3, 85, alpha=0.05, tails=2)
    assert round(pw, 2) == 0.80, pw


def test_correlation_required_n():
    n = P.n_for_correlation(0.3, power=0.80, alpha=0.05, tails=2)
    assert n == 85, n


# ---------------------------------------------------------------------------
# 5. 多元回归 R²
# ---------------------------------------------------------------------------

def test_regression_gpower_anchor():
    # G*Power: f²=0.15(中), 5 预测元, power=.80 → N≈92
    pw = P.power_regression(0.15, 5, 92, alpha=0.05)
    assert _close(pw, 0.80, 2.5e-2), pw


def test_regression_required_n():
    n = P.n_for_regression(0.15, 5, power=0.80, alpha=0.05)
    assert 88 <= n <= 96, n


# ---------------------------------------------------------------------------
# 6. SEM RMSEA 接近度检验
# ---------------------------------------------------------------------------

def test_sem_critical_value_self_consistent():
    df, n = 20, 200
    lam0 = (n - 1) * df * 0.05 ** 2
    crit = P.ncx2_ppf(0.95, df, lam0)
    # 构造点处生存概率应为 α
    assert _close(P.ncx2_sf(crit, df, lam0), 0.05, 1e-3)


def test_sem_power_in_range_and_monotone():
    lo = P.power_sem_rmsea(20, 100, rmsea0=0.05, rmsea1=0.08)
    hi = P.power_sem_rmsea(20, 300, rmsea0=0.05, rmsea1=0.08)
    assert 0.05 < lo < hi < 1.0, (lo, hi)


def test_sem_power_equals_alpha_when_h1_equals_h0():
    pw = P.power_sem_rmsea(30, 250, rmsea0=0.06, rmsea1=0.06, alpha=0.05)
    assert _close(pw, 0.05, 1e-2), pw


# ---------------------------------------------------------------------------
# 7. 中介 Monte Carlo
# ---------------------------------------------------------------------------

def test_mediation_monotone_in_n():
    lo = P.power_mediation_mc(0.3, 0.3, 50, n_sims=150, mc_reps=300, seed=7)
    hi = P.power_mediation_mc(0.3, 0.3, 250, n_sims=150, mc_reps=300, seed=7)
    assert 0.0 < lo < hi <= 1.0, (lo, hi)


def test_mediation_monotone_in_effect():
    small = P.power_mediation_mc(0.2, 0.2, 120, n_sims=150, mc_reps=300, seed=11)
    big = P.power_mediation_mc(0.45, 0.45, 120, n_sims=150, mc_reps=300, seed=11)
    assert big > small, (small, big)


def test_ols_recovers_known_slope():
    # y = 2 + 3x 无噪声 → 斜率 3、截距 2
    rows = [[1.0, float(x)] for x in range(10)]
    y = [2.0 + 3.0 * x for x in range(10)]
    fit = P._ols(rows, y)
    assert _close(fit["beta"][0], 2.0, 1e-6) and _close(fit["beta"][1], 3.0, 1e-6)


# ---------------------------------------------------------------------------
# 8. compute() / render() / 先验 / 告警 编排
# ---------------------------------------------------------------------------

def test_compute_power_direction():
    res = P.compute("ttest", d=0.5, n=64)
    assert res["solve"] == "power"
    assert _close(res["power"], 0.8015, 6e-3)
    assert res["effect"]["value"] == 0.5


def test_compute_n_direction_with_total():
    res = P.compute("ttest", d=0.5, power=0.80)
    assert res["solve"] == "n"
    assert res["n"] == 64
    assert res["n_total"] == 128


def test_compute_applies_conservative_priors():
    res = P.compute("ttest")  # 不给 d
    assert res["effect"]["value"] == 0.40
    assert any("先验" in nt for nt in res["notes"])


def test_compute_always_warns_publication_bias():
    res = P.compute("anova", f=0.25, k=4, n=45)
    assert any("发表偏倚" in nt for nt in res["notes"])


def test_render_and_run_power_smoke():
    res = P.compute("r", r=0.3, n=85)
    txt = P.render(res)
    assert "功效分析" in txt and "Pearson" in txt
    assert P.run_power("sem", df=30, n=200) == 0


def test_unknown_test_errors():
    res = P.compute("bogus")
    assert "error" in res
    assert P.run_power("bogus") == 1


# ---------------------------------------------------------------------------
# 自包含 runner(无 pytest 也可跑:python tests/test_power.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
