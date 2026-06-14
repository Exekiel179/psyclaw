"""tests/test_sensitivity.py — P3-3 敏感性分析框架测试（≥ 20 例）"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

from psyclaw.psych.sensitivity import (
    _apply_outlier_filter,
    _detect_outlier_threshold,
    _detect_test_label,
    _extract_forks_from_markdown,
    _parse_forks_yaml,
    _r_to_d,
    _run_spec,
    analyze_sensitivity,
    apply_spec_to_data,
    compute_robustness,
    format_apa_sensitivity,
    format_ascii_spec_curve,
    generate_multiverse,
    parse_forks,
    run_multiverse,
)


# ===========================================================================
# 辅助：构造样本数据
# ===========================================================================

def _rows(g1_vals, g2_vals, dv="score", group="cond", g1_label="A", g2_label="B"):
    rows = []
    for v in g1_vals:
        rows.append({dv: str(v), group: g1_label})
    for v in g2_vals:
        rows.append({dv: str(v), group: g2_label})
    return rows


def _make_csv(g1_vals, g2_vals, dv="score", group="cond"):
    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[dv, group])
    writer.writeheader()
    for v in g1_vals:
        writer.writerow({dv: str(v), group: "A"})
    for v in g2_vals:
        writer.writerow({dv: str(v), group: "B"})
    return buf.getvalue()


_YAML_TEXT = """\
forks:
  - name: outlier_exclusion
    label: "离群值剔除"
    type: outlier
    choices:
      - label: none
        description: "不剔除"
      - label: "2SD"
        description: "剔除 2SD"
      - label: "3SD"
        description: "剔除 3SD"
  - name: test_type
    label: "统计检验"
    type: test_type
    choices:
      - label: welch
        description: "Welch t"
      - label: mann_whitney
        description: "Mann-Whitney U"
"""

_MD_TEXT = f"""\
# 研究计划

这里是文字说明。

```yaml sensitivity_forks
{_YAML_TEXT}```

其他内容。
"""


# ===========================================================================
# 1–4: YAML 解析
# ===========================================================================

def test_parse_forks_yaml_basic():
    forks = _parse_forks_yaml(_YAML_TEXT)
    assert len(forks) == 2
    assert forks[0]["name"] == "outlier_exclusion"
    assert forks[0]["label"] == "离群值剔除"
    assert forks[0]["type"] == "outlier"
    assert len(forks[0]["choices"]) == 3
    assert forks[1]["name"] == "test_type"
    assert len(forks[1]["choices"]) == 2


def test_parse_forks_yaml_choice_labels():
    forks = _parse_forks_yaml(_YAML_TEXT)
    labels = [c["label"] for c in forks[0]["choices"]]
    assert labels == ["none", "2SD", "3SD"]


def test_parse_forks_yaml_choice_descriptions():
    forks = _parse_forks_yaml(_YAML_TEXT)
    descs = [c["description"] for c in forks[0]["choices"]]
    assert "不剔除" in descs[0]
    assert "2SD" in descs[1]


def test_parse_forks_yaml_empty():
    assert _parse_forks_yaml("") == []
    assert _parse_forks_yaml("# just a comment") == []


# ===========================================================================
# 5–6: Markdown 提取
# ===========================================================================

def test_extract_forks_from_markdown_found():
    extracted = _extract_forks_from_markdown(_MD_TEXT)
    assert extracted is not None
    assert "forks:" in extracted


def test_extract_forks_from_markdown_not_found():
    result = _extract_forks_from_markdown("# no code block here\nsome text")
    assert result is None


# ===========================================================================
# 7–9: 文件解析（parse_forks）
# ===========================================================================

def test_parse_forks_from_yaml_file():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(_YAML_TEXT)
        fname = f.name
    try:
        forks = parse_forks(fname)
        assert len(forks) == 2
        assert forks[0]["name"] == "outlier_exclusion"
    finally:
        os.unlink(fname)


def test_parse_forks_from_markdown_file():
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(_MD_TEXT)
        fname = f.name
    try:
        forks = parse_forks(fname)
        assert len(forks) == 2
    finally:
        os.unlink(fname)


def test_parse_forks_from_json_file():
    data = {"forks": [{"name": "test", "label": "Test", "type": "test_type",
                        "choices": [{"label": "a"}, {"label": "b"}]}]}
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                     encoding="utf-8", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        forks = parse_forks(fname)
        assert len(forks) == 1
        assert forks[0]["name"] == "test"
    finally:
        os.unlink(fname)


def test_parse_forks_file_not_found():
    raised = False
    try:
        parse_forks("/nonexistent/path/forks.yaml")
    except FileNotFoundError:
        raised = True
    assert raised, "Expected FileNotFoundError"


# ===========================================================================
# 10–13: 多元宇宙生成
# ===========================================================================

def test_generate_multiverse_count():
    forks = _parse_forks_yaml(_YAML_TEXT)
    specs = generate_multiverse(forks)
    # 3 outlier choices × 2 test choices = 6
    assert len(specs) == 6


def test_generate_multiverse_ids_unique():
    forks = _parse_forks_yaml(_YAML_TEXT)
    specs = generate_multiverse(forks)
    ids = [s["id"] for s in specs]
    assert len(set(ids)) == len(ids)


def test_generate_multiverse_empty():
    assert generate_multiverse([]) == []


def test_generate_multiverse_choices_keys():
    forks = _parse_forks_yaml(_YAML_TEXT)
    specs = generate_multiverse(forks)
    for spec in specs:
        assert "outlier_exclusion" in spec["choices"]
        assert "test_type" in spec["choices"]


# ===========================================================================
# 14–17: 离群值过滤
# ===========================================================================

def test_apply_outlier_filter_none():
    pairs = [(1.0, "A"), (100.0, "A"), (2.0, "B")]
    result = _apply_outlier_filter(pairs, None)
    assert result == pairs


def test_apply_outlier_filter_2sd_removes_extreme():
    # A 组：20 个紧密聚集的正常值(mean≈5, SD≈0.1)+ 1 个极端值 100
    # 包含极端值时均值≈9.5, SD≈20 → 100 距均值约 4.5 SD，被 2SD 阈值剔除
    normal_a = [4.9 + (i % 5) * 0.05 for i in range(20)]  # ≈ [4.9~5.1]
    pairs = [(v, "A") for v in normal_a] + [(100.0, "A")]
    pairs += [(3.0, "B"), (4.0, "B"), (5.0, "B")]
    filtered = _apply_outlier_filter(pairs, 2.0)
    a_vals = [v for v, g in filtered if g == "A"]
    assert 100.0 not in a_vals
    assert any(v in a_vals for v in normal_a[:5])


def test_apply_outlier_filter_3sd_keeps_moderate():
    # 同一数据，3SD 阈值更宽松
    pairs = [(4.0, "A"), (5.0, "A"), (6.0, "A"), (12.0, "A"),
             (3.0, "B"), (4.0, "B"), (5.0, "B")]
    filtered_2sd = _apply_outlier_filter(pairs, 2.0)
    filtered_3sd = _apply_outlier_filter(pairs, 3.0)
    # 3SD 过滤后保留的数量应 ≥ 2SD 过滤后
    assert len(filtered_3sd) >= len(filtered_2sd)


def test_apply_outlier_filter_empty():
    assert _apply_outlier_filter([], 2.0) == []


# ===========================================================================
# 18–22: 单规格统计检验
# ===========================================================================

_G1 = [1.0, 2.0, 3.0, 4.0, 5.0]
_G2 = [3.0, 4.0, 5.0, 6.0, 7.0]


def test_run_spec_welch_returns_d_and_p():
    r = _run_spec(_G1, _G2, "welch")
    assert "error" not in r
    assert not math.isnan(r["d"])
    assert not math.isnan(r["p"])
    assert r["d"] < 0  # G1 < G2 → negative d


def test_run_spec_mann_whitney_returns_d_and_p():
    r = _run_spec(_G1, _G2, "mann_whitney")
    assert "error" not in r
    assert not math.isnan(r["d"])
    assert not math.isnan(r["p"])


def test_run_spec_student_returns_d_and_p():
    r = _run_spec(_G1, _G2, "student")
    assert "error" not in r
    assert not math.isnan(r["d"])
    assert 0.0 < r["p"] <= 1.0


def test_run_spec_ci_contains_d():
    r = _run_spec(_G1, _G2, "welch")
    assert r["ci_lo"] <= r["d"] <= r["ci_hi"]


def test_run_spec_insufficient_data_returns_error():
    r = _run_spec([1.0], [2.0], "welch")
    assert "error" in r
    assert math.isnan(r["d"])


# ===========================================================================
# 23–25: 规格应用于数据
# ===========================================================================

def _make_spec(outlier="none", test="welch"):
    return {
        "id": "spec_test",
        "choices": {
            "outlier_exclusion": {
                "fork": "outlier_exclusion",
                "fork_label": "离群值剔除",
                "label": outlier,
                "description": "",
            },
            "test_type": {
                "fork": "test_type",
                "fork_label": "统计检验",
                "label": test,
                "description": "",
            },
        },
    }


def test_apply_spec_welch_no_outlier():
    rows = _rows(_G1, _G2)
    spec = _make_spec(outlier="none", test="welch")
    r = apply_spec_to_data(rows, "score", "cond", spec)
    assert "error" not in r
    assert r["n1"] == 5
    assert r["n2"] == 5
    assert r["n_removed"] == 0
    assert not math.isnan(r["d"])


def test_apply_spec_mann_whitney():
    rows = _rows(_G1, _G2)
    spec = _make_spec(outlier="none", test="mann_whitney")
    r = apply_spec_to_data(rows, "score", "cond", spec)
    assert "error" not in r
    assert r["test"] == "Mann-Whitney U"


def test_apply_spec_with_outlier_removal():
    g1_with_outlier = _G1 + [100.0]
    rows = _rows(g1_with_outlier, _G2)
    spec_none = _make_spec(outlier="none", test="welch")
    spec_2sd = _make_spec(outlier="2SD", test="welch")
    r_none = apply_spec_to_data(rows, "score", "cond", spec_none)
    r_2sd = apply_spec_to_data(rows, "score", "cond", spec_2sd)
    assert r_2sd["n_removed"] > 0
    assert r_2sd["n_total"] < r_none["n_total"]


# ===========================================================================
# 26–28: 稳健性计算
# ===========================================================================

def _make_results(ds_ps):
    """ds_ps: [(d, p), ...]"""
    return [{"d": d, "p": p, "n1": 10, "n2": 10, "ci_lo": d - 0.5, "ci_hi": d + 0.5}
            for d, p in ds_ps]


def test_compute_robustness_all_significant():
    results = _make_results([(0.5, 0.01), (0.6, 0.02), (0.4, 0.03)])
    rob = compute_robustness(results, alpha=0.05)
    assert rob["k_valid"] == 3
    assert rob["k_sig"] == 3
    assert rob["pct_sig"] == 100.0
    assert rob["pct_robust"] == 100.0


def test_compute_robustness_none_significant():
    results = _make_results([(0.1, 0.5), (0.2, 0.6), (0.0, 0.9)])
    rob = compute_robustness(results, alpha=0.05)
    assert rob["k_sig"] == 0
    assert rob["pct_sig"] == 0.0


def test_compute_robustness_mixed():
    results = _make_results([(0.5, 0.01), (0.3, 0.08), (0.4, 0.03), (0.2, 0.2)])
    rob = compute_robustness(results, alpha=0.05)
    assert rob["k_sig"] == 2
    assert rob["k_valid"] == 4
    assert abs(rob["pct_sig"] - 50.0) < 0.01
    assert not math.isnan(rob["median_d"])


def test_compute_robustness_empty_valid():
    results = [{"d": float("nan"), "p": float("nan"), "error": "err"}]
    rob = compute_robustness(results)
    assert rob["k_valid"] == 0
    assert math.isnan(rob["median_d"])


# ===========================================================================
# 29–30: ASCII 规格曲线
# ===========================================================================

def test_format_ascii_spec_curve_basic():
    results = _make_results([(0.5, 0.01), (0.2, 0.06), (-0.1, 0.7)])
    for i, r in enumerate(results):
        r["spec_id"] = f"spec_{i+1:03d}"
        r["choices_desc"] = f"spec {i+1}"
    output = format_ascii_spec_curve(results, alpha=0.05)
    assert "规格曲线" in output
    assert "●" in output  # 有显著项
    assert "○" in output  # 有不显著项
    assert "-0.100" in output or "−0.100" in output or "-0.1" in output


def test_format_ascii_spec_curve_empty():
    output = format_ascii_spec_curve([{"d": float("nan"), "p": 0.5, "error": "err"}])
    assert "无有效规格" in output


# ===========================================================================
# 31–32: APA-7 段落
# ===========================================================================

def test_format_apa_high_robustness():
    forks = _parse_forks_yaml(_YAML_TEXT)
    rob = {"k_specs": 6, "k_valid": 6, "k_sig": 6, "k_pos": 6, "k_robust": 6,
           "pct_sig": 100.0, "pct_robust": 100.0,
           "median_d": 0.45, "d_range": (0.3, 0.6), "median_p": 0.02, "alpha": 0.05}
    text = format_apa_sensitivity(forks, rob)
    assert "稳健性" in text or "Steegen" in text
    assert "多元宇宙" in text


def test_format_apa_no_data():
    forks = _parse_forks_yaml(_YAML_TEXT)
    rob = {"k_specs": 6, "k_valid": 0, "alpha": 0.05}
    text = format_apa_sensitivity(forks, rob)
    assert "规格曲线将在数据收集完成后" in text


# ===========================================================================
# 33–36: 主入口 analyze_sensitivity
# ===========================================================================

def test_analyze_sensitivity_enumerate_only():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write(_YAML_TEXT)
        fname = f.name
    try:
        result = analyze_sensitivity(fname)
        assert result.get("error") is None
        assert result["k_forks"] == 2
        assert result["k_specs"] == 6
        assert result["results"] == []  # 无数据
        assert "多元宇宙" in result["apa_text"]
    finally:
        os.unlink(fname)


def test_analyze_sensitivity_with_data():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as yf:
        yf.write(_YAML_TEXT)
        yname = yf.name

    csv_content = _make_csv(_G1, _G2)
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w",
                                     encoding="utf-8", delete=False) as cf:
        cf.write(csv_content)
        cname = cf.name
    try:
        result = analyze_sensitivity(yname, data_path=cname, dv_col="score", group_col="cond")
        assert result.get("error") is None
        assert len(result["results"]) == 6  # 3×2
        assert result["robustness"]["k_valid"] == 6
        assert result["ascii_spec_curve"] != ""
        assert "Steegen" in result["apa_text"]
    finally:
        os.unlink(yname)
        os.unlink(cname)


def test_analyze_sensitivity_file_not_found():
    raised = False
    try:
        analyze_sensitivity("/not/exists.yaml")
    except FileNotFoundError:
        raised = True
    assert raised, "Expected FileNotFoundError"


def test_analyze_sensitivity_no_forks():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as f:
        f.write("# just comments\nno_forks_here: true\n")
        fname = f.name
    try:
        result = analyze_sensitivity(fname)
        assert "error" in result
        assert result["k_forks"] == 0
    finally:
        os.unlink(fname)


def test_analyze_sensitivity_missing_columns():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as yf:
        yf.write(_YAML_TEXT)
        yname = yf.name

    csv_content = _make_csv(_G1, _G2)
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w",
                                     encoding="utf-8", delete=False) as cf:
        cf.write(csv_content)
        cname = cf.name
    try:
        result = analyze_sensitivity(yname, data_path=cname,
                                     dv_col="NONEXISTENT", group_col="cond")
        assert "error" in result
    finally:
        os.unlink(yname)
        os.unlink(cname)


# ===========================================================================
# 37–38: 辅助函数
# ===========================================================================

def test_r_to_d_conversion():
    # r=0 → d=0
    assert _r_to_d(0.0) == 0.0
    # r=0.5 → d ≈ 1.155 (2*0.5/sqrt(1-0.25))
    expected = 2 * 0.5 / math.sqrt(1 - 0.25)
    assert abs(_r_to_d(0.5) - expected) < 1e-9
    # 正负对称
    assert abs(_r_to_d(-0.5) - (-expected)) < 1e-9


def test_detect_outlier_threshold():
    choices_2sd = {
        "outlier_exclusion": {"fork": "outlier_exclusion", "label": "2SD"}
    }
    assert _detect_outlier_threshold(choices_2sd) == 2.0

    choices_none = {
        "outlier_exclusion": {"fork": "outlier_exclusion", "label": "none"}
    }
    assert _detect_outlier_threshold(choices_none) is None

    choices_3sd = {
        "outlier_exclusion": {"fork": "outlier_exclusion", "label": "3SD"}
    }
    assert _detect_outlier_threshold(choices_3sd) == 3.0


def test_detect_test_label():
    choices_mw = {
        "test_type": {"fork": "test_type", "label": "mann_whitney"}
    }
    assert _detect_test_label(choices_mw) == "mann_whitney"

    choices_student = {
        "test_type": {"fork": "test_type", "label": "student"}
    }
    assert _detect_test_label(choices_student) == "student"

    # 默认
    assert _detect_test_label({}) == "welch"


# ===========================================================================
# 39: sidecar 写出
# ===========================================================================

def test_analyze_sensitivity_sidecar_output():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w",
                                     encoding="utf-8", delete=False) as yf:
        yf.write(_YAML_TEXT)
        yname = yf.name

    csv_content = _make_csv(_G1, _G2)
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w",
                                     encoding="utf-8", delete=False) as cf:
        cf.write(csv_content)
        cname = cf.name

    with tempfile.TemporaryDirectory() as td:
        try:
            analyze_sensitivity(yname, data_path=cname, dv_col="score",
                                group_col="cond", out_dir=td)
            assert Path(td, "sensitivity_report.md").exists()
            assert Path(td, "sensitivity_report.json").exists()
            # JSON is valid
            with open(Path(td, "sensitivity_report.json"), encoding="utf-8") as jf:
                data = json.load(jf)
            assert "k_specs" in data
        finally:
            os.unlink(yname)
            os.unlink(cname)


# ---------------------------------------------------------------------------
# 自跑块（python tests/test_sensitivity.py）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
