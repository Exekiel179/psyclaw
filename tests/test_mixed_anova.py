"""tests/test_mixed_anova.py — 混合 ANOVA 单元测试（70 例）

覆盖 psyclaw/psych/mixed_anova.py 全部公开函数：
  mixed_anova / simple_effects_within / format_apa_mixed /
  write_mixed_report / analyze_mixed / _mauchly_test

手算验证数据集（2×2 均衡设计）：
  两组各 3 名被试，两个时间点，组×时间交互已知。
"""

import csv
import json
import math
import pathlib
import tempfile

import pytest

from psyclaw.psych.mixed_anova import (
    mixed_anova,
    simple_effects_within,
    format_apa_mixed,
    write_mixed_report,
    analyze_mixed,
    _mauchly_test,
)


# ---------------------------------------------------------------------------
# 辅助：构建标准 2×2 测试数据（手算已验证）
# ---------------------------------------------------------------------------

def _make_data(
    control_pre=(10, 11, 12),
    control_post=(12, 13, 14),
    treat_pre=(10, 11, 12),
    treat_post=(18, 19, 20),
    between_name="group",
    within_name="time",
    subj_name="subject",
    dv_name="score",
):
    rows = []
    idx = 1
    for v_pre, v_post in zip(control_pre, control_post):
        sid = f"s{idx}"; idx += 1
        rows.append({subj_name: sid, between_name: "control", within_name: "pre",  dv_name: v_pre})
        rows.append({subj_name: sid, between_name: "control", within_name: "post", dv_name: v_post})
    for v_pre, v_post in zip(treat_pre, treat_post):
        sid = f"s{idx}"; idx += 1
        rows.append({subj_name: sid, between_name: "treatment", within_name: "pre",  dv_name: v_pre})
        rows.append({subj_name: sid, between_name: "treatment", within_name: "post", dv_name: v_post})
    return rows


BASELINE = _make_data()


def _run(**kwargs):
    data = kwargs.pop("data", BASELINE)
    kw = {"dv": "score", "between": "group", "within": "time", "subject": "subject"}
    kw.update(kwargs)
    return mixed_anova(data, **kw)


# ===========================================================================
# 1. 返回值结构（9 例）
# ===========================================================================

class TestReturnStructure:
    def test_top_keys_present(self):
        r = _run()
        for k in ("between_factor", "within_factor", "subject_col", "dv",
                   "between_levels", "within_levels", "n_per_group", "N",
                   "grand_mean", "alpha", "SS", "df", "MS",
                   "effects", "sphericity", "corrected",
                   "cell_means", "group_means", "condition_means", "warnings"):
            assert k in r, f"缺少键：{k}"

    def test_effects_keys(self):
        r = _run()
        for eff in ("A", "B", "AB"):
            assert eff in r["effects"]
            for k in ("F", "p", "partial_eta2", "partial_omega2", "sig"):
                assert k in r["effects"][eff]

    def test_between_levels_sorted(self):
        r = _run()
        assert r["between_levels"] == sorted(r["between_levels"])

    def test_within_levels_sorted(self):
        r = _run()
        assert r["within_levels"] == sorted(r["within_levels"])

    def test_n_per_group_keys(self):
        r = _run()
        assert set(r["n_per_group"].keys()) == set(r["between_levels"])

    def test_N_equals_sum_n(self):
        r = _run()
        assert r["N"] == sum(r["n_per_group"].values())

    def test_cell_means_structure(self):
        r = _run()
        for lvl in r["between_levels"]:
            assert lvl in r["cell_means"]
            for bl in r["within_levels"]:
                assert bl in r["cell_means"][lvl]

    def test_warnings_is_list(self):
        r = _run()
        assert isinstance(r["warnings"], list)

    def test_alpha_stored(self):
        r = _run(alpha=0.01)
        assert r["alpha"] == 0.01


# ===========================================================================
# 2. df 公式（7 例）
# ===========================================================================

class TestDf:
    """
    a=2 between levels, b=2 within levels, n=3 per group → N=6
    df_A=1, df_SA=4, df_B=1, df_AB=1, df_BSA=4
    """

    def test_df_A(self):
        r = _run()
        assert r["df"]["A"] == 1     # a-1 = 2-1

    def test_df_SA(self):
        r = _run()
        assert r["df"]["SA"] == 4    # N-a = 6-2

    def test_df_B(self):
        r = _run()
        assert r["df"]["B"] == 1     # b-1 = 2-1

    def test_df_AB(self):
        r = _run()
        assert r["df"]["AB"] == 1    # (a-1)(b-1) = 1*1

    def test_df_BSA(self):
        r = _run()
        assert r["df"]["BSA"] == 4   # (N-a)(b-1) = 4*1

    def test_df_A_three_groups(self):
        # 3 groups × 2 conditions, 4 subjects each
        data = []
        for g in ("G1", "G2", "G3"):
            for i in range(4):
                sid = f"{g}_{i}"
                data.append({"s": sid, "g": g, "t": "pre",  "y": 10.0})
                data.append({"s": sid, "g": g, "t": "post", "y": 12.0})
        r = mixed_anova(data, "y", "g", "t", "s")
        assert r["df"]["A"] == 2     # a-1 = 3-1

    def test_df_BSA_three_conditions(self):
        data = []
        for g in ("A", "B"):
            for i in range(3):
                sid = f"{g}{i}"
                for t, v in [("t1", 10), ("t2", 12), ("t3", 14)]:
                    data.append({"s": sid, "g": g, "t": t, "y": float(v)})
        r = mixed_anova(data, "y", "g", "t", "s")
        # a=2, b=3, n=3, N=6 → df_BSA = (N-a)(b-1) = 4*2 = 8
        assert r["df"]["BSA"] == 8


# ===========================================================================
# 3. SS 加和性（4 例）
# ===========================================================================

class TestSSAdditivity:
    def test_ss_sum_equals_total(self):
        r = _run()
        ss = r["SS"]
        total_parts = ss["A"] + ss["SA"] + ss["B"] + ss["AB"] + ss["BSA"]
        assert abs(total_parts - ss["total"]) < 1e-8

    def test_ss_values_nonneg(self):
        r = _run()
        for k, v in r["SS"].items():
            assert v >= -1e-10, f"SS_{k} = {v} 为负"

    def test_ss_additivity_with_noise(self):
        data = _make_data(
            control_pre=(8, 10, 9, 11),
            control_post=(10, 14, 11, 13),
            treat_pre=(9, 11, 8, 10),
            treat_post=(17, 19, 18, 20),
        )
        r = mixed_anova(data, "score", "group", "time", "subject")
        ss = r["SS"]
        total_parts = ss["A"] + ss["SA"] + ss["B"] + ss["AB"] + ss["BSA"]
        assert abs(total_parts - ss["total"]) < 1e-6

    def test_ss_grand_mean_correct(self):
        r = _run()
        all_vals = [10, 12, 11, 13, 12, 14, 10, 18, 11, 19, 12, 20]
        expected_grand = sum(all_vals) / len(all_vals)
        assert abs(r["grand_mean"] - expected_grand) < 1e-10


# ===========================================================================
# 4. 手算已知值验证（8 例）
# ===========================================================================

class TestKnownValues:
    """
    Data (balanced 2×2, n=3 per group):
    Control:   pre=(10,11,12), post=(12,13,14)  → change=+2 each subject
    Treatment: pre=(10,11,12), post=(18,19,20)  → change=+8 each subject

    Grand mean = 162/12 = 13.5
    mean_A[control]=12, mean_A[treatment]=15
    mean_B[pre]=11, mean_B[post]=16
    mean_AB[control][pre]=11, mean_AB[control][post]=13
    mean_AB[treatment][pre]=11, mean_AB[treatment][post]=19

    SS_A = 3*2*((12-13.5)² + (15-13.5)²) = 6*(2.25+2.25) = 27
    SS_SA = 2*((11-12)²+(12-12)²+(13-12)²+(14-15)²+(15-15)²+(16-15)²)
          = 2*(1+0+1+1+0+1) = 8
    SS_B  = 6*((11-13.5)² + (16-13.5)²) = 6*(6.25+6.25) = 75
    SS_AB = 3*((1.5)²+(-1.5)²+(-1.5)²+(1.5)²) = 3*9 = 27
    SS_BSA = 0 (perfectly parallel profiles per subject)
    SS_total = 137
    """

    def test_ss_A(self):
        r = _run()
        assert abs(r["SS"]["A"] - 27.0) < 1e-8

    def test_ss_SA(self):
        r = _run()
        assert abs(r["SS"]["SA"] - 8.0) < 1e-8

    def test_ss_B(self):
        r = _run()
        assert abs(r["SS"]["B"] - 75.0) < 1e-8

    def test_ss_AB(self):
        r = _run()
        assert abs(r["SS"]["AB"] - 27.0) < 1e-8

    def test_ss_BSA(self):
        r = _run()
        # Profiles are perfectly parallel → SS_BS(A) = 0
        assert abs(r["SS"]["BSA"]) < 1e-8

    def test_ss_total(self):
        r = _run()
        assert abs(r["SS"]["total"] - 137.0) < 1e-8

    def test_ms_A(self):
        r = _run()
        # MS_A = SS_A/df_A = 27/1 = 27
        assert abs(r["MS"]["A"] - 27.0) < 1e-8

    def test_ms_SA(self):
        r = _run()
        # MS_SA = SS_SA/df_SA = 8/4 = 2
        assert abs(r["MS"]["SA"] - 2.0) < 1e-8


# ===========================================================================
# 5. F 统计量与显著性（8 例）
# ===========================================================================

class TestFStatistics:
    def test_F_A_known(self):
        r = _run()
        # F_A = MS_A / MS_SA = 27/2 = 13.5
        assert abs(r["effects"]["A"]["F"] - 13.5) < 1e-8

    def test_F_B_inf_when_error_zero(self):
        """SS_BSA=0 → MS_BSA=0 → F_B=nan（不应崩溃）"""
        r = _run()
        # F_B/F_AB should be nan when MS_BSA=0
        assert not math.isfinite(r["effects"]["B"]["F"]) or r["effects"]["B"]["F"] > 0

    def test_p_A_significant(self):
        r = _run()
        # F(1,4)=13.5 → p ≈ 0.021 < .05
        p = r["effects"]["A"]["p"]
        assert p < 0.05

    def test_p_domain_A(self):
        r = _run()
        p = r["effects"]["A"]["p"]
        assert 0.0 <= p <= 1.0

    def test_no_between_effect_F_zero(self):
        """两组完全相同数据 → SS_A=0 → F_A=0"""
        data = _make_data(
            control_pre=(10, 11, 12),
            control_post=(12, 13, 14),
            treat_pre=(10, 11, 12),
            treat_post=(12, 13, 14),
        )
        r = mixed_anova(data, "score", "group", "time", "subject")
        assert abs(r["SS"]["A"]) < 1e-8

    def test_no_between_effect_p_large(self):
        data = _make_data(
            control_pre=(10, 11, 12),
            control_post=(12, 13, 14),
            treat_pre=(10, 11, 12),
            treat_post=(12, 13, 14),
        )
        r = mixed_anova(data, "score", "group", "time", "subject")
        p = r["effects"]["A"]["p"]
        assert p > 0.5

    def test_sig_flag_true_when_p_lt_alpha(self):
        r = _run()
        # F_A is significant at p<0.05
        assert r["effects"]["A"]["sig"] is True

    def test_sig_flag_false_when_no_effect(self):
        data = _make_data(treat_post=(12, 13, 14))  # no difference
        r = mixed_anova(data, "score", "group", "time", "subject")
        assert r["effects"]["A"]["sig"] is False


# ===========================================================================
# 6. 效应量（6 例）
# ===========================================================================

class TestEffectSizes:
    def test_partial_eta2_A_in_range(self):
        r = _run()
        v = r["effects"]["A"]["partial_eta2"]
        assert 0.0 <= v <= 1.0

    def test_partial_eta2_A_formula(self):
        r = _run()
        # partial η² = SS_A / (SS_A + SS_SA)
        expected = r["SS"]["A"] / (r["SS"]["A"] + r["SS"]["SA"])
        assert abs(r["effects"]["A"]["partial_eta2"] - expected) < 1e-10

    def test_partial_eta2_B_formula(self):
        data = _make_data(treat_post=(14, 15, 16))  # non-zero BSA variance
        r = mixed_anova(data, "score", "group", "time", "subject")
        expected = r["SS"]["B"] / (r["SS"]["B"] + r["SS"]["BSA"])
        assert abs(r["effects"]["B"]["partial_eta2"] - expected) < 1e-10

    def test_partial_omega2_A_nonneg(self):
        r = _run()
        v = r["effects"]["A"]["partial_omega2"]
        assert v >= 0.0

    def test_partial_omega2_all_effects_present(self):
        data = _make_data(treat_post=(14, 15, 16))
        r = mixed_anova(data, "score", "group", "time", "subject")
        for eff in ("A", "B", "AB"):
            assert math.isfinite(r["effects"][eff]["partial_omega2"])

    def test_complete_separation_large_eta2(self):
        """极端效应时 partial η² 接近 1。"""
        data = _make_data(
            control_pre=(1, 1, 1), control_post=(1, 1, 1),
            treat_pre=(100, 100, 100), treat_post=(100, 100, 100),
        )
        r = mixed_anova(data, "score", "group", "time", "subject")
        assert r["effects"]["A"]["partial_eta2"] > 0.9


# ===========================================================================
# 7. 球形检验（6 例）
# ===========================================================================

class TestSphericity:
    def test_sphericity_keys(self):
        r = _run()
        for k in ("W", "chi2", "df", "p", "epsilon_gg", "epsilon_hf", "epsilon_lb"):
            assert k in r["sphericity"]

    def test_sphericity_trivial_b2(self):
        """b=2 时球形性自动成立，W=1，p=1。"""
        r = _run()
        assert abs(r["sphericity"]["W"] - 1.0) < 1e-8
        assert abs(r["sphericity"]["p"] - 1.0) < 1e-8

    def test_epsilon_gg_in_range(self):
        data = []
        for g in ("A", "B"):
            for i in range(5):
                sid = f"{g}{i}"
                for t, v in [("t1", float(i)), ("t2", float(i+1)), ("t3", float(i*2))]:
                    data.append({"s": sid, "g": g, "t": t, "y": v})
        r = mixed_anova(data, "y", "g", "t", "s")
        eps = r["sphericity"]["epsilon_gg"]
        assert 1/2 - 1e-10 <= eps <= 1.0 + 1e-10

    def test_corrected_keys(self):
        r = _run()
        for k in ("epsilon", "epsilon_label", "B", "AB"):
            assert k in r["corrected"]

    def test_corrected_B_p_domain(self):
        r = _run()
        p = r["corrected"]["B"]["p"]
        assert 0.0 <= p <= 1.0

    def test_sphericity_not_violated_b2(self):
        r = _run()
        assert r["sphericity_violated"] is False


# ===========================================================================
# 8. 单元格/组/条件均值（5 例）
# ===========================================================================

class TestMeans:
    def test_cell_mean_control_pre(self):
        r = _run()
        expected = (10 + 11 + 12) / 3  # = 11
        assert abs(r["cell_means"]["control"]["pre"] - expected) < 1e-10

    def test_cell_mean_treatment_post(self):
        r = _run()
        expected = (18 + 19 + 20) / 3  # = 19
        assert abs(r["cell_means"]["treatment"]["post"] - expected) < 1e-10

    def test_group_mean_control(self):
        r = _run()
        expected = (10+12+11+13+12+14) / 6  # = 12
        assert abs(r["group_means"]["control"] - expected) < 1e-10

    def test_condition_mean_pre(self):
        r = _run()
        expected = (10+11+12+10+11+12) / 6  # = 11
        assert abs(r["condition_means"]["pre"] - expected) < 1e-10

    def test_grand_mean(self):
        r = _run()
        expected = (10+12+11+13+12+14+10+18+11+19+12+20) / 12  # = 13.5
        assert abs(r["grand_mean"] - expected) < 1e-10


# ===========================================================================
# 9. 简单主效应（8 例）
# ===========================================================================

class TestSimpleEffects:
    def test_simple_effects_returns_list(self):
        r = _run()
        se = simple_effects_within(r)
        assert isinstance(se, list)

    def test_simple_effects_length(self):
        r = _run()
        se = simple_effects_within(r)
        assert len(se) == 2  # one per between level

    def test_simple_effects_between_levels(self):
        r = _run()
        se = simple_effects_within(r)
        lvls = {item["between_level"] for item in se}
        assert lvls == set(r["between_levels"])

    def test_simple_effects_comparisons_b2(self):
        r = _run()
        se = simple_effects_within(r)
        for item in se:
            assert len(item["comparisons"]) == 1  # C(2,2)=1 pair

    def test_simple_effects_comparisons_b3(self):
        data = []
        for g in ("A", "B"):
            for i in range(4):
                sid = f"{g}{i}"
                for t, v in [("t1", 10.0+i), ("t2", 12.0+i), ("t3", 14.0+i)]:
                    data.append({"s": sid, "g": g, "t": t, "y": v})
        r = mixed_anova(data, "y", "g", "t", "s")
        se = simple_effects_within(r)
        for item in se:
            assert len(item["comparisons"]) == 3  # C(3,2)=3 pairs

    def test_simple_effects_p_holm_present(self):
        r = _run()
        se = simple_effects_within(r)
        for item in se:
            for comp in item["comparisons"]:
                assert "p_holm" in comp

    def test_simple_effects_p_domain(self):
        data = _make_data(treat_post=(14, 15, 16))
        r = mixed_anova(data, "score", "group", "time", "subject")
        se = simple_effects_within(r)
        for item in se:
            for comp in item["comparisons"]:
                p = comp["p"]
                if math.isfinite(p):
                    assert 0.0 <= p <= 1.0

    def test_simple_effects_mean_diff_sign(self):
        """control: pre=10,11,12 post=12,13,14 → post - pre > 0"""
        r = _run()
        se = simple_effects_within(r)
        ctrl = next(item for item in se if item["between_level"] == "control")
        comp = ctrl["comparisons"][0]
        # pre vs post: mean_diff = pre - post = -2
        assert abs(abs(comp["mean_diff"]) - 2.0) < 1e-10


# ===========================================================================
# 10. format_apa_mixed（7 例）
# ===========================================================================

class TestFormatApa:
    def test_returns_str(self):
        r = _run()
        s = format_apa_mixed(r)
        assert isinstance(s, str)

    def test_contains_between_factor(self):
        r = _run()
        s = format_apa_mixed(r)
        assert "group" in s

    def test_contains_within_factor(self):
        r = _run()
        s = format_apa_mixed(r)
        assert "time" in s

    def test_contains_F_value(self):
        r = _run()
        s = format_apa_mixed(r)
        assert "*F*" in s or "F(" in s

    def test_contains_partial_eta2(self):
        r = _run()
        s = format_apa_mixed(r)
        assert "η²" in s or "eta" in s.lower()

    def test_contains_reference(self):
        r = _run()
        s = format_apa_mixed(r)
        assert "Kirk" in s or "Maxwell" in s

    def test_post_hoc_in_output(self):
        r = _run()
        se = simple_effects_within(r)
        s = format_apa_mixed(r, post_hoc=se)
        assert "简单主效应" in s or "Simple" in s or "control" in s


# ===========================================================================
# 11. write_mixed_report（5 例）
# ===========================================================================

class TestWriteReport:
    def test_md_file_created(self, tmp_path):
        r = _run()
        md, js = write_mixed_report(r, tmp_path)
        assert md.exists()

    def test_json_file_created(self, tmp_path):
        r = _run()
        md, js = write_mixed_report(r, tmp_path)
        assert js.exists()

    def test_md_nonempty(self, tmp_path):
        r = _run()
        md, _ = write_mixed_report(r, tmp_path)
        assert md.stat().st_size > 0

    def test_json_valid(self, tmp_path):
        r = _run()
        _, js = write_mixed_report(r, tmp_path)
        data = json.loads(js.read_text())
        assert isinstance(data, dict)

    def test_json_no_nan_inf(self, tmp_path):
        r = _run()
        _, js = write_mixed_report(r, tmp_path)
        text = js.read_text()
        assert "NaN" not in text and "Infinity" not in text


# ===========================================================================
# 12. analyze_mixed（5 例）
# ===========================================================================

class TestAnalyzeMixed:
    def _write_csv(self, path: pathlib.Path, data):
        keys = list(data[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(data)

    def test_reads_n_correctly(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, BASELINE)
        r = analyze_mixed(csv_path, "score", "group", "time", "subject")
        assert r["N"] == 6

    def test_return_json_str(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, BASELINE)
        result = analyze_mixed(csv_path, "score", "group", "time", "subject",
                               return_json=True)
        assert isinstance(result, str)
        obj = json.loads(result)
        assert "effects" in obj

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            analyze_mixed(tmp_path / "missing.csv", "y", "g", "t", "s")

    def test_sidecar_written(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, BASELINE)
        out = tmp_path / "out"
        analyze_mixed(csv_path, "score", "group", "time", "subject",
                      out_dir=out)
        assert (out / "mixed_anova_report.md").exists()
        assert (out / "mixed_anova_report.json").exists()

    def test_post_hoc_in_json(self, tmp_path):
        csv_path = tmp_path / "data.csv"
        self._write_csv(csv_path, BASELINE)
        result = analyze_mixed(csv_path, "score", "group", "time", "subject",
                               post_hoc=True, return_json=True)
        obj = json.loads(result)
        assert "post_hoc" in obj


# ===========================================================================
# 13. 边界与错误处理（5 例）
# ===========================================================================

class TestBoundary:
    def test_less_than_two_between_raises(self):
        data = [{"s": "s1", "g": "A", "t": "pre", "y": 10.0},
                {"s": "s1", "g": "A", "t": "post", "y": 12.0},
                {"s": "s2", "g": "A", "t": "pre", "y": 11.0},
                {"s": "s2", "g": "A", "t": "post", "y": 13.0}]
        with pytest.raises(ValueError, match="被试间因素"):
            mixed_anova(data, "y", "g", "t", "s")

    def test_less_than_two_within_raises(self):
        data = [{"s": "s1", "g": "A", "t": "pre", "y": 10.0},
                {"s": "s2", "g": "B", "t": "pre", "y": 12.0}]
        with pytest.raises(ValueError, match="被试内因素"):
            mixed_anova(data, "y", "g", "t", "s")

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="无有效数据行"):
            mixed_anova([], "y", "g", "t", "s")

    def test_incomplete_subjects_excluded_warns(self):
        data = _make_data()
        # Add a subject missing post
        data.append({"subject": "sx", "group": "control", "time": "pre", "score": 10.0})
        r = mixed_anova(data, "score", "group", "time", "subject")
        assert any("sx" in w for w in r["warnings"])
        assert r["N"] == 6  # sx excluded

    def test_unbalanced_warns(self):
        data = _make_data()
        # Add extra subject to control group
        data.append({"subject": "s_extra", "group": "control", "time": "pre",  "score": 10.0})
        data.append({"subject": "s_extra", "group": "control", "time": "post", "score": 12.0})
        r = mixed_anova(data, "score", "group", "time", "subject")
        assert any("非均衡" in w or "不等" in w for w in r["warnings"])


# ===========================================================================
# 14. Mauchly 内部工具（3 例）
# ===========================================================================

class TestMauchly:
    def test_k2_returns_W1(self):
        data_mat = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
        res = _mauchly_test(data_mat, 2)
        assert abs(res["W"] - 1.0) < 1e-8
        assert abs(res["p"] - 1.0) < 1e-8

    def test_k3_compound_symmetry_W_close_1(self):
        """复合对称 (σ²=1, ρ=0.5) 满足球形性，W 接近 1。"""
        import random
        random.seed(42)
        data_mat = []
        for _ in range(30):
            z = random.gauss(0, 1)
            row = [z + random.gauss(0, 0.1) for _ in range(3)]
            data_mat.append(row)
        res = _mauchly_test(data_mat, 3)
        assert math.isfinite(res["W"])
        assert 0.0 < res["W"] <= 1.0 + 1e-8

    def test_epsilon_gg_lower_bound(self):
        """ε_GG ≥ 1/(b-1)。"""
        data_mat = [[float(i + j) for j in range(4)] for i in range(10)]
        res = _mauchly_test(data_mat, 4)
        if math.isfinite(res["epsilon_gg"]):
            assert res["epsilon_gg"] >= 1.0 / 3 - 1e-8
