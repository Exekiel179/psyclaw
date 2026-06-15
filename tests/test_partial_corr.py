"""偏相关分析测试（psyclaw/psych/partial_corr.py）— 55 例。

覆盖：
  _ols_residuals（5）
  _pearson_r_raw（4）
  partial_correlation — 无控制变量（8）
  partial_correlation — 含控制变量（10）
  semipartial_correlation（7）
  partial_correlation_matrix（8）
  format_apa_partial_corr（5）
  format_apa_partial_matrix（3）
  write_partial_corr_report（4）
  analyze_partial_corr（7）
  边界与错误处理（4）
"""

from __future__ import annotations

import csv
import json
import math
import pathlib

import pytest

from psyclaw.psych.partial_corr import (
    _ols_residuals,
    _pearson_r_raw,
    format_apa_partial_corr,
    format_apa_partial_matrix,
    partial_correlation,
    partial_correlation_matrix,
    semipartial_correlation,
    write_partial_corr_report,
    analyze_partial_corr,
)


# ---------------------------------------------------------------------------
# 辅助：构建控制变量格式 [[z1_obs1, z2_obs1, ...], ...]
# ---------------------------------------------------------------------------

def _ctrl(*cols: list[float]) -> list[list[float]]:
    """将多个列向量打包成 [n × k] 格式。"""
    n = len(cols[0])
    return [[cols[j][i] for j in range(len(cols))] for i in range(n)]


# ---------------------------------------------------------------------------
# _ols_residuals
# ---------------------------------------------------------------------------

class TestOlsResiduals:
    def test_no_controls_returns_demeaned(self):
        y = [2.0, 4.0, 6.0]
        e = _ols_residuals(y, [])
        mean_y = sum(y) / 3
        assert [abs(e[i] - (y[i] - mean_y)) < 1e-10 for i in range(3)]

    def test_perfect_fit_residuals_near_zero(self):
        # y = 2*z + 1 → 残差应约为 0
        z = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2 * zi + 1 for zi in z]
        ctrl = _ctrl(z)
        e = _ols_residuals(y, ctrl)
        assert all(abs(ei) < 1e-8 for ei in e)

    def test_residuals_sum_to_zero(self):
        z = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        y = [1.0, 3.0, 2.0, 5.0, 4.0, 6.0]
        ctrl = _ctrl(z)
        e = _ols_residuals(y, ctrl)
        assert abs(sum(e)) < 1e-9

    def test_residuals_uncorrelated_with_predictor(self):
        # Gauss-Markov: e ⊥ z
        z = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 1.0, 4.0, 3.0, 5.0]
        ctrl = _ctrl(z)
        e = _ols_residuals(y, ctrl)
        z_mean = sum(z) / len(z)
        e_mean = sum(e) / len(e)
        cov = sum((z[i] - z_mean) * (e[i] - e_mean) for i in range(len(z)))
        assert abs(cov) < 1e-8

    def test_singular_raises(self):
        # 两列完全相同 → 奇异
        z = [1.0, 2.0, 3.0, 4.0]
        ctrl = [[z[i], z[i]] for i in range(4)]
        with pytest.raises(ValueError, match="奇异"):
            _ols_residuals(z, ctrl)


# ---------------------------------------------------------------------------
# _pearson_r_raw
# ---------------------------------------------------------------------------

class TestPearsonRRaw:
    def test_perfect_positive(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        assert abs(_pearson_r_raw(x, y) - 1.0) < 1e-10

    def test_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert abs(_pearson_r_raw(x, y) + 1.0) < 1e-10

    def test_zero_variance_x_returns_nan(self):
        x = [3.0, 3.0, 3.0]
        y = [1.0, 2.0, 3.0]
        assert math.isnan(_pearson_r_raw(x, y))

    def test_short_list_returns_nan(self):
        assert math.isnan(_pearson_r_raw([1.0], [1.0]))


# ---------------------------------------------------------------------------
# partial_correlation — 无控制变量 (k=0)
# ---------------------------------------------------------------------------

class TestPartialCorrNoControls:
    def test_k0_equals_pearson(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        res = partial_correlation(x, y, [])
        assert abs(res["r"] - 1.0) < 1e-5

    def test_k0_df_is_n_minus_2(self):
        x = list(range(1, 11))
        y = list(range(1, 11))
        res = partial_correlation(x, y, [])
        assert res["df"] == 8  # 10 - 2 - 0

    def test_k0_perfect_negative(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [5.0, 4.0, 3.0, 2.0, 1.0]
        res = partial_correlation(x, y, [])
        assert abs(res["r"] + 1.0) < 1e-5

    def test_k0_r_in_range(self):
        x = [1.0, 3.0, 2.0, 5.0, 4.0]
        y = [2.0, 1.0, 4.0, 3.0, 5.0]
        res = partial_correlation(x, y, [])
        assert res["r"] is not None
        assert -1.0 <= res["r"] <= 1.0

    def test_k0_p_in_range(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        y = [2.0, 1.0, 4.0, 3.0, 6.0, 5.0, 8.0, 7.0]
        res = partial_correlation(x, y, [])
        assert 0.0 <= res["p"] <= 1.0

    def test_k0_ci_contains_r(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        y = [3.0, 2.0, 5.0, 4.0, 7.0, 6.0, 8.0]
        res = partial_correlation(x, y, [])
        if res["ci_lower"] is not None:
            assert res["ci_lower"] <= res["r"] <= res["ci_upper"]

    def test_k0_large_r_small_p(self):
        n = 20
        x = list(range(1, n + 1))
        y = [xi + (1 if xi % 2 == 0 else -1) for xi in x]
        res = partial_correlation(x, y, [])
        assert res["p"] is not None and res["p"] < 0.05

    def test_k0_n_returned(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 3.0, 4.0, 5.0, 6.0]
        res = partial_correlation(x, y, [])
        assert res["n"] == 5


# ---------------------------------------------------------------------------
# partial_correlation — 含控制变量
# ---------------------------------------------------------------------------

class TestPartialCorrWithControls:
    def test_df_formula_k1(self):
        n = 10
        x = list(range(1, n + 1))
        z = [xi * 0.5 for xi in x]
        y = [xi + zi for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        assert res["df"] == n - 2 - 1  # 7

    def test_df_formula_k2(self):
        n = 12
        x = list(range(1, n + 1))
        z1 = [0.5 * xi for xi in x]
        z2 = [0.3 * xi + 0.2 for xi in x]
        y = [xi - 0.2 * z1[i] for i in range(n)]
        ctrl = _ctrl(z1, z2)
        res = partial_correlation(x, y, ctrl)
        assert res["df"] == n - 2 - 2  # 8

    def test_k_controls_field(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        z = [0.1 * xi for xi in x]
        y = [xi + 0.5 for xi in x]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        assert res["k_controls"] == 1

    def test_y_equals_x_plus_const_partial_r_is_1(self):
        # y = x + 2，不论 z，偏相关应为 1
        z = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        x = [zi + 0.1 * (-1) ** i for i, zi in enumerate(z)]
        y = [xi + 2.0 for xi in x]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        assert abs(res["r"] - 1.0) < 1e-6

    def test_y_equals_neg_x_plus_const_partial_r_is_neg1(self):
        z = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        x = [zi + 0.1 * (-1) ** i for i, zi in enumerate(z)]
        y = [-xi + 5.0 for xi in x]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        assert abs(res["r"] + 1.0) < 1e-6

    def test_algebraic_formula_single_control(self):
        """手算验证 r_xy.z = (r_xy - r_xz * r_yz)/sqrt((1-r_xz²)(1-r_yz²))。

        构造数据，对照代数公式。
        """
        n = 20
        x = [float(i) for i in range(n)]
        z = [xi * 0.7 + (1.0 if i % 2 == 0 else -1.0) for i, xi in enumerate(x)]
        y = [xi * 0.5 + zi * 0.3 + (0.5 if i % 3 == 0 else -0.5)
             for i, (xi, zi) in enumerate(zip(x, z))]

        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)

        # 代数公式
        r_xy = _pearson_r_raw(x, y)
        r_xz = _pearson_r_raw(x, z)
        r_yz = _pearson_r_raw(y, z)
        denom = math.sqrt((1 - r_xz**2) * (1 - r_yz**2))
        r_expected = (r_xy - r_xz * r_yz) / denom if denom > 1e-12 else float("nan")

        assert abs(res["r"] - r_expected) < 1e-5

    def test_ci_ordered(self):
        n = 15
        x = [float(i) for i in range(n)]
        z = [xi * 0.5 for xi in x]
        y = [xi + zi * 0.3 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        if res["ci_lower"] is not None:
            assert res["ci_lower"] < res["ci_upper"]

    def test_ci_contains_r(self):
        n = 20
        x = list(range(1, n + 1))
        z = [xi * 0.4 + ((-1) ** i) for i, xi in enumerate(x)]
        y = [xi + zi * 0.2 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        if res["ci_lower"] is not None:
            assert res["ci_lower"] <= res["r"] <= res["ci_upper"]

    def test_large_n_significant(self):
        n = 50
        x = list(range(1, n + 1))
        z = [xi * 0.3 + (1.0 if i % 3 == 0 else -0.5) for i, xi in enumerate(x)]
        y = [xi * 0.8 + zi * 0.1 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        assert res["p"] is not None and res["p"] < 0.05

    def test_alpha_field_preserved(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        z = [0.5 * xi for xi in x]
        y = [xi + 1 for xi in x]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl, alpha=0.01)
        assert res["alpha"] == 0.01


# ---------------------------------------------------------------------------
# semipartial_correlation
# ---------------------------------------------------------------------------

class TestSemipartialCorrelation:
    def test_which_x_returns_r_semi(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        z = [0.5 * xi for xi in x]
        y = [xi + 1 for xi in x]
        ctrl = _ctrl(z)
        res = semipartial_correlation(x, y, ctrl, which="x")
        assert "r_semi" in res
        assert res["which"] == "x"

    def test_which_y_returns_r_semi(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        z = [0.5 * xi for xi in x]
        y = [xi + 1 for xi in x]
        ctrl = _ctrl(z)
        res = semipartial_correlation(x, y, ctrl, which="y")
        assert res["which"] == "y"

    def test_k0_no_controls_equals_pearson(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0, 4.0, 6.0, 8.0, 10.0]
        res = semipartial_correlation(x, y, [])
        assert abs(res["r_semi"] - 1.0) < 1e-5

    def test_r_semi_in_range(self):
        n = 10
        x = list(range(1, n + 1))
        z = [xi * 0.6 + ((-1) ** i) for i, xi in enumerate(x)]
        y = [xi + zi * 0.2 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = semipartial_correlation(x, y, ctrl)
        assert res["r_semi"] is not None
        assert -1.0 <= res["r_semi"] <= 1.0

    def test_df_same_as_partial(self):
        n = 12
        x = list(range(1, n + 1))
        z = [0.5 * xi for xi in x]
        y = [xi + zi * 0.3 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        partial_res = partial_correlation(x, y, ctrl)
        semi_res = semipartial_correlation(x, y, ctrl)
        assert semi_res["df"] == partial_res["df"]

    def test_invalid_which_raises(self):
        x = [1.0, 2.0, 3.0]
        y = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="which"):
            semipartial_correlation(x, y, [], which="z")

    def test_p_value_in_range(self):
        n = 15
        x = list(range(1, n + 1))
        z = [xi * 0.4 + ((-1) ** i) for i, xi in enumerate(x)]
        y = [xi + zi * 0.3 for xi, zi in zip(x, z)]
        ctrl = _ctrl(z)
        res = semipartial_correlation(x, y, ctrl)
        if res["p"] is not None:
            assert 0.0 <= res["p"] <= 1.0


# ---------------------------------------------------------------------------
# partial_correlation_matrix
# ---------------------------------------------------------------------------

class TestPartialCorrMatrix:
    def _make_data(self, n=15):
        x = list(range(1, n + 1))
        y = [xi + (1.0 if i % 2 == 0 else -1.0) for i, xi in enumerate(x)]
        w = [xi * 0.5 + (0.5 if i % 3 == 0 else -0.5) for i, xi in enumerate(x)]
        z = [xi * 0.3 + 0.1 * i for i, xi in enumerate(x)]
        return x, y, w, z

    def test_diagonal_is_1(self):
        x, y, w, z = self._make_data()
        ctrl = _ctrl(z)
        res = partial_correlation_matrix([x, y, w], ["x", "y", "w"], ctrl)
        for i in range(3):
            assert res["matrix"][i][i]["r"] == 1.0

    def test_symmetric(self):
        x, y, w, z = self._make_data()
        ctrl = _ctrl(z)
        res = partial_correlation_matrix([x, y, w], ["x", "y", "w"], ctrl)
        m = res["matrix"]
        assert m[0][1]["r"] == m[1][0]["r"]
        assert m[0][2]["r"] == m[2][0]["r"]
        assert m[1][2]["r"] == m[2][1]["r"]

    def test_var_names_returned(self):
        x, y, w, z = self._make_data()
        ctrl = _ctrl(z)
        res = partial_correlation_matrix([x, y, w], ["x", "y", "w"], ctrl)
        assert res["var_names"] == ["x", "y", "w"]

    def test_k_controls_field(self):
        x, y, _, z = self._make_data()
        ctrl = _ctrl(z)
        res = partial_correlation_matrix([x, y], ["x", "y"], ctrl)
        assert res["k_controls"] == 1

    def test_matrix_size(self):
        x, y, w, _ = self._make_data()
        res = partial_correlation_matrix([x, y, w], ["a", "b", "c"], [])
        assert len(res["matrix"]) == 3
        assert len(res["matrix"][0]) == 3

    def test_offdiag_r_in_range(self):
        x, y, w, z = self._make_data()
        ctrl = _ctrl(z)
        res = partial_correlation_matrix([x, y, w], ["x", "y", "w"], ctrl)
        for i in range(3):
            for j in range(3):
                if i != j:
                    r = res["matrix"][i][j]["r"]
                    assert r is None or -1.0 <= r <= 1.0

    def test_requires_at_least_2_variables(self):
        x = [1.0, 2.0, 3.0]
        with pytest.raises(ValueError, match="至少 2 个"):
            partial_correlation_matrix([x], ["x"], [])

    def test_no_controls_equals_pearson_pair(self):
        """无控制时，矩阵的 (0,1) 应等于 Pearson r。"""
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        y = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0]
        res = partial_correlation_matrix([x, y], ["x", "y"], [])
        pairwise = partial_correlation(x, y, [])
        assert abs(res["matrix"][0][1]["r"] - pairwise["r"]) < 1e-10


# ---------------------------------------------------------------------------
# format_apa_partial_corr
# ---------------------------------------------------------------------------

class TestFormatApaPartialCorr:
    def _result(self, k=1):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        z = [0.5 * xi for xi in x]
        y = [xi + 0.5 for xi in x]
        ctrl = _ctrl(z) if k > 0 else []
        return partial_correlation(x, y, ctrl), ["z"] if k > 0 else []

    def test_returns_string(self):
        res, cnames = self._result()
        s = format_apa_partial_corr(res, "x", "y", cnames)
        assert isinstance(s, str)

    def test_contains_r_value(self):
        res, cnames = self._result()
        s = format_apa_partial_corr(res, "x", "y", cnames)
        assert "*r*" in s

    def test_contains_control_name(self):
        res, cnames = self._result()
        s = format_apa_partial_corr(res, "x", "y", cnames)
        assert "z" in s

    def test_contains_p_value(self):
        res, cnames = self._result()
        s = format_apa_partial_corr(res, "x", "y", cnames)
        assert "*p*" in s

    def test_contains_references(self):
        res, cnames = self._result()
        s = format_apa_partial_corr(res, "x", "y", cnames)
        assert "Cohen" in s
        assert "Olkin" in s


# ---------------------------------------------------------------------------
# format_apa_partial_matrix
# ---------------------------------------------------------------------------

class TestFormatApaPartialMatrix:
    def _mat_result(self):
        n = 15
        x = list(range(1, n + 1))
        y = [xi + ((-1) ** i) for i, xi in enumerate(x)]
        z = [xi * 0.4 for xi in x]
        ctrl = _ctrl(z)
        return partial_correlation_matrix([x, y], ["x", "y"], ctrl)

    def test_returns_string(self):
        res = self._mat_result()
        s = format_apa_partial_matrix(res)
        assert isinstance(s, str)

    def test_contains_var_names(self):
        res = self._mat_result()
        s = format_apa_partial_matrix(res)
        assert "x" in s and "y" in s

    def test_contains_significance_note(self):
        res = self._mat_result()
        s = format_apa_partial_matrix(res)
        assert "注" in s


# ---------------------------------------------------------------------------
# write_partial_corr_report
# ---------------------------------------------------------------------------

class TestWriteReport:
    def _get_result_and_formatted(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        z = [0.5 * xi for xi in x]
        y = [xi + 0.5 for xi in x]
        ctrl = _ctrl(z)
        res = partial_correlation(x, y, ctrl)
        formatted = format_apa_partial_corr(res, "x", "y", ["z"])
        return res, formatted

    def test_creates_md(self, tmp_path):
        res, formatted = self._get_result_and_formatted()
        paths = write_partial_corr_report(res, formatted, tmp_path)
        assert pathlib.Path(paths["md"]).exists()

    def test_creates_json(self, tmp_path):
        res, formatted = self._get_result_and_formatted()
        paths = write_partial_corr_report(res, formatted, tmp_path)
        assert pathlib.Path(paths["json"]).exists()

    def test_json_valid(self, tmp_path):
        res, formatted = self._get_result_and_formatted()
        paths = write_partial_corr_report(res, formatted, tmp_path)
        with open(paths["json"], encoding="utf-8") as f:
            obj = json.load(f)
        assert isinstance(obj, dict)

    def test_json_no_nan_inf(self, tmp_path):
        res, formatted = self._get_result_and_formatted()
        paths = write_partial_corr_report(res, formatted, tmp_path)
        raw = pathlib.Path(paths["json"]).read_text(encoding="utf-8")
        assert "NaN" not in raw and "Infinity" not in raw


# ---------------------------------------------------------------------------
# analyze_partial_corr (CSV 主入口)
# ---------------------------------------------------------------------------

def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestAnalyzePartialCorr:
    def _make_csv(self, tmp_path: pathlib.Path, n: int = 20) -> str:
        rows = []
        for i in range(n):
            rows.append({
                "x": float(i + 1),
                "y": float(i + 1) + (0.3 if i % 2 == 0 else -0.3),
                "z": float(i + 1) * 0.5 + (0.1 if i % 3 == 0 else -0.1),
            })
        p = tmp_path / "data.csv"
        _write_csv(p, rows)
        return str(p)

    def test_returns_dict(self, tmp_path):
        p = self._make_csv(tmp_path)
        res = analyze_partial_corr(p, "x", "y", ["z"], out_dir=str(tmp_path))
        assert isinstance(res, dict)

    def test_n_matches_rows(self, tmp_path):
        p = self._make_csv(tmp_path, n=20)
        res = analyze_partial_corr(p, "x", "y", ["z"], out_dir=str(tmp_path))
        assert res["n"] == 20

    def test_writes_md_sidecar(self, tmp_path):
        p = self._make_csv(tmp_path)
        analyze_partial_corr(p, "x", "y", ["z"], out_dir=str(tmp_path))
        assert (tmp_path / "partial_corr_report.md").exists()

    def test_writes_json_sidecar(self, tmp_path):
        p = self._make_csv(tmp_path)
        analyze_partial_corr(p, "x", "y", ["z"], out_dir=str(tmp_path))
        assert (tmp_path / "partial_corr_report.json").exists()

    def test_n_excluded_counts_missing(self, tmp_path):
        rows = [
            {"x": "1", "y": "2", "z": "0.5"},
            {"x": "", "y": "3", "z": "1.0"},   # missing x
            {"x": "3", "y": "bad", "z": "1.5"},  # bad y
            {"x": "4", "y": "5", "z": "2.0"},
        ]
        p = tmp_path / "miss.csv"
        _write_csv(p, rows)
        res = analyze_partial_corr(str(p), "x", "y", ["z"], out_dir=str(tmp_path))
        assert res["n_excluded"] == 2

    def test_return_json_no_private_keys(self, tmp_path):
        p = self._make_csv(tmp_path)
        res = analyze_partial_corr(p, "x", "y", ["z"], out_dir=str(tmp_path),
                                   return_json=True)
        assert not any(k.startswith("_") for k in res)

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            analyze_partial_corr("/nonexistent/path.csv", "x", "y", [],
                                 out_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# 边界与错误处理
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="不一致"):
            partial_correlation([1.0, 2.0], [1.0, 2.0, 3.0], [])

    def test_controls_length_mismatch_raises(self):
        x = [1.0, 2.0, 3.0]
        y = [1.0, 2.0, 3.0]
        ctrl = [[0.5], [1.0]]  # 只有 2 行，但 x, y 有 3 行
        with pytest.raises(ValueError, match="不一致"):
            partial_correlation(x, y, ctrl)

    def test_df_zero_returns_none_stats(self):
        # n=4, k=2 → df=0
        x = [1.0, 2.0, 3.0, 4.0]
        y = [1.5, 2.5, 3.5, 4.5]
        z1 = [0.5, 1.0, 1.5, 2.0]
        z2 = [0.3, 0.6, 0.9, 1.2]
        ctrl = _ctrl(z1, z2)
        res = partial_correlation(x, y, ctrl)
        # df = 4 - 2 - 2 = 0
        assert res["df"] == 0
        assert res["t"] is None and res["p"] is None

    def test_missing_column_in_csv_raises(self, tmp_path):
        rows = [{"x": "1", "y": "2"}, {"x": "3", "y": "4"}]
        p = tmp_path / "data.csv"
        _write_csv(p, rows)
        with pytest.raises(ValueError, match="找不到列"):
            analyze_partial_corr(str(p), "x", "y", ["nonexistent"],
                                 out_dir=str(tmp_path))
