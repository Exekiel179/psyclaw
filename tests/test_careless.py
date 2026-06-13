"""Tests for psyclaw.psych.careless — 草率作答筛查扩展指标(M-5)。"""

import csv
import inspect
import math
import sys
import tempfile
from pathlib import Path

from psyclaw.psych.careless import (
    chi2_critical,
    flag_respondent,
    infrequency_score,
    irv,
    longstring,
    mahalanobis_d,
    psychsyn_score,
    response_time_flag,
    screen_csv,
    straightline_pct,
)


# ---------------------------------------------------------------------------
# longstring
# ---------------------------------------------------------------------------

def test_longstring_all_same():
    assert longstring([3, 3, 3, 3, 3]) == 5


def test_longstring_alternating():
    assert longstring([1, 2, 1, 2, 1]) == 1


def test_longstring_run_in_middle():
    assert longstring([1, 2, 2, 2, 1, 1]) == 3


def test_longstring_empty():
    assert longstring([]) == 0


# ---------------------------------------------------------------------------
# straightline_pct
# ---------------------------------------------------------------------------

def test_straightline_all_same():
    assert straightline_pct([3, 3, 3, 3]) == 1.0


def test_straightline_diverse():
    pct = straightline_pct([1, 2, 3, 4, 5])
    assert abs(pct - 0.2) < 1e-9


def test_straightline_empty():
    assert straightline_pct([]) == 0.0


# ---------------------------------------------------------------------------
# irv
# ---------------------------------------------------------------------------

def test_irv_all_same():
    assert irv([3, 3, 3, 3]) < 1e-9


def test_irv_varied():
    val = irv([1, 2, 3, 4, 5])
    assert abs(val - math.sqrt(2.5)) < 1e-6


def test_irv_single_item():
    assert irv([3]) == 0.0


# ---------------------------------------------------------------------------
# psychsyn_score
# ---------------------------------------------------------------------------

def test_psychsyn_perfect_synonym():
    score = psychsyn_score([3.0, 3.0, 2.0], synonym_pairs=[(0, 1)], antonym_pairs=[])
    assert abs(score - 1.0) < 1e-9


def test_psychsyn_worst_synonym():
    score = psychsyn_score([1.0, 5.0], synonym_pairs=[(0, 1)], antonym_pairs=[],
                           scale_min=1.0, scale_max=5.0)
    assert abs(score - 0.0) < 1e-9


def test_psychsyn_perfect_antonym():
    score = psychsyn_score([1.0, 5.0], synonym_pairs=[], antonym_pairs=[(0, 1)],
                           scale_min=1.0, scale_max=5.0)
    assert abs(score - 1.0) < 1e-9


def test_psychsyn_worst_antonym():
    # antonym: answered 1, 1; mirror of 1 = 5; diff = |1-5|=4; score = 0
    score = psychsyn_score([1.0, 1.0], synonym_pairs=[], antonym_pairs=[(0, 1)],
                           scale_min=1.0, scale_max=5.0)
    assert abs(score - 0.0) < 1e-9


def test_psychsyn_mixed_pairs():
    # synonym(0,1): both 3 → 1.0; antonym(2,3): 1 vs 5 → 1.0; mean = 1.0
    score = psychsyn_score(
        [3.0, 3.0, 1.0, 5.0],
        synonym_pairs=[(0, 1)],
        antonym_pairs=[(2, 3)],
        scale_min=1.0, scale_max=5.0,
    )
    assert abs(score - 1.0) < 1e-9


def test_psychsyn_no_pairs():
    score = psychsyn_score([3.0, 3.0], synonym_pairs=[], antonym_pairs=[])
    assert math.isnan(score)


def test_psychsyn_partial_consistency():
    # synonym(0,1): 1 vs 3 → 1 - 2/4 = 0.5; synonym(2,3): 4 vs 5 → 1 - 1/4 = 0.75
    # mean = 0.625
    score = psychsyn_score(
        [1.0, 3.0, 4.0, 5.0],
        synonym_pairs=[(0, 1), (2, 3)],
        antonym_pairs=[],
        scale_min=1.0, scale_max=5.0,
    )
    assert abs(score - 0.625) < 1e-9


# ---------------------------------------------------------------------------
# mahalanobis_d
# ---------------------------------------------------------------------------

def test_mahalanobis_center_smallest():
    matrix = [
        [1.0, 1.0],
        [5.0, 5.0],
        [3.0, 3.0],  # center
        [2.0, 4.0],
        [4.0, 2.0],
        [2.0, 2.0],
        [4.0, 4.0],
    ]
    d2 = mahalanobis_d(matrix)
    assert len(d2) == 7
    assert all(v >= 0 for v in d2)
    assert d2[2] == min(d2)


def test_mahalanobis_outlier_largest():
    matrix = [
        [3.0, 3.0],
        [2.0, 3.0],
        [3.0, 4.0],
        [4.0, 3.0],
        [3.0, 2.0],
        [10.0, 10.0],  # outlier
    ]
    d2 = mahalanobis_d(matrix)
    assert d2[-1] == max(d2)


def test_mahalanobis_nonnegative():
    matrix = [[float(i * 0.5 + j * 0.3 + (i % 3)) for j in range(3)] for i in range(8)]
    d2 = mahalanobis_d(matrix)
    assert all(v >= 0 for v in d2)


def test_mahalanobis_too_few_respondents():
    matrix = [[1.0, 2.0, 3.0], [2.0, 3.0, 1.0], [3.0, 1.0, 2.0]]
    raised = False
    try:
        mahalanobis_d(matrix)
    except ValueError as e:
        raised = True
        assert "至少" in str(e)
    assert raised, "should have raised ValueError"


def test_mahalanobis_empty():
    assert mahalanobis_d([]) == []


# ---------------------------------------------------------------------------
# chi2_critical
# ---------------------------------------------------------------------------

def test_chi2_critical_df2():
    val = chi2_critical(2, alpha=0.001)
    assert 13.0 <= val <= 15.5


def test_chi2_critical_df5():
    val = chi2_critical(5, alpha=0.001)
    assert 19.0 <= val <= 22.5


def test_chi2_critical_alpha05():
    val = chi2_critical(3, alpha=0.05)
    assert 6.5 <= val <= 9.0


# ---------------------------------------------------------------------------
# response_time_flag
# ---------------------------------------------------------------------------

def test_response_time_flag_fast():
    flag = response_time_flag([0.3, 0.5, 0.2], min_seconds_per_item=1.0)
    assert flag is not None
    assert "fast_response" in flag


def test_response_time_flag_ok():
    flag = response_time_flag([2.0, 3.0, 2.5], min_seconds_per_item=1.0)
    assert flag is None


def test_response_time_flag_empty():
    assert response_time_flag([], min_seconds_per_item=1.0) is None


def test_response_time_flag_boundary():
    # Exactly at threshold: mean=1.0, should NOT trigger (< not ≤)
    flag = response_time_flag([1.0, 1.0, 1.0], min_seconds_per_item=1.0)
    assert flag is None


# ---------------------------------------------------------------------------
# infrequency_score
# ---------------------------------------------------------------------------

def test_infrequency_all_correct():
    count = infrequency_score([1.0, 5.0, 3.0], [(0, 1), (1, 5)])
    assert count == 0


def test_infrequency_all_wrong():
    count = infrequency_score([3.0, 3.0, 3.0], [(0, 1), (1, 5)])
    assert count == 2


def test_infrequency_partial():
    count = infrequency_score([1.0, 3.0, 4.0], [(0, 1), (1, 5), (2, 2)])
    assert count == 2


def test_infrequency_out_of_bounds_index():
    count = infrequency_score([1.0, 2.0], [(10, 1)])
    assert count == 0


# ---------------------------------------------------------------------------
# flag_respondent (integrated)
# ---------------------------------------------------------------------------

def test_flag_respondent_clean():
    flags = flag_respondent([1, 2, 3, 4, 5, 2, 3, 4, 1, 2], n_items=10)
    assert flags == []


def test_flag_respondent_longstring():
    flags = flag_respondent([3] * 10, n_items=10, longstring_max=8)
    assert any("longstring" in f for f in flags)


def test_flag_respondent_irv():
    flags = flag_respondent([3] * 8, n_items=8, irv_min=0.3)
    assert any("IRV" in f for f in flags)


def test_flag_respondent_psychsyn():
    responses = [1.0, 5.0, 3.0, 3.0]
    flags = flag_respondent(
        responses, n_items=4,
        synonym_pairs=[(0, 1)], antonym_pairs=[],
        psychsyn_min=0.5,
    )
    assert any("psychsyn" in f for f in flags)


def test_flag_respondent_infrequency():
    responses = [3.0, 3.0, 3.0]
    flags = flag_respondent(
        responses, n_items=3,
        infrequency_items=[(0, 1), (1, 5), (2, 1)],
        infrequency_max=1,
    )
    assert any("infrequency" in f for f in flags)


def test_flag_respondent_fast_response():
    responses = [2, 3, 4, 2, 3]
    flags = flag_respondent(
        responses, n_items=5,
        time_vals=[0.3, 0.2, 0.4, 0.1, 0.3],
        min_seconds_per_item=1.0,
    )
    assert any("fast_response" in f for f in flags)


# ---------------------------------------------------------------------------
# screen_csv (integration)
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list, header: list):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_screen_csv_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "data.csv"
        header = ["Q1A", "Q2A", "Q3A", "Q4A", "Q5A"]
        rows = [
            [3, 3, 3, 3, 3],
            [1, 2, 3, 4, 5],
            [2, 3, 4, 5, 1],
            [4, 4, 4, 4, 4],
        ]
        _write_csv(str(p), rows, header)
        result = screen_csv(str(p), compute_mahal=False)
        assert result["n_total"] == 4
        assert result["n_flagged"] >= 2


def test_screen_csv_time_cols():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "data_time.csv"
        header = ["Q1A", "Q2A", "Q3A", "Q1E", "Q2E", "Q3E"]
        rows = [
            [2, 3, 4, 0.2, 0.3, 0.1],  # fast responder
            [3, 2, 4, 2.0, 3.0, 2.5],
            [1, 3, 5, 1.5, 2.0, 1.8],
            [4, 2, 3, 2.1, 1.9, 2.3],
        ]
        _write_csv(str(p), rows, header)
        result = screen_csv(str(p), compute_mahal=False)
        assert len(result["time_cols"]) == 3
        fast_flags = [r for r in result["rows"] if any("fast" in f for f in r["flags"])]
        assert len(fast_flags) >= 1


def test_screen_csv_mahal_outlier():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "mahal.csv"
        header = ["Q1A", "Q2A", "Q3A"]
        rows = [[3, 3, 3]] * 15 + [[2, 4, 3]] * 5 + [[10, 10, 10]]
        _write_csv(str(p), rows, header)
        result = screen_csv(str(p), compute_mahal=True)
        assert "mahal" in result
        assert result["mahal"]["n_outliers"] >= 1


def test_screen_csv_no_item_cols():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "bad.csv"
        header = ["id", "name", "value"]
        _write_csv(str(p), [[1, "a", 5]], header)
        result = screen_csv(str(p), compute_mahal=False)
        assert result["n_total"] == 0
        assert result["items"] == []


def test_screen_csv_tab_separated():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "tab.tsv"
        with open(str(p), "w", newline="", encoding="utf-8") as f:
            f.write("Q1A\tQ2A\tQ3A\n")
            f.write("3\t3\t3\n")  # flagged (straightline)
            f.write("1\t3\t5\n")
        result = screen_csv(str(p), compute_mahal=False)
        assert result["n_total"] == 2


# ---------------------------------------------------------------------------
# 自跑块
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
