"""测试单因素 ANOVA 模块（psyclaw/psych/anova.py）。

数值对照：
  - 已知 F：3 组均匀间隔数据的 F 统计量手工验算
  - eta² = SS_b / SS_t，omega² ≤ eta²
  - 组间均值相同时 F=0，p=1
  - 组完全分离时 F→∞，eta²→1
  - 事后检验：显著对比含预期符号差异
  - CSV 主入口：缺失行过滤、多组
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.anova import (
    one_way_anova,
    post_hoc_pairwise,
    format_apa_anova,
    format_apa_post_hoc,
    write_anova_report,
    analyze_anova,
)


# ---------------------------------------------------------------------------
# one_way_anova
# ---------------------------------------------------------------------------

def _uniform_groups():
    """3 组：[1,2,3,4,5], [6,7,8,9,10], [11,12,13,14,15]。"""
    return {
        "A": [1.0, 2.0, 3.0, 4.0, 5.0],
        "B": [6.0, 7.0, 8.0, 9.0, 10.0],
        "C": [11.0, 12.0, 13.0, 14.0, 15.0],
    }


def test_anova_f_significant():
    """3 组均值分别 3、8、13：组间方差远大于组内，F 应很大。"""
    result = one_way_anova(_uniform_groups())
    assert result["F"] >= 50, f"F={result['F']}"
    assert result["p"] < 0.001, f"p={result['p']}"


def test_anova_null_f_zero():
    """所有组均值相同时 F=0。"""
    groups = {"A": [5.0, 5.0, 5.0], "B": [5.0, 5.0, 5.0], "C": [5.0, 5.0, 5.0]}
    result = one_way_anova(groups)
    assert result["F"] == 0.0 or result["F"] < 1e-10
    assert result["eta2"] == 0.0 or result["eta2"] < 1e-10


def test_anova_eta2_in_range():
    result = one_way_anova(_uniform_groups())
    assert 0 <= result["eta2"] <= 1


def test_anova_omega2_le_eta2():
    result = one_way_anova(_uniform_groups())
    assert result["omega2"] <= result["eta2"]


def test_anova_omega2_non_negative():
    """omega² 应 ≥ 0（clamp 防止计算得负值）。"""
    groups = {"A": [1.0, 2.0, 3.0], "B": [1.5, 2.0, 2.5]}  # 小效应
    result = one_way_anova(groups)
    assert result["omega2"] >= 0


def test_anova_ss_consistency():
    """SS_total = SS_between + SS_within。"""
    result = one_way_anova(_uniform_groups())
    assert abs(result["SS_between"] + result["SS_within"] - result["SS_total"]) < 1e-6


def test_anova_df_correct():
    """df_between = k-1 = 2, df_within = N-k = 12（3组5人）。"""
    result = one_way_anova(_uniform_groups())
    assert result["df_between"] == 2
    assert result["df_within"] == 12


def test_anova_grand_mean():
    """全体均值 = 8（1..15 的均值）。"""
    result = one_way_anova(_uniform_groups())
    assert abs(result["grand_mean"] - 8.0) < 0.01


def test_anova_group_stats():
    result = one_way_anova(_uniform_groups())
    assert len(result["group_stats"]) == 3
    for g in result["group_stats"]:
        for k in ("name", "n", "mean", "sd"):
            assert k in g
    names = [g["name"] for g in result["group_stats"]]
    assert set(names) == {"A", "B", "C"}


def test_anova_group_means_correct():
    result = one_way_anova(_uniform_groups())
    means = {g["name"]: g["mean"] for g in result["group_stats"]}
    assert abs(means["A"] - 3.0) < 0.01
    assert abs(means["B"] - 8.0) < 0.01
    assert abs(means["C"] - 13.0) < 0.01


def test_anova_perfect_separation():
    """各组完全不重叠，组内方差=0 → F=inf, eta²≈1。"""
    groups = {"A": [1.0, 1.0, 1.0], "B": [10.0, 10.0, 10.0]}
    result = one_way_anova(groups)
    assert not math.isfinite(result["F"]) or result["F"] > 1e6
    assert result["eta2"] > 0.99


def test_anova_too_few_groups():
    try:
        one_way_anova({"A": [1.0, 2.0, 3.0]})
        assert False
    except ValueError:
        pass


def test_anova_too_few_obs():
    try:
        one_way_anova({"A": [1.0], "B": [2.0]})
        assert False
    except ValueError:
        pass


def test_anova_fields():
    result = one_way_anova(_uniform_groups())
    for key in ("F", "df_between", "df_within", "p", "eta2", "omega2",
                "SS_between", "SS_within", "SS_total", "N", "k", "grand_mean",
                "group_stats"):
        assert key in result, f"缺少字段: {key}"


def test_anova_n_correct():
    result = one_way_anova(_uniform_groups())
    assert result["N"] == 15
    assert result["k"] == 3


# ---------------------------------------------------------------------------
# post_hoc_pairwise
# ---------------------------------------------------------------------------

def test_post_hoc_comparisons_count():
    """k=3 → C(3,2)=3 对比。"""
    ph = post_hoc_pairwise(_uniform_groups())
    assert len(ph["comparisons"]) == 3


def test_post_hoc_all_significant():
    """均值 3、8、13 差异极大，所有对比应显著。"""
    ph = post_hoc_pairwise(_uniform_groups())
    assert ph["n_significant"] == 3


def test_post_hoc_null_not_significant():
    """同均值组，无显著对比。"""
    groups = {"A": [5.0, 5.0, 5.0], "B": [5.0, 5.0, 5.0], "C": [5.0, 5.0, 5.0]}
    ph = post_hoc_pairwise(groups)
    assert ph["n_significant"] == 0


def test_post_hoc_diff_sign():
    """A 均值 > B 均值 → diff > 0。"""
    groups = {"A": [8.0, 9.0, 10.0], "B": [2.0, 3.0, 4.0]}
    ph = post_hoc_pairwise(groups)
    assert ph["comparisons"][0]["diff"] > 0


def test_post_hoc_cohen_d_present():
    ph = post_hoc_pairwise(_uniform_groups())
    for c in ph["comparisons"]:
        assert c["d"] is not None
        assert abs(c["d"]) > 0


def test_post_hoc_fields():
    ph = post_hoc_pairwise(_uniform_groups())
    for c in ph["comparisons"]:
        for k in ("group1", "group2", "diff", "t", "df", "p_orig", "p_adj", "reject_h0", "d"):
            assert k in c, f"缺少字段: {k}"


def test_post_hoc_method():
    ph = post_hoc_pairwise(_uniform_groups())
    assert ph["method"] == "holm"


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa_anova_contains_key():
    result = one_way_anova(_uniform_groups())
    text = format_apa_anova(result)
    assert "*F*" in text
    assert "*η*²" in text or "η²" in text
    assert "*ω*²" in text or "ω²" in text
    assert "p" in text


def test_format_apa_anova_table():
    result = one_way_anova(_uniform_groups())
    text = format_apa_anova(result)
    assert "|" in text
    assert "A" in text and "B" in text and "C" in text


def test_format_apa_post_hoc_table():
    ph = post_hoc_pairwise(_uniform_groups())
    text = format_apa_post_hoc(ph)
    assert "vs" in text
    assert "|" in text


# ---------------------------------------------------------------------------
# write_anova_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    result = one_way_anova(_uniform_groups())
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_anova_report(result, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "ANOVA" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "anova" in data


def test_write_report_with_post_hoc():
    result = one_way_anova(_uniform_groups())
    ph = post_hoc_pairwise(_uniform_groups())
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_anova_report(result, ph_result=ph, out_dir=tmpdir)
        content = md.read_text(encoding="utf-8")
        assert "事后" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "post_hoc" in data


# ---------------------------------------------------------------------------
# analyze_anova（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_anova_basic():
    rows = (
        [{"score": str(v), "group": "A"} for v in [1, 2, 3, 4, 5]] +
        [{"score": str(v), "group": "B"} for v in [6, 7, 8, 9, 10]] +
        [{"score": str(v), "group": "C"} for v in [11, 12, 13, 14, 15]]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova(csv_path, dv="score", group_col="group",
                               write_files=True, out_dir=tmpdir)
        assert result["anova"]["F"] >= 50
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_anova_missing_filter():
    rows = (
        [{"score": str(v), "group": "A"} for v in [1, 2, 3, 4, 5]] +
        [{"score": str(v), "group": "B"} for v in [6, 7, 8, 9, 10]] +
        [{"score": "", "group": "B"}]  # 缺失值
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova(csv_path, dv="score", group_col="group",
                               write_files=False)
        assert result["anova"]["n_excluded"] == 1
        assert result["anova"]["N"] == 10


def test_analyze_anova_with_post_hoc():
    rows = (
        [{"y": str(v), "g": "X"} for v in [1, 2, 3, 4, 5]] +
        [{"y": str(v), "g": "Y"} for v in [6, 7, 8, 9, 10]] +
        [{"y": str(v), "g": "Z"} for v in [11, 12, 13, 14, 15]]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_anova(csv_path, dv="y", group_col="g",
                               include_post_hoc=True, write_files=False)
        assert "post_hoc" in result
        assert result["post_hoc"]["n_significant"] == 3


def test_analyze_anova_too_few_groups():
    rows = [{"score": "1", "group": "A"}, {"score": "2", "group": "A"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_anova(csv_path, dv="score", group_col="group", write_files=False)
            assert False, "应抛出 ValueError"
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
