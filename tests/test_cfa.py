"""tests/test_cfa.py — 验证性因子分析（CFA）单元测试 (P5-E7)。

被测：psyclaw/psych/cfa.py
  - _parse_model: 模型规格解析
  - compute_cfa:  ULS 估计 + Adam 优化器
  - format_apa_cfa: APA-7 Markdown 报告格式化
  - write_cfa_report: MD + JSON sidecar 输出
  - analyze_cfa:  CSV 主入口

不需要 LLM / API key，stdlib only。合成数据来自已知因子结构（固定种子）。
"""
from __future__ import annotations

import csv
import json
import math
import pathlib
import random
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from psyclaw.psych.cfa import (
    _parse_model,
    _corr_matrix,
    compute_cfa,
    format_apa_cfa,
    write_cfa_report,
    analyze_cfa,
)


# ─── 测试数据生成器（stdlib only，固定种子）──────────────────────────────────────

def _gen_2factor_data(n: int = 250, seed: int = 42) -> dict[str, list[float]]:
    """生成双因子结构数据（6 条目，载荷 ≈ 0.80，正交）。

    F1 → x1, x2, x3  (λ = 0.80)
    F2 → x4, x5, x6  (λ = 0.80)
    """
    rng = random.Random(seed)

    def normal() -> float:
        u1 = max(1e-15, rng.random())
        u2 = rng.random()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

    lam = 0.80
    err = math.sqrt(1.0 - lam ** 2)
    data: dict[str, list[float]] = {c: [] for c in ["x1", "x2", "x3", "x4", "x5", "x6"]}
    for _ in range(n):
        f1, f2 = normal(), normal()
        for col in ["x1", "x2", "x3"]:
            data[col].append(lam * f1 + err * normal())
        for col in ["x4", "x5", "x6"]:
            data[col].append(lam * f2 + err * normal())
    return data


def _gen_1factor_data(n: int = 200, seed: int = 7) -> dict[str, list[float]]:
    """生成单因子结构数据（4 条目，载荷 ≈ 0.75）。"""
    rng = random.Random(seed)

    def normal() -> float:
        u1 = max(1e-15, rng.random())
        u2 = rng.random()
        return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)

    lam = 0.75
    err = math.sqrt(1.0 - lam ** 2)
    data: dict[str, list[float]] = {c: [] for c in ["y1", "y2", "y3", "y4"]}
    for _ in range(n):
        f = normal()
        for col in ["y1", "y2", "y3", "y4"]:
            data[col].append(lam * f + err * normal())
    return data


# ─── _parse_model 测试 ────────────────────────────────────────────────────────

class TestParseModel:
    COL_NAMES = ["x1", "x2", "x3", "x4", "x5", "x6"]

    def test_string_format_two_factors(self):
        factors, items, free, marker = _parse_model(
            "F1:x1,x2,x3;F2:x4,x5,x6", self.COL_NAMES
        )
        assert factors == ["F1", "F2"]
        assert items == ["x1", "x2", "x3", "x4", "x5", "x6"]

    def test_dict_format(self):
        factors, items, free, marker = _parse_model(
            {"FA": ["x1", "x2", "x3"], "FB": ["x4", "x5", "x6"]},
            self.COL_NAMES,
        )
        assert factors == ["FA", "FB"]
        assert len(items) == 6

    def test_marker_is_first_item_per_factor(self):
        factors, items, free, marker = _parse_model(
            "F1:x1,x2,x3;F2:x4,x5,x6", self.COL_NAMES
        )
        # F1 marker → x1 (index 0), F2 marker → x4 (index 3)
        f1_idx = factors.index("F1")
        f2_idx = factors.index("F2")
        x1_idx = items.index("x1")
        x4_idx = items.index("x4")
        assert marker[x1_idx][f1_idx] is True
        assert marker[x4_idx][f2_idx] is True

    def test_non_marker_items_not_in_marker_mask(self):
        factors, items, free, marker = _parse_model(
            "F1:x1,x2,x3;F2:x4,x5,x6", self.COL_NAMES
        )
        x2_idx = items.index("x2")
        assert not any(marker[x2_idx])  # x2 is not a marker

    def test_free_mask_covers_specified_items(self):
        factors, items, free, marker = _parse_model(
            "F1:x1,x2,x3;F2:x4,x5,x6", self.COL_NAMES
        )
        f1_idx = factors.index("F1")
        # x1, x2, x3 should be free for F1
        for col in ["x1", "x2", "x3"]:
            assert free[items.index(col)][f1_idx] is True

    def test_cross_loadings_not_free(self):
        factors, items, free, marker = _parse_model(
            "F1:x1,x2,x3;F2:x4,x5,x6", self.COL_NAMES
        )
        f2_idx = factors.index("F2")
        for col in ["x1", "x2", "x3"]:
            assert free[items.index(col)][f2_idx] is False

    def test_unknown_item_raises(self):
        with pytest.raises(ValueError, match="不在数据列中"):
            _parse_model("F1:x1,x99", self.COL_NAMES)

    def test_invalid_format_string_raises(self):
        with pytest.raises(ValueError, match="无效模型规格"):
            _parse_model("F1_x1_x2", self.COL_NAMES)  # missing ":"

    def test_empty_spec_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            _parse_model("", self.COL_NAMES)

    def test_factor_with_one_item_raises(self):
        with pytest.raises(ValueError, match="至少需要 2 个条目"):
            _parse_model("F1:x1", self.COL_NAMES)

    def test_spaces_around_semicolons(self):
        factors, items, free, marker = _parse_model(
            "F1 : x1 , x2 , x3 ; F2 : x4 , x5 , x6", self.COL_NAMES
        )
        assert len(factors) == 2

    def test_single_factor_spec(self):
        factors, items, free, marker = _parse_model(
            "G:x1,x2,x3", self.COL_NAMES
        )
        assert factors == ["G"]
        assert items == ["x1", "x2", "x3"]


# ─── _corr_matrix 测试 ────────────────────────────────────────────────────────

class TestCorrMatrix:
    def test_diagonal_ones(self):
        data = _gen_2factor_data()
        cols = [data[c] for c in ["x1", "x2", "x3"]]
        R, n = _corr_matrix(cols)
        for i in range(len(R)):
            assert abs(R[i][i] - 1.0) < 1e-9

    def test_symmetric(self):
        data = _gen_2factor_data()
        cols = [data[c] for c in ["x1", "x2", "x3", "x4"]]
        R, n = _corr_matrix(cols)
        for i in range(4):
            for j in range(4):
                assert abs(R[i][j] - R[j][i]) < 1e-12

    def test_values_in_neg1_pos1(self):
        data = _gen_2factor_data()
        cols = [data[c] for c in ["x1", "x2", "x3", "x4", "x5", "x6"]]
        R, n = _corr_matrix(cols)
        for row in R:
            for v in row:
                assert -1.0 <= v <= 1.0

    def test_within_factor_correlation_higher(self):
        data = _gen_2factor_data(n=400)
        cols = [data[c] for c in ["x1", "x2", "x4", "x5"]]
        R, n = _corr_matrix(cols)
        # x1-x2 (same factor) should correlate more than x1-x4 (different factors)
        r_within = R[0][1]   # x1 vs x2
        r_cross = R[0][2]    # x1 vs x4
        assert r_within > r_cross

    def test_insufficient_cases_raises(self):
        cols = [[1.0, 2.0], [3.0, 4.0]]
        with pytest.raises(ValueError, match="完整案例不足"):
            _corr_matrix(cols)

    def test_n_reported_correctly(self):
        data = _gen_2factor_data(n=100)
        cols = [data[c] for c in ["x1", "x2"]]
        R, n = _corr_matrix(cols)
        assert n == 100

    def test_nan_excluded(self):
        cols = [
            [1.0, float("nan"), 2.0, 3.0, 4.0, 5.0],
            [2.0, 3.0, float("nan"), 4.0, 5.0, 6.0],
        ]
        # idx=1: col0 nan → invalid; idx=2: col1 nan → invalid; rest valid (4 rows)
        R, n = _corr_matrix(cols)
        assert n == 4


# ─── compute_cfa 基础结构测试 ──────────────────────────────────────────────────

class TestComputeCFAStructure:
    def setup_method(self):
        self.data2 = _gen_2factor_data(n=300)
        self.data1 = _gen_1factor_data(n=200)
        self.spec2 = "F1:x1,x2,x3;F2:x4,x5,x6"
        self.spec1 = "G:y1,y2,y3,y4"

    def test_returns_dict(self):
        result = compute_cfa(self.data2, self.spec2)
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        result = compute_cfa(self.data2, self.spec2)
        for key in ("n", "p", "k", "factors", "items", "loadings",
                    "communalities", "unique_variances", "factor_correlations",
                    "oblique", "S", "Sigma", "residuals", "fit",
                    "convergence", "n_iter", "warnings"):
            assert key in result, f"缺少键 {key}"

    def test_fit_keys_present(self):
        result = compute_cfa(self.data2, self.spec2)
        for key in ("srmr", "cfi", "tli", "rmsea", "rmsea_ci_lower",
                    "rmsea_ci_upper", "chi2_approx", "df", "n_free_params",
                    "f_uls_min"):
            assert key in result["fit"], f"fit 缺少键 {key}"

    def test_dimensions_correct(self):
        result = compute_cfa(self.data2, self.spec2)
        assert result["k"] == 2
        assert result["p"] == 6
        assert result["n"] == 300

    def test_loadings_shape(self):
        result = compute_cfa(self.data2, self.spec2)
        assert len(result["loadings"]) == 6
        for row in result["loadings"]:
            assert len(row) == 2

    def test_communalities_in_range(self):
        result = compute_cfa(self.data2, self.spec2)
        for h2 in result["communalities"]:
            assert 0.0 <= h2 <= 1.0, f"共同度超出范围: {h2}"

    def test_unique_variances_positive(self):
        result = compute_cfa(self.data2, self.spec2)
        for psi in result["unique_variances"]:
            assert psi > 0.0, f"独特方差非正: {psi}"

    def test_factor_correlations_identity_orthogonal(self):
        result = compute_cfa(self.data2, self.spec2, oblique=False)
        phi = result["factor_correlations"]
        # 正交模式：因子间相关固定为 0（对角为 1）
        assert abs(phi[0][0] - 1.0) < 1e-9
        assert abs(phi[1][1] - 1.0) < 1e-9

    def test_fit_cfi_in_range(self):
        result = compute_cfa(self.data2, self.spec2)
        assert 0.0 <= result["fit"]["cfi"] <= 1.0

    def test_fit_tli_not_crazy(self):
        result = compute_cfa(self.data2, self.spec2)
        assert result["fit"]["tli"] > -1.0

    def test_fit_rmsea_non_negative(self):
        result = compute_cfa(self.data2, self.spec2)
        assert result["fit"]["rmsea"] >= 0.0

    def test_fit_srmr_non_negative(self):
        result = compute_cfa(self.data2, self.spec2)
        assert result["fit"]["srmr"] >= 0.0

    def test_rmsea_ci_order(self):
        result = compute_cfa(self.data2, self.spec2)
        fit = result["fit"]
        assert fit["rmsea_ci_lower"] <= fit["rmsea"] <= fit["rmsea_ci_upper"]

    def test_single_factor(self):
        result = compute_cfa(self.data1, self.spec1)
        assert result["k"] == 1
        assert result["p"] == 4

    def test_convergence_flag_bool(self):
        result = compute_cfa(self.data2, self.spec2)
        assert isinstance(result["convergence"], bool)

    def test_oblique_phi_symmetric(self):
        result = compute_cfa(self.data2, self.spec2, oblique=True)
        phi = result["factor_correlations"]
        k = result["k"]
        for a in range(k):
            for b in range(k):
                assert abs(phi[a][b] - phi[b][a]) < 1e-10

    def test_oblique_phi_diagonal_one(self):
        result = compute_cfa(self.data2, self.spec2, oblique=True)
        phi = result["factor_correlations"]
        k = result["k"]
        for i in range(k):
            assert abs(phi[i][i] - 1.0) < 1e-9


# ─── compute_cfa 结构恢复精度测试 ────────────────────────────────────────────

class TestComputeCFARecovery:
    """测试 CFA 能从已知因子结构数据中恢复预期载荷方向和模式。"""

    def setup_method(self):
        self.data = _gen_2factor_data(n=400, seed=42)
        self.result = compute_cfa(
            self.data, "F1:x1,x2,x3;F2:x4,x5,x6", max_iter=4000
        )

    def test_within_factor_loadings_substantial(self):
        """F1 条目对 F1 的载荷应 > 0.5（强载荷）。"""
        loadings = self.result["loadings"]
        items = self.result["items"]
        factors = self.result["factors"]
        f1_idx = factors.index("F1")
        for col in ["x1", "x2", "x3"]:
            pi = items.index(col)
            assert loadings[pi][f1_idx] > 0.5, (
                f"{col} 对 F1 的载荷 {loadings[pi][f1_idx]:.3f} 太低"
            )

    def test_f2_items_load_on_f2(self):
        """F2 条目对 F2 的载荷应 > 0.5。"""
        loadings = self.result["loadings"]
        items = self.result["items"]
        factors = self.result["factors"]
        f2_idx = factors.index("F2")
        for col in ["x4", "x5", "x6"]:
            pi = items.index(col)
            assert loadings[pi][f2_idx] > 0.5, (
                f"{col} 对 F2 的载荷 {loadings[pi][f2_idx]:.3f} 太低"
            )

    def test_marker_items_loading_exactly_one(self):
        """标记变量（每因子首个条目）载荷初始化为 1.0 且从不被优化器更新（固定参数）。"""
        loadings = self.result["loadings"]
        items = self.result["items"]
        factors = self.result["factors"]
        # x1 是 F1 的标记变量，x4 是 F2 的标记变量
        f1_idx = factors.index("F1")
        f2_idx = factors.index("F2")
        x1_idx = items.index("x1")
        x4_idx = items.index("x4")
        assert abs(loadings[x1_idx][f1_idx] - 1.0) < 1e-9
        assert abs(loadings[x4_idx][f2_idx] - 1.0) < 1e-9

    def test_communalities_reasonable_for_known_structure(self):
        """公共度应反映真实 λ²=0.64 附近（宽泛验证）。"""
        for h2 in self.result["communalities"]:
            assert h2 > 0.2, f"共同度 {h2:.3f} 偏低"

    def test_good_fit_for_generating_model(self):
        """数据来自 CFA 模型，拟合应较好（宽泛判据）。"""
        fit = self.result["fit"]
        assert fit["cfi"] > 0.85, f"CFI = {fit['cfi']:.3f} 偏低"
        assert fit["rmsea"] < 0.15, f"RMSEA = {fit['rmsea']:.3f} 偏高"

    def test_srmr_low_for_true_model(self):
        fit = self.result["fit"]
        assert fit["srmr"] < 0.15, f"SRMR = {fit['srmr']:.3f} 偏高"


# ─── format_apa_cfa 测试 ──────────────────────────────────────────────────────

class TestFormatApaCFA:
    def setup_method(self):
        data = _gen_2factor_data(n=200)
        self.result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        self.report = format_apa_cfa(self.result)

    def test_returns_string(self):
        assert isinstance(self.report, str)

    def test_contains_cfi(self):
        assert "CFI" in self.report

    def test_contains_tli(self):
        assert "TLI" in self.report

    def test_contains_rmsea(self):
        assert "RMSEA" in self.report

    def test_contains_srmr(self):
        assert "SRMR" in self.report

    def test_contains_factor_names(self):
        assert "F1" in self.report
        assert "F2" in self.report

    def test_contains_item_names(self):
        for col in ["x1", "x2", "x3", "x4", "x5", "x6"]:
            assert col in self.report, f"条目 {col} 未出现在报告中"

    def test_contains_sample_size(self):
        assert "N" in self.report or "200" in self.report

    def test_apa_reference_in_report(self):
        assert "Hu" in self.report or "Bentler" in self.report or "Browne" in self.report

    def test_oblique_adds_phi_section(self):
        data = _gen_2factor_data(n=200)
        result_ob = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6", oblique=True)
        report_ob = format_apa_cfa(result_ob)
        assert "斜交" in report_ob or "相关" in report_ob

    def test_single_factor_report(self):
        data = _gen_1factor_data(n=150)
        result = compute_cfa(data, "G:y1,y2,y3,y4")
        report = format_apa_cfa(result)
        assert "G" in report
        assert isinstance(report, str)

    def test_warnings_section_when_bad_fit(self):
        """当拟合警告存在时，报告应含注意事项。"""
        # 构造已有 warnings 的结果
        data = _gen_2factor_data(n=200)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        # 手动注入 warning
        result["warnings"].append("测试警告")
        report = format_apa_cfa(result)
        assert "测试警告" in report

    def test_table_structure_present(self):
        assert "|" in self.report  # Markdown table

    def test_fit_values_numeric_in_report(self):
        fit = self.result["fit"]
        cfi_str = f"{fit['cfi']:.3f}"
        assert cfi_str in self.report


# ─── write_cfa_report 测试 ────────────────────────────────────────────────────

class TestWriteCFAReport:
    def setup_method(self):
        data = _gen_2factor_data(n=200)
        self.result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")

    def test_creates_md_file(self, tmp_path):
        md, js = write_cfa_report(self.result, tmp_path)
        assert md.exists()

    def test_creates_json_file(self, tmp_path):
        md, js = write_cfa_report(self.result, tmp_path)
        assert js.exists()

    def test_md_content_nonempty(self, tmp_path):
        md, _ = write_cfa_report(self.result, tmp_path)
        assert md.read_text(encoding="utf-8").strip()

    def test_json_valid(self, tmp_path):
        _, js = write_cfa_report(self.result, tmp_path)
        data = json.loads(js.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "fit" in data

    def test_json_no_nan_inf(self, tmp_path):
        _, js = write_cfa_report(self.result, tmp_path)
        text = js.read_text(encoding="utf-8")
        assert "NaN" not in text
        assert "Infinity" not in text

    def test_creates_parent_dir(self, tmp_path):
        out_dir = tmp_path / "deep" / "nested"
        write_cfa_report(self.result, out_dir)
        assert (out_dir / "cfa_report.md").exists()


# ─── analyze_cfa CSV 主入口测试 ───────────────────────────────────────────────

class TestAnalyzeCFA:
    def _write_csv(self, path: pathlib.Path, data: dict[str, list[float]]) -> None:
        cols = list(data.keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            n = len(next(iter(data.values())))
            for i in range(n):
                writer.writerow({c: data[c][i] for c in cols})

    def test_reads_csv_correctly(self, tmp_path):
        data = _gen_2factor_data(n=200)
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, data)
        result = analyze_cfa(csv_path, "F1:x1,x2,x3;F2:x4,x5,x6", out_dir=None)
        assert result["n"] == 200

    def test_writes_sidecar_when_out_dir(self, tmp_path):
        data = _gen_2factor_data(n=200)
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, data)
        result = analyze_cfa(csv_path, "F1:x1,x2,x3;F2:x4,x5,x6",
                              out_dir=tmp_path / "out")
        assert (tmp_path / "out" / "cfa_report.md").exists()

    def test_return_json_flag(self, tmp_path):
        data = _gen_2factor_data(n=200)
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, data)
        result = analyze_cfa(csv_path, "F1:x1,x2,x3;F2:x4,x5,x6",
                              return_json=True, out_dir=None)
        assert "_formatted" in result
        assert isinstance(result["_formatted"], str)

    def test_missing_csv_raises(self):
        with pytest.raises((FileNotFoundError, OSError)):
            analyze_cfa("/nonexistent/path/data.csv", "F1:x1,x2")

    def test_oblique_option_passed_through(self, tmp_path):
        data = _gen_2factor_data(n=200)
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, data)
        result = analyze_cfa(csv_path, "F1:x1,x2,x3;F2:x4,x5,x6",
                              oblique=True, out_dir=None)
        assert result["oblique"] is True

    def test_max_iter_respected(self, tmp_path):
        data = _gen_2factor_data(n=200)
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, data)
        result = analyze_cfa(csv_path, "F1:x1,x2,x3;F2:x4,x5,x6",
                              max_iter=5, out_dir=None)
        # 5 次迭代不足以收敛，但不应崩溃
        assert result["n_iter"] <= 5


# ─── 边界与错误处理测试 ───────────────────────────────────────────────────────

class TestCFAEdgeCases:
    def test_mismatched_column_in_model_raises(self):
        data = _gen_2factor_data(n=100)
        with pytest.raises(ValueError, match="不在数据列中"):
            compute_cfa(data, "F1:x1,x2,GHOST;F2:x4,x5,x6")

    def test_single_factor_minimum_items(self):
        data = {"a": [1.0, 2.0, 3.0, 4.0, 5.0],
                "b": [2.0, 3.0, 4.0, 5.0, 6.0]}
        result = compute_cfa(data, "F:a,b")
        assert result["k"] == 1
        assert result["p"] == 2

    def test_warnings_is_list(self):
        data = _gen_2factor_data(n=100)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        assert isinstance(result["warnings"], list)

    def test_factor_correlations_square_matrix(self):
        data = _gen_2factor_data(n=150)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        k = result["k"]
        phi = result["factor_correlations"]
        assert len(phi) == k
        for row in phi:
            assert len(row) == k

    def test_residuals_shape_matches_p(self):
        data = _gen_2factor_data(n=150)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        p = result["p"]
        assert len(result["residuals"]) == p
        for row in result["residuals"]:
            assert len(row) == p

    def test_sigma_shape_matches_p(self):
        data = _gen_2factor_data(n=150)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        p = result["p"]
        assert len(result["Sigma"]) == p

    def test_s_diagonal_ones(self):
        """S = 相关矩阵，对角应为 1.0。"""
        data = _gen_2factor_data(n=200)
        result = compute_cfa(data, "F1:x1,x2,x3;F2:x4,x5,x6")
        S = result["S"]
        p = result["p"]
        for i in range(p):
            assert abs(S[i][i] - 1.0) < 1e-9
