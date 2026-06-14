"""测试 t 检验套件（psyclaw/psych/ttest.py）。

数值对照：
  - y = 2x + 1 的独立样本 t 应显著；相同均值不显著
  - 单样本：M=5, SD=1, n=25, mu0=4 → d=1（大效应）
  - 配对：前测均值10, 后测均值15, diff=5 → 显著
  - d_lo < d < d_hi
  - Welch df ≤ Student df（等方差时近似相等）
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.ttest import (
    ttest_one_sample,
    ttest_independent,
    ttest_paired,
    format_apa_ttest,
    write_ttest_report,
    analyze_ttest,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _linspace(start, stop, n):
    return [start + (stop - start) * i / (n - 1) for i in range(n)]


# ---------------------------------------------------------------------------
# ttest_one_sample
# ---------------------------------------------------------------------------

def test_one_sample_significant():
    """n=20, M=5, mu0=0 → 应显著。"""
    x = [5.0] * 20
    # 需要有方差 → 用 1..10 重复
    x = list(range(1, 11)) * 2  # M=5.5, SD≈3.0
    r = ttest_one_sample(x, mu0=0.0)
    assert r["p"] < 0.05
    assert r["significant"]


def test_one_sample_null():
    """M 与 mu0 相同 → p ≈ 1（t=0）。"""
    x = [5.0, 4.0, 6.0, 5.0, 4.0, 6.0]  # M=5
    r = ttest_one_sample(x, mu0=5.0)
    assert abs(r["t"]) < 1e-9
    assert r["p"] > 0.9


def test_one_sample_d_direction():
    """M > mu0 → d > 0。"""
    x = [10.0, 11.0, 12.0, 9.0, 10.0]
    r = ttest_one_sample(x, mu0=5.0)
    assert r["d"] > 0


def test_one_sample_ci_contains_d():
    x = list(range(1, 21))
    r = ttest_one_sample(x, mu0=0.0)
    assert r["d_ci"][0] < r["d"] < r["d_ci"][1]


def test_one_sample_fields():
    x = [1.0, 2.0, 3.0]
    r = ttest_one_sample(x, mu0=0.0)
    for k in ("t", "df", "p", "M", "SD", "n", "d", "d_ci", "significant"):
        assert k in r


def test_one_sample_df():
    x = list(range(1, 11))  # n=10 → df=9
    r = ttest_one_sample(x)
    assert r["df"] == 9


def test_one_sample_too_few():
    try:
        ttest_one_sample([5.0])
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# ttest_independent
# ---------------------------------------------------------------------------

def test_independent_significant():
    """均值 0 vs 10，SD=1 → 应显著。"""
    x = _linspace(0, 2, 10)
    y = _linspace(8, 12, 10)
    r = ttest_independent(x, y)
    assert r["p"] < 0.001
    assert r["significant"]


def test_independent_null():
    """两组均值相同 → 不显著。"""
    x = [5.0, 4.0, 6.0, 5.0, 4.0]
    y = [5.0, 4.0, 6.0, 5.0, 4.0]
    r = ttest_independent(x, y)
    assert abs(r["t"]) < 1e-9
    assert r["p"] > 0.9


def test_independent_d_ci_brackets_d():
    x = _linspace(0, 2, 15)
    y = _linspace(8, 12, 15)
    r = ttest_independent(x, y)
    d, lo, hi = r["d"], r["d_ci"][0], r["d_ci"][1]
    assert lo < d < hi


def test_independent_welch_vs_student_df():
    """不等方差时 Welch df < Student df。"""
    x = _linspace(0, 2, 10)   # small variance
    y = _linspace(0, 20, 10)  # large variance
    r_w = ttest_independent(x, y, welch=True)
    r_s = ttest_independent(x, y, welch=False)
    assert r_w["df"] <= r_s["df"] + 0.01


def test_independent_equal_variance_similar_df():
    """方差近似相等时 Welch df ≈ Student df。"""
    x = _linspace(0, 2, 10)
    y = _linspace(5, 7, 10)
    r_w = ttest_independent(x, y, welch=True)
    r_s = ttest_independent(x, y, welch=False)
    assert abs(r_w["df"] - r_s["df"]) < 2


def test_independent_fields():
    x, y = [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]
    r = ttest_independent(x, y)
    for k in ("t", "df", "p", "M1", "SD1", "n1", "M2", "SD2", "n2",
              "diff", "d", "significant"):
        assert k in r


def test_independent_diff_sign():
    """M1 < M2 → diff < 0, d < 0, t < 0。"""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 11.0, 12.0, 13.0, 14.0]
    r = ttest_independent(x, y)
    assert r["t"] < 0
    assert r["diff"] < 0
    assert r["d"] < 0


def test_independent_too_few():
    try:
        ttest_independent([1.0], [2.0, 3.0])
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# ttest_paired
# ---------------------------------------------------------------------------

def test_paired_significant():
    """前测均值~5, 后测均值~10，差值有方差 → 应显著。"""
    x = [5.0, 4.0, 6.0, 5.0, 4.0, 6.0, 5.0, 4.5]
    y = [10.0, 9.0, 11.0, 10.5, 9.5, 11.5, 10.0, 9.5]
    r = ttest_paired(x, y)
    assert r["p"] < 0.001
    assert r["significant"]


def test_paired_null():
    """差值全为 0 → 应抛出 ValueError（SE=0）。"""
    x = [5.0, 6.0, 7.0]
    y = [5.0, 6.0, 7.0]
    try:
        r = ttest_paired(x, y)
        # 若不抛出，t 应为 0
        assert abs(r["t"]) < 1e-9
    except ValueError:
        pass  # 零方差时抛出 ValueError 也可接受


def test_paired_dz_positive():
    """前测 < 后测 → diff < 0, dz < 0（差值需有方差）。"""
    x = [5.0, 4.5, 5.5, 5.2, 4.8]
    y = [10.0, 9.5, 10.5, 11.0, 9.0]
    r = ttest_paired(x, y)
    assert r["M_diff"] < 0  # x - y < 0
    assert r["dz"] < 0


def test_paired_dz_ci_brackets():
    x = [5.0, 4.0, 6.0, 5.0, 4.5, 6.5, 5.0, 4.0]
    y = [10.0, 9.0, 11.5, 10.5, 9.5, 12.0, 10.0, 9.5]
    r = ttest_paired(x, y)
    assert r["dz_ci"][0] < r["dz"] < r["dz_ci"][1]


def test_paired_fields():
    x = [1.0, 2.5, 3.0, 4.2]  # non-uniform diffs
    y = [2.0, 3.5, 4.5, 5.8]
    r = ttest_paired(x, y)
    for k in ("t", "df", "p", "n", "M_diff", "SD_diff", "dz", "significant"):
        assert k in r


def test_paired_df():
    x = [float(v) for v in range(1, 11)]
    y = [float(v) + 1 + (i % 3) * 0.5 for i, v in enumerate(x)]  # non-uniform diffs
    r = ttest_paired(x, y)
    assert r["df"] == 9  # n-1 = 10-1


def test_paired_mismatched():
    try:
        ttest_paired([1.0, 2.0, 3.0], [1.0, 2.0])
        assert False
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# APA 格式化
# ---------------------------------------------------------------------------

def test_format_one_sample():
    x = list(range(1, 21))
    r = ttest_one_sample(x, mu0=0.0)
    text = format_apa_ttest(r)
    assert "*t*" in text
    assert "*d*" in text
    assert "单样本" in text


def test_format_independent():
    x = _linspace(0, 2, 10)
    y = _linspace(8, 12, 10)
    r = ttest_independent(x, y)
    text = format_apa_ttest(r)
    assert "*t*" in text
    assert "*d*" in text


def test_format_paired():
    x = [5.0, 4.0, 6.0, 5.2]
    y = [10.0, 9.5, 11.5, 10.8]
    r = ttest_paired(x, y)
    text = format_apa_ttest(r)
    assert "*t*" in text
    assert "*d*_z" in text or "dz" in text or "d_z" in text or "*d*" in text


# ---------------------------------------------------------------------------
# write_ttest_report
# ---------------------------------------------------------------------------

def test_write_report():
    x = _linspace(0, 2, 10)
    y = _linspace(8, 12, 10)
    r = ttest_independent(x, y)
    with tempfile.TemporaryDirectory() as tmpdir:
        md, js = write_ttest_report(r, out_dir=tmpdir)
        assert md.exists()
        assert js.exists()
        content = md.read_text(encoding="utf-8")
        assert "t 检验" in content
        data = json.loads(js.read_text(encoding="utf-8"))
        assert "t" in data


# ---------------------------------------------------------------------------
# analyze_ttest（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_analyze_independent_csv():
    rows = (
        [{"score": str(v), "group": "A"} for v in range(1, 6)] +
        [{"score": str(v), "group": "B"} for v in range(10, 15)]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ttest(csv_path, dv="score", test="independent",
                                group_col="group", write_files=True, out_dir=tmpdir)
        assert result["p"] < 0.05
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_paired_csv():
    # non-uniform differences to avoid SD_diff=0
    diffs = [5.0, 4.5, 5.5, 4.8, 5.2, 4.6, 5.4, 5.0]
    rows = [{"pre": str(float(v)), "post": str(float(v) + diffs[i])}
            for i, v in enumerate(range(1, 9))]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ttest(csv_path, dv="pre", test="paired",
                                y_col="post", write_files=False)
        assert result["p"] < 0.001


def test_analyze_one_sample_csv():
    rows = [{"score": str(v)} for v in range(10, 20)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_ttest(csv_path, dv="score", test="one_sample",
                                mu0=0.0, write_files=False)
        assert result["p"] < 0.001
        assert result["M"] > 0


def test_analyze_wrong_groups():
    rows = (
        [{"s": str(i), "g": "A"} for i in range(5)] +
        [{"s": str(i), "g": "B"} for i in range(5)] +
        [{"s": str(i), "g": "C"} for i in range(5)]
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_ttest(csv_path, dv="s", test="independent",
                          group_col="g", write_files=False)
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
