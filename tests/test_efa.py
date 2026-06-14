"""探索性因子分析 (EFA) 测试套件 — 44 例，stdlib only。

涵盖：Jacobi 特征值分解 / Pearson 相关矩阵 / SMC / PAF 提取 /
       Varimax 旋转 / APA-7 格式化 / CSV 主入口 / CLI 处理器
"""

from __future__ import annotations

import csv
import io
import json
import math
import pathlib
import sys
import tempfile
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.efa import (
    _corr_matrix,
    _jacobi_eig,
    _smc,
    _varimax,
    analyze_efa,
    compute_efa,
    efa_cli,
    format_apa_efa,
    write_efa_report,
)


# ─── 辅助 ────────────────────────────────────────────────────────────────────

def _write_csv(rows: list[dict], tmp_dir: str, fname: str = "data.csv") -> str:
    p = pathlib.Path(tmp_dir) / fname
    if not rows:
        p.write_text("")
        return str(p)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return str(p)


def _make_two_factor_data(n: int = 120) -> list[list[float]]:
    """生成 6 变量、2 因子结构数据（固定种子，可重复）。

    F1 → x1/x2/x3，F2 → x4/x5/x6（载荷≈0.8）。
    """
    import random
    rng = random.Random(42)
    f1 = [rng.gauss(0, 1) for _ in range(n)]
    f2 = [rng.gauss(0, 1) for _ in range(n)]
    data = []
    for fl in (f1, f1, f1):
        data.append([0.8 * fi + 0.6 * rng.gauss(0, 1) for fi in fl])
    for fl in (f2, f2, f2):
        data.append([0.8 * fi + 0.6 * rng.gauss(0, 1) for fi in fl])
    return data


def _capture(fn):
    """运行 fn()，捕获 stdout，返回 (result, captured_str)。"""
    old = sys.stdout
    sio = io.StringIO()
    sys.stdout = sio
    try:
        result = fn()
    finally:
        sys.stdout = old
    return result, sio.getvalue()


# ─── 1. Jacobi 特征值分解 ──────────────────────────────────────────────────

def test_jacobi_2x2_diagonal():
    A = [[3.0, 0.0], [0.0, 1.0]]
    evals, _ = _jacobi_eig(A)
    assert abs(evals[0] - 3.0) < 1e-9
    assert abs(evals[1] - 1.0) < 1e-9


def test_jacobi_identity():
    n = 4
    I = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    evals, _ = _jacobi_eig(I)
    assert all(abs(v - 1.0) < 1e-9 for v in evals)


def test_jacobi_sorted_descending():
    A = [[1.0, 0.5, 0.0], [0.5, 2.0, 0.3], [0.0, 0.3, 3.0]]
    evals, _ = _jacobi_eig(A)
    assert evals[0] >= evals[1] >= evals[2]


def test_jacobi_2x2_known_eigenvalues():
    # [[5, 2], [2, 5]] → λ = 7, 3
    A = [[5.0, 2.0], [2.0, 5.0]]
    evals, _ = _jacobi_eig(A)
    assert abs(evals[0] - 7.0) < 1e-9
    assert abs(evals[1] - 3.0) < 1e-9


def test_jacobi_eigenvectors_orthonormal():
    A = [[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]]
    evals, evecs = _jacobi_eig(A)
    n = len(A)
    for col in range(n):
        norm = sum(evecs[row][col] ** 2 for row in range(n))
        assert abs(norm - 1.0) < 1e-8, f"col {col} norm={norm:.6f}"


def test_jacobi_eigenvalue_sum_equals_trace():
    A = [[3.0, 0.7, 0.3], [0.7, 2.0, 0.1], [0.3, 0.1, 1.5]]
    evals, _ = _jacobi_eig(A)
    trace = sum(A[i][i] for i in range(3))
    assert abs(sum(evals) - trace) < 1e-8


def test_jacobi_positive_definite_positive_evals():
    A = [[1.0, 0.5, 0.3], [0.5, 1.0, 0.4], [0.3, 0.4, 1.0]]
    evals, _ = _jacobi_eig(A)
    assert all(v > 0 for v in evals)


# ─── 2. Pearson 相关矩阵 ───────────────────────────────────────────────────

def test_corr_diagonal_is_one():
    data = [[1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 1.0, 3.0]]
    R = _corr_matrix(data)
    assert R[0][0] == 1.0
    assert R[1][1] == 1.0


def test_corr_symmetry():
    import random
    rng = random.Random(7)
    data = [[rng.gauss(0, 1) for _ in range(30)] for _ in range(4)]
    R = _corr_matrix(data)
    for i in range(4):
        for j in range(4):
            assert abs(R[i][j] - R[j][i]) < 1e-12


def test_corr_perfect_positive():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    R = _corr_matrix([x, [v * 2.0 for v in x]])
    assert abs(R[0][1] - 1.0) < 1e-10


def test_corr_perfect_negative():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    R = _corr_matrix([x, [-v for v in x]])
    assert abs(R[0][1] + 1.0) < 1e-10


def test_corr_values_in_range():
    import random
    rng = random.Random(99)
    data = [[rng.gauss(0, 1) for _ in range(50)] for _ in range(5)]
    R = _corr_matrix(data)
    for i in range(5):
        for j in range(5):
            assert -1.0 <= R[i][j] <= 1.0


# ─── 3. SMC ──────────────────────────────────────────────────────────────────

def test_smc_identity_near_zero():
    R = [[1.0, 0.0], [0.0, 1.0]]
    smc = _smc(R)
    for v in smc:
        assert abs(v) < 1e-6


def test_smc_in_zero_one():
    R = [[1.0, 0.6, 0.3], [0.6, 1.0, 0.5], [0.3, 0.5, 1.0]]
    smc = _smc(R)
    for v in smc:
        assert 0.0 <= v <= 1.0, f"SMC out of range: {v}"


def test_smc_increases_with_correlation():
    R_low = [[1.0, 0.1], [0.1, 1.0]]
    R_high = [[1.0, 0.9], [0.9, 1.0]]
    assert _smc(R_high)[0] > _smc(R_low)[0]


# ─── 4. compute_efa ───────────────────────────────────────────────────────────

def test_efa_loadings_shape():
    data = _make_two_factor_data()
    result = compute_efa(data, n_factors=2)
    L = result["loadings"]
    assert len(L) == 6
    assert len(L[0]) == 2


def test_efa_communalities_in_zero_one():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    for h in result["communalities"]:
        assert 0.0 <= h <= 1.0, f"h²={h}"


def test_efa_uniqueness_complement():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    for h, u in zip(result["communalities"], result["uniqueness"]):
        assert abs(h + u - 1.0) < 1e-9


def test_efa_cumulative_pct_correct():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    pct = result["pct_var"]
    cum = result["cum_pct_var"]
    assert abs(cum[-1] - sum(pct)) < 1e-9


def test_efa_eigenvalues_sorted_descending():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    ev = result["eigenvalues"]
    assert all(ev[i] >= ev[i + 1] for i in range(len(ev) - 1))


def test_efa_kaiser_auto_detect():
    result = compute_efa(_make_two_factor_data(), n_factors=0)
    assert result["n_factors"] >= 1
    assert any("Kaiser" in w for w in result["warnings"])


def test_efa_rotation_none_equals_unrotated():
    data = _make_two_factor_data()
    result = compute_efa(data, n_factors=2, rotation="none")
    assert result["loadings"] == result["loadings_unrotated"]
    assert result["rotation"] == "none"


def test_efa_pca_method_works():
    result = compute_efa(_make_two_factor_data(), n_factors=2, method="pca")
    assert result["method"] == "pca"
    assert len(result["loadings"]) == 6


def test_efa_two_factor_structure_detected():
    """强因子结构：前 3 与后 3 变量应主载荷于不同因子。"""
    result = compute_efa(_make_two_factor_data(), n_factors=2, rotation="varimax")
    L = result["loadings"]
    dom1 = [max(range(2), key=lambda f: abs(L[i][f])) for i in range(3)]
    dom2 = [max(range(2), key=lambda f: abs(L[i][f])) for i in range(3, 6)]
    assert len(set(dom1)) == 1, "前 3 变量主因子不一致"
    assert len(set(dom2)) == 1, "后 3 变量主因子不一致"
    assert dom1[0] != dom2[0], "两组变量应主载荷于不同因子"


def test_efa_ssl_sums_to_cumulative():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    expected = sum(result["ssl"]) / result["n_vars"] * 100.0
    assert abs(result["cum_pct_var"][-1] - expected) < 1e-8


def test_efa_cols_preserved():
    cols = ["a", "b", "c", "d", "e", "f"]
    result = compute_efa(_make_two_factor_data(), n_factors=2, cols=cols)
    assert result["cols"] == cols


def test_efa_single_factor_no_rotation_matrix():
    result = compute_efa(_make_two_factor_data(), n_factors=1)
    assert result["n_factors"] == 1
    assert result["rotation_matrix"] is None


def test_efa_error_too_few_variables():
    try:
        compute_efa([[1.0, 2.0, 3.0]])
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "至少 2 个变量" in str(e)


def test_efa_pct_var_positive():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    assert all(v > 0 for v in result["pct_var"])


def test_efa_corr_matrix_diagonal_one():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    R = result["corr_matrix"]
    assert all(abs(R[i][i] - 1.0) < 1e-12 for i in range(6))


def test_efa_scree_ascii_non_empty():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    assert len(result["scree_ascii"]) > 20


def test_efa_small_n_warning():
    """n < p+1 时应触发偏小警告。"""
    import random
    rng = random.Random(17)
    # 5 变量，4 观测 → n=4 < p+1=6
    small = [[rng.gauss(0, 1) for _ in range(4)] for _ in range(5)]
    result = compute_efa(small, n_factors=1)
    assert any("偏小" in w for w in result["warnings"])


# ─── 5. Varimax 旋转 ──────────────────────────────────────────────────────────

def test_varimax_single_factor_unchanged():
    L = [[0.8], [0.7], [0.6]]
    L_rot, T = _varimax(L)
    for i in range(3):
        assert abs(L_rot[i][0] - L[i][0]) < 1e-10


def test_varimax_rotation_matrix_orthogonal():
    from psyclaw.psych.efa import _extract_paf
    data = _make_two_factor_data()
    R = _corr_matrix(data)
    L, _, _ = _extract_paf(R, 2)
    _, T = _varimax(L)
    k = len(T)
    for i in range(k):
        for j in range(k):
            dot = sum(T[r][i] * T[r][j] for r in range(k))
            expected = 1.0 if i == j else 0.0
            assert abs(dot - expected) < 1e-6, f"T^T T [{i},{j}] = {dot:.6f}"


def test_varimax_criterion_non_decreasing():
    L = [[0.6, 0.3], [0.5, 0.4], [0.4, 0.5], [0.3, 0.6]]
    p = len(L)
    crit_before = sum(
        p * sum(L[i][f] ** 4 for i in range(p))
        - sum(L[i][f] ** 2 for i in range(p)) ** 2
        for f in range(2)
    )
    L_rot, _ = _varimax(L)
    crit_after = sum(
        p * sum(L_rot[i][f] ** 4 for i in range(p))
        - sum(L_rot[i][f] ** 2 for i in range(p)) ** 2
        for f in range(2)
    )
    assert crit_after >= crit_before - 1e-8


# ─── 6. format_apa_efa ────────────────────────────────────────────────────────

def test_format_contains_factor_headers():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    text = format_apa_efa(result)
    assert "*F1*" in text and "*F2*" in text


def test_format_contains_h2():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    assert "*h*²" in format_apa_efa(result)


def test_format_contains_ssl_and_variance():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    text = format_apa_efa(result)
    assert "SSL" in text
    assert "方差解释" in text
    assert "累积方差" in text


def test_format_contains_paragraph():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    text = format_apa_efa(result)
    assert "探索性因子分析" in text


def test_format_bolded_strong_loadings():
    result = compute_efa(_make_two_factor_data(), n_factors=2)
    text = format_apa_efa(result, min_loading=0.30)
    assert "**" in text


# ─── 7. write_efa_report ─────────────────────────────────────────────────────

def test_write_creates_md_and_json():
    with tempfile.TemporaryDirectory() as tmp:
        result = compute_efa(_make_two_factor_data(), n_factors=2)
        md, js = write_efa_report(result, out_dir=tmp)
        assert md.exists()
        assert js.exists()


def test_write_json_parseable():
    with tempfile.TemporaryDirectory() as tmp:
        result = compute_efa(_make_two_factor_data(), n_factors=2)
        _, js = write_efa_report(result, out_dir=tmp)
        parsed = json.loads(js.read_text(encoding="utf-8"))
        assert "loadings" in parsed
        assert "communalities" in parsed


def test_write_md_contains_scree():
    with tempfile.TemporaryDirectory() as tmp:
        result = compute_efa(_make_two_factor_data(), n_factors=2)
        md, _ = write_efa_report(result, out_dir=tmp)
        assert "碎石图" in md.read_text(encoding="utf-8")


# ─── 8. analyze_efa ──────────────────────────────────────────────────────────

def test_analyze_reads_csv():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data()
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(len(data[0]))]
        csv_path = _write_csv(rows, tmp)
        result, _ = _capture(lambda: analyze_efa(csv_path, cols=cols, n_factors=2))
        assert result["n_vars"] == 6


def test_analyze_excludes_missing():
    with tempfile.TemporaryDirectory() as tmp:
        rows = [{"a": 1, "b": 2}, {"a": "", "b": 3},
                {"a": 3, "b": 4}, {"a": 4, "b": 5}, {"a": 5, "b": 6}]
        csv_path = _write_csv(rows, tmp)
        result, _ = _capture(lambda: analyze_efa(csv_path, cols=["a", "b"], n_factors=1))
        assert result["n_excluded"] == 1
        assert result["n_obs"] == 4


def test_analyze_auto_cols():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=60)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(60)]
        csv_path = _write_csv(rows, tmp)
        result, _ = _capture(lambda: analyze_efa(csv_path, cols=[], n_factors=2))
        assert result["n_vars"] == 6


def test_analyze_file_not_found():
    try:
        analyze_efa("/nonexistent/path.csv", cols=["x"])
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_analyze_json_output():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=60)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(60)]
        csv_path = _write_csv(rows, tmp)
        _, captured = _capture(
            lambda: analyze_efa(csv_path, cols=cols, n_factors=2, as_json=True)
        )
        parsed = json.loads(captured)
        assert "loadings" in parsed


def test_analyze_writes_sidecar():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=60)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(60)]
        csv_path = _write_csv(rows, tmp)
        out_dir = str(pathlib.Path(tmp) / "out")
        _capture(lambda: analyze_efa(csv_path, cols=cols, n_factors=2, out_dir=out_dir))
        assert (pathlib.Path(out_dir) / "efa_report.md").exists()


# ─── 9. efa_cli ──────────────────────────────────────────────────────────────

def test_cli_basic_exit_0():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=80)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(80)]
        csv_path = _write_csv(rows, tmp)
        _, _ = _capture(
            lambda: efa_cli([csv_path, "--cols", "x1,x2,x3,x4,x5,x6", "--n-factors", "2"])
        )
        rc, _ = _capture(
            lambda: efa_cli([csv_path, "--cols", "x1,x2,x3,x4,x5,x6", "--n-factors", "2"])
        )
        assert rc == 0


def test_cli_bad_file_exit_1():
    rc, _ = _capture(lambda: efa_cli(["/no/such/file.csv", "--cols", "x"]))
    assert rc == 1


def test_cli_rotation_none():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=60)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(60)]
        csv_path = _write_csv(rows, tmp)
        rc, _ = _capture(
            lambda: efa_cli([csv_path, "--cols", "x1,x2,x3,x4,x5,x6",
                             "--n-factors", "2", "--rotation", "none"])
        )
        assert rc == 0


def test_cli_json_flag():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=60)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(60)]
        csv_path = _write_csv(rows, tmp)
        rc, captured = _capture(
            lambda: efa_cli([csv_path, "--cols", "x1,x2,x3,x4,x5,x6",
                             "--n-factors", "2", "--json"])
        )
        assert rc == 0
        parsed = json.loads(captured)
        assert "loadings" in parsed


def test_cli_auto_kaiser():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_two_factor_data(n=80)
        cols = [f"x{i+1}" for i in range(6)]
        rows = [{cols[i]: data[i][j] for i in range(6)} for j in range(80)]
        csv_path = _write_csv(rows, tmp)
        rc, _ = _capture(
            lambda: efa_cli([csv_path, "--cols", "x1,x2,x3,x4,x5,x6"])
        )
        assert rc == 0


# ─── 自跑块 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _fns = [(k, v) for k, v in sorted(globals().items())
            if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for _name, _fn in _fns:
        try:
            _fn()
            passed += 1
            print(f"  PASS  {_name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {_name}")
            traceback.print_exc()
    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  ({failed} FAILED)")
    raise SystemExit(1 if failed else 0)
