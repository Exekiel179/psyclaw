"""测试效应量转换器（psyclaw/psych/effect_size.py）。

数值对照：
  - d↔r 互逆（Cohen 1988）
  - d=0.5 → r≈0.243（课本值）
  - f → eta² 互逆
  - F → eta² 边界值（F→0 时 eta²→0，F→∞ 时 eta²→1）
  - t → d（独立/单样本）
  - chi² → phi（已知 chi²/N 关系）
  - OR → d 对数变换验证
  - 言语标签边界（d < .20, ≥ .20, ≥ .50, ≥ .80）
  - 从摘要统计计算 d：两组/单样本
  - convert() 通用入口
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.effect_size import (
    d_to_r, r_to_d,
    d_to_f, f_to_d,
    d_to_eta2, eta2_to_d,
    f_to_eta2, eta2_to_f,
    F_to_eta2,
    t_to_d_two_sample, t_to_d_one_sample,
    chi2_to_phi, chi2_to_cramers_v,
    or_to_d, d_to_or,
    interpret_d, interpret_r, interpret_eta2, interpret_f,
    cohens_d_two_group, cohens_d_one_sample,
    convert,
    format_apa_effect_size,
)


# ---------------------------------------------------------------------------
# d ↔ r
# ---------------------------------------------------------------------------

def test_d_to_r_known():
    """d=0.5 → r ≈ 0.2425（Cohen 1988 p. 23）。"""
    r = d_to_r(0.5)
    assert abs(r - 0.2425) < 0.001, f"d_to_r(0.5) = {r}"


def test_r_to_d_known():
    """r=0.3 → d ≈ 0.632（通过公式验算）。"""
    d = r_to_d(0.3)
    expected = 2 * 0.3 / math.sqrt(1 - 0.3 ** 2)
    assert abs(d - expected) < 1e-9


def test_d_r_inverse():
    """d → r → d 精确还原。"""
    for d_orig in [-2.0, -0.5, 0.0, 0.5, 1.0, 2.0]:
        r = d_to_r(d_orig)
        d_back = r_to_d(r)
        assert abs(d_back - d_orig) < 1e-8, f"d={d_orig} → r={r} → d={d_back}"


def test_r_d_inverse():
    """r → d → r 精确还原。"""
    for r_orig in [-0.8, -0.3, 0.0, 0.3, 0.8]:
        d = r_to_d(r_orig)
        r_back = d_to_r(d)
        assert abs(r_back - r_orig) < 1e-8, f"r={r_orig} → d={d} → r={r_back}"


def test_d_to_r_zero():
    """d=0 → r=0。"""
    assert d_to_r(0.0) == 0.0


def test_r_to_d_zero():
    assert r_to_d(0.0) == 0.0


def test_r_to_d_boundary():
    """r=1 → d=inf; r=-1 → d=-inf。"""
    assert not math.isfinite(r_to_d(1.0))
    assert not math.isfinite(r_to_d(-1.0))


def test_d_to_r_symmetric():
    """d_to_r(-d) = -d_to_r(d)。"""
    for d in [0.2, 0.5, 1.0]:
        assert abs(d_to_r(-d) + d_to_r(d)) < 1e-12


# ---------------------------------------------------------------------------
# d ↔ f
# ---------------------------------------------------------------------------

def test_d_f_inverse():
    for d in [0.2, 0.5, 0.8, 1.5]:
        assert abs(f_to_d(d_to_f(d)) - d) < 1e-10


def test_d_to_f_medium():
    """d=0.5 → f=0.25（Cohen 1988 约定 medium）。"""
    assert abs(d_to_f(0.5) - 0.25) < 1e-10


# ---------------------------------------------------------------------------
# d ↔ eta²
# ---------------------------------------------------------------------------

def test_d_eta2_inverse():
    for d in [0.2, 0.5, 0.8, 1.0]:
        eta2 = d_to_eta2(d)
        d_back = eta2_to_d(eta2)
        assert abs(d_back - d) < 1e-8


def test_d_to_eta2_medium():
    """d=0.5 → eta² = 0.25/(0.25+4) ≈ 0.0588。"""
    eta2 = d_to_eta2(0.5)
    expected = 0.25 / (0.25 + 4.0)
    assert abs(eta2 - expected) < 1e-9


def test_eta2_boundary():
    """eta² 在 (0,1) 内；boundary 返回 nan。"""
    assert math.isnan(eta2_to_d(0.0))
    assert math.isnan(eta2_to_d(1.0))


# ---------------------------------------------------------------------------
# f ↔ eta²
# ---------------------------------------------------------------------------

def test_f_eta2_inverse():
    for f in [0.1, 0.25, 0.4, 0.6]:
        assert abs(eta2_to_f(f_to_eta2(f)) - f) < 1e-8


def test_f_to_eta2_medium():
    """f=0.25 → eta² = 0.0625/1.0625 ≈ 0.0588（Cohen 1988 medium）。"""
    eta2 = f_to_eta2(0.25)
    assert abs(eta2 - 0.25 ** 2 / (1 + 0.25 ** 2)) < 1e-9


# ---------------------------------------------------------------------------
# F → eta²
# ---------------------------------------------------------------------------

def test_F_to_eta2_basic():
    """F=4, df1=1, df2=48 → eta² = 4/(4+48) ≈ 0.0769。"""
    eta2 = F_to_eta2(4.0, 1, 48)
    assert abs(eta2 - 4.0 / 52.0) < 1e-9


def test_F_to_eta2_large_F():
    """F 很大时 eta² → 1。"""
    eta2 = F_to_eta2(1e6, 1, 10)
    assert eta2 > 0.999


def test_F_to_eta2_zero():
    eta2 = F_to_eta2(0.0, 1, 10)
    assert math.isnan(eta2) or eta2 == 0.0


# ---------------------------------------------------------------------------
# t → d
# ---------------------------------------------------------------------------

def test_t_to_d_two_sample():
    """t=2, n1=n2=25 → d = 2 * sqrt(2/25) = 2*0.2828 ≈ 0.566。"""
    d = t_to_d_two_sample(2.0, 25, 25)
    expected = 2.0 * math.sqrt(1 / 25 + 1 / 25)
    assert abs(d - expected) < 1e-9


def test_t_to_d_one_sample():
    """t=2, n=20 → d = 2/sqrt(20) ≈ 0.447。"""
    d = t_to_d_one_sample(2.0, 20)
    assert abs(d - 2.0 / math.sqrt(20)) < 1e-9


def test_t_to_d_zero():
    assert t_to_d_two_sample(0.0, 20, 20) == 0.0
    assert t_to_d_one_sample(0.0, 20) == 0.0


# ---------------------------------------------------------------------------
# chi² → phi / Cramér's V
# ---------------------------------------------------------------------------

def test_chi2_to_phi_basic():
    """chi²=4, N=100 → phi=0.2。"""
    phi = chi2_to_phi(4.0, 100)
    assert abs(phi - 0.2) < 1e-9


def test_chi2_to_phi_small():
    """chi²=0 → phi=0。"""
    assert chi2_to_phi(0.0, 100) == 0.0


def test_cramers_v_2x2_equals_phi():
    """2×2 表中 k=2，Cramér's V = phi。"""
    chi2, n = 4.0, 100
    assert abs(chi2_to_cramers_v(chi2, n, 2) - chi2_to_phi(chi2, n)) < 1e-9


def test_cramers_v_3x2():
    """3×2 表（k=2），V = sqrt(chi²/N)。"""
    v = chi2_to_cramers_v(9.0, 100, 2)
    assert abs(v - math.sqrt(9.0 / 100)) < 1e-9


# ---------------------------------------------------------------------------
# OR ↔ d
# ---------------------------------------------------------------------------

def test_or_d_inverse():
    """OR=1 → d=0; OR=exp(π/√3) → d=1。"""
    assert abs(or_to_d(1.0)) < 1e-10
    expected_d = 1.0
    OR = d_to_or(expected_d)
    d_back = or_to_d(OR)
    assert abs(d_back - expected_d) < 1e-8


def test_or_to_d_large():
    """OR > 1 → d > 0。"""
    assert or_to_d(3.0) > 0


# ---------------------------------------------------------------------------
# 言语标签
# ---------------------------------------------------------------------------

def test_interpret_d_small():
    label = interpret_d(0.3)
    assert "小效应" in label or "small" in label.lower()


def test_interpret_d_medium():
    label = interpret_d(0.6)
    assert "中效应" in label or "medium" in label.lower()


def test_interpret_d_large():
    label = interpret_d(1.0)
    assert "大效应" in label or "large" in label.lower()


def test_interpret_d_negligible():
    label = interpret_d(0.1)
    assert "可忽略" in label or "negligible" in label.lower()


def test_interpret_r_medium():
    label = interpret_r(0.35)
    assert "中效应" in label


def test_interpret_eta2_large():
    label = interpret_eta2(0.20)
    assert "大效应" in label


def test_interpret_f_small():
    label = interpret_f(0.15)
    assert "小效应" in label


# ---------------------------------------------------------------------------
# cohens_d_two_group / cohens_d_one_sample
# ---------------------------------------------------------------------------

def test_cohens_d_two_group_basic():
    """M1=6, M2=4, SD1=SD2=2, n1=n2=30 → d = (6-4)/2 = 1.0。"""
    result = cohens_d_two_group(6.0, 2.0, 30, 4.0, 2.0, 30)
    assert abs(result["d"] - 1.0) < 0.01
    assert result["n1"] == 30
    assert result["n2"] == 30


def test_cohens_d_two_group_hedges_g():
    """Hedges' g < d（偏差校正后绝对值略小）。"""
    result = cohens_d_two_group(6.0, 2.0, 15, 4.0, 2.0, 15)
    assert abs(result["hedges_g"]) < abs(result["d"])


def test_cohens_d_two_group_ci():
    """95% CI 应包含真值 d=1.0（大样本）。"""
    result = cohens_d_two_group(6.0, 2.0, 50, 4.0, 2.0, 50)
    assert result["ci_lower_95"] < 1.0 < result["ci_upper_95"]


def test_cohens_d_two_group_fields():
    result = cohens_d_two_group(5.0, 1.0, 20, 4.0, 1.0, 20)
    for k in ("d", "hedges_g", "se", "ci_lower_95", "ci_upper_95",
              "pooled_sd", "interpretation", "r", "eta2"):
        assert k in result, f"缺少字段: {k}"


def test_cohens_d_one_sample():
    """M=5, SD=2, n=30, mu0=0 → d = 2.5。"""
    result = cohens_d_one_sample(5.0, 2.0, 30, mu0=0.0)
    assert abs(result["d"] - 2.5) < 0.01


def test_cohens_d_two_group_too_few():
    try:
        cohens_d_two_group(5.0, 1.0, 1, 4.0, 1.0, 1)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_cohens_d_zero_sd_raises():
    try:
        cohens_d_two_group(5.0, 0.0, 10, 4.0, 0.0, 10)
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# convert() 通用入口
# ---------------------------------------------------------------------------

def test_convert_d_to_r():
    assert abs(convert(0.5, "d", "r") - d_to_r(0.5)) < 1e-9


def test_convert_r_to_d():
    assert abs(convert(0.3, "r", "d") - r_to_d(0.3)) < 1e-9


def test_convert_d_to_eta2():
    assert abs(convert(0.5, "d", "eta2") - d_to_eta2(0.5)) < 1e-9


def test_convert_f_to_eta2():
    assert abs(convert(0.25, "f", "eta2") - f_to_eta2(0.25)) < 1e-9


def test_convert_same_type():
    """from=to 时直接返回原值。"""
    assert convert(0.5, "d", "d") == 0.5


def test_convert_unsupported():
    try:
        convert(0.5, "phi", "d")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# format_apa_effect_size
# ---------------------------------------------------------------------------

def test_format_apa_effect_size_d():
    text = format_apa_effect_size(d=0.5)
    assert "*d*" in text and "0.50" in text


def test_format_apa_effect_size_r():
    text = format_apa_effect_size(r=0.3)
    assert "*r*" in text


def test_format_apa_effect_size_multi():
    text = format_apa_effect_size(d=0.5, r=0.24, eta2=0.06)
    assert "*d*" in text and "*r*" in text and "*η*²" in text


def test_format_apa_effect_size_empty():
    text = format_apa_effect_size()
    assert "未指定" in text or len(text) > 0


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
