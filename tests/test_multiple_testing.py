"""测试多重检验校正模块（psyclaw/psych/multiple_testing.py）。

数值对照：
  - Bonferroni：adjusted_p = min(p*m, 1)，阈值 = alpha/m
  - Holm：逐步 FWER 控制，比 Bonferroni 更有效（拒绝 ≥ Bonferroni）
  - BH FDR：k*alpha/m 规则，比 Holm 更有效（拒绝 ≥ Holm ≥ Bonferroni）
  - 已知例子（Benjamini & Hochberg 1995 论文 Table 1）
  - APA 段落含方法名和 m/n_rejected
  - CSV 主入口
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.multiple_testing import (
    bonferroni,
    holm,
    benjamini_hochberg,
    format_apa_corrections,
    write_corrections_report,
    analyze_corrections,
    _empty_result,
)


# ---------------------------------------------------------------------------
# Bonferroni
# ---------------------------------------------------------------------------

def test_bonferroni_basic():
    """p = [0.01, 0.04, 0.03], alpha=0.05 → threshold=0.05/3≈0.0167，仅 p[0]=0.01 显著。"""
    pvals = [0.01, 0.04, 0.03]
    result = bonferroni(pvals, alpha=0.05)
    rej = [t["reject_h0"] for t in result["tests"]]
    assert rej[0] is True   # 0.01 < 0.0167
    assert rej[1] is False  # 0.04 > 0.0167
    assert rej[2] is False  # 0.03 > 0.0167


def test_bonferroni_adjusted_p():
    """调整 p = min(orig_p * m, 1)。"""
    pvals = [0.01, 0.04, 0.2]
    result = bonferroni(pvals, alpha=0.05)
    m = 3
    for t, p in zip(result["tests"], pvals):
        expected = min(p * m, 1.0)
        assert abs(t["p_adj"] - expected) < 1e-9, f"{t['label']}: {t['p_adj']} != {expected}"


def test_bonferroni_all_significant():
    pvals = [0.001, 0.002, 0.003]
    result = bonferroni(pvals, alpha=0.05)
    assert result["n_rejected"] == 3


def test_bonferroni_none_significant():
    pvals = [0.5, 0.6, 0.7]
    result = bonferroni(pvals, alpha=0.05)
    assert result["n_rejected"] == 0


def test_bonferroni_adj_p_capped_at_1():
    """调整 p 不超过 1.0。"""
    pvals = [0.9, 0.8, 0.7]
    result = bonferroni(pvals, alpha=0.05)
    for t in result["tests"]:
        assert t["p_adj"] <= 1.0


def test_bonferroni_fields():
    result = bonferroni([0.01, 0.05], alpha=0.05)
    for key in ("method", "m", "alpha", "threshold", "n_rejected", "tests"):
        assert key in result


def test_bonferroni_threshold():
    result = bonferroni([0.01, 0.02, 0.03, 0.04], alpha=0.05)
    assert abs(result["threshold"] - 0.05 / 4) < 1e-9


def test_bonferroni_empty():
    result = bonferroni([])
    assert result["m"] == 0
    assert result["n_rejected"] == 0


def test_bonferroni_labels():
    pvals = [0.01, 0.5]
    labels = ["测验 A", "测验 B"]
    result = bonferroni(pvals, alpha=0.05, labels=labels)
    assert result["tests"][0]["label"] == "测验 A"
    assert result["tests"][1]["label"] == "测验 B"


# ---------------------------------------------------------------------------
# Holm
# ---------------------------------------------------------------------------

def test_holm_basic():
    """p = [0.01, 0.04, 0.03], alpha=0.05: 排序 [0.01,0.03,0.04]。
    k=1: 0.01 ≤ 0.05/3=0.0167 ✓
    k=2: 0.03 ≤ 0.05/2=0.025 ✗ → 停止
    """
    pvals = [0.01, 0.04, 0.03]
    result = holm(pvals, alpha=0.05)
    # 原索引 0: p=0.01 应显著
    tests = {t["label"]: t for t in result["tests"]}
    # 按默认标签
    assert result["tests"][0]["reject_h0"] is True
    assert result["n_rejected"] == 1


def test_holm_ge_bonferroni():
    """Holm 拒绝数 ≥ Bonferroni 拒绝数（更有效）。"""
    import random
    random.seed(42)
    pvals = [random.uniform(0, 0.1) for _ in range(10)]
    r_bon = bonferroni(pvals, alpha=0.05)["n_rejected"]
    r_holm = holm(pvals, alpha=0.05)["n_rejected"]
    assert r_holm >= r_bon


def test_holm_monotone_adj_p():
    """调整后 p 值应单调递增（在排序后）。"""
    pvals = [0.005, 0.02, 0.05, 0.1, 0.2]
    result = holm(pvals, alpha=0.05)
    # 按原 p 值排序后的调整 p
    orig_order = sorted(range(5), key=lambda i: pvals[i])
    adj_ordered = [result["tests"][i]["p_adj"] for i in orig_order]
    for i in range(len(adj_ordered) - 1):
        assert adj_ordered[i] <= adj_ordered[i + 1], f"非单调: {adj_ordered}"


def test_holm_all_null():
    """若所有 p > alpha，全不显著。"""
    pvals = [0.5, 0.4, 0.6]
    result = holm(pvals)
    assert result["n_rejected"] == 0


def test_holm_one_test():
    """m=1 时等价于单次检验（无校正）。"""
    result = holm([0.03], alpha=0.05)
    assert result["tests"][0]["reject_h0"] is True
    result2 = holm([0.06], alpha=0.05)
    assert result2["tests"][0]["reject_h0"] is False


def test_holm_empty():
    result = holm([])
    assert result["m"] == 0


def test_holm_fields():
    result = holm([0.01, 0.05], alpha=0.05)
    for key in ("method", "m", "alpha", "n_rejected", "tests"):
        assert key in result
    for t in result["tests"]:
        for k in ("label", "p_orig", "p_adj", "reject_h0"):
            assert k in t


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------

_BH_1995_PVALS = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201,
                  0.0278, 0.0298, 0.0344, 0.0459, 0.3240,
                  0.4262, 0.5719, 0.6528, 0.7590, 0.7628]


def test_bh_1995_paper_example():
    """Benjamini & Hochberg (1995) Table 1 示例：m=15, alpha=0.05 → 拒绝前 4 个（k=4）。"""
    result = benjamini_hochberg(_BH_1995_PVALS, alpha=0.05)
    # 按排序后 k=4: p_(4)=0.0095 ≤ 4*0.05/15=0.0133 ✓; p_(5)=0.0201 ≤ 5/15*0.05=0.0167 ✗
    assert result["n_rejected"] == 4, f"预期拒绝 4，实际 {result['n_rejected']}"


def test_bh_ge_holm():
    """BH FDR 拒绝数 ≥ Holm（更有效）。"""
    import random
    random.seed(99)
    pvals = [random.uniform(0, 0.1) for _ in range(20)]
    r_holm = holm(pvals, alpha=0.05)["n_rejected"]
    r_bh = benjamini_hochberg(pvals, alpha=0.05)["n_rejected"]
    assert r_bh >= r_holm


def test_bh_adj_p_monotone():
    """BH 调整 p 值单调递增（排序后）。"""
    pvals = sorted([0.001, 0.006, 0.012, 0.046, 0.2, 0.4])
    result = benjamini_hochberg(pvals, alpha=0.05)
    adj = [result["tests"][i]["p_adj"] for i in range(len(pvals))]
    for i in range(len(adj) - 1):
        assert adj[i] <= adj[i + 1], f"非单调: {adj}"


def test_bh_all_tiny():
    """所有 p 极小时全部显著。"""
    pvals = [1e-10] * 5
    result = benjamini_hochberg(pvals, alpha=0.05)
    assert result["n_rejected"] == 5


def test_bh_all_large():
    """所有 p 极大时全不显著。"""
    pvals = [0.9, 0.8, 0.7]
    result = benjamini_hochberg(pvals, alpha=0.05)
    assert result["n_rejected"] == 0


def test_bh_empty():
    result = benjamini_hochberg([])
    assert result["m"] == 0


def test_bh_fields():
    result = benjamini_hochberg([0.01, 0.05], alpha=0.05)
    for key in ("method", "m", "alpha", "n_rejected", "tests"):
        assert key in result


def test_bh_adj_p_le_1():
    """调整 p 不超过 1.0。"""
    pvals = [0.9, 0.95, 0.99]
    result = benjamini_hochberg(pvals, alpha=0.05)
    for t in result["tests"]:
        assert t["p_adj"] <= 1.0


def test_bh_single_p():
    """m=1 时等价于单次检验。"""
    result = benjamini_hochberg([0.03], alpha=0.05)
    assert result["tests"][0]["reject_h0"] is True
    result2 = benjamini_hochberg([0.06], alpha=0.05)
    assert result2["tests"][0]["reject_h0"] is False


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_apa_bonferroni():
    result = bonferroni([0.01, 0.04, 0.03])
    text = format_apa_corrections(result)
    assert "Bonferroni" in text
    assert "3" in text  # m=3


def test_format_apa_holm():
    result = holm([0.01, 0.04, 0.03])
    text = format_apa_corrections(result)
    assert "Holm" in text


def test_format_apa_bh():
    result = benjamini_hochberg([0.01, 0.04, 0.03])
    text = format_apa_corrections(result)
    assert "Benjamini" in text or "BH" in text or "FDR" in text


def test_format_apa_table_present():
    result = bonferroni([0.01, 0.04])
    text = format_apa_corrections(result)
    # Markdown 表格
    assert "|" in text


def test_format_apa_n_rejected():
    result = bonferroni([0.001, 0.5])
    text = format_apa_corrections(result)
    assert "1" in text  # 1 项显著


# ---------------------------------------------------------------------------
# write_corrections_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    result = benjamini_hochberg([0.01, 0.05, 0.2])
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_corrections_report(result, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "Benjamini" in content or "BH" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "n_rejected" in data


# ---------------------------------------------------------------------------
# analyze_corrections（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_corrections_basic():
    rows = [{"label": "A", "p": "0.001"},
            {"label": "B", "p": "0.04"},
            {"label": "C", "p": "0.3"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "pvals.csv")
        _make_csv(rows, csv_path)
        result = analyze_corrections(csv_path, p_col="p", label_col="label",
                                     method="bh", write_files=False)
        assert result["m"] == 3
        assert result["method"] == "benjamini_hochberg"


def test_analyze_corrections_write_files():
    rows = [{"p": "0.01"}, {"p": "0.05"}, {"p": "0.2"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_corrections(csv_path, p_col="p",
                                     method="bonferroni", out_dir=tmpdir)
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_corrections_invalid_col():
    rows = [{"x": "0.01"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_corrections(csv_path, p_col="p", write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_corrections_all_methods():
    rows = [{"p": str(v)} for v in [0.001, 0.01, 0.05, 0.2, 0.5]]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        for method in ["bonferroni", "holm", "benjamini_hochberg"]:
            result = analyze_corrections(csv_path, p_col="p",
                                         method=method, write_files=False)
            assert result["method"] in ("bonferroni", "holm", "benjamini_hochberg")


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
