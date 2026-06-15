"""测试生存分析套件（psyclaw/psych/survival.py）。

数值对照（手算金标准，逐行复核；与 R survival::survfit / survdiff 同向）：
  - Kaplan-Meier 乘积极限：无删失 [6,7,10,15,19,25] → S=5/6,4/6,1/2,1/3,1/6,0，中位=10
  - Greenwood SE：首事件 SE = S·√(d/(n(n−d)))
  - Log-rank：A=[1,2,3] vs B=[4,5,6]（全事件）→ O_A=3, E_A=1.15, V_AA=0.6775,
    χ²=1.85²/0.6775≈5.0517, df=1, p≈0.0246
  - 同分布两组 → O=E → χ²=0, p=1
  - log-log CI 始终落在 [0,1]
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.survival import (
    kaplan_meier,
    logrank_test,
    format_apa_survival,
    write_survival_report,
    analyze_survival,
    survival_cli,
    _clean_survival,
    _chi2_sf,
    _norm_ppf,
    _matrix_inverse,
)


# ---------------------------------------------------------------------------
# 分布工具
# ---------------------------------------------------------------------------

def test_chi2_sf_critical_df1():
    # χ²=3.841, df=1 → p≈0.05
    assert abs(_chi2_sf(3.841, 1) - 0.05) < 1e-3


def test_chi2_sf_zero():
    assert _chi2_sf(0.0, 1) == 1.0


def test_chi2_sf_negative():
    assert _chi2_sf(-5.0, 1) == 1.0


def test_chi2_sf_df2_critical():
    # χ²=5.991, df=2 → p≈0.05
    assert abs(_chi2_sf(5.991, 2) - 0.05) < 1e-3


def test_chi2_sf_range():
    p = _chi2_sf(2.5, 3)
    assert 0.0 <= p <= 1.0


def test_norm_ppf_975():
    assert abs(_norm_ppf(0.975) - 1.959964) < 1e-4


def test_norm_ppf_median():
    assert abs(_norm_ppf(0.5)) < 1e-6


def test_norm_ppf_symmetry():
    assert abs(_norm_ppf(0.1) + _norm_ppf(0.9)) < 1e-4


def test_matrix_inverse_identity():
    inv = _matrix_inverse([[2.0, 0.0], [0.0, 4.0]])
    assert abs(inv[0][0] - 0.5) < 1e-9
    assert abs(inv[1][1] - 0.25) < 1e-9


def test_matrix_inverse_singular():
    with pytest.raises(ValueError):
        _matrix_inverse([[1.0, 1.0], [1.0, 1.0]])


# ---------------------------------------------------------------------------
# 输入清洗
# ---------------------------------------------------------------------------

def test_clean_length_mismatch():
    with pytest.raises(ValueError):
        _clean_survival([1, 2, 3], [1, 0])


def test_clean_empty():
    with pytest.raises(ValueError):
        _clean_survival([], [])


def test_clean_negative_time():
    with pytest.raises(ValueError):
        _clean_survival([1, -2], [1, 1])


def test_clean_bad_event():
    with pytest.raises(ValueError):
        _clean_survival([1, 2], [1, 2])


def test_clean_normalizes():
    t, e = _clean_survival([1.0, 2.0, 3.0], [1.0, 0.0, 1.0])
    assert t == [1.0, 2.0, 3.0]
    assert e == [1, 0, 1]


# ---------------------------------------------------------------------------
# Kaplan-Meier 乘积极限 — 手算金标准
# ---------------------------------------------------------------------------

def test_km_no_censoring_survival_curve():
    times = [6, 7, 10, 15, 19, 25]
    events = [1, 1, 1, 1, 1, 1]
    r = kaplan_meier(times, events)
    surv = [row["survival"] for row in r["timeline"]]
    expected = [5/6, 4/6, 0.5, 1/3, 1/6, 0.0]
    assert len(surv) == 6
    for got, exp in zip(surv, expected):
        assert abs(got - exp) < 1e-5


def test_km_no_censoring_median():
    r = kaplan_meier([6, 7, 10, 15, 19, 25], [1] * 6)
    assert r["median_survival"] == 10


def test_km_counts():
    r = kaplan_meier([1, 2, 3, 4, 5], [1, 0, 1, 0, 1])
    assert r["n"] == 5
    assert r["n_events"] == 3
    assert r["n_censored"] == 2


def test_km_with_censoring_curve():
    # times=[2,3,4,5,6], events=[1,1,0,1,1]
    # t=2:S=4/5=.8; t=3:.8*3/4=.6; t=5:.6*1/2=.3; t=6:0
    r = kaplan_meier([2, 3, 4, 5, 6], [1, 1, 0, 1, 1])
    surv = [row["survival"] for row in r["timeline"]]
    expected = [0.8, 0.6, 0.3, 0.0]
    for got, exp in zip(surv, expected):
        assert abs(got - exp) < 1e-6
    assert r["median_survival"] == 5


def test_km_censored_counted_in_risk_set():
    # 删失 t=4 在 t<4 时仍计入风险集
    r = kaplan_meier([2, 3, 4, 5, 6], [1, 1, 0, 1, 1])
    # t=3 处风险数应含尚未删失的 4 → n_risk=4 (3,4,5,6)
    row_t3 = [row for row in r["timeline"] if row["time"] == 3][0]
    assert row_t3["n_risk"] == 4
    # t=5 处删失的 4 已离开 → n_risk=2 (5,6)
    row_t5 = [row for row in r["timeline"] if row["time"] == 5][0]
    assert row_t5["n_risk"] == 2


def test_km_greenwood_se_first_event():
    # 首事件 t=6, n=6, d=1: SE = (5/6)·√(1/(6·5)) = 0.83333·0.182574
    r = kaplan_meier([6, 7, 10, 15, 19, 25], [1] * 6)
    se = r["timeline"][0]["se"]
    exp = (5/6) * math.sqrt(1 / (6 * 5))
    assert abs(se - exp) < 1e-5


def test_km_median_not_reached():
    # 重删失，S 始终 > 0.5
    r = kaplan_meier([1, 2, 3], [1, 0, 0])
    assert r["median_survival"] is None


def test_km_ci_within_bounds():
    r = kaplan_meier([1, 2, 3, 4, 5, 6, 7, 8], [1, 0, 1, 1, 0, 1, 1, 1])
    for row in r["timeline"]:
        assert 0.0 <= row["ci_lower"] <= 1.0
        assert 0.0 <= row["ci_upper"] <= 1.0
        assert row["ci_lower"] <= row["survival"] + 1e-9
        assert row["survival"] <= row["ci_upper"] + 1e-9


def test_km_survival_monotone_nonincreasing():
    r = kaplan_meier([3, 1, 4, 1, 5, 9, 2, 6], [1, 1, 0, 1, 1, 0, 1, 1])
    surv = [row["survival"] for row in r["timeline"]]
    for a, b in zip(surv, surv[1:]):
        assert b <= a + 1e-12


def test_km_single_observation():
    r = kaplan_meier([5], [1])
    assert r["n"] == 1
    assert r["timeline"][0]["survival"] == 0.0


def test_km_all_censored():
    # 无事件 → 空 timeline, median None
    r = kaplan_meier([1, 2, 3], [0, 0, 0])
    assert r["timeline"] == []
    assert r["n_events"] == 0
    assert r["median_survival"] is None


# ---------------------------------------------------------------------------
# Log-rank 检验 — 手算金标准
# ---------------------------------------------------------------------------

def test_logrank_separated_groups_goldstandard():
    groups = {
        "A": ([1, 2, 3], [1, 1, 1]),
        "B": ([4, 5, 6], [1, 1, 1]),
    }
    r = logrank_test(groups)
    assert r["df"] == 1
    # O_A=3, E_A=1.15 → diff=1.85; V_AA=0.6775; χ²=1.85²/0.6775≈5.0517
    assert abs(r["chi2"] - 5.0517) < 1e-3
    assert abs(r["p"] - 0.0246) < 1e-3
    assert r["significant"] is True


def test_logrank_group_observed_expected():
    groups = {"A": ([1, 2, 3], [1, 1, 1]), "B": ([4, 5, 6], [1, 1, 1])}
    r = logrank_test(groups)
    ga = [g for g in r["groups"] if g["name"] == "A"][0]
    assert abs(ga["observed"] - 3.0) < 1e-6
    assert abs(ga["expected"] - 1.15) < 1e-3


def test_logrank_identical_groups_chi2_zero():
    groups = {"A": ([1, 2, 3], [1, 1, 1]), "B": ([1, 2, 3], [1, 1, 1])}
    r = logrank_test(groups)
    assert abs(r["chi2"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9
    assert r["significant"] is False


def test_logrank_requires_two_groups():
    with pytest.raises(ValueError):
        logrank_test({"A": ([1, 2], [1, 1])})


def test_logrank_chi2_nonnegative():
    groups = {
        "A": ([2, 4, 6, 8], [1, 1, 0, 1]),
        "B": ([1, 3, 5, 7], [1, 0, 1, 1]),
    }
    r = logrank_test(groups)
    assert r["chi2"] >= 0.0
    assert 0.0 <= r["p"] <= 1.0


def test_logrank_three_groups_df():
    groups = {
        "A": ([1, 2, 3], [1, 1, 1]),
        "B": ([4, 5, 6], [1, 1, 1]),
        "C": ([7, 8, 9], [1, 1, 1]),
    }
    r = logrank_test(groups)
    assert r["df"] == 2
    assert r["k"] == 3
    assert r["chi2"] > 0.0


def test_logrank_three_identical_groups():
    g = ([1, 2, 3], [1, 1, 1])
    r = logrank_test({"A": g, "B": g, "C": g})
    assert abs(r["chi2"]) < 1e-9
    assert abs(r["p"] - 1.0) < 1e-9


def test_logrank_group_summaries_have_km():
    groups = {"A": ([1, 2, 3], [1, 1, 1]), "B": ([4, 5, 6], [1, 1, 1])}
    r = logrank_test(groups)
    for g in r["groups"]:
        assert "median_survival" in g
        assert "timeline" in g
        assert g["n"] == 3


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def test_format_apa_km():
    r = kaplan_meier([6, 7, 10, 15, 19, 25], [1] * 6)
    txt = format_apa_survival(r)
    assert "Kaplan-Meier" in txt
    assert "中位生存" in txt


def test_format_apa_km_median_not_reached():
    r = kaplan_meier([1, 2, 3], [1, 0, 0])
    txt = format_apa_survival(r)
    assert "未达到" in txt


def test_format_apa_logrank():
    groups = {"A": ([1, 2, 3], [1, 1, 1]), "B": ([4, 5, 6], [1, 1, 1])}
    r = logrank_test(groups)
    txt = format_apa_survival(r)
    assert "Log-rank" in txt
    assert "χ" in txt
    assert "显著" in txt


# ---------------------------------------------------------------------------
# 报告写出
# ---------------------------------------------------------------------------

def test_write_km_report():
    r = kaplan_meier([6, 7, 10, 15, 19, 25], [1] * 6)
    with tempfile.TemporaryDirectory() as d:
        md, js = write_survival_report(r, out_dir=d, filename="km")
        assert md.exists() and js.exists()
        content = md.read_text(encoding="utf-8")
        assert "生存函数表" in content
        loaded = json.loads(js.read_text(encoding="utf-8"))
        assert loaded["test"] == "Kaplan-Meier"


def test_write_logrank_report():
    groups = {"A": ([1, 2, 3], [1, 1, 1]), "B": ([4, 5, 6], [1, 1, 1])}
    r = logrank_test(groups)
    with tempfile.TemporaryDirectory() as d:
        md, js = write_survival_report(r, out_dir=d, filename="lr")
        content = md.read_text(encoding="utf-8")
        assert "观测/期望" in content
        loaded = json.loads(js.read_text(encoding="utf-8"))
        assert loaded["test"] == "Log-rank"


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_analyze_survival_km():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["t", "e"],
                   [[6, 1], [7, 1], [10, 1], [15, 1], [19, 1], [25, 1]])
        r = analyze_survival(str(p), "t", "e", out_dir=d)
        assert r["test"] == "Kaplan-Meier"
        assert r["median_survival"] == 10
        assert r["n_excluded"] == 0


def test_analyze_survival_logrank():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[1, 1, "A"], [2, 1, "A"], [3, 1, "A"],
                [4, 1, "B"], [5, 1, "B"], [6, 1, "B"]]
        _write_csv(p, ["t", "e", "g"], rows)
        r = analyze_survival(str(p), "t", "e", group_col="g", out_dir=d)
        assert r["test"] == "Log-rank"
        assert abs(r["chi2"] - 5.0517) < 1e-3
        assert r["df"] == 1


def test_analyze_survival_excludes_bad_rows():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[6, 1], ["", 1], [10, 1], ["bad", 0], [15, 2], [19, 1]]
        _write_csv(p, ["t", "e"], rows)
        r = analyze_survival(str(p), "t", "e", out_dir=d)
        # 3 行非法: 空 time、非数 time、event=2
        assert r["n_excluded"] == 3
        assert r["n"] == 3


def test_analyze_survival_logrank_excludes_missing_group():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[1, 1, "A"], [2, 1, ""], [3, 1, "A"],
                [4, 1, "B"], [5, 1, "B"]]
        _write_csv(p, ["t", "e", "g"], rows)
        r = analyze_survival(str(p), "t", "e", group_col="g", out_dir=d)
        assert r["n_excluded"] == 1


def test_analyze_survival_needs_two_groups():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["t", "e", "g"], [[1, 1, "A"], [2, 1, "A"]])
        with pytest.raises(ValueError):
            analyze_survival(str(p), "t", "e", group_col="g", out_dir=d)


def test_analyze_survival_no_valid_rows():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["t", "e"], [["", ""], ["x", "y"]])
        with pytest.raises(ValueError):
            analyze_survival(str(p), "t", "e", out_dir=d)


def test_analyze_survival_writes_reports():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["t", "e"], [[6, 1], [7, 1], [10, 1]])
        r = analyze_survival(str(p), "t", "e", out_dir=d)
        assert "report_md" in r
        assert Path(r["report_md"]).exists()
        assert Path(r["report_json"]).exists()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def test_survival_cli_km(capsys):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        _write_csv(p, ["t", "e"], [[6, 1], [7, 1], [10, 1], [15, 1]])
        rc = survival_cli([str(p), "--time", "t", "--event", "e", "--out", d])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Kaplan-Meier" in out


def test_survival_cli_logrank_json(capsys):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "data.csv"
        rows = [[1, 1, "A"], [2, 1, "A"], [4, 1, "B"], [5, 1, "B"]]
        _write_csv(p, ["t", "e", "g"], rows)
        rc = survival_cli([str(p), "--time", "t", "--event", "e",
                           "--group", "g", "--json", "--out", d])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["test"] == "Log-rank"


def test_survival_cli_bad_file():
    rc = survival_cli(["/nonexistent/path.csv", "--time", "t", "--event", "e"])
    assert rc == 1
