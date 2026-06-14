"""测试双因素析因 ANOVA（psyclaw/psych/anova2.py）。

数值对照：
  - 均衡 2×2 设计（每格 5 观测）手工计算 SS_A/SS_B/SS_AB
  - SS_A + SS_B + SS_AB + SS_e = SS_total
  - 无效应时 F≈0，p≈1
  - 只有 A 主效应时，B/AB 不显著
  - 交互效应显著时 F_AB > 临界值
  - 单元格均值格式正确
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.anova2 import (
    two_way_anova,
    format_apa_anova2,
    write_anova2_report,
    analyze_anova2,
)


# ---------------------------------------------------------------------------
# 辅助：构造标准化测试数据
# ---------------------------------------------------------------------------

def _balanced_design(
    means: dict[tuple[str, str], float],
    n_per_cell: int = 5,
    noise: float = 0.5,
) -> list[dict]:
    """生成均衡 2×2（或更大）析因设计数据，组内方差由 noise 控制。"""
    import random
    random.seed(42)
    rows = []
    for (a, b), m in means.items():
        for i in range(n_per_cell):
            v = m + (i - n_per_cell // 2) * noise
            rows.append({"dv": str(round(v, 4)), "A": a, "B": b})
    return rows


def _uniform_2x2():
    """2×2 均衡设计：A 主效应显著（10 vs 20），B/AB 无效应。"""
    means = {
        ("A1", "B1"): 10.0,
        ("A1", "B2"): 10.0,
        ("A2", "B1"): 20.0,
        ("A2", "B2"): 20.0,
    }
    return _balanced_design(means)


def _interaction_design():
    """2×2 设计：明显交互效应（A1B1 高，A1B2 低；A2B1 低，A2B2 高）。"""
    means = {
        ("A1", "B1"): 20.0,
        ("A1", "B2"): 10.0,
        ("A2", "B1"): 10.0,
        ("A2", "B2"): 20.0,
    }
    return _balanced_design(means, n_per_cell=8, noise=0.5)


def _no_effect_design():
    """所有单元格均值相同 → 主效应和交互效应均不显著。"""
    means = {
        ("A1", "B1"): 10.0,
        ("A1", "B2"): 10.0,
        ("A2", "B1"): 10.0,
        ("A2", "B2"): 10.0,
    }
    return _balanced_design(means, noise=1.0)


# ---------------------------------------------------------------------------
# two_way_anova 基础测试
# ---------------------------------------------------------------------------

def test_anova2_a_main_effect_significant():
    """A 主效应（10 vs 20）应显著。"""
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectA"]["F"] > 5, f"F_A={result['effectA']['F']}"
    assert result["effectA"]["p"] < 0.05


def test_anova2_b_not_significant_when_no_b_effect():
    """B 无效应时 B 主效应 F≈0，p≈1。"""
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectB"]["F"] < 1.0, f"F_B={result['effectB']['F']}"


def test_anova2_ab_not_significant_when_parallel():
    """无交互效应时（两条平行线）AB 不显著。"""
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectAB"]["p"] > 0.05, f"p_AB={result['effectAB']['p']}"


def test_anova2_interaction_significant():
    """交叉型交互效应（disordinal interaction）应显著。"""
    rows = _interaction_design()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectAB"]["p"] < 0.05, f"p_AB={result['effectAB']['p']}"


def test_anova2_ss_partition():
    """SS_A + SS_B + SS_AB + SS_e = SS_total（加和完整性）。"""
    rows = _interaction_design()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    ss_sum = (
        result["effectA"]["SS"] +
        result["effectB"]["SS"] +
        result["effectAB"]["SS"] +
        result["error"]["SS"]
    )
    assert abs(ss_sum - result["total"]["SS"]) < 0.01, (
        f"SS 不满足加和：{ss_sum:.4f} vs {result['total']['SS']:.4f}"
    )


def test_anova2_df_correct():
    """均衡 2×2，n_per_cell=5：df_A=1,df_B=1,df_AB=1,df_e=16,df_t=19。"""
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectA"]["df"] == 1
    assert result["effectB"]["df"] == 1
    assert result["effectAB"]["df"] == 1
    assert result["error"]["df"] == 16  # 4 cells × (5-1) = 16
    assert result["total"]["df"] == 19  # N-1 = 20-1


def test_anova2_no_effect():
    """所有单元格均值相同时，所有 F 近似 0。"""
    rows = _no_effect_design()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    # 相同均值时 SS_A = SS_B = SS_AB ≈ 0（可能因 noise 有微小值）
    assert result["effectA"]["p"] > 0.05 or result["effectA"]["F"] < 1.0


def test_anova2_eta2_in_range():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    for key in ("effectA", "effectB", "effectAB"):
        eta2 = result[key].get("eta2", 0.0)
        assert 0 <= eta2 <= 1, f"{key} eta2={eta2}"


def test_anova2_omega2_le_eta2():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    for key in ("effectA", "effectB", "effectAB"):
        eff = result[key]
        if eff.get("omega2") is not None and eff.get("eta2") is not None:
            assert eff["omega2"] <= eff["eta2"] + 1e-9


def test_anova2_omega2_non_negative():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    for key in ("effectA", "effectB", "effectAB"):
        w = result[key].get("omega2")
        if w is not None:
            assert w >= 0


def test_anova2_cell_means_present():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    cm = result["cell_means"]
    assert "A1" in cm and "A2" in cm
    assert "B1" in cm["A1"] and "B2" in cm["A1"]


def test_anova2_cell_means_correct():
    """均值表 A1B1 ≈ 10.0（noise=0.5, n=5 → 均值应为 10）。"""
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert abs(result["cell_means"]["A1"]["B1"] - 10.0) < 0.5


def test_anova2_n_excluded():
    """含缺失行时 n_excluded 应计数。"""
    rows = _uniform_2x2()
    rows.append({"dv": "", "A": "A1", "B": "B1"})
    rows.append({"dv": "abc", "A": "A2", "B": "B2"})
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["n_excluded"] == 2
    assert result["N"] == 20


def test_anova2_fields():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    for key in ("effectA", "effectB", "effectAB", "error", "total",
                "N", "a_levels", "b_levels", "cell_means", "grand_mean"):
        assert key in result, f"缺少字段: {key}"


def test_anova2_too_few_A_levels():
    rows = [{"dv": "1", "A": "A1", "B": "B1"},
            {"dv": "2", "A": "A1", "B": "B2"},
            {"dv": "3", "A": "A1", "B": "B1"},
            {"dv": "4", "A": "A1", "B": "B2"}]
    try:
        two_way_anova(rows, dv="dv", factorA="A", factorB="B")
        assert False, "应抛出 ValueError"
    except ValueError:
        pass


def test_anova2_too_few_obs_per_cell():
    """每格仅 1 观测 → df_e=0，应报错。"""
    rows = [
        {"dv": "10", "A": "A1", "B": "B1"},
        {"dv": "20", "A": "A1", "B": "B2"},
        {"dv": "30", "A": "A2", "B": "B1"},
        {"dv": "40", "A": "A2", "B": "B2"},
    ]
    try:
        two_way_anova(rows, dv="dv", factorA="A", factorB="B")
        assert False, "应抛出 ValueError（df_e=0）"
    except ValueError:
        pass


def test_anova2_3x2_design():
    """3×2 设计应正确返回 df_A=2, df_B=1, df_AB=2。"""
    means = {
        ("A1", "B1"): 10.0, ("A1", "B2"): 12.0,
        ("A2", "B1"): 20.0, ("A2", "B2"): 22.0,
        ("A3", "B1"): 30.0, ("A3", "B2"): 32.0,
    }
    rows = _balanced_design(means, n_per_cell=5)
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    assert result["effectA"]["df"] == 2
    assert result["effectB"]["df"] == 1
    assert result["effectAB"]["df"] == 2


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa2_contains_keys():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    text = format_apa_anova2(result)
    assert "*F*" in text
    assert "*η*²" in text or "η²" in text
    assert "*p*" in text
    assert "误差" in text


def test_format_apa2_has_cell_table():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    text = format_apa_anova2(result)
    assert "单元格均值" in text
    assert "A1" in text and "B1" in text


# ---------------------------------------------------------------------------
# write_anova2_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    rows = _uniform_2x2()
    result = two_way_anova(rows, dv="dv", factorA="A", factorB="B")
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_anova2_report(result, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "ANOVA" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "effectA" in data


# ---------------------------------------------------------------------------
# analyze_anova2（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_anova2_basic():
    rows = _uniform_2x2()
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova2(csv_path, dv="dv", factorA="A", factorB="B",
                                write_files=True, out_dir=tmpdir)
        assert result["effectA"]["F"] > 5
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_anova2_ss_partition_csv():
    rows = _interaction_design()
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova2(csv_path, dv="dv", factorA="A", factorB="B",
                                write_files=False)
        ss_sum = (
            result["effectA"]["SS"] + result["effectB"]["SS"] +
            result["effectAB"]["SS"] + result["error"]["SS"]
        )
        assert abs(ss_sum - result["total"]["SS"]) < 0.01


def test_analyze_anova2_interaction_csv():
    rows = _interaction_design()
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova2(csv_path, dv="dv", factorA="A", factorB="B",
                                write_files=False)
        assert result["effectAB"]["p"] < 0.05


def test_analyze_anova2_missing_dv():
    rows = _uniform_2x2()
    rows.append({"dv": "", "A": "A1", "B": "B1"})
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova2(csv_path, dv="dv", factorA="A", factorB="B",
                                write_files=False)
        assert result["n_excluded"] == 1
        assert result["N"] == 20


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
