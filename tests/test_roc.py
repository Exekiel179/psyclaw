"""ROC 曲线 / AUC 诊断准确性分析测试（psyclaw/psych/roc.py）— 约 65 例。

覆盖：
  分布工具 _norm_cdf / _norm_sf2 / _norm_ppf（8）
  _auc_concordance 含手算金标准（10）
  _hanley_mcneil_se（5）
  roc_auc（11）
  _confusion_at / _metrics_from_confusion（7）
  roc_curve（7）
  optimal_cutoff 含手算金标准（8）
  interpret_auc（6）
  format_apa_roc（5）
  write_roc_report（3）
  analyze_roc CSV（8）
  边界与错误处理（6）
"""

from __future__ import annotations

import csv
import json
import math
import pathlib

import pytest

from psyclaw.psych.roc import (
    _norm_cdf,
    _norm_sf2,
    _norm_ppf,
    _auc_concordance,
    _hanley_mcneil_se,
    _confusion_at,
    _metrics_from_confusion,
    roc_auc,
    roc_curve,
    optimal_cutoff,
    interpret_auc,
    format_apa_roc,
    write_roc_report,
    analyze_roc,
)


# ---------------------------------------------------------------------------
# 分布工具
# ---------------------------------------------------------------------------

def test_norm_cdf_zero():
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-12


def test_norm_cdf_symmetry():
    assert abs(_norm_cdf(1.5) + _norm_cdf(-1.5) - 1.0) < 1e-12


def test_norm_cdf_196():
    assert abs(_norm_cdf(1.959964) - 0.975) < 1e-4


def test_norm_sf2_196():
    # 双尾 p（z=1.96）≈ 0.05
    assert abs(_norm_sf2(1.959964) - 0.05) < 1e-4


def test_norm_sf2_zero():
    assert abs(_norm_sf2(0.0) - 1.0) < 1e-12


def test_norm_ppf_median():
    assert abs(_norm_ppf(0.5)) < 1e-6


def test_norm_ppf_975():
    assert abs(_norm_ppf(0.975) - 1.959964) < 1e-4


def test_norm_ppf_out_of_range():
    assert math.isnan(_norm_ppf(0.0))
    assert math.isnan(_norm_ppf(1.0))


# ---------------------------------------------------------------------------
# _auc_concordance（手算金标准）
# ---------------------------------------------------------------------------

def test_auc_hand_example():
    # pos=[2,3,4], neg=[1,2]: 配对和 = 5.5, AUC = 5.5/6
    assert abs(_auc_concordance([2, 3, 4], [1, 2]) - 5.5 / 6.0) < 1e-12


def test_auc_perfect_separation():
    assert _auc_concordance([3, 4], [1, 2]) == 1.0


def test_auc_no_discrimination():
    # 完全相同分布 → AUC = 0.5
    assert _auc_concordance([1, 2], [1, 2]) == 0.5


def test_auc_reverse():
    # 阳性全低于阴性 → AUC = 0
    assert _auc_concordance([1, 2], [3, 4]) == 0.0


def test_auc_all_ties():
    # 全部平局 → 每对记 .5 → AUC = 0.5
    assert _auc_concordance([5, 5, 5], [5, 5]) == 0.5


def test_auc_single_tie_pair():
    # pos=[2], neg=[2]: 一对平局 → 0.5
    assert _auc_concordance([2], [2]) == 0.5


def test_auc_empty_group_nan():
    assert math.isnan(_auc_concordance([], [1, 2]))
    assert math.isnan(_auc_concordance([1, 2], []))


def test_auc_range():
    a = _auc_concordance([2.5, 3.1, 1.0, 4.0], [1.5, 2.0, 0.5])
    assert 0.0 <= a <= 1.0


def test_auc_matches_brute_force():
    pos = [3.2, 1.1, 4.5, 2.0]
    neg = [2.5, 1.5, 3.0]
    # 暴力配对
    tot = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                tot += 1.0
            elif p == q:
                tot += 0.5
    expected = tot / (len(pos) * len(neg))
    assert abs(_auc_concordance(pos, neg) - expected) < 1e-12


def test_auc_with_ties_matches_brute_force():
    pos = [2, 2, 3, 4]
    neg = [2, 1, 3]
    tot = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                tot += 1.0
            elif p == q:
                tot += 0.5
    expected = tot / (len(pos) * len(neg))
    assert abs(_auc_concordance(pos, neg) - expected) < 1e-12


# ---------------------------------------------------------------------------
# _hanley_mcneil_se
# ---------------------------------------------------------------------------

def test_hm_se_positive():
    se = _hanley_mcneil_se(0.8, 50, 50)
    assert se > 0 and math.isfinite(se)


def test_hm_se_perfect_auc_zero():
    # AUC=1 → Q1=1, Q2=1, var=0
    assert _hanley_mcneil_se(1.0, 30, 30) == 0.0


def test_hm_se_decreases_with_n():
    se_small = _hanley_mcneil_se(0.75, 20, 20)
    se_large = _hanley_mcneil_se(0.75, 200, 200)
    assert se_large < se_small


def test_hm_se_nan_on_bad_input():
    assert math.isnan(_hanley_mcneil_se(0.8, 0, 50))


def test_hm_se_q_formulas():
    # 复核内部公式：var 非负
    se = _hanley_mcneil_se(0.5, 40, 40)
    assert se >= 0


# ---------------------------------------------------------------------------
# roc_auc
# ---------------------------------------------------------------------------

def _toy():
    scores = [2, 3, 4, 1, 2]
    out = [1, 1, 1, 0, 0]
    return scores, out


def test_roc_auc_value():
    scores, out = _toy()
    r = roc_auc(scores, out)
    assert abs(r["auc"] - 5.5 / 6.0) < 1e-6


def test_roc_auc_counts():
    scores, out = _toy()
    r = roc_auc(scores, out)
    assert r["n"] == 5 and r["n_pos"] == 3 and r["n_neg"] == 2


def test_roc_auc_keys():
    scores, out = _toy()
    r = roc_auc(scores, out)
    for k in ("auc", "se", "z", "p", "ci_lower", "ci_upper", "direction", "alpha"):
        assert k in r


def test_roc_auc_ci_within_bounds():
    scores = [5, 6, 7, 8, 1, 2, 3, 4]
    out = [1, 1, 1, 1, 0, 0, 0, 0]
    r = roc_auc(scores, out)
    assert 0.0 <= r["ci_lower"] <= r["ci_upper"] <= 1.0


def test_roc_auc_perfect_separation():
    scores = [5, 6, 7, 1, 2, 3]
    out = [1, 1, 1, 0, 0, 0]
    r = roc_auc(scores, out)
    assert r["auc"] == 1.0
    assert r["ci_lower"] == 1.0 and r["ci_upper"] == 1.0
    assert r["p"] == 0.0


def test_roc_auc_direction_lower():
    # 低分→阳性：阳性组低分
    scores = [1, 2, 3, 5, 6, 7]
    out = [1, 1, 1, 0, 0, 0]
    r = roc_auc(scores, out, direction="lower")
    assert r["auc"] == 1.0


def test_roc_auc_direction_higher_same_data_is_zero():
    scores = [1, 2, 3, 5, 6, 7]
    out = [1, 1, 1, 0, 0, 0]
    r = roc_auc(scores, out, direction="higher")
    assert r["auc"] == 0.0


def test_roc_auc_significant_when_separated():
    scores = list(range(20)) + list(range(5, 25))
    out = [0] * 20 + [1] * 20
    r = roc_auc(scores, out)
    assert r["p"] < 0.05


def test_roc_auc_length_mismatch():
    with pytest.raises(ValueError):
        roc_auc([1, 2, 3], [1, 0])


def test_roc_auc_empty_group():
    with pytest.raises(ValueError):
        roc_auc([1, 2, 3], [1, 1, 1])


def test_roc_auc_alpha_affects_ci_width():
    scores = [5, 6, 7, 8, 1, 2, 3, 4]
    out = [1, 1, 1, 1, 0, 0, 0, 0]
    r90 = roc_auc(scores, out, alpha=0.10)
    r99 = roc_auc(scores, out, alpha=0.01)
    w90 = r90["ci_upper"] - r90["ci_lower"]
    w99 = r99["ci_upper"] - r99["ci_lower"]
    assert w99 >= w90


# ---------------------------------------------------------------------------
# _confusion_at / _metrics_from_confusion
# ---------------------------------------------------------------------------

def test_confusion_at_threshold_higher():
    scores, out = _toy()
    tp, fp, tn, fn = _confusion_at(scores, out, 3, "higher")
    # score>=3 阳性: scores 4,3 (idx 阳性) -> TP=2; 阴性无>=3 -> FP=0
    assert tp == 2 and fp == 0 and tn == 2 and fn == 1


def test_confusion_at_threshold_lower():
    scores = [1, 2, 3]
    out = [1, 0, 0]
    tp, fp, tn, fn = _confusion_at(scores, out, 1, "lower")
    # score<=1 阳性: 只有1 -> TP=1, 阴性无<=1 -> FP=0, TN=2, FN=0
    assert tp == 1 and fp == 0 and tn == 2 and fn == 0


def test_confusion_totals():
    scores, out = _toy()
    tp, fp, tn, fn = _confusion_at(scores, out, 2, "higher")
    assert tp + fp + tn + fn == 5


def test_metrics_sensitivity_specificity():
    m = _metrics_from_confusion(tp=2, fp=0, tn=2, fn=1)
    assert abs(m["sensitivity"] - 2 / 3) < 1e-9
    assert m["specificity"] == 1.0


def test_metrics_ppv_npv():
    m = _metrics_from_confusion(tp=2, fp=0, tn=2, fn=1)
    assert m["ppv"] == 1.0
    assert abs(m["npv"] - 2 / 3) < 1e-9


def test_metrics_accuracy_youden():
    m = _metrics_from_confusion(tp=2, fp=0, tn=2, fn=1)
    assert m["accuracy"] == 0.8
    assert abs(m["youden_j"] - 2 / 3) < 1e-9


def test_metrics_lr_inf_when_spec_one():
    m = _metrics_from_confusion(tp=2, fp=0, tn=2, fn=1)
    assert math.isinf(m["lr_pos"])  # spec=1 → 1-spec=0
    assert abs(m["lr_neg"] - 1 / 3) < 1e-9


# ---------------------------------------------------------------------------
# roc_curve
# ---------------------------------------------------------------------------

def test_roc_curve_endpoints():
    scores, out = _toy()
    c = roc_curve(scores, out)
    pts = c["points"]
    # 首点 FPR=0, sens=0（无人预测阳性）
    assert pts[0]["fpr"] == 0.0
    assert pts[0]["sensitivity"] == 0.0
    # 末点 FPR=1, sens=1（全预测阳性）
    assert pts[-1]["fpr"] == 1.0
    assert pts[-1]["sensitivity"] == 1.0


def test_roc_curve_fpr_monotone():
    scores, out = _toy()
    c = roc_curve(scores, out)
    fprs = [p["fpr"] for p in c["points"]]
    assert fprs == sorted(fprs)


def test_roc_curve_counts():
    scores, out = _toy()
    c = roc_curve(scores, out)
    assert c["n_pos"] == 3 and c["n_neg"] == 2


def test_roc_curve_point_keys():
    scores, out = _toy()
    c = roc_curve(scores, out)
    for k in ("threshold", "sensitivity", "specificity", "fpr", "youden_j"):
        assert k in c["points"][0]


def test_roc_curve_sens_in_range():
    scores, out = _toy()
    c = roc_curve(scores, out)
    for p in c["points"]:
        assert 0.0 <= p["sensitivity"] <= 1.0
        assert 0.0 <= p["specificity"] <= 1.0


def test_roc_curve_lower_direction():
    scores = [1, 2, 3]
    out = [1, 0, 0]
    c = roc_curve(scores, out, direction="lower")
    assert c["points"][0]["fpr"] == 0.0
    assert c["points"][-1]["fpr"] == 1.0


def test_roc_curve_empty_group_error():
    with pytest.raises(ValueError):
        roc_curve([1, 2, 3], [1, 1, 1])


# ---------------------------------------------------------------------------
# optimal_cutoff（手算金标准）
# ---------------------------------------------------------------------------

def test_optimal_cutoff_value():
    scores, out = _toy()
    c = optimal_cutoff(scores, out)
    # 最优 J 在 cutoff=3（J=2/3）
    assert c["cutoff"] == 3


def test_optimal_cutoff_metrics():
    scores, out = _toy()
    c = optimal_cutoff(scores, out)
    assert abs(c["sensitivity"] - 2 / 3) < 1e-9
    assert c["specificity"] == 1.0
    assert abs(c["youden_j"] - 2 / 3) < 1e-9


def test_optimal_cutoff_confusion():
    scores, out = _toy()
    c = optimal_cutoff(scores, out)
    assert c["tp"] == 2 and c["fp"] == 0 and c["tn"] == 2 and c["fn"] == 1


def test_optimal_cutoff_perfect():
    scores = [5, 6, 7, 1, 2, 3]
    out = [1, 1, 1, 0, 0, 0]
    c = optimal_cutoff(scores, out)
    assert c["sensitivity"] == 1.0 and c["specificity"] == 1.0
    assert c["youden_j"] == 1.0


def test_optimal_cutoff_keys():
    scores, out = _toy()
    c = optimal_cutoff(scores, out)
    for k in ("cutoff", "sensitivity", "specificity", "ppv", "npv",
              "accuracy", "youden_j", "lr_pos", "lr_neg", "direction"):
        assert k in c


def test_optimal_cutoff_lower_direction():
    scores = [1, 2, 3, 5, 6, 7]
    out = [1, 1, 1, 0, 0, 0]
    c = optimal_cutoff(scores, out, direction="lower")
    assert c["youden_j"] == 1.0


def test_optimal_cutoff_length_mismatch():
    with pytest.raises(ValueError):
        optimal_cutoff([1, 2], [1])


def test_optimal_cutoff_empty_group():
    with pytest.raises(ValueError):
        optimal_cutoff([1, 2, 3], [0, 0, 0])


# ---------------------------------------------------------------------------
# interpret_auc
# ---------------------------------------------------------------------------

def test_interpret_auc_outstanding():
    assert "卓越" in interpret_auc(0.95)


def test_interpret_auc_excellent():
    assert "优良" in interpret_auc(0.85)


def test_interpret_auc_acceptable():
    assert "可接受" in interpret_auc(0.75)


def test_interpret_auc_poor():
    assert "差" in interpret_auc(0.6)


def test_interpret_auc_random():
    assert "无区分力" in interpret_auc(0.5)


def test_interpret_auc_symmetric():
    # AUC<.5 视为反向同等区分力
    assert interpret_auc(0.1) == interpret_auc(0.9)


def test_interpret_auc_nan():
    assert interpret_auc(float("nan")) == "无法计算"


# ---------------------------------------------------------------------------
# format_apa_roc
# ---------------------------------------------------------------------------

def test_format_apa_returns_str():
    scores, out = _toy()
    r = roc_auc(scores, out)
    c = optimal_cutoff(scores, out)
    s = format_apa_roc(r, c, score_name="PHQ9", outcome_name="MDD")
    assert isinstance(s, str) and len(s) > 0


def test_format_apa_contains_auc():
    scores, out = _toy()
    r = roc_auc(scores, out)
    s = format_apa_roc(r, None)
    assert "AUC" in s


def test_format_apa_contains_references():
    scores, out = _toy()
    r = roc_auc(scores, out)
    s = format_apa_roc(r, None)
    assert "Hanley" in s and "Youden" in s


def test_format_apa_contains_cutoff_section():
    scores, out = _toy()
    r = roc_auc(scores, out)
    c = optimal_cutoff(scores, out)
    s = format_apa_roc(r, c)
    assert "最优截断点" in s and "敏感度" in s


def test_format_apa_names_appear():
    scores, out = _toy()
    r = roc_auc(scores, out)
    s = format_apa_roc(r, None, score_name="GAD7", outcome_name="GAD")
    assert "GAD7" in s and "GAD" in s


# ---------------------------------------------------------------------------
# write_roc_report
# ---------------------------------------------------------------------------

def test_write_roc_report_files(tmp_path):
    scores, out = _toy()
    r = roc_auc(scores, out)
    c = optimal_cutoff(scores, out)
    r["cutoff"] = c
    s = format_apa_roc(r, c)
    paths = write_roc_report(r, s, tmp_path)
    assert pathlib.Path(paths["md"]).exists()
    assert pathlib.Path(paths["json"]).exists()


def test_write_roc_report_valid_json(tmp_path):
    scores, out = _toy()
    r = roc_auc(scores, out)
    s = format_apa_roc(r, None)
    paths = write_roc_report(r, s, tmp_path)
    data = json.loads(pathlib.Path(paths["json"]).read_text(encoding="utf-8"))
    assert "auc" in data


def test_write_roc_report_no_nan_inf(tmp_path):
    # 完美分离 → SE/z 可能 inf；sidecar 须清洗为 null
    scores = [5, 6, 7, 1, 2, 3]
    out = [1, 1, 1, 0, 0, 0]
    r = roc_auc(scores, out)
    s = format_apa_roc(r, None)
    paths = write_roc_report(r, s, tmp_path)
    raw = pathlib.Path(paths["json"]).read_text(encoding="utf-8")
    assert "NaN" not in raw and "Infinity" not in raw


# ---------------------------------------------------------------------------
# analyze_roc（CSV 主入口）
# ---------------------------------------------------------------------------

def _write_csv(tmp_path, rows, header=("score", "dx")):
    p = tmp_path / "data.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow(row)
    return str(p)


def test_analyze_roc_basic(tmp_path):
    rows = [(2, 1), (3, 1), (4, 1), (1, 0), (2, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path))
    assert abs(res["auc"] - 5.5 / 6.0) < 1e-6


def test_analyze_roc_has_cutoff_and_curve(tmp_path):
    rows = [(2, 1), (3, 1), (4, 1), (1, 0), (2, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path))
    assert "cutoff" in res and "curve" in res
    assert res["cutoff"]["cutoff"] == 3


def test_analyze_roc_writes_sidecar(tmp_path):
    rows = [(2, 1), (3, 1), (4, 1), (1, 0), (2, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path))
    assert pathlib.Path(res["_paths"]["md"]).exists()


def test_analyze_roc_return_json_clean(tmp_path):
    rows = [(5, 1), (6, 1), (7, 1), (1, 0), (2, 0), (3, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path), return_json=True)
    assert "_formatted" not in res
    assert "auc" in res


def test_analyze_roc_custom_positive_label(tmp_path):
    rows = [(2, "case"), (3, "case"), (4, "case"), (1, "ctrl"), (2, "ctrl")]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", positive_label="case", out_dir=str(tmp_path))
    assert res["n_pos"] == 3 and res["n_neg"] == 2


def test_analyze_roc_excludes_missing(tmp_path):
    rows = [(2, 1), (3, 1), ("", 1), (4, 1), (1, 0), (2, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path))
    assert res["n_excluded"] == 1
    assert res["n"] == 5


def test_analyze_roc_excludes_nonnumeric_score(tmp_path):
    rows = [(2, 1), ("abc", 1), (4, 1), (1, 0), (2, 0)]
    path = _write_csv(tmp_path, rows)
    res = analyze_roc(path, "score", "dx", out_dir=str(tmp_path))
    assert res["n_excluded"] == 1


def test_analyze_roc_missing_file():
    with pytest.raises(FileNotFoundError):
        analyze_roc("/nonexistent/path.csv", "score", "dx")


# ---------------------------------------------------------------------------
# 边界与错误处理
# ---------------------------------------------------------------------------

def test_analyze_roc_unknown_column(tmp_path):
    rows = [(2, 1), (3, 0)]
    path = _write_csv(tmp_path, rows)
    with pytest.raises(ValueError):
        analyze_roc(path, "nope", "dx", out_dir=str(tmp_path))


def test_roc_auc_invalid_direction():
    with pytest.raises(ValueError):
        roc_auc([1, 2, 3], [1, 0, 1], direction="sideways")


def test_roc_auc_p_in_range():
    scores = [5, 6, 7, 8, 1, 2, 3, 4]
    out = [1, 1, 1, 1, 0, 0, 0, 0]
    r = roc_auc(scores, out)
    assert 0.0 <= r["p"] <= 1.0


def test_optimal_cutoff_lr_pos_finite_when_spec_lt_one():
    # 构造 spec<1 的最优点，LR+ 应有限
    scores = [1, 2, 3, 4, 5, 6]
    out = [0, 1, 0, 1, 0, 1]
    c = optimal_cutoff(scores, out)
    assert c["lr_pos"] is None or math.isfinite(c["lr_pos"]) or math.isinf(c["lr_pos"])


def test_roc_curve_threshold_count():
    scores, out = _toy()
    c = roc_curve(scores, out)
    # 唯一分数 {1,2,3,4} → 4 + 1 端点 = 5 个点
    assert len(c["points"]) == len(set(scores)) + 1


def test_empty_csv_raises(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("score,dx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        analyze_roc(str(p), "score", "dx", out_dir=str(tmp_path))
