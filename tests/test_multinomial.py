"""多项 Logistic 回归测试（约 55 例）。

金标准（手算精确 / 与 logistic.py 交叉验证）：
  - 仅截距模型：MLE 截距 = log(n_j / n_ref)，ll_model == ll_null；
  - 单二元预测变量饱和模型：截距/斜率由各单元格经验对数优势唯一确定（精确恢复）；
  - J=2 退化：与已验证 logistic.logistic_regression 交叉对照（同一似然）；
  - predict_probs 各类别概率和=1；OR=exp(B) 精确；
  - 伪 R² 边界、LR χ²≥0、AIC/BIC 公式。
"""

import json
import math
import os
import tempfile

import pytest

from psyclaw.psych import multinomial as mn


# ─────────────────────────────────────────────────────────────────────────────
# 数学工具
# ─────────────────────────────────────────────────────────────────────────────

class TestMathTools:
    def test_mat_invert_identity(self):
        I = [[1.0, 0.0], [0.0, 1.0]]
        inv = mn._mat_invert(I)
        assert inv is not None
        assert abs(inv[0][0] - 1.0) < 1e-12
        assert abs(inv[1][1] - 1.0) < 1e-12

    def test_mat_invert_known(self):
        M = [[2.0, 0.0], [0.0, 4.0]]
        inv = mn._mat_invert(M)
        assert abs(inv[0][0] - 0.5) < 1e-12
        assert abs(inv[1][1] - 0.25) < 1e-12

    def test_mat_invert_singular(self):
        assert mn._mat_invert([[1.0, 1.0], [1.0, 1.0]]) is None

    def test_mat_invert_roundtrip(self):
        M = [[4.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 2.0]]
        inv = mn._mat_invert(M)
        prod = [[sum(M[i][t] * inv[t][j] for t in range(3)) for j in range(3)]
                for i in range(3)]
        for i in range(3):
            for j in range(3):
                assert abs(prod[i][j] - (1.0 if i == j else 0.0)) < 1e-9

    def test_mat_vec(self):
        A = [[1.0, 2.0], [3.0, 4.0]]
        assert mn._mat_vec(A, [1.0, 1.0]) == [3.0, 7.0]

    def test_safe_exp_overflow(self):
        assert mn._safe_exp(1000.0) == math.inf
        assert mn._safe_exp(-1000.0) == 0.0
        assert abs(mn._safe_exp(0.0) - 1.0) < 1e-12

    def test_normal_sf_half(self):
        assert abs(mn._normal_sf(0.0) - 0.5) < 1e-6

    def test_normal_sf_196(self):
        # P(Z > 1.96) ≈ .025
        assert abs(mn._normal_sf(1.96) - 0.025) < 1e-3

    def test_normal_quantile_median(self):
        assert abs(mn._normal_quantile(0.5)) < 1e-6

    def test_normal_quantile_975(self):
        assert abs(mn._normal_quantile(0.975) - 1.959964) < 1e-3

    def test_chi2_sf_zero(self):
        assert mn._chi2_sf(0.0, 1) == 1.0

    def test_chi2_sf_df1_385(self):
        # χ²(1) 临界值 3.841 → p ≈ .05
        assert abs(mn._chi2_sf(3.841, 1) - 0.05) < 1e-3

    def test_chi2_sf_df2(self):
        # χ²(2) 临界值 5.991 → p ≈ .05
        assert abs(mn._chi2_sf(5.991, 2) - 0.05) < 1e-3

    def test_chi2_sf_monotone(self):
        assert mn._chi2_sf(10.0, 3) < mn._chi2_sf(5.0, 3)


# ─────────────────────────────────────────────────────────────────────────────
# softmax / 对数似然
# ─────────────────────────────────────────────────────────────────────────────

class TestSoftmaxLoglik:
    def test_row_probs_sum_to_one(self):
        # J=3 → 2 非参照, k=2
        beta = [0.5, 1.0, -0.3, 0.2]
        p_nr, p_ref = mn._row_probs([1.0, 2.0], beta, 2, 2)
        assert abs(sum(p_nr) + p_ref - 1.0) < 1e-12

    def test_row_probs_zero_beta_uniform(self):
        # 全零系数 → 各类别等概率 1/J
        p_nr, p_ref = mn._row_probs([1.0, 5.0], [0.0, 0.0, 0.0, 0.0], 2, 2)
        assert abs(p_ref - 1.0 / 3.0) < 1e-12
        for p in p_nr:
            assert abs(p - 1.0 / 3.0) < 1e-12

    def test_row_probs_all_positive(self):
        p_nr, p_ref = mn._row_probs([1.0, 3.0], [2.0, 1.0, -1.0, 0.5], 2, 2)
        assert all(p > 0 for p in p_nr)
        assert p_ref > 0

    def test_loglik_zero_beta(self):
        # 全零 → 每观测 log(1/J)
        X = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0]]
        targets = [0, 1, -1]
        ll = mn._loglik(X, targets, [0.0] * 4, 2, 2)
        assert abs(ll - 3 * math.log(1.0 / 3.0)) < 1e-12

    def test_loglik_negative(self):
        X = [[1.0], [1.0], [1.0]]
        targets = [0, 1, -1]
        ll = mn._loglik(X, targets, [0.0, 0.0], 2, 1)
        assert ll < 0


# ─────────────────────────────────────────────────────────────────────────────
# 仅截距模型金标准
# ─────────────────────────────────────────────────────────────────────────────

class TestInterceptOnly:
    def _fit(self):
        # 计数 cat1(ref)=4, cat2=2, cat3=8
        y = [1] * 4 + [2] * 2 + [3] * 8
        X = [[1.0]] * len(y)
        return mn.multinomial_regression(X, y)

    def test_intercept_cat2(self):
        res = self._fit()
        # 截距_2 = log(n2/n_ref) = log(2/4)
        assert abs(res["coef"][2][0] - math.log(2 / 4)) < 1e-5

    def test_intercept_cat3(self):
        res = self._fit()
        assert abs(res["coef"][3][0] - math.log(8 / 4)) < 1e-5

    def test_ll_model_equals_null(self):
        res = self._fit()
        assert abs(res["log_lik_model"] - res["log_lik_null"]) < 1e-6

    def test_lr_chi2_zero(self):
        res = self._fit()
        # 无预测变量 → LR ≈ 0，df=0
        assert res["lr_df"] == 0
        assert res["lr_chi2"] < 1e-5

    def test_n_per_cat(self):
        res = self._fit()
        assert res["n_per_cat"] == {1: 4, 2: 2, 3: 8}
        assert sum(res["n_per_cat"].values()) == res["n"]


# ─────────────────────────────────────────────────────────────────────────────
# 单二元预测变量饱和模型金标准
# ─────────────────────────────────────────────────────────────────────────────

class TestSaturatedBinary:
    def _fit(self):
        # x=0: cat1×2, cat2×2, cat3×2  → 各类等概率 → 截距=0
        # x=1: cat1×1, cat2×2, cat3×4  → slope2=log2, slope3=log4
        rows = []
        for _ in range(2):
            rows += [(0.0, 1), (0.0, 2), (0.0, 3)]
        rows += [(1.0, 1)]
        rows += [(1.0, 2), (1.0, 2)]
        rows += [(1.0, 3), (1.0, 3), (1.0, 3), (1.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return mn.multinomial_regression(X, y, predictor_names=["x"])

    def test_intercepts_zero(self):
        res = self._fit()
        assert abs(res["coef"][2][0]) < 1e-4
        assert abs(res["coef"][3][0]) < 1e-4

    def test_slope_cat2_log2(self):
        res = self._fit()
        assert abs(res["coef"][2][1] - math.log(2)) < 1e-4

    def test_slope_cat3_log4(self):
        res = self._fit()
        assert abs(res["coef"][3][1] - math.log(4)) < 1e-4

    def test_or_cat2(self):
        res = self._fit()
        assert abs(res["or_"][2][1] - 2.0) < 1e-3

    def test_or_cat3(self):
        res = self._fit()
        assert abs(res["or_"][3][1] - 4.0) < 1e-3

    def test_converged(self):
        res = self._fit()
        assert res["convergence"]

    def test_or_is_exp_b(self):
        res = self._fit()
        for lab in res["nonref"]:
            for j in range(res["k"]):
                b = res["coef"][lab][j]
                assert abs(res["or_"][lab][j] - math.exp(b)) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# J=2 退化：与二元 Logistic 交叉验证
# ─────────────────────────────────────────────────────────────────────────────

class TestBinaryEquivalence:
    def _data(self):
        # 饱和二元：x=0 → P(1)=1/4；x=1 → P(1)=3/4
        rows = [(0.0, 0), (0.0, 0), (0.0, 0), (0.0, 1),
                (1.0, 0), (1.0, 1), (1.0, 1), (1.0, 1)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return X, y

    def test_matches_logistic(self):
        from psyclaw.psych.logistic import logistic_regression
        X, y = self._data()
        m = mn.multinomial_regression(X, y, predictor_names=["x"])
        b = logistic_regression(X, [float(v) for v in y], predictor_names=["x"])
        # 非参照类别=1（事件），系数应与二元 logistic 一致
        assert abs(m["coef"][1][0] - b["coef"][0]) < 1e-3
        assert abs(m["coef"][1][1] - b["coef"][1]) < 1e-3

    def test_saturated_intercept(self):
        X, y = self._data()
        m = mn.multinomial_regression(X, y, predictor_names=["x"])
        # 截距 = log((1/4)/(3/4)) = -log3
        assert abs(m["coef"][1][0] - (-math.log(3))) < 1e-3

    def test_saturated_slope(self):
        X, y = self._data()
        m = mn.multinomial_regression(X, y, predictor_names=["x"])
        # 斜率 = 2 log3
        assert abs(m["coef"][1][1] - 2 * math.log(3)) < 1e-3

    def test_se_matches_logistic(self):
        from psyclaw.psych.logistic import logistic_regression
        X, y = self._data()
        m = mn.multinomial_regression(X, y, predictor_names=["x"])
        b = logistic_regression(X, [float(v) for v in y], predictor_names=["x"])
        assert abs(m["se"][1][1] - b["se"][1]) < 1e-2


# ─────────────────────────────────────────────────────────────────────────────
# predict_probs
# ─────────────────────────────────────────────────────────────────────────────

class TestPredictProbs:
    def _fit(self):
        rows = []
        for _ in range(3):
            rows += [(0.0, 1), (0.0, 2), (1.0, 2), (1.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return mn.multinomial_regression(X, y, predictor_names=["x"])

    def test_sums_to_one(self):
        res = self._fit()
        probs = mn.predict_probs(res, [1.0, 0.5])
        assert abs(sum(probs.values()) - 1.0) < 1e-12

    def test_all_categories_present(self):
        res = self._fit()
        probs = mn.predict_probs(res, [1.0, 0.0])
        assert set(probs.keys()) == set(res["categories"])

    def test_all_positive(self):
        res = self._fit()
        probs = mn.predict_probs(res, [1.0, 2.0])
        assert all(p > 0 for p in probs.values())

    def test_ref_included(self):
        res = self._fit()
        probs = mn.predict_probs(res, [1.0, 1.0])
        assert res["ref"] in probs


# ─────────────────────────────────────────────────────────────────────────────
# 显著性方向（单调预测变量）
# ─────────────────────────────────────────────────────────────────────────────

class TestSignificance:
    def test_strong_predictor_significant(self):
        # x 与类别正相关但**重叠**（非完全分离）：cat3 平均 x 高于 ref(1)
        rows = []
        for _ in range(8):
            rows += [(0.0, 1), (1.0, 1), (2.0, 1),
                     (1.0, 2), (2.0, 2), (3.0, 2),
                     (2.0, 3), (3.0, 3), (4.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        res = mn.multinomial_regression(X, y, predictor_names=["x"])
        # cat3 vs ref：x 系数显著为正
        assert res["coef"][3][1] > 0
        assert res["p"][3][1] < 0.05

    def test_lr_positive(self):
        rows = []
        for _ in range(8):
            rows += [(0.0, 1), (1.0, 1), (2.0, 1),
                     (1.0, 2), (2.0, 2), (3.0, 2),
                     (2.0, 3), (3.0, 3), (4.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        res = mn.multinomial_regression(X, y, predictor_names=["x"])
        assert res["lr_chi2"] >= 0
        assert res["lr_df"] == 2  # (J-1)*1


# ─────────────────────────────────────────────────────────────────────────────
# 模型拟合统计
# ─────────────────────────────────────────────────────────────────────────────

class TestModelFit:
    def _fit(self):
        # 重叠（非分离）数据，保证 SE 有限、伪 R² 严格 < 1
        rows = []
        for _ in range(8):
            rows += [(0.0, 1), (1.0, 1), (2.0, 1),
                     (1.0, 2), (2.0, 2), (3.0, 2),
                     (2.0, 3), (3.0, 3), (4.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return mn.multinomial_regression(X, y, predictor_names=["x"])

    def test_ll_model_geq_null(self):
        res = self._fit()
        assert res["log_lik_model"] >= res["log_lik_null"] - 1e-6

    def test_mcfadden_range(self):
        res = self._fit()
        assert 0.0 <= res["mcfadden_r2"] <= 1.0

    def test_cox_snell_range(self):
        res = self._fit()
        assert 0.0 <= res["cox_snell_r2"] < 1.0

    def test_nagelkerke_geq_cox_snell(self):
        res = self._fit()
        assert res["nagelkerke_r2"] >= res["cox_snell_r2"] - 1e-9

    def test_lr_df_formula(self):
        res = self._fit()
        assert res["lr_df"] == (res["J"] - 1) * (res["k"] - 1)

    def test_aic_formula(self):
        res = self._fit()
        D = (res["J"] - 1) * res["k"]
        assert abs(res["aic"] - (-2 * res["log_lik_model"] + 2 * D)) < 1e-9

    def test_bic_formula(self):
        res = self._fit()
        D = (res["J"] - 1) * res["k"]
        assert abs(res["bic"]
                   - (-2 * res["log_lik_model"] + D * math.log(res["n"]))) < 1e-9

    def test_lr_p_in_range(self):
        res = self._fit()
        assert 0.0 <= res["lr_p"] <= 1.0

    def test_nonref_order(self):
        res = self._fit()
        # 参照=最小标签 1，非参照按升序 [2,3]
        assert res["ref"] == 1
        assert res["nonref"] == [2, 3]

    def test_categories_sorted(self):
        res = self._fit()
        assert res["categories"] == [1, 2, 3]


# ─────────────────────────────────────────────────────────────────────────────
# 参照类别选择 / 多预测变量
# ─────────────────────────────────────────────────────────────────────────────

class TestRefAndMulti:
    def test_custom_ref(self):
        y = [1] * 4 + [2] * 4 + [3] * 4
        X = [[1.0]] * len(y)
        res = mn.multinomial_regression(X, y, ref=2)
        assert res["ref"] == 2
        assert res["nonref"] == [1, 3]
        # 仅截距：截距_1 = log(n1/n2) = log(4/4) = 0
        assert abs(res["coef"][1][0]) < 1e-5

    def test_invalid_ref(self):
        y = [1, 1, 2, 2, 3, 3]
        X = [[1.0]] * len(y)
        with pytest.raises(ValueError):
            mn.multinomial_regression(X, y, ref=99)

    def test_two_predictors(self):
        rows = []
        for i in range(12):
            rows += [(0.0, 0.0, 1), (1.0, 2.0, 2), (2.0, 1.0, 3)]
        X = [[1.0, a, b] for a, b, _ in rows]
        y = [c for _, _, c in rows]
        res = mn.multinomial_regression(X, y, predictor_names=["a", "b"])
        assert res["k"] == 3
        for lab in res["nonref"]:
            assert len(res["coef"][lab]) == 3

    def test_single_category_raises(self):
        with pytest.raises(ValueError):
            mn.multinomial_regression([[1.0], [1.0]], [1, 1])


# ─────────────────────────────────────────────────────────────────────────────
# format APA
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatAPA:
    def _fit(self):
        rows = []
        for _ in range(10):
            rows += [(0.0, 1), (1.0, 2), (2.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return mn.multinomial_regression(X, y, predictor_names=["x"])

    def test_returns_str(self):
        out = mn.format_apa_multinomial(self._fit(), dv_name="group")
        assert isinstance(out, str) and len(out) > 0

    def test_contains_category_header(self):
        out = mn.format_apa_multinomial(self._fit())
        assert "vs. reference" in out

    def test_contains_or(self):
        out = mn.format_apa_multinomial(self._fit())
        assert "OR" in out

    def test_contains_model_fit(self):
        out = mn.format_apa_multinomial(self._fit())
        assert "McFadden" in out and "χ²" in out

    def test_contains_reference_note(self):
        out = mn.format_apa_multinomial(self._fit(), dv_name="group")
        assert "reference" in out and "group" in out

    def test_fmt_p_small(self):
        assert mn._fmt_p(0.0001) == "< .001"

    def test_fmt_or_inf(self):
        assert mn._fmt_or(math.inf) == ">1e15"


# ─────────────────────────────────────────────────────────────────────────────
# JSON 安全 + 报告写出
# ─────────────────────────────────────────────────────────────────────────────

class TestReportIO:
    def _fit(self):
        rows = []
        for _ in range(8):
            rows += [(0.0, 1), (1.0, 2), (2.0, 3)]
        X = [[1.0, x] for x, _ in rows]
        y = [c for _, c in rows]
        return mn.multinomial_regression(X, y, predictor_names=["x"])

    def test_json_safe_nan(self):
        assert mn._json_safe(float("nan")) is None
        assert mn._json_safe(float("inf")) is None
        assert mn._json_safe(1.5) == 1.5

    def test_json_safe_dict_keys_str(self):
        out = mn._json_safe({1: 2.0, 3: float("nan")})
        assert out == {"1": 2.0, "3": None}

    def test_write_report(self):
        res = self._fit()
        with tempfile.TemporaryDirectory() as d:
            paths = mn.write_multinomial_report(res, out_dir=d, dv_name="g")
            assert os.path.exists(paths["md"])
            assert os.path.exists(paths["json"])
            payload = json.loads(open(paths["json"], encoding="utf-8").read())
            assert "coef" in payload

    def test_write_report_valid_json(self):
        res = self._fit()
        with tempfile.TemporaryDirectory() as d:
            paths = mn.write_multinomial_report(res, out_dir=d)
            # 不应含 NaN/Infinity 字面量
            txt = open(paths["json"], encoding="utf-8").read()
            assert "NaN" not in txt and "Infinity" not in txt

    def test_write_report_no_dir(self):
        res = self._fit()
        assert mn.write_multinomial_report(res, out_dir=None) == {}


# ─────────────────────────────────────────────────────────────────────────────
# analyze CSV 主入口
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeCSV:
    def _write_csv(self, d, rows, header="grp,x"):
        path = os.path.join(d, "data.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header + "\n")
            for r in rows:
                f.write(",".join(str(v) for v in r) + "\n")
        return path

    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for _ in range(10):
                rows += [("A", 0.0), ("B", 1.0), ("C", 2.0)]
            path = self._write_csv(d, rows)
            out = mn.analyze_multinomial(path, "grp", ["x"])
            res = out["result"]
            assert res["J"] == 3
            assert res["category_labels"][res["ref"]] == "A"

    def test_numeric_labels_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for _ in range(8):
                rows += [(10, 0.0), (2, 1.0), (30, 2.0)]
            path = self._write_csv(d, rows)
            out = mn.analyze_multinomial(path, "grp", ["x"])
            res = out["result"]
            # 数值排序 2<10<30 → 参照=最小=2
            assert res["category_labels"][res["ref"]] == "2"

    def test_missing_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for _ in range(8):
                rows += [("A", 0.0), ("B", 1.0), ("C", 2.0)]
            rows.append(("A", ""))      # 缺 x
            rows.append(("", 1.0))      # 缺 grp
            path = self._write_csv(d, rows)
            out = mn.analyze_multinomial(path, "grp", ["x"])
            assert out["result"]["n_excluded"] == 2

    def test_two_categories_raises(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [("A", 0.0), ("B", 1.0)] * 5
            path = self._write_csv(d, rows)
            with pytest.raises(ValueError):
                mn.analyze_multinomial(path, "grp", ["x"])

    def test_custom_ref_label(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for _ in range(8):
                rows += [("A", 0.0), ("B", 1.0), ("C", 2.0)]
            path = self._write_csv(d, rows)
            out = mn.analyze_multinomial(path, "grp", ["x"], ref="B")
            assert out["result"]["ref_label"] == "B"

    def test_invalid_ref_label_raises(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [("A", 0.0), ("B", 1.0), ("C", 2.0)] * 5
            path = self._write_csv(d, rows)
            with pytest.raises(ValueError):
                mn.analyze_multinomial(path, "grp", ["x"], ref="Z")

    def test_writes_sidecar(self):
        with tempfile.TemporaryDirectory() as d:
            rows = []
            for _ in range(8):
                rows += [("A", 0.0), ("B", 1.0), ("C", 2.0)]
            path = self._write_csv(d, rows)
            mn.analyze_multinomial(path, "grp", ["x"], out_dir=d)
            assert os.path.exists(os.path.join(d, "multinomial_report.md"))
            assert os.path.exists(os.path.join(d, "multinomial_report.json"))

    def test_too_few_rows_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_csv(d, [("A", 0.0)])
            with pytest.raises(ValueError):
                mn.analyze_multinomial(path, "grp", ["x"])


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

class TestCLI:
    def _write_csv(self, d):
        path = os.path.join(d, "data.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("grp,x\n")
            for _ in range(10):
                f.write("A,0\nB,1\nC,2\n")
        return path

    def test_cli_runs(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_csv(d)
            rc = mn.multinomial_cli([path, "--dv", "grp", "--iv", "x"])
            assert rc == 0
            assert "vs. reference" in capsys.readouterr().out

    def test_cli_json(self, capsys):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_csv(d)
            rc = mn.multinomial_cli([path, "--dv", "grp", "--iv", "x", "--json"])
            assert rc == 0
            payload = json.loads(capsys.readouterr().out)
            assert "coef" in payload

    def test_cli_bad_file(self, capsys):
        rc = mn.multinomial_cli(["/nonexistent.csv", "--dv", "grp", "--iv", "x"])
        assert rc == 1


# ─────────────────────────────────────────────────────────────────────────────
# CLI 注册
# ─────────────────────────────────────────────────────────────────────────────

class TestCLIRegistration:
    def test_registered(self):
        from psyclaw.cli import build_parser
        parser = build_parser()
        subparsers = [a for a in parser._actions
                      if hasattr(a, "choices") and a.choices]
        found = any("multinom" in a.choices for a in subparsers)
        assert found
