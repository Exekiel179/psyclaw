"""Tests for hierarchical OLS regression (P10-1).

Coverage:
  - hierarchical_regression: ΔR², F-change, correct coefficients
  - analyze_hierarchical: CSV entry
  - format_apa_* functions
  - hierarchical_cli: --block1/--block2 parsing, --json
  - Edge cases: single block, many blocks, zero ΔR², collinear
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.hierarchical_regression import (
    hierarchical_regression,
    analyze_hierarchical,
    format_apa_hierarchical_table,
    format_apa_coefficients_table,
    format_apa_hierarchical_paragraph,
    write_hierarchical_report,
    hierarchical_cli,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(tmp_path: pathlib.Path, data: dict) -> str:
    path = tmp_path / "data.csv"
    cols = list(data.keys())
    with open(str(path), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for i in range(len(data[cols[0]])):
            writer.writerow({c: (data[c][i] if data[c][i] is not None else "") for c in cols})
    return str(path)


def _make_data(n: int = 50, seed: int = 42) -> dict:
    import random
    rng = random.Random(seed)
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    x3 = [rng.gauss(0, 1) for _ in range(n)]
    y = [2 * x1[i] + 3 * x2[i] + rng.gauss(0, 0.5) for i in range(n)]
    return {"x1": x1, "x2": x2, "x3": x3, "y": y}


def _assert_raises(exc_type, fn, *args, match=None, **kwargs):
    try:
        fn(*args, **kwargs)
        raise AssertionError(f"Expected {exc_type.__name__} but no exception raised")
    except exc_type as e:
        if match and match not in str(e):
            raise AssertionError(f"Expected match '{match}' in '{e}'")


# ---------------------------------------------------------------------------
# Core: hierarchical_regression
# ---------------------------------------------------------------------------

def test_single_block_r2_high():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1", "x2"]], X_cols)
    r2 = result["blocks_results"][0]["R2"]
    assert 0.9 < r2 <= 1.0, f"Expected high R², got {r2}"


def test_two_blocks_r2_increases():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"]], X_cols)
    r2_b1 = result["blocks_results"][0]["R2"]
    r2_b2 = result["blocks_results"][1]["R2"]
    assert r2_b2 >= r2_b1


def test_delta_r2_correct():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"]], X_cols)
    brs = result["blocks_results"]
    r2_b1 = brs[0]["R2"]
    r2_b2 = brs[1]["R2"]
    delta = brs[1]["delta_R2"]
    assert abs(delta - round(r2_b2 - r2_b1, 4)) < 1e-6


def test_three_blocks_delta_nonnegative():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"], ["x3"]], X_cols)
    for br in result["blocks_results"]:
        assert br["delta_R2"] >= -1e-10


def test_first_block_f_change_equals_model_f():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"]], X_cols)
    br = result["blocks_results"][0]
    assert br["F_change"] == br["F"]


def test_second_block_f_change_formula():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"]], X_cols)
    br2 = result["blocks_results"][1]
    delta = br2["delta_R2"]
    r2 = br2["R2"]
    df_res = br2["df_resid"]
    df_ch = br2["df_change"]
    expected_f = (delta / df_ch) / ((1.0 - r2) / df_res)
    assert abs(br2["F_change"] - expected_f) < 0.01, f"F_change={br2['F_change']}, expected {expected_f}"


def test_p_change_in_range():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"]], X_cols)
    for br in result["blocks_results"]:
        assert 0.0 <= br["p_change"] <= 1.0


def test_n_blocks_metadata():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"], ["x3"]], X_cols)
    assert result["n_blocks"] == 3
    assert len(result["blocks_results"]) == 3


def test_cumulative_vars_grows():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"], ["x3"]], X_cols)
    brs = result["blocks_results"]
    assert brs[0]["cumulative_vars"] == ["x1"]
    assert brs[1]["cumulative_vars"] == ["x1", "x2"]
    assert brs[2]["cumulative_vars"] == ["x1", "x2", "x3"]


def test_final_coefficients_present():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"]], X_cols)
    names = [c["name"] for c in result["final_coefficients"]]
    assert "x1" in names
    assert "x2" in names


def test_coefficient_recovery_known_data():
    import random
    rng = random.Random(99)
    n = 200
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    y = [5.0 * x1[i] + rng.gauss(0, 0.2) for i in range(n)]
    result = hierarchical_regression(y, [["x1"]], {"x1": x1})
    coefs = {c["name"]: c["B"] for c in result["final_coefficients"]}
    assert abs(coefs["x1"] - 5.0) < 0.2, f"B_x1 = {coefs['x1']}"


def test_two_predictors_coefficient_signs():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1", "x2"]], X_cols)
    coefs = {c["name"]: c["B"] for c in result["final_coefficients"]}
    assert coefs["x1"] > 0
    assert coefs["x2"] > 0


def test_df_resid_decreases_with_blocks():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2"], ["x3"]], X_cols)
    brs = result["blocks_results"]
    assert brs[0]["df_resid"] > brs[1]["df_resid"] > brs[2]["df_resid"]


def test_df_change_equals_new_var_count():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"], ["x2", "x3"]], X_cols)
    assert result["blocks_results"][0]["df_change"] == 1
    assert result["blocks_results"][1]["df_change"] == 2


def test_r2_adj_valid():
    import random
    rng = random.Random(7)
    n = 30
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    y = [x1[i] + rng.gauss(0, 1) for i in range(n)]
    result = hierarchical_regression(y, [["x1"], ["x2"]], {"x1": x1, "x2": x2})
    for br in result["blocks_results"]:
        assert br["R2_adj"] is not None


def test_empty_blocks_raises():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    _assert_raises(ValueError, hierarchical_regression, y, [], X_cols, match="至少须提供一个块")


def test_empty_inner_block_raises():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    _assert_raises(ValueError, hierarchical_regression, y, [[], ["x2"]], X_cols, match="不能为空")


def test_duplicate_var_across_blocks_raises():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    _assert_raises(ValueError, hierarchical_regression, y, [["x1"], ["x1", "x2"]], X_cols, match="重复")


def test_n_too_small_raises():
    y = [1.0, 2.0]
    _assert_raises(ValueError, hierarchical_regression, y, [["x1"]], {"x1": [0.0, 1.0]})


def test_high_r2_significant():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1", "x2"]], X_cols)
    r2 = result["blocks_results"][0]["R2"]
    fp = result["blocks_results"][0]["F_p"]
    assert r2 > 0.95
    assert fp < 0.001


def test_irrelevant_block_small_delta():
    import random
    rng = random.Random(42)
    n = 100
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x3 = [rng.gauss(0, 1) for _ in range(n)]
    y = [2 * x1[i] + rng.gauss(0, 0.3) for i in range(n)]
    result = hierarchical_regression(y, [["x1"], ["x3"]], {"x1": x1, "x3": x3})
    delta = result["blocks_results"][1]["delta_R2"]
    assert delta < 0.05


def test_p_change_significant_strong_predictor():
    import random
    rng = random.Random(11)
    n = 100
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    y = [0.1 * x1[i] + 5.0 * x2[i] + rng.gauss(0, 0.5) for i in range(n)]
    result = hierarchical_regression(y, [["x1"], ["x2"]], {"x1": x1, "x2": x2})
    pc = result["blocks_results"][1]["p_change"]
    assert pc < 0.001, f"Expected significant p_change, got {pc}"


def test_result_dv_name():
    d = _make_data()
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    result = hierarchical_regression(y, [["x1"]], X_cols, dv_name="score")
    assert result["dv_name"] == "score"


# ---------------------------------------------------------------------------
# CSV entry
# ---------------------------------------------------------------------------

def test_csv_two_blocks(tmp_path):
    d = _make_data(60, 77)
    csv_path = _make_csv(tmp_path, d)
    result = analyze_hierarchical(
        csv_path, dv="y", blocks=[["x1"], ["x2", "x3"]],
        out_dir=tmp_path, write_files=True,
    )
    assert result["n"] == 60
    assert result["n_blocks"] == 2
    assert (tmp_path / "hierarchical_regression_report.md").exists()
    assert (tmp_path / "hierarchical_regression_report.json").exists()


def test_csv_missing_values_excluded(tmp_path):
    d = _make_data(50, 3)
    d["x1"][5] = None
    d["y"][10] = None
    csv_path = _make_csv(tmp_path, d)
    result = analyze_hierarchical(csv_path, dv="y", blocks=[["x1"]], out_dir=tmp_path)
    assert result["n"] <= 48
    assert result["n_excluded"] >= 2


def test_csv_no_write(tmp_path):
    d = _make_data(40, 5)
    csv_path = _make_csv(tmp_path, d)
    result = analyze_hierarchical(
        csv_path, dv="y", blocks=[["x1"], ["x2"]], write_files=False
    )
    assert "report_md" not in result


def test_csv_missing_dv_raises(tmp_path):
    d = _make_data(30, 6)
    csv_path = _make_csv(tmp_path, d)
    try:
        analyze_hierarchical(csv_path, dv="nonexistent", blocks=[["x1"]])
        assert False, "Should raise"
    except (ValueError, KeyError):
        pass


def test_csv_duplicate_var_raises(tmp_path):
    d = _make_data(30, 6)
    csv_path = _make_csv(tmp_path, d)
    _assert_raises(ValueError, analyze_hierarchical,
                   csv_path, dv="y", blocks=[["x1"], ["x1"]], match="重复")


def test_json_sidecar_parseable(tmp_path):
    d = _make_data(50, 8)
    csv_path = _make_csv(tmp_path, d)
    analyze_hierarchical(csv_path, dv="y", blocks=[["x1"], ["x2"]], out_dir=tmp_path)
    jpath = tmp_path / "hierarchical_regression_report.json"
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert "blocks_results" in data
    assert "n_blocks" in data


# ---------------------------------------------------------------------------
# APA-7 formatting
# ---------------------------------------------------------------------------

def _make_format_result():
    d = _make_data(60, 22)
    y = d["y"]
    X_cols = {k: d[k] for k in ("x1", "x2", "x3")}
    return hierarchical_regression(y, [["x1"], ["x2"], ["x3"]], X_cols, dv_name="score")


def test_hierarchical_table_contains_header():
    table = format_apa_hierarchical_table(_make_format_result())
    assert "Δ" in table or "ΔR" in table
    assert "块" in table


def test_hierarchical_table_three_block_rows():
    table = format_apa_hierarchical_table(_make_format_result())
    # Data rows use "| 块N |" (N=1,2,3); header uses "| 块 |"
    assert "| 块1 |" in table
    assert "| 块2 |" in table
    assert "| 块3 |" in table


def test_coefficients_table_all_vars():
    table = format_apa_coefficients_table(_make_format_result())
    assert "x1" in table
    assert "x2" in table
    assert "x3" in table


def test_paragraph_all_blocks():
    para = format_apa_hierarchical_paragraph(_make_format_result())
    assert "步骤 1" in para
    assert "步骤 2" in para
    assert "步骤 3" in para


def test_paragraph_contains_r2():
    para = format_apa_hierarchical_paragraph(_make_format_result())
    assert "R*²" in para or "R²" in para


def test_no_nan_in_table():
    table = format_apa_hierarchical_table(_make_format_result())
    assert "nan" not in table.lower()


def test_write_report_creates_files(tmp_path):
    result = _make_format_result()
    md, js = write_hierarchical_report(result, out_dir=tmp_path)
    assert md.exists()
    assert js.exists()


def test_json_no_ols_key(tmp_path):
    result = _make_format_result()
    _, js = write_hierarchical_report(result, out_dir=tmp_path)
    data = json.loads(js.read_text(encoding="utf-8"))
    for br in data["blocks_results"]:
        assert "ols" not in br


def test_paragraph_sig_predictor():
    import random
    rng = random.Random(55)
    n = 80
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    y = [0.0 * x1[i] + 5.0 * x2[i] + rng.gauss(0, 0.2) for i in range(n)]
    result = hierarchical_regression(y, [["x1"], ["x2"]], {"x1": x1, "x2": x2})
    para = format_apa_hierarchical_paragraph(result)
    assert "x2" in para


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class _CapturedOut:
    def __init__(self):
        self.data = ""
    def write(self, s):
        self.data += s
    def flush(self):
        pass


def _cli_run(argv):
    cap = _CapturedOut()
    old = sys.stdout
    sys.stdout = cap
    try:
        rc = hierarchical_cli(argv)
    finally:
        sys.stdout = old
    return rc, cap.data


def test_cli_basic(tmp_path):
    d = _make_data(50, 33)
    csv_path = _make_csv(tmp_path, d)
    rc, out = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1", "--block2", "x2,x3", "--out", str(tmp_path)])
    assert rc == 0, f"rc={rc}, out={out}"


def test_cli_json_output(tmp_path):
    d = _make_data(50, 44)
    csv_path = _make_csv(tmp_path, d)
    rc, out = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1", "--block2", "x2", "--json"])
    assert rc == 0
    data = json.loads(out)
    assert "blocks_results" in data


def test_cli_no_blocks_returns_error(tmp_path):
    d = _make_data(30, 1)
    csv_path = _make_csv(tmp_path, d)
    rc, _ = _cli_run([str(csv_path), "--dv", "y"])
    assert rc == 1


def test_cli_bad_csv_returns_error():
    rc, _ = _cli_run(["nonexistent.csv", "--dv", "y", "--block1", "x1"])
    assert rc == 1


def test_cli_single_block(tmp_path):
    d = _make_data(40, 55)
    csv_path = _make_csv(tmp_path, d)
    rc, _ = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1,x2", "--out", str(tmp_path)])
    assert rc == 0


def test_cli_three_blocks(tmp_path):
    d = _make_data(60, 66)
    csv_path = _make_csv(tmp_path, d)
    rc, out = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1", "--block2", "x2", "--block3", "x3", "--out", str(tmp_path)])
    assert rc == 0


def test_cli_json_n_blocks(tmp_path):
    d = _make_data(50, 77)
    csv_path = _make_csv(tmp_path, d)
    rc, out = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1", "--block2", "x2", "--json"])
    data = json.loads(out)
    assert data["n_blocks"] == 2


def test_cli_delta_r2_in_json(tmp_path):
    d = _make_data(50, 88)
    csv_path = _make_csv(tmp_path, d)
    rc, out = _cli_run([str(csv_path), "--dv", "y", "--block1", "x1", "--block2", "x2", "--json"])
    data = json.loads(out)
    for br in data["blocks_results"]:
        assert "delta_R2" in br


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

def test_r2_between_0_and_1():
    import random
    for seed in range(10):
        rng = random.Random(seed)
        n = 30
        x1 = [rng.gauss(0, 1) for _ in range(n)]
        x2 = [rng.gauss(0, 1) for _ in range(n)]
        y = [rng.gauss(0, 1) for _ in range(n)]
        result = hierarchical_regression(y, [["x1"], ["x2"]], {"x1": x1, "x2": x2})
        for br in result["blocks_results"]:
            assert -1e-9 <= br["R2"] <= 1.0 + 1e-9


def test_f_change_positive():
    import random
    for seed in range(5):
        rng = random.Random(seed + 100)
        n = 40
        x1 = [rng.gauss(0, 1) for _ in range(n)]
        x2 = [rng.gauss(0, 1) for _ in range(n)]
        y = [rng.gauss(0, 1) for _ in range(n)]
        result = hierarchical_regression(y, [["x1"], ["x2"]], {"x1": x1, "x2": x2})
        for br in result["blocks_results"]:
            if br["F_change"] is not None:
                assert br["F_change"] >= 0.0


def test_sum_delta_r2_equals_final_r2():
    import random
    rng = random.Random(999)
    n = 60
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    x3 = [rng.gauss(0, 1) for _ in range(n)]
    y = [rng.gauss(0, 1) for _ in range(n)]
    result = hierarchical_regression(
        y, [["x1"], ["x2"], ["x3"]], {"x1": x1, "x2": x2, "x3": x3}
    )
    total_delta = sum(br["delta_R2"] for br in result["blocks_results"])
    final_r2 = result["blocks_results"][-1]["R2"]
    assert abs(total_delta - final_r2) < 1e-6, f"sum={total_delta}, R²={final_r2}"


def test_ci_width_positive():
    import random
    rng = random.Random(77)
    n = 50
    x1 = [rng.gauss(0, 1) for _ in range(n)]
    x2 = [rng.gauss(0, 1) for _ in range(n)]
    y = [x1[i] + 2 * x2[i] + rng.gauss(0, 0.5) for i in range(n)]
    result = hierarchical_regression(y, [["x1", "x2"]], {"x1": x1, "x2": x2})
    for c in result["final_coefficients"]:
        if c["ci_lower"] is not None and c["ci_upper"] is not None:
            assert c["ci_upper"] > c["ci_lower"]


# ---------------------------------------------------------------------------
# Self-run block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    _pass = 0
    _fail = 0
    _errors = []

    def _run(name, fn, *args, **kwargs):
        global _pass, _fail
        try:
            fn(*args, **kwargs)
            _pass += 1
            print(f"  ✓ {name}")
        except Exception as exc:
            _fail += 1
            _errors.append((name, exc))
            print(f"  ✗ {name}: {exc}")

    def _tmp():
        return pathlib.Path(tempfile.mkdtemp())

    # Core
    _run("single_block_r2_high", test_single_block_r2_high)
    _run("two_blocks_r2_increases", test_two_blocks_r2_increases)
    _run("delta_r2_correct", test_delta_r2_correct)
    _run("three_blocks_delta_nonneg", test_three_blocks_delta_nonnegative)
    _run("first_block_f_change", test_first_block_f_change_equals_model_f)
    _run("second_block_f_change_formula", test_second_block_f_change_formula)
    _run("p_change_in_range", test_p_change_in_range)
    _run("n_blocks_metadata", test_n_blocks_metadata)
    _run("cumulative_vars_grows", test_cumulative_vars_grows)
    _run("final_coefficients_present", test_final_coefficients_present)
    _run("coefficient_recovery", test_coefficient_recovery_known_data)
    _run("two_pred_signs", test_two_predictors_coefficient_signs)
    _run("df_resid_decreases", test_df_resid_decreases_with_blocks)
    _run("df_change_equals_new_vars", test_df_change_equals_new_var_count)
    _run("r2_adj_valid", test_r2_adj_valid)
    _run("empty_blocks_raises", test_empty_blocks_raises)
    _run("empty_inner_block_raises", test_empty_inner_block_raises)
    _run("duplicate_var_raises", test_duplicate_var_across_blocks_raises)
    _run("n_too_small_raises", test_n_too_small_raises)
    _run("high_r2_significant", test_high_r2_significant)
    _run("irrelevant_block_small_delta", test_irrelevant_block_small_delta)
    _run("p_change_sig_strong_pred", test_p_change_significant_strong_predictor)
    _run("result_dv_name", test_result_dv_name)

    # CSV
    _run("csv_two_blocks", test_csv_two_blocks, _tmp())
    _run("csv_missing_excluded", test_csv_missing_values_excluded, _tmp())
    _run("csv_no_write", test_csv_no_write, _tmp())
    _run("csv_missing_dv_raises", test_csv_missing_dv_raises, _tmp())
    _run("csv_duplicate_var_raises", test_csv_duplicate_var_raises, _tmp())
    _run("json_sidecar_parseable", test_json_sidecar_parseable, _tmp())

    # Formatting
    _run("table_header", test_hierarchical_table_contains_header)
    _run("table_three_rows", test_hierarchical_table_three_block_rows)
    _run("coef_table_all_vars", test_coefficients_table_all_vars)
    _run("para_all_blocks", test_paragraph_all_blocks)
    _run("para_has_r2", test_paragraph_contains_r2)
    _run("no_nan_in_table", test_no_nan_in_table)
    _run("write_report_files", test_write_report_creates_files, _tmp())
    _run("json_no_ols_key", test_json_no_ols_key, _tmp())
    _run("para_sig_predictor", test_paragraph_sig_predictor)

    # CLI
    _run("cli_basic", test_cli_basic, _tmp())
    _run("cli_json_output", test_cli_json_output, _tmp())
    _run("cli_no_blocks_error", test_cli_no_blocks_returns_error, _tmp())
    _run("cli_bad_csv_error", test_cli_bad_csv_returns_error)
    _run("cli_single_block", test_cli_single_block, _tmp())
    _run("cli_three_blocks", test_cli_three_blocks, _tmp())
    _run("cli_json_n_blocks", test_cli_json_n_blocks, _tmp())
    _run("cli_delta_in_json", test_cli_delta_r2_in_json, _tmp())

    # Properties
    _run("r2_between_0_and_1", test_r2_between_0_and_1)
    _run("f_change_positive", test_f_change_positive)
    _run("sum_delta_r2_equals_final", test_sum_delta_r2_equals_final_r2)
    _run("ci_width_positive", test_ci_width_positive)

    print(f"\n{'=' * 50}")
    print(f"结果：{_pass} passed, {_fail} failed")
    if _errors:
        print("\n失败详情：")
        for name, exc in _errors:
            print(f"  {name}: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
        sys.exit(1)
    else:
        print("全部通过 ✓")
        sys.exit(0)
