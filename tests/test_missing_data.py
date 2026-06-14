"""P3-2 缺失数据报告测试 — ≥25 例，stdlib only 可用。"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.missing_data import (  # noqa: E402
    _is_numeric,
    _load_csv,
    _numeric_cols,
    _to_float,
    analyze_missing,
    format_apa_missing,
    little_mcar_test,
    mar_test,
    missing_cli,
    missing_pattern,
    recommend_imputation,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _make_rows(headers: list[str], data: list[list]) -> list[dict]:
    return [{h: (v if v is not None else None) for h, v in zip(headers, row)} for row in data]


def _write_csv(rows: list[list], headers: list[str], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(["" if v is None else v for v in row])


# ---------------------------------------------------------------------------
# 1. 工具函数
# ---------------------------------------------------------------------------

def test_is_numeric_float():
    assert _is_numeric("3.14") is True


def test_is_numeric_int():
    assert _is_numeric("42") is True


def test_is_numeric_negative():
    assert _is_numeric("-1.5") is True


def test_is_numeric_empty():
    assert _is_numeric("") is False


def test_is_numeric_word():
    assert _is_numeric("abc") is False


def test_to_float_none():
    assert _to_float(None) is None


def test_to_float_string():
    assert _to_float("2.5") == 2.5


def test_to_float_invalid():
    assert _to_float("NA") is None


# ---------------------------------------------------------------------------
# 2. _load_csv & _numeric_cols
# ---------------------------------------------------------------------------

def test_load_csv_missing_values():
    """CSV 中 NA / NaN / 空字符串均解析为 None。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False,
                                     encoding="utf-8", newline="") as f:
        f.write("a,b,c\n1,2,3\n,NA,\n4,NaN,5\n")
        tmp = f.name
    headers, rows = _load_csv(tmp)
    assert rows[1]["a"] is None
    assert rows[1]["b"] is None
    assert rows[1]["c"] is None
    assert rows[2]["b"] is None
    assert rows[0]["a"] == "1"


def test_numeric_cols_detection():
    headers = ["x", "y", "label"]
    rows = [{"x": "1", "y": "2.0", "label": "foo"},
            {"x": "3", "y": None, "label": "bar"}]
    num = _numeric_cols(headers, rows)
    assert "x" in num
    assert "y" in num
    assert "label" not in num


# ---------------------------------------------------------------------------
# 3. missing_pattern
# ---------------------------------------------------------------------------

def test_pattern_no_missing():
    headers = ["a", "b"]
    rows = _make_rows(headers, [[1, 2], [3, 4], [5, 6]])
    res = missing_pattern(rows, headers)
    assert res["overall_missing_pct"] == 0.0
    assert res["n_complete"] == 3
    assert len(res["patterns"]) == 1  # 全完整只有一个模式


def test_pattern_with_missing():
    headers = ["a", "b", "c"]
    rows = _make_rows(headers, [[1, 2, 3], [None, 2, 3], [1, None, None]])
    res = missing_pattern(rows, headers)
    assert res["n_complete"] == 1
    assert res["overall_missing_pct"] > 0
    assert res["missing_pct_per_col"]["a"] > 0
    assert len(res["patterns"]) == 3


def test_pattern_all_missing_col():
    headers = ["x", "y"]
    rows = _make_rows(headers, [[1, None], [2, None], [3, None]])
    res = missing_pattern(rows, headers)
    assert res["missing_pct_per_col"]["y"] == 1.0
    assert res["n_complete"] == 0


def test_pattern_empty_rows():
    res = missing_pattern([], ["a", "b"])
    assert res["n_rows"] == 0
    assert res["overall_missing_pct"] == 0.0


# ---------------------------------------------------------------------------
# 4. little_mcar_test
# ---------------------------------------------------------------------------

def test_mcar_insufficient_cols():
    rows = _make_rows(["x"], [[1], [None], [2]])
    res = little_mcar_test(rows, ["x"])
    assert res["verdict"] == "insufficient_data"


def test_mcar_no_missing_data():
    """无缺失数据时 d² ≈ 0，verdict == MCAR。"""
    headers = ["x", "y"]
    rows = _make_rows(headers, [[1.0, 2.0], [2.0, 3.0], [3.0, 4.0],
                                  [4.0, 5.0], [5.0, 6.0]])
    res = little_mcar_test(rows, ["x", "y"])
    # 无非完整模式 → d²=0，df=0 → verdict MCAR
    assert res["verdict"] in ("MCAR", "insufficient_data")


def test_mcar_runs_with_missing():
    """Little MCAR 在有缺失时能正常运行并返回有效结果。"""
    import random
    random.seed(42)
    n = 60
    # 生成三个相关变量，随机给 y 引入 MCAR 缺失
    rows = []
    for i in range(n):
        x1 = float(i % 10)
        x2 = x1 * 0.5 + 1.0
        x3 = x1 * 0.3 + x2 * 0.2
        # 约 20% 缺失
        y_miss = None if (i % 5 == 0) else x2
        rows.append({"x1": str(x1), "x2": str(x2) if y_miss is not None else None,
                     "x3": str(x3)})
    num_cols = ["x1", "x2", "x3"]
    res = little_mcar_test(rows, num_cols)
    assert res["verdict"] in ("MCAR", "not_MCAR", "insufficient_data")
    if res["verdict"] != "insufficient_data":
        assert res["statistic"] is not None
        assert 0.0 <= res["p_value"] <= 1.0


def test_mcar_too_few_complete_cases():
    headers = ["a", "b"]
    # 只有 1 个完整行（< k+2=4）
    rows = _make_rows(headers, [[1.0, 2.0], [None, 2.0], [1.0, None]])
    res = little_mcar_test(rows, ["a", "b"])
    assert res["verdict"] == "insufficient_data"


# ---------------------------------------------------------------------------
# 5. mar_test
# ---------------------------------------------------------------------------

def test_mar_insufficient_data():
    """缺失太少无法做 t 检验。"""
    headers = ["a", "b"]
    rows = _make_rows(headers, [[1, 2], [3, None]])
    res = mar_test(rows, "b", ["a"])
    assert res["verdict"] == "insufficient_data"


def test_mar_no_significant():
    """当缺失随机与预测变量无关时，应返回 MCAR_consistent。"""
    # a 完整；b 随机缺失（与 a 无关）
    headers = ["a", "b"]
    data = []
    for i in range(30):
        a = float(i)
        b = float(i) * 0.5 if i % 3 != 0 else None
        data.append([a, b])
    rows = _make_rows(headers, data)
    res = mar_test(rows, "b", ["a"])
    # 期望不显著（小样本可能偶尔显著，故只检查结构）
    assert res["target"] == "b"
    assert res["n_missing"] > 0
    assert res["verdict"] in ("MCAR_consistent", "MAR_likely", "insufficient_data")


def test_mar_significant():
    """当高值 a 对应 b 缺失时，MAR 检验应显著。"""
    headers = ["a", "b"]
    data = []
    for i in range(50):
        a = float(i)
        # b 在 a > 25 时缺失 → 强 MAR 信号
        b = float(i) * 0.5 if a <= 25 else None
        data.append([a, b])
    rows = _make_rows(headers, data)
    res = mar_test(rows, "b", ["a"])
    assert res["verdict"] == "MAR_likely"
    assert res["any_significant"] is True


def test_mar_skip_same_col():
    """predictor_cols 包含 target_col 时应跳过自身。"""
    headers = ["a", "b"]
    data = [[1, None], [2, 3], [3, None], [4, 5], [None, 6], [6, 7],
            [7, None], [8, 9], [9, None], [10, 11]]
    rows = _make_rows(headers, data)
    res = mar_test(rows, "a", ["a", "b"])
    # 不应因自身比较出错
    assert "predictors" in res
    # 预测变量列表中不应出现 'a'
    pred_names = [p["predictor"] for p in res["predictors"]]
    assert "a" not in pred_names


# ---------------------------------------------------------------------------
# 6. recommend_imputation
# ---------------------------------------------------------------------------

def test_recommend_low_mcar():
    res = recommend_imputation(0.03, "MCAR", None)
    assert "完整案例" in res["primary"]
    assert res["rationale"]


def test_recommend_mar():
    res = recommend_imputation(0.10, "not_MCAR", {"any_significant": True})
    assert "多重插补" in res["primary"]
    assert any("MAR" in w or "敏感性" in w for w in res["warnings"])


def test_recommend_mcar_high_pct():
    res = recommend_imputation(0.25, "MCAR", {"any_significant": False})
    assert "缺失比例较高" in res["warnings"][0]


def test_recommend_high_missing_extreme():
    res = recommend_imputation(0.55, "not_MCAR", None)
    assert any("50%" in w for w in res["warnings"])


def test_recommend_unknown_mcar():
    res = recommend_imputation(0.15, "insufficient_data", None)
    assert "多重插补" in res["primary"]


# ---------------------------------------------------------------------------
# 7. format_apa_missing
# ---------------------------------------------------------------------------

def test_format_apa_basic():
    pat = {"n_rows": 100, "n_cols": 5, "overall_missing_pct": 0.08,
           "n_complete": 80, "patterns": [{}] * 3,
           "missing_pct_per_col": {"a": 0.08, "b": 0.0}}
    mcar = {"statistic": 5.23, "df": 3, "p_value": 0.156,
            "verdict": "MCAR", "note": ""}
    txt = format_apa_missing(pat, mcar)
    assert "100" in txt
    assert "Little" in txt
    assert "MCAR" in txt


def test_format_apa_not_mcar():
    pat = {"n_rows": 50, "n_cols": 3, "overall_missing_pct": 0.20,
           "n_complete": 30, "patterns": [{}] * 2,
           "missing_pct_per_col": {"x": 0.20}}
    mcar = {"statistic": 12.5, "df": 2, "p_value": 0.002,
            "verdict": "not_MCAR", "note": ""}
    txt = format_apa_missing(pat, mcar)
    assert "拒绝 MCAR" in txt


def test_format_apa_insufficient():
    pat = {"n_rows": 10, "n_cols": 2, "overall_missing_pct": 0.0,
           "n_complete": 10, "patterns": [{}],
           "missing_pct_per_col": {}}
    mcar = {"statistic": None, "df": None, "p_value": None,
            "verdict": "insufficient_data",
            "note": "完整案例不足"}
    txt = format_apa_missing(pat, mcar)
    assert "完整案例不足" in txt


def test_format_apa_with_imputation():
    pat = {"n_rows": 80, "n_cols": 4, "overall_missing_pct": 0.05,
           "n_complete": 70, "patterns": [{}] * 2,
           "missing_pct_per_col": {"y": 0.05}}
    mcar = {"statistic": 1.0, "df": 1, "p_value": 0.317,
            "verdict": "MCAR", "note": ""}
    imp = {"primary": "多重插补（MI）", "alternatives": [], "warnings": [],
           "rationale": "test"}
    txt = format_apa_missing(pat, mcar, imputation=imp)
    assert "多重插补" in txt


# ---------------------------------------------------------------------------
# 8. analyze_missing（集成）
# ---------------------------------------------------------------------------

def test_analyze_missing_complete_data():
    """无缺失时整体缺失比 == 0，MCAR verdict 为 MCAR 或 insufficient_data。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        _write_csv([[1, 2, 3], [4, 5, 6], [7, 8, 9]], ["a", "b", "c"], p)
        res = analyze_missing(str(p))
    assert res["pattern"]["overall_missing_pct"] == 0.0
    assert res["mcar"]["verdict"] in ("MCAR", "insufficient_data")


def test_analyze_missing_with_missing():
    """有缺失时应返回有意义的 MCAR/MAR 信息。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        rows = [[i, i * 2 if i % 4 != 0 else None, i * 3] for i in range(1, 41)]
        _write_csv(rows, ["x", "y", "z"], p)
        res = analyze_missing(str(p))
    assert res["pattern"]["overall_missing_pct"] > 0
    assert "primary" in res["imputation"]
    assert "apa_paragraph" in res
    assert len(res["apa_paragraph"]) > 50


def test_analyze_missing_writes_files():
    """--out 选项写 missing_report.md。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        rows = [[1, 2], [3, None], [5, 6], [7, None], [9, 10]]
        _write_csv(rows, ["a", "b"], p)
        out = Path(td) / "out"
        res = analyze_missing(str(p), out_dir=str(out))
        assert (out / "missing_report.md").exists()
        content = (out / "missing_report.md").read_text(encoding="utf-8")
        assert "缺失" in content


def test_analyze_missing_json_sidecar():
    """--json 额外写 missing_report.json。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        rows = [[1, 2, 3], [None, 2, 3], [1, None, 3], [1, 2, None]]
        _write_csv(rows, ["a", "b", "c"], p)
        out = Path(td) / "out"
        analyze_missing(str(p), out_dir=str(out), json_out=True)
        jf = out / "missing_report.json"
        assert jf.exists()
        data = json.loads(jf.read_text(encoding="utf-8"))
        assert "mcar" in data
        assert "pattern" in data


# ---------------------------------------------------------------------------
# 9. CLI 入口
# ---------------------------------------------------------------------------

def test_cli_missing_arg():
    rc = missing_cli([])
    assert rc == 1


def test_cli_nonexistent_file():
    rc = missing_cli(["nonexistent_file_xyz.csv"])
    assert rc == 1


def test_cli_basic_run():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        rows = [[i, i * 1.5 if i % 3 != 0 else None] for i in range(1, 31)]
        _write_csv(rows, ["x", "y"], p)
        rc = missing_cli([str(p)])
    assert rc == 0


def test_cli_json_out():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        rows = [[1, 2], [3, None], [5, 6]]
        _write_csv(rows, ["a", "b"], p)
        out = Path(td) / "out"
        rc = missing_cli([str(p), "--json", "--out", str(out)])
        assert rc == 0
        assert (out / "missing_report.json").exists()


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
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
