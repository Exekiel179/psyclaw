"""P3-1 元分析工具测试 — ≥30 例，无 scipy 降级可用。"""

from __future__ import annotations

import csv
import io
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.meta import (  # noqa: E402
    _chi2_p_wilson_hilferty,
    _fisher_z,
    _fisher_z_to_r,
    _norm_cdf,
    _ols_simple,
    _se_from_ci,
    _se_from_n1n2,
    compute_meta,
    format_apa,
    forest_plot_text,
    write_sidecar,
    _parse_csv,
)
from psyclaw.gates.checker import (  # noqa: E402
    KIND_TRIGGERS,
    REQUIREMENT_CHECKS,
    check_artifact,
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _make_studies(ds, ses):
    return [{"label": f"S{i+1}", "d": d, "se": se} for i, (d, se) in enumerate(zip(ds, ses))]


def _csv_text(rows, header="study,d,se"):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header.split(","))
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. 统计工具函数
# ---------------------------------------------------------------------------

def test_norm_cdf_half():
    assert abs(_norm_cdf(0) - 0.5) < 1e-10


def test_norm_cdf_196():
    assert abs(_norm_cdf(1.96) - 0.975) < 0.001


def test_norm_cdf_neg():
    assert _norm_cdf(-1.96) < 0.05


def test_chi2_p_zero_q():
    assert _chi2_p_wilson_hilferty(0, 1) == 1.0


def test_chi2_p_df0():
    assert _chi2_p_wilson_hilferty(5, 0) == 1.0


def test_chi2_p_384():
    # chi2(1) = 3.84 → p ≈ 0.05
    p = _chi2_p_wilson_hilferty(3.84, 1)
    assert 0.04 < p < 0.06


def test_fisher_z_roundtrip():
    for r in [0.1, 0.5, 0.9, -0.3]:
        assert abs(_fisher_z_to_r(_fisher_z(r)) - r) < 1e-9


def test_se_from_ci():
    # d=0, CI [-0.392, 0.392] → SE ≈ 0.2
    se = _se_from_ci(0, -0.392, 0.392)
    assert abs(se - 0.2) < 0.01


def test_se_from_n1n2_large():
    # large samples → small SE
    se = _se_from_n1n2(0.3, 100, 100)
    assert se < 0.2


def test_ols_simple_basic():
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [2.0, 4.0, 6.0, 8.0]
    b0, b1, se_b0, se_b1 = _ols_simple(xs, ys)
    assert abs(b1 - 2.0) < 1e-9
    assert abs(b0) < 1e-9


def test_ols_simple_min_n():
    # n<3 returns inf
    _, _, se_b0, _ = _ols_simple([1.0], [2.0])
    assert math.isinf(se_b0)


# ---------------------------------------------------------------------------
# 2. compute_meta — 核心计算
# ---------------------------------------------------------------------------

def test_compute_meta_k2():
    studies = _make_studies([0.5, 0.3], [0.2, 0.15])
    r = compute_meta(studies)
    assert r["k"] == 2


def test_compute_meta_k_too_small():
    try:
        compute_meta(_make_studies([0.5], [0.2]))
        assert False, "应抛 ValueError"
    except ValueError:
        pass


def test_fixed_effect_known():
    # w1=25, w2≈44.44; theta_FE ≈ 0.3722
    studies = _make_studies([0.5, 0.3], [0.2, 1 / math.sqrt(1 / 0.0225)])
    r = compute_meta(studies)
    # 固定效应区间应覆盖 theta_FE
    fe = r["fixed"]
    assert fe["ci"][0] < fe["theta"] < fe["ci"][1]


def test_random_effect_ci_contains_theta():
    studies = _make_studies([0.5, 0.3, 0.4, 0.6], [0.1, 0.12, 0.11, 0.15])
    r = compute_meta(studies)
    re = r["random"]
    assert re["ci"][0] < re["theta"] < re["ci"][1]


def test_tau2_nonneg():
    for ds, ses in [
        ([0.5, 0.3], [0.2, 0.15]),
        ([0.1, 0.9], [0.05, 0.05]),
        ([0.3, 0.3], [0.1, 0.1]),
    ]:
        r = compute_meta(_make_studies(ds, ses))
        assert r["heterogeneity"]["tau2"] >= 0


def test_i2_range():
    studies = _make_studies([0.1, 0.5, 0.9], [0.1, 0.1, 0.1])
    r = compute_meta(studies)
    h = r["heterogeneity"]
    assert 0 <= h["I2"] <= 100


def test_i2_low_for_homogeneous():
    studies = _make_studies([0.5, 0.5, 0.5], [0.1, 0.1, 0.1])
    r = compute_meta(studies)
    assert r["heterogeneity"]["I2"] < 1.0


def test_q_positive():
    studies = _make_studies([0.1, 0.5, 0.9], [0.1, 0.1, 0.1])
    r = compute_meta(studies)
    assert r["heterogeneity"]["Q"] > 0


def test_egger_absent_k_lt10():
    studies = _make_studies([0.3] * 9, [0.1] * 9)
    r = compute_meta(studies)
    assert r["egger"] == {}


def test_egger_present_k10():
    studies = _make_studies([0.2 + i * 0.05 for i in range(10)],
                            [0.1 + i * 0.01 for i in range(10)])
    r = compute_meta(studies)
    eg = r["egger"]
    assert "b0" in eg and "p" in eg and "significant" in eg


def test_gate_fields_present():
    r = compute_meta(_make_studies([0.4, 0.6], [0.1, 0.1]))
    assert r["meta_heterogeneity_reported"] is True
    assert r["meta_effect_ci_reported"] is True


def test_weight_pct_sums_100():
    studies = _make_studies([0.2, 0.4, 0.6], [0.1, 0.12, 0.08])
    r = compute_meta(studies)
    total = sum(s["weight_pct"] for s in r["studies"])
    assert abs(total - 100) < 0.5


def test_tau_eq_sqrt_tau2():
    studies = _make_studies([0.1, 0.9], [0.05, 0.05])
    r = compute_meta(studies)
    h = r["heterogeneity"]
    # both tau and tau2 are rounded to 4dp independently, so tolerance is 1e-4
    assert abs(h["tau"] - math.sqrt(h["tau2"])) < 1e-4


def test_effect_type_passthrough():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies, effect_type="g")
    assert r["effect_type"] == "g"


# ---------------------------------------------------------------------------
# 3. _parse_csv
# ---------------------------------------------------------------------------

def test_parse_csv_se_col():
    txt = _csv_text([["S1", 0.5, 0.1], ["S2", 0.3, 0.12]])
    eff_type, studies = _parse_csv(txt)
    assert eff_type == "d"
    assert len(studies) == 2
    assert abs(studies[0]["se"] - 0.1) < 1e-9


def test_parse_csv_ci_cols():
    txt = _csv_text(
        [["S1", 0.5, 0.108, 0.892], ["S2", 0.3, 0.066, 0.534]],
        header="study,d,ci_lower,ci_upper",
    )
    _, studies = _parse_csv(txt)
    assert abs(studies[0]["se"] - 0.2) < 0.01


def test_parse_csv_n1n2_cols():
    txt = _csv_text(
        [["S1", 0.5, 50, 50], ["S2", 0.3, 60, 60]],
        header="study,d,n1,n2",
    )
    _, studies = _parse_csv(txt)
    assert studies[0]["se"] > 0


def test_parse_csv_r_type():
    txt = _csv_text([["S1", 0.4, 100], ["S2", 0.5, 120]], header="study,r,n")
    eff_type, studies = _parse_csv(txt)
    assert eff_type == "r_z"
    # Fisher z of 0.4 ≈ 0.4236
    assert abs(studies[0]["d"] - _fisher_z(0.4)) < 1e-6


def test_parse_csv_g_type():
    txt = _csv_text([["S1", 0.4, 0.1], ["S2", 0.2, 0.08]], header="study,g,se")
    eff_type, _ = _parse_csv(txt)
    assert eff_type == "g"


def test_parse_csv_no_effect_col():
    txt = _csv_text([["S1", 0.5], ["S2", 0.3]], header="study,x")
    try:
        _parse_csv(txt)
        assert False
    except ValueError:
        pass


def test_parse_csv_invalid_se():
    txt = _csv_text([["S1", 0.5, -0.1]], header="study,d,se")
    try:
        _parse_csv(txt)
        assert False
    except ValueError:
        pass


def test_parse_csv_label_fallback():
    txt = _csv_text([[0.5, 0.1], [0.3, 0.12]], header="d,se")
    _, studies = _parse_csv(txt)
    assert studies[0]["label"] == "Study 1"


# ---------------------------------------------------------------------------
# 4. format_apa
# ---------------------------------------------------------------------------

def test_format_apa_contains_dl():
    studies = _make_studies([0.3, 0.5, 0.4], [0.1, 0.12, 0.09])
    r = compute_meta(studies)
    txt = format_apa(r)
    assert "DerSimonian-Laird" in txt


def test_format_apa_contains_i2():
    studies = _make_studies([0.1, 0.9], [0.05, 0.05])
    r = compute_meta(studies)
    txt = format_apa(r)
    assert "I" in txt and "%" in txt


def test_format_apa_p_lt001():
    # construct extreme effect to get p<0.001
    studies = _make_studies([5.0, 5.0, 5.0, 5.0], [0.01, 0.01, 0.01, 0.01])
    r = compute_meta(studies)
    txt = format_apa(r)
    assert "< .001" in txt


def test_format_apa_r_type_symbol():
    txt = _csv_text([["S1", 0.4, 100], ["S2", 0.5, 120]], header="study,r,n")
    eff_type, studies = _parse_csv(txt)
    r = compute_meta(studies, eff_type)
    txt_apa = format_apa(r)
    assert "*z*" in txt_apa or "z" in txt_apa


# ---------------------------------------------------------------------------
# 5. forest_plot_text
# ---------------------------------------------------------------------------

def test_forest_plot_contains_re_model():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies)
    fp = forest_plot_text(r)
    assert "RE 模型" in fp


def test_forest_plot_contains_heterogeneity():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies)
    fp = forest_plot_text(r)
    assert "I²" in fp or "I2" in fp or "异质性" in fp


def test_forest_plot_contains_study_labels():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies)
    fp = forest_plot_text(r)
    assert "S1" in fp
    assert "S2" in fp


# ---------------------------------------------------------------------------
# 6. write_sidecar
# ---------------------------------------------------------------------------

def test_write_sidecar_json_valid():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies)
    with tempfile.TemporaryDirectory() as d:
        p = write_sidecar(r, Path(d))
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["k"] == 2
        assert "heterogeneity" in data


def test_write_sidecar_gate_fields():
    studies = _make_studies([0.3, 0.5], [0.1, 0.1])
    r = compute_meta(studies)
    with tempfile.TemporaryDirectory() as d:
        p = write_sidecar(r, Path(d))
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["meta_heterogeneity_reported"] is True
        assert data["meta_effect_ci_reported"] is True


# ---------------------------------------------------------------------------
# 7. 门禁 — checker 集成
# ---------------------------------------------------------------------------

def test_meta_in_kind_triggers():
    assert "meta" in KIND_TRIGGERS
    assert "meta_analysis" in KIND_TRIGGERS["meta"]


def test_requirement_checks_registered():
    assert "meta_heterogeneity_reported" in REQUIREMENT_CHECKS
    assert "meta_effect_ci_reported" in REQUIREMENT_CHECKS


def test_gate_passes_with_valid_sidecar():
    studies = _make_studies([0.3, 0.5, 0.4], [0.1, 0.12, 0.09])
    r = compute_meta(studies)
    with tempfile.TemporaryDirectory() as d:
        p = write_sidecar(r, Path(d))
        result = check_artifact(str(p), "meta")
        blocking = [b["gate"] for b in result["blocking"]]
        assert "STAT.meta" not in blocking


def test_gate_blocks_missing_heterogeneity():
    bad = {"meta_heterogeneity_reported": False, "meta_effect_ci_reported": True}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "meta_result.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        result = check_artifact(str(p), "meta")
        blocking = [b["gate"] for b in result["blocking"]]
        assert "STAT.meta" in blocking


def test_gate_blocks_missing_effect_ci():
    bad = {"meta_heterogeneity_reported": True, "meta_effect_ci_reported": False}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "meta_result.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        result = check_artifact(str(p), "meta")
        blocking = [b["gate"] for b in result["blocking"]]
        assert "STAT.meta" in blocking


def test_gate_blocks_missing_sidecar():
    result = check_artifact("/nonexistent/meta_result.json", "meta")
    assert not result["passed"]
    assert result["blocking"]


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
