"""M-1: 量表自动计分 — tests (stdlib only, no external deps)."""
from __future__ import annotations

import csv
import inspect
import io
import math
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    class _Approx:
        def __init__(self, v, abs=1e-6, rel=None):
            self._v = v
            self._abs = abs
        def __eq__(self, other):
            return abs(other - self._v) <= self._abs
        def __repr__(self):
            return f"approx({self._v})"
    class pytest:  # type: ignore[no-redef]
        @staticmethod
        def approx(v, abs=1e-6, rel=None):
            return _Approx(v, abs=abs)

from psyclaw.psych.scales import (
    _response_range,
    reverse_item,
    score_participant,
    score_datafile,
    write_scored_csv,
    get_scale,
)


# ---------------------------------------------------------------------------
# _response_range
# ---------------------------------------------------------------------------

def test_response_range_0_3():
    s = {"response": "0-3 Likert,子量表总分×2"}
    assert _response_range(s) == (0, 3)


def test_response_range_1_4():
    s = {"response": "1-4 Likert(在线版常见)"}
    assert _response_range(s) == (1, 4)


def test_response_range_1_7():
    s = {"response": "1-7"}
    assert _response_range(s) == (1, 7)


def test_response_range_fallback():
    s = {"response": "Likert"}
    assert _response_range(s) == (1, 5)


def test_response_range_parens():
    s = {"response": "1-4(或 0-3)"}
    assert _response_range(s) == (1, 4)


# ---------------------------------------------------------------------------
# reverse_item
# ---------------------------------------------------------------------------

def test_reverse_0_3():
    assert reverse_item(0, 0, 3) == 3
    assert reverse_item(3, 0, 3) == 0
    assert reverse_item(1, 0, 3) == 2
    assert reverse_item(2, 0, 3) == 1


def test_reverse_1_7():
    assert reverse_item(1, 1, 7) == 7
    assert reverse_item(7, 1, 7) == 1
    assert reverse_item(4, 1, 7) == 4  # mid-point unchanged


def test_reverse_1_4():
    assert reverse_item(1, 1, 4) == 4
    assert reverse_item(2, 1, 4) == 3
    assert reverse_item(4, 1, 4) == 1


# ---------------------------------------------------------------------------
# score_participant — forward-only (no reverse items)
# ---------------------------------------------------------------------------

def _dass21_scale():
    return get_scale("dass-21")


def _tipi_scale():
    return get_scale("tipi")


def _phq9_scale():
    return get_scale("phq-9")


def test_score_participant_dass21_sum():
    """DASS-21 没有反向题，直接相加。"""
    scale = _dass21_scale()
    # 只填 Depression 子量表（条目 3,5,10,13,16,17,21）全部答 2
    item_vals = {i: 2.0 for i in range(1, 22)}
    res = score_participant(item_vals, scale, method="sum")
    assert res["missing_items"] == []
    # Depression = 7 * 2 = 14
    assert res["subscales"]["Depression"] == pytest.approx(14.0)
    # Anxiety = 7 * 2 = 14
    assert res["subscales"]["Anxiety"] == pytest.approx(14.0)
    # Stress = 7 * 2 = 14
    assert res["subscales"]["Stress"] == pytest.approx(14.0)
    assert res["total"] == pytest.approx(42.0)


def test_score_participant_dass21_mean():
    scale = _dass21_scale()
    item_vals = {i: 2.0 for i in range(1, 22)}
    res = score_participant(item_vals, scale, method="mean")
    assert res["subscales"]["Depression"] == pytest.approx(2.0)
    assert res["total"] == pytest.approx(6.0)  # 3 subscales × mean=2


def test_score_participant_missing():
    scale = _dass21_scale()
    # 只填条目 1-10
    item_vals = {i: 1.0 for i in range(1, 11)}
    res = score_participant(item_vals, scale)
    assert set(res["missing_items"]) == set(range(11, 22))


# ---------------------------------------------------------------------------
# score_participant — reverse items (TIPI)
# ---------------------------------------------------------------------------

def test_tipi_reverse_coding():
    """TIPI 反向题: 2,4,6,8,10 → 应翻转，1-7 量表。"""
    scale = _tipi_scale()
    # 原始答 1
    item_vals = {i: 1.0 for i in range(1, 11)}
    res = score_participant(item_vals, scale)
    # 正向题（1,3,5,7,9）保持 1
    for i in [1, 3, 5, 7, 9]:
        assert res["items"][i] == pytest.approx(1.0), f"item {i} should stay 1"
    # 反向题（2,4,6,8,10）应翻转为 7（1+7-1=7）
    for i in [2, 4, 6, 8, 10]:
        assert res["items"][i] == pytest.approx(7.0), f"item {i} should reverse to 7"


def test_tipi_extraversion():
    """Extraversion = items 1(正) + 6(反) 之和。"""
    scale = _tipi_scale()
    item_vals = {i: 3.0 for i in range(1, 11)}
    res = score_participant(item_vals, scale)
    # item 1 正向=3, item 6 反向=1+7-3=5 → Extraversion sum=8
    assert res["subscales"]["Extraversion"] == pytest.approx(8.0)


def test_tipi_all_max():
    """若所有条目答 7，反向题翻转后为 1。"""
    scale = _tipi_scale()
    item_vals = {i: 7.0 for i in range(1, 11)}
    res = score_participant(item_vals, scale)
    for i in [2, 4, 6, 8, 10]:
        assert res["items"][i] == pytest.approx(1.0)
    for i in [1, 3, 5, 7, 9]:
        assert res["items"][i] == pytest.approx(7.0)


def test_rses_reverse():
    """RSES 反向题 3,5,8,9,10，1-4 量表。"""
    from psyclaw.psych.scales import get_scale
    scale = get_scale("rses")
    item_vals = {i: 1.0 for i in range(1, 11)}
    res = score_participant(item_vals, scale)
    for i in [3, 5, 8, 9, 10]:
        assert res["items"][i] == pytest.approx(4.0), f"rses item {i} should reverse"
    for i in [1, 2, 4, 6, 7]:
        assert res["items"][i] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# score_datafile — from CSV
# ---------------------------------------------------------------------------

def _make_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_score_datafile_tipi_basic(tmp_path):
    """5 人 TIPI 数据，列名 Q1-Q10，验证子量表分。"""
    # 所有人答 4（中间值），反向题翻 1+7-4=4，子量表均=8
    rows = [{"Q" + str(i): "4" for i in range(1, 11)} for _ in range(5)]
    f = tmp_path / "tipi.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "tipi", prefix="Q", suffix="")
    assert result.get("error") is None
    assert result["n"] == 5
    assert result["n_complete"] == 5
    assert result["reverse_applied"] == [2, 4, 6, 8, 10]
    # All subscales mean should be 8.0 (4+4, both items=4 after reverse)
    for sub, st in result["subscale_stats"].items():
        assert st["mean"] == pytest.approx(8.0), f"{sub} mean should be 8"
    assert result["total_stats"]["mean"] == pytest.approx(40.0)


def test_score_datafile_dass21_suffix(tmp_path):
    """DASS-21 数据，使用 OpenPsychometrics 列名 Q1A-Q21A。"""
    rows = [{"Q" + str(i) + "A": "1" for i in range(1, 22)} for _ in range(3)]
    f = tmp_path / "dass.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "dass-21", prefix="Q", suffix="A")
    assert result.get("error") is None
    assert result["n"] == 3
    assert result["n_complete"] == 3
    assert result["missing_items_global"] == []
    # Each subscale = 7 items × 1 = 7
    for sub, st in result["subscale_stats"].items():
        assert st["mean"] == pytest.approx(7.0)


def test_score_datafile_missing_items(tmp_path):
    """只提供前 5 列，其余条目缺失。"""
    rows = [{"Q" + str(i): "2" for i in range(1, 6)} for _ in range(4)]
    f = tmp_path / "partial.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "dass-21", prefix="Q", suffix="")
    assert result.get("error") is None
    assert len(result["missing_items_global"]) == 16  # items 6-21
    assert any("缺失" in w for w in result["warnings"])


def test_score_datafile_unknown_scale(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("Q1\n1\n", encoding="utf-8")
    result = score_datafile(str(f), "nonexistent-scale")
    assert "error" in result


def test_score_datafile_file_not_found():
    result = score_datafile("/no/such/file.csv", "tipi")
    assert "error" in result


def test_score_datafile_phq9_ethics_warning(tmp_path):
    """PHQ-9 条目 9 应答 ≥ 1 时触发伦理警告。"""
    rows = [{"Q" + str(i): "1" for i in range(1, 10)} for _ in range(5)]
    f = tmp_path / "phq9.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    assert any("PHQ-9" in w and "自伤" in w for w in result["warnings"])


def test_score_datafile_phq9_no_warning_item9_zero(tmp_path):
    """PHQ-9 条目 9 全零时不触发伦理警告。"""
    rows = [{"Q" + str(i): ("0" if i == 9 else "1") for i in range(1, 10)} for _ in range(5)]
    f = tmp_path / "phq9z.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    assert not any("自伤" in w for w in result["warnings"])


def test_score_datafile_dass42_warning(tmp_path):
    """DASS-42 应发出 1-4 vs 0-3 歧义提示。"""
    rows = [{"Q" + str(i): "2" for i in range(1, 43)} for _ in range(2)]
    f = tmp_path / "dass42.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "dass-42", prefix="Q", suffix="")
    assert any("DASS-42" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# write_scored_csv
# ---------------------------------------------------------------------------

def test_write_scored_csv(tmp_path):
    """验证输出 CSV 包含子量表列和总分列。"""
    rows = [{"Q" + str(i): "3" for i in range(1, 11)}
            for _ in range(3)]
    src = tmp_path / "tipi.csv"
    _make_csv(rows, src)

    result = score_datafile(str(src), "tipi", prefix="Q", suffix="")
    out = tmp_path / "tipi_scored.csv"
    write_scored_csv(result, str(out), str(src))

    assert out.exists()
    with open(out, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        scored_rows = list(reader)

    assert len(scored_rows) == 3
    assert "TIPI_Extraversion" in scored_rows[0]
    assert "TIPI_Total" in scored_rows[0]
    # item 1 正向=3, item 6 反向=1+7-3=5 → Extraversion=8
    assert float(scored_rows[0]["TIPI_Extraversion"]) == pytest.approx(8.0, abs=0.01)


def test_write_scored_csv_total(tmp_path):
    """DASS-21 总分写入 CSV 列。"""
    rows = [{"Q" + str(i): "1" for i in range(1, 22)} for _ in range(2)]
    src = tmp_path / "dass21.csv"
    _make_csv(rows, src)

    result = score_datafile(str(src), "dass-21", prefix="Q", suffix="")
    out = tmp_path / "out.csv"
    write_scored_csv(result, str(out), str(src))

    with open(out, newline="", encoding="utf-8") as f:
        r = list(csv.DictReader(f))
    # 21 items × 1 = 21 total
    assert float(r[0]["DASS_21_Total"]) == pytest.approx(21.0, abs=0.01)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def test_cli_score_command_runs(tmp_path):
    """cmd_score 不崩溃，返回 0。"""
    from psyclaw.cli import cmd_score
    import argparse

    rows = [{"Q" + str(i): "4" for i in range(1, 11)} for _ in range(5)]
    f = tmp_path / "t.csv"
    _make_csv(rows, f)

    args = argparse.Namespace(
        data=str(f), scale="tipi", prefix="Q", suffix="",
        method="sum", out=None, json=False,
    )
    rc = cmd_score(args)
    assert rc == 0


def test_cli_score_command_bad_scale(tmp_path):
    from psyclaw.cli import cmd_score
    import argparse

    f = tmp_path / "x.csv"
    f.write_text("Q1\n1\n", encoding="utf-8")
    args = argparse.Namespace(
        data=str(f), scale="nonexistent", prefix="Q", suffix="",
        method="sum", out=None, json=False,
    )
    rc = cmd_score(args)
    assert rc == 1


def test_cli_score_with_out(tmp_path):
    from psyclaw.cli import cmd_score
    import argparse

    rows = [{"Q" + str(i): "5" for i in range(1, 11)} for _ in range(3)]
    f = tmp_path / "t.csv"
    _make_csv(rows, f)
    out = tmp_path / "scored.csv"

    args = argparse.Namespace(
        data=str(f), scale="tipi", prefix="Q", suffix="",
        method="sum", out=str(out), json=False,
    )
    rc = cmd_score(args)
    assert rc == 0
    assert out.exists()


# ---------------------------------------------------------------------------
# M-2: 子量表自动信度
# ---------------------------------------------------------------------------

from psyclaw.psych.scales import compute_subscale_reliability
from psyclaw.psych.reliability import cronbach_alpha, interpret_alpha


def test_compute_reliability_phq9(tmp_path):
    """PHQ-9 Total 子量表信度（9 条目，全相同应答 → α=NaN 或有值）。"""
    # 9 题 × 20 人，各行随机模拟 0-3
    import random
    random.seed(42)
    rows = [{"Q" + str(i): str(random.randint(0, 3)) for i in range(1, 10)}
            for _ in range(20)]
    f = tmp_path / "phq.csv"
    _make_csv(rows, f)
    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    rel = result["reliability"]
    assert "Total" in rel
    a = rel["Total"]["alpha"]
    # 随机数据 α 应在合理区间（允许 NaN 仅当零方差，实际随机数据不会）
    if not math.isnan(a):
        assert -1.0 <= a <= 1.0


def test_compute_reliability_tipi(tmp_path):
    """TIPI 5 个维度各有 2 题，α 应均可计算。"""
    import random
    random.seed(7)
    rows = [{"Q" + str(i): str(random.randint(1, 7)) for i in range(1, 11)}
            for _ in range(30)]
    f = tmp_path / "tipi.csv"
    _make_csv(rows, f)
    result = score_datafile(str(f), "tipi", prefix="Q", suffix="")
    rel = result["reliability"]
    for sub in ["Extraversion", "Agreeableness", "Conscientiousness",
                "EmotionalStability", "Openness"]:
        assert sub in rel
        assert rel[sub]["n_items"] == 2
        assert rel[sub]["n_obs"] == 30


def test_reliability_too_few_obs():
    """n < 3 → α = NaN，不崩溃。"""
    from psyclaw.psych.scales import get_scale
    scale = get_scale("phq-9")
    # 只有 2 名被试
    participants = [
        {"items": {i: 1.0 for i in range(1, 10)}, "subscales": {}, "total": 9.0, "missing_items": []},
        {"items": {i: 2.0 for i in range(1, 10)}, "subscales": {}, "total": 18.0, "missing_items": []},
    ]
    rel = compute_subscale_reliability(participants, scale)
    assert math.isnan(rel["Total"]["alpha"])


def test_reliability_few_items():
    """单条目子量表无法计 α。"""
    scale = {"subscales": {"Single": [1]}, "reverse": [], "items": 1, "id": "test"}
    participants = [{"items": {1: float(v)}, "subscales": {}, "total": float(v), "missing_items": []}
                    for v in range(1, 10)]
    rel = compute_subscale_reliability(participants, scale)
    assert math.isnan(rel["Single"]["alpha"])


def test_reliability_in_score_datafile_result(tmp_path):
    """score_datafile 返回值包含 reliability 键。"""
    rows = [{"Q" + str(i): str(i % 3 + 1) for i in range(1, 10)} for _ in range(10)]
    f = tmp_path / "phq.csv"
    _make_csv(rows, f)
    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    assert "reliability" in result
    assert isinstance(result["reliability"], dict)
    assert "Total" in result["reliability"]


def test_cronbach_alpha_known_value():
    """验证 α 计算与公式一致（k=3，完全线性相关 → α=11/12≈0.917）。"""
    # item2=2×item1, item3=3×item1  → 各分量方差 5/3,20/3,15；总分方差 60
    # α = (3/2)*(1 - (5/3+20/3+15)/60) = 11/12
    items = [
        [1.0, 2.0, 3.0, 4.0],
        [2.0, 4.0, 6.0, 8.0],
        [3.0, 6.0, 9.0, 12.0],
    ]
    a = cronbach_alpha(items)
    assert a == pytest.approx(11 / 12, abs=0.001)


def test_interpret_alpha_bands():
    """信度解释文字覆盖各区间。"""
    assert "优" in interpret_alpha(0.92)
    assert "良" in interpret_alpha(0.85)
    assert "可接受" in interpret_alpha(0.75)
    assert "勉强" in interpret_alpha(0.65)
    assert "差" in interpret_alpha(0.55)
    assert "无法" in interpret_alpha(float("nan"))


def test_alpha_if_deleted_length():
    """alpha_if_deleted 返回与条目数相同长度的列表。"""
    from psyclaw.psych.reliability import alpha_if_deleted
    items = [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0], [1.5, 2.5, 3.5]]
    aid = alpha_if_deleted(items)
    assert len(aid) == 3
    for item_num, a in aid:
        assert not math.isnan(a)


def test_cli_score_shows_reliability(tmp_path, capsys=None):
    """cmd_score 显示信度区段（smoke test，只检查不崩溃）。"""
    from psyclaw.cli import cmd_score
    import argparse
    import random
    random.seed(99)
    rows = [{"Q" + str(i): str(random.randint(0, 3)) for i in range(1, 10)} for _ in range(15)]
    f = tmp_path / "phq.csv"
    _make_csv(rows, f)
    args = argparse.Namespace(
        data=str(f), scale="phq-9", prefix="Q", suffix="",
        method="sum", out=None, json=False,
    )
    rc = cmd_score(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# Self-run block (no pytest needed)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
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
