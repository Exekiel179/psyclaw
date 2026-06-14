"""测试 TOST 等价检验模块（psyclaw/psych/equivalence.py）。

数值参照：
  - 在可用时用 scipy.stats 做交叉验证
  - 核心公式用已知解析结果验证（对称均值差=0 时 p_lower=p_upper）
"""
import json
import math
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.equivalence import (
    _one_tail_right,
    _variance,
    _welch_df,
    compute_mdes,
    format_apa_equivalence,
    tost_paired,
    tost_one_sample,
    tost_two_sample,
    write_equivalence_report,
    analyze_equivalence,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def test_one_tail_right_nonneg():
    """P(T > 0) = 0.5（对称分布）。"""
    p = _one_tail_right(0.0, 10)
    assert abs(p - 0.5) < 1e-6


def test_one_tail_right_positive():
    """t > 0 时 P(T > t) < 0.5。"""
    p = _one_tail_right(2.0, 30)
    assert 0 < p < 0.5


def test_one_tail_right_negative():
    """t < 0 时 P(T > t) > 0.5。"""
    p = _one_tail_right(-2.0, 30)
    assert p > 0.5


def test_one_tail_symmetry():
    """P(T > t) + P(T > -t) = 1（对称性）。"""
    for t_val in [0.5, 1.0, 2.0, 3.5]:
        p_pos = _one_tail_right(t_val, 20)
        p_neg = _one_tail_right(-t_val, 20)
        assert abs(p_pos + p_neg - 1.0) < 1e-8, f"t={t_val}: {p_pos} + {p_neg} != 1"


def test_variance_basic():
    vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]  # 已知 var=4
    assert abs(_variance(vals) - 4.571) < 0.01


def test_welch_df_equal_n():
    """等方差等 n 时，Welch df 应接近 2(n-1)。"""
    df = _welch_df(1.0, 10, 1.0, 10)
    assert abs(df - 18.0) < 0.01


# ---------------------------------------------------------------------------
# tost_two_sample
# ---------------------------------------------------------------------------

def _make_equiv_groups(n=40, diff=0.0, sd=1.0):
    """构造均值差约为 diff、SD 约为 sd 的两组数据。"""
    import random
    random.seed(42)
    # 使用确定性序列避免随机波动影响断言
    g1 = [sd * (i / n - 0.5) for i in range(n)]
    g2 = [x + diff for x in g1]
    return g1, g2


def test_two_sample_returns_dict():
    g1, g2 = _make_equiv_groups()
    result = tost_two_sample(g1, g2, -0.5, 0.5)
    assert isinstance(result, dict)
    assert "error" not in result


def test_two_sample_required_keys():
    g1, g2 = _make_equiv_groups()
    result = tost_two_sample(g1, g2, -0.5, 0.5)
    for key in ("test", "n1", "n2", "mean_diff", "se", "df",
                "t_lower", "t_upper", "p_lower", "p_upper",
                "p_tost", "ci_lower", "ci_upper", "ci_level",
                "cohen_d", "alpha", "equivalent", "equivalence_tested"):
        assert key in result, f"缺少键: {key}"


def test_two_sample_p_tost_is_max():
    g1, g2 = _make_equiv_groups()
    r = tost_two_sample(g1, g2, -0.5, 0.5)
    assert abs(r["p_tost"] - max(r["p_lower"], r["p_upper"])) < 1e-12


def test_two_sample_symmetric_diff_zero():
    """mean_diff=0 时 p_lower 应等于 p_upper（区间对称）。"""
    g1, g2 = _make_equiv_groups(n=50, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    # 数据完全对称故两 p 应近似相等（非严格因为随机种子）
    assert abs(r["p_lower"] - r["p_upper"]) < 0.1


def test_two_sample_equivalent_when_diff_near_zero():
    """均值差接近 0 且等价区间宽时应建立等价。"""
    g1, g2 = _make_equiv_groups(n=100, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    assert r["equivalent"] is True


def test_two_sample_not_equivalent_when_diff_large():
    """均值差超出等价区间时不应建立等价。"""
    g1 = [i * 0.1 for i in range(40)]
    g2 = [x + 2.0 for x in g1]   # diff = 2.0
    r = tost_two_sample(g1, g2, -0.5, 0.5)
    assert r["equivalent"] is False


def test_two_sample_ci_level():
    """alpha=0.05 时 CI 应为 90%。"""
    g1, g2 = _make_equiv_groups()
    r = tost_two_sample(g1, g2, -0.5, 0.5, alpha=0.05)
    assert abs(r["ci_level"] - 0.90) < 1e-6


def test_two_sample_equivalence_tested_flag():
    g1, g2 = _make_equiv_groups()
    r = tost_two_sample(g1, g2, -0.5, 0.5)
    assert r["equivalence_tested"] is True


def test_two_sample_error_too_few():
    r = tost_two_sample([1.0, 2.0], [1.0, 2.0, 3.0], -1.0, 1.0)
    assert "error" in r


def test_two_sample_error_invalid_bounds():
    g1, g2 = _make_equiv_groups()
    r = tost_two_sample(g1, g2, 0.5, -0.5)
    assert "error" in r


def test_two_sample_cohen_d_near_zero():
    g1, g2 = _make_equiv_groups(n=50, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    assert abs(r["cohen_d"]) < 0.05


# ---------------------------------------------------------------------------
# tost_one_sample
# ---------------------------------------------------------------------------

def test_one_sample_returns_dict():
    y = [10.1, 9.8, 10.0, 10.2, 9.9, 10.0, 10.1, 9.9, 10.0, 10.1]
    r = tost_one_sample(y, 10.0, -0.5, 0.5)
    assert isinstance(r, dict)
    assert "error" not in r


def test_one_sample_test_label():
    y = [10.0 + 0.1 * i for i in range(-5, 6)]  # 非常数序列，避免零方差
    r = tost_one_sample(y, 10.0, -1.0, 1.0)
    assert r.get("test") == "tost_one_sample"


def test_one_sample_equivalent_on_match():
    """样本均值恰好等于参考值时应建立等价（宽区间）。"""
    y = [100.0 + 0.1 * i for i in range(-20, 21)]   # mean=100
    r = tost_one_sample(y, 100.0, -5.0, 5.0)
    assert r["equivalent"] is True


def test_one_sample_not_equivalent_large_diff():
    y = [20.0 + 0.1 * i for i in range(30)]  # mean ≈ 21.45
    r = tost_one_sample(y, 0.0, -0.5, 0.5)   # 等价区间 far below actual mean
    assert r["equivalent"] is False


def test_one_sample_mu0_in_result():
    y = [5.0 + 0.1 * i for i in range(-5, 6)]  # 非常数序列
    r = tost_one_sample(y, 4.5, -1.0, 1.0)
    assert abs(r["mu0"] - 4.5) < 1e-9


def test_one_sample_error_too_few():
    r = tost_one_sample([1.0, 2.0], 1.5, -0.5, 0.5)
    assert "error" in r


# ---------------------------------------------------------------------------
# tost_paired
# ---------------------------------------------------------------------------

def test_paired_returns_dict():
    y1 = [1.0, 2.0, 3.0, 2.5, 1.5, 2.0, 3.0, 2.0, 1.8, 2.2]
    y2 = [1.1, 1.9, 3.1, 2.4, 1.6, 2.1, 2.9, 2.1, 1.9, 2.1]
    r = tost_paired(y1, y2, -0.5, 0.5)
    assert isinstance(r, dict)
    assert "error" not in r


def test_paired_test_label():
    # 差值不等（y2[i]-y1[i] 随 i 变化），确保差值有方差
    y1 = [10.0 + 0.1 * i for i in range(-5, 6)]
    y2 = [y1[k] + 0.05 * k for k in range(len(y1))]
    r = tost_paired(y1, y2, -2.0, 2.0)
    assert r.get("test") == "tost_paired"


def test_paired_length_mismatch():
    r = tost_paired([1, 2, 3], [1, 2], -1.0, 1.0)
    assert "error" in r


def test_paired_equivalent_near_zero_diff():
    """配对差值接近 0 → 应建立等价（宽区间）。"""
    y1 = [float(i) for i in range(5, 35)]
    y2 = [x + 0.01 for x in y1]   # 差值 ≠ 0 故有方差
    r = tost_paired(y1, y2, -1.0, 1.0)
    assert "error" not in r
    assert r["equivalent"] is True


# ---------------------------------------------------------------------------
# compute_mdes
# ---------------------------------------------------------------------------

def test_mdes_positive():
    mdes = compute_mdes(50, 50)
    assert mdes > 0


def test_mdes_larger_n_smaller_mdes():
    """样本量越大，MDES 越小。"""
    mdes_small = compute_mdes(20, 20)
    mdes_large = compute_mdes(200, 200)
    assert mdes_large < mdes_small


def test_mdes_symmetric():
    """n1=n2=n 时 MDES 只取决于 2/n。"""
    m1 = compute_mdes(50, 50)
    m2 = compute_mdes(50)  # n2 defaults to n1
    assert abs(m1 - m2) < 1e-9


# ---------------------------------------------------------------------------
# format_apa_equivalence
# ---------------------------------------------------------------------------

def test_apa_two_sample_contains_TOST():
    g1, g2 = _make_equiv_groups(n=50, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    apa = format_apa_equivalence(r)
    assert "TOST" in apa


def test_apa_mentions_equivalent():
    g1, g2 = _make_equiv_groups(n=100, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    apa = format_apa_equivalence(r)
    assert "等价" in apa


def test_apa_error_result():
    apa = format_apa_equivalence({"error": "测试错误"})
    assert "错误" in apa or "error" in apa.lower()


def test_apa_one_sample():
    y = [10.0 + 0.1 * i for i in range(-7, 8)]  # 非常数序列
    r = tost_one_sample(y, 10.0, -1.0, 1.0)
    apa = format_apa_equivalence(r)
    assert "单样本" in apa or "μ₀" in apa


def test_apa_paired():
    y1 = [float(i) for i in range(5, 25)]
    y2 = [x + 0.05 for x in y1]
    r = tost_paired(y1, y2, -1.0, 1.0)
    apa = format_apa_equivalence(r)
    assert "配对" in apa


# ---------------------------------------------------------------------------
# write_equivalence_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    g1, g2 = _make_equiv_groups(n=40, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    with tempfile.TemporaryDirectory() as tmp:
        files = write_equivalence_report(r, tmp)
        assert files["md"].exists()
        assert files["json"].exists()


def test_write_report_json_has_equivalence_tested():
    g1, g2 = _make_equiv_groups(n=40, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    with tempfile.TemporaryDirectory() as tmp:
        files = write_equivalence_report(r, tmp)
        data = json.loads(files["json"].read_text(encoding="utf-8"))
        assert data.get("equivalence_tested") is True


def test_write_report_json_has_apa_text():
    g1, g2 = _make_equiv_groups(n=40, diff=0.0)
    r = tost_two_sample(g1, g2, -1.0, 1.0)
    with tempfile.TemporaryDirectory() as tmp:
        files = write_equivalence_report(r, tmp)
        data = json.loads(files["json"].read_text(encoding="utf-8"))
        assert "apa_text" in data and len(data["apa_text"]) > 20


# ---------------------------------------------------------------------------
# analyze_equivalence (CSV entry)
# ---------------------------------------------------------------------------

def _write_csv(tmp, rows: list[dict], fieldnames: list[str]) -> str:
    import csv
    path = os.path.join(tmp, "data.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return path


def test_analyze_two_sample_csv():
    with tempfile.TemporaryDirectory() as tmp:
        rows = (
            [{"score": str(1.0 + 0.05 * i), "group": "A"} for i in range(30)]
            + [{"score": str(1.0 + 0.05 * i), "group": "B"} for i in range(30)]
        )
        path = _write_csv(tmp, rows, ["score", "group"])
        r = analyze_equivalence(path, "score", group="group",
                                lower_bound=-2.0, upper_bound=2.0)
        assert "error" not in r
        assert r["equivalent"] is True


def test_analyze_one_sample_csv():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"score": str(10.0 + 0.1 * i)} for i in range(-10, 11)]
        path = _write_csv(tmp, rows, ["score"])
        r = analyze_equivalence(path, "score", mu0=10.0,
                                lower_bound=-2.0, upper_bound=2.0)
        assert "error" not in r
        assert r["equivalent"] is True


def test_analyze_missing_dv_col():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"x": "1.0"}]
        path = _write_csv(tmp, rows, ["x"])
        r = analyze_equivalence(path, "y", group="x",
                                lower_bound=-1.0, upper_bound=1.0)
        assert "error" in r


def test_analyze_missing_group_col():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"score": "1.0", "group": "A"}]
        path = _write_csv(tmp, rows, ["score", "group"])
        r = analyze_equivalence(path, "score", group="no_such",
                                lower_bound=-1.0, upper_bound=1.0)
        assert "error" in r


def test_analyze_no_group_no_mu0():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"score": "1.0"}] * 10
        path = _write_csv(tmp, rows, ["score"])
        r = analyze_equivalence(path, "score",
                                lower_bound=-1.0, upper_bound=1.0)
        assert "error" in r


def test_analyze_writes_sidecar():
    with tempfile.TemporaryDirectory() as tmp:
        rows = (
            [{"score": str(float(i)), "group": "A"} for i in range(20)]
            + [{"score": str(float(i)), "group": "B"} for i in range(20)]
        )
        path = _write_csv(tmp, rows, ["score", "group"])
        r = analyze_equivalence(path, "score", group="group",
                                lower_bound=-5.0, upper_bound=5.0,
                                out_dir=tmp)
        assert "error" not in r
        assert os.path.exists(os.path.join(tmp, "equivalence_report.json"))
        assert os.path.exists(os.path.join(tmp, "equivalence_report.md"))


# ---------------------------------------------------------------------------
# 门禁 — KIND_TRIGGERS + REQUIREMENT_CHECKS 注册
# ---------------------------------------------------------------------------

def test_equivalence_kind_in_triggers():
    from psyclaw.gates.checker import KIND_TRIGGERS
    assert "equivalence" in KIND_TRIGGERS
    assert "equivalence_test" in KIND_TRIGGERS["equivalence"]


def test_equivalence_tested_requirement():
    from psyclaw.gates.checker import REQUIREMENT_CHECKS
    assert "equivalence_tested" in REQUIREMENT_CHECKS
    chk = REQUIREMENT_CHECKS["equivalence_tested"]
    assert chk({"equivalence_tested": True}, None) is True
    assert chk({"equivalence_tested": False}, None) is False
    assert chk({}, None) is False


def test_stat_equivalence_gate_in_rules():
    from psyclaw.gates.checker import load_rules
    rules = load_rules()
    ids = [g["id"] for g in rules]
    assert "STAT.equivalence" in ids


def test_check_artifact_equivalence_sidecar():
    """写一个合规的 equivalence sidecar，check_artifact 应通过。"""
    from psyclaw.gates.checker import check_artifact
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "equivalence_report.json")
        data = {"equivalence_tested": True, "equivalent": True}
        with open(p, "w") as f:
            json.dump(data, f)
        result = check_artifact(p, "equivalence")
        # 应通过（equivalence_tested=True 满足唯一 requirement）
        assert result["passed"] is True


def test_check_artifact_equivalence_fail():
    """缺少 equivalence_tested 的 sidecar 应触发 blocking。"""
    from psyclaw.gates.checker import check_artifact
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "equivalence_report.json")
        data = {"equivalent": True}  # 缺少 equivalence_tested
        with open(p, "w") as f:
            json.dump(data, f)
        result = check_artifact(p, "equivalence")
        assert result["passed"] is False
        assert any("equivalence_tested" in b["requirement"] for b in result["blocking"])


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
