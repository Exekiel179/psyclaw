"""M-3 测量不变性序列测试。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.invariance import (  # noqa: E402
    compute_verdict,
    format_report,
    write_sidecar,
    DELTA_CFI_THRESHOLD,
    DELTA_RMSEA_THRESHOLD,
    _normalize_fits,
    _parse_r_fits,
)
from psyclaw.gates.checker import load_rules, check_artifact, KIND_TRIGGERS  # noqa: E402


# ---------------------------------------------------------------------------
# 常量与判据
# ---------------------------------------------------------------------------

def test_delta_cfi_threshold():
    assert DELTA_CFI_THRESHOLD == -0.010


def test_delta_rmsea_threshold():
    assert DELTA_RMSEA_THRESHOLD == 0.015


# ---------------------------------------------------------------------------
# _normalize_fits — 别名映射
# ---------------------------------------------------------------------------

def test_normalize_alias_loadings():
    fits = {"loadings": {"cfi": 0.98, "rmsea": 0.05}}
    assert "metric" in _normalize_fits(fits)
    assert "loadings" not in _normalize_fits(fits)


def test_normalize_alias_intercepts():
    fits = {"intercepts": {"cfi": 0.97, "rmsea": 0.06}}
    assert "scalar" in _normalize_fits(fits)


def test_normalize_passthrough():
    fits = {"configural": {"cfi": 0.99, "rmsea": 0.04}}
    assert "configural" in _normalize_fits(fits)


# ---------------------------------------------------------------------------
# compute_verdict — 完全不变性
# ---------------------------------------------------------------------------

def test_full_invariance():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.988, "rmsea": 0.044},
        "scalar":     {"cfi": 0.985, "rmsea": 0.046},
    }
    r = compute_verdict(fits)
    assert r["verdict"] == "full_invariance"
    assert r["metric_invariance"] is True
    assert r["scalar_invariance"] is True
    assert r["latent_mean_comparison_ok"] is True
    assert r["partial_invariance_suggested"] is False
    assert r["invariance_tested"] is True


def test_full_invariance_delta_values():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.982, "rmsea": 0.048},
        "scalar":     {"cfi": 0.979, "rmsea": 0.050},
    }
    r = compute_verdict(fits)
    # ΔCFI = 0.982-0.990 = −.008 ≥ −.010 → metric OK
    assert r["levels"]["metric"]["delta_cfi"] == round(0.982 - 0.990, 4)
    assert r["metric_invariance"] is True


# ---------------------------------------------------------------------------
# compute_verdict — scalar 失败 (metric only)
# ---------------------------------------------------------------------------

def test_scalar_fails_metric_only():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.985, "rmsea": 0.046},
        "scalar":     {"cfi": 0.970, "rmsea": 0.065},  # ΔCFI = −.015, ΔRMSEA = +.019
    }
    r = compute_verdict(fits)
    assert r["verdict"] == "metric_only"
    assert r["metric_invariance"] is True
    assert r["scalar_invariance"] is False
    assert r["latent_mean_comparison_ok"] is False
    assert r["partial_invariance_suggested"] is True


def test_scalar_fails_exact_threshold():
    """ΔCFI 恰好等于阈值时通过 (≥ −.010)。"""
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.982, "rmsea": 0.048},
        "scalar":     {"cfi": 0.972, "rmsea": 0.060},  # ΔCFI = −.010 exactly
    }
    r = compute_verdict(fits)
    assert r["scalar_invariance"] is True  # 恰好等于 −.010, 应通过


def test_scalar_fails_just_below_threshold():
    """ΔCFI 略低于阈值时失败 (< −.010)。"""
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.982, "rmsea": 0.048},
        "scalar":     {"cfi": 0.971, "rmsea": 0.060},  # ΔCFI = −.011
    }
    r = compute_verdict(fits)
    assert r["scalar_invariance"] is False


# ---------------------------------------------------------------------------
# compute_verdict — metric 失败 (configural only)
# ---------------------------------------------------------------------------

def test_metric_fails():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.970, "rmsea": 0.070},  # ΔCFI = −.020, ΔRMSEA = +.025
    }
    r = compute_verdict(fits)
    assert r["verdict"] == "configural_only"
    assert r["metric_invariance"] is False
    assert r["scalar_invariance"] is False
    assert r["latent_mean_comparison_ok"] is False
    assert r["partial_invariance_suggested"] is True


# ---------------------------------------------------------------------------
# compute_verdict — 仅含两层
# ---------------------------------------------------------------------------

def test_only_configural_metric():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.988, "rmsea": 0.046},
    }
    r = compute_verdict(fits)
    assert r["metric_invariance"] is True
    assert "scalar" not in r["levels"]


def test_only_configural():
    fits = {"configural": {"cfi": 0.990, "rmsea": 0.045}}
    r = compute_verdict(fits)
    assert r["metric_invariance"] is False
    assert r["scalar_invariance"] is False


# ---------------------------------------------------------------------------
# compute_verdict — 别名输入
# ---------------------------------------------------------------------------

def test_alias_input_loadings_intercepts():
    fits = {
        "configural":  {"cfi": 0.990, "rmsea": 0.045},
        "loadings":    {"cfi": 0.988, "rmsea": 0.045},   # → metric
        "intercepts":  {"cfi": 0.986, "rmsea": 0.046},   # → scalar
    }
    r = compute_verdict(fits)
    assert r["verdict"] == "full_invariance"


# ---------------------------------------------------------------------------
# compute_verdict — RMSEA 标准独立触发失败
# ---------------------------------------------------------------------------

def test_rmsea_threshold_triggers_failure():
    """ΔCFI 通过但 ΔRMSEA 超标 → scalar 失败。"""
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.040},
        "metric":     {"cfi": 0.988, "rmsea": 0.042},
        "scalar":     {"cfi": 0.985, "rmsea": 0.058},   # ΔRMSEA = +.016 > .015
    }
    r = compute_verdict(fits)
    assert r["scalar_invariance"] is False


# ---------------------------------------------------------------------------
# format_report — 内容校验
# ---------------------------------------------------------------------------

def test_format_report_full_invariance():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.988, "rmsea": 0.046},
        "scalar":     {"cfi": 0.985, "rmsea": 0.047},
    }
    report = format_report(compute_verdict(fits))
    assert "完全不变性" in report
    assert "scalar" in report.lower()
    assert "configural" in report.lower()
    assert "Cheung" in report


def test_format_report_scalar_failure():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.985, "rmsea": 0.046},
        "scalar":     {"cfi": 0.968, "rmsea": 0.068},
    }
    report = format_report(compute_verdict(fits))
    assert "阻断" in report or "partial" in report.lower() or "部分" in report
    assert "✗" in report


def test_format_report_has_delta():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.985, "rmsea": 0.048},
    }
    report = format_report(compute_verdict(fits))
    assert "ΔCFI" in report


# ---------------------------------------------------------------------------
# write_sidecar
# ---------------------------------------------------------------------------

def test_write_sidecar_creates_file():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.988, "rmsea": 0.046},
        "scalar":     {"cfi": 0.985, "rmsea": 0.047},
    }
    result = compute_verdict(fits)
    with tempfile.TemporaryDirectory() as td:
        p = write_sidecar(result, td)
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["invariance_tested"] is True
        assert loaded["verdict"] == "full_invariance"


def test_sidecar_contains_all_keys():
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.985, "rmsea": 0.048},
        "scalar":     {"cfi": 0.970, "rmsea": 0.065},
    }
    result = compute_verdict(fits)
    with tempfile.TemporaryDirectory() as td:
        p = write_sidecar(result, td)
        d = json.loads(p.read_text(encoding="utf-8"))
        for key in ("invariance_tested", "scalar_invariance", "metric_invariance",
                    "latent_mean_comparison_ok", "verdict", "levels", "reference"):
            assert key in d, f"missing key: {key}"


# ---------------------------------------------------------------------------
# _parse_r_fits — 解析 R 输出片段
# ---------------------------------------------------------------------------

def test_parse_r_fits_standard():
    r_output = """
psyclaw:fits
fit.configural  0.990  0.045
fit.loadings    0.988  0.044
fit.intercepts  0.985  0.046
psyclaw:models
"""
    fits = _parse_r_fits(r_output)
    assert "configural" in fits
    assert abs(fits["configural"]["cfi"] - 0.990) < 1e-6
    assert abs(fits["configural"]["rmsea"] - 0.045) < 1e-6
    assert "loadings" in fits or "metric" in fits


def test_parse_r_fits_empty():
    assert _parse_r_fits("no relevant output") == {}


def test_parse_r_fits_only_in_block():
    r_output = "fit.configural  0.990  0.045\n"  # 不在 psyclaw:fits 块内
    assert _parse_r_fits(r_output) == {}


# ---------------------------------------------------------------------------
# 门禁集成 — KIND_TRIGGERS
# ---------------------------------------------------------------------------

def test_invariance_trigger_registered():
    assert "invariance" in KIND_TRIGGERS
    assert "latent_mean_comparison" in KIND_TRIGGERS["invariance"]


def test_gate_rule_exists():
    rules = load_rules()
    ids = [g["id"] for g in rules]
    assert "MEASURE.invariance" in ids


def test_gate_is_block():
    rules = load_rules()
    gate = next(g for g in rules if g["id"] == "MEASURE.invariance")
    assert gate.get("action") == "block"


def test_gate_requires_both():
    rules = load_rules()
    gate = next(g for g in rules if g["id"] == "MEASURE.invariance")
    reqs = gate.get("requires", [])
    assert "invariance_tested" in reqs
    assert "scalar_invariance_met" in reqs


# ---------------------------------------------------------------------------
# 门禁 check_artifact — 完整流程
# ---------------------------------------------------------------------------

def _make_invariance_sidecar(tmp_dir: str, scalar_ok: bool) -> str:
    fits = {
        "configural": {"cfi": 0.990, "rmsea": 0.045},
        "metric":     {"cfi": 0.988, "rmsea": 0.046},
        "scalar":     {"cfi": 0.985 if scalar_ok else 0.970,
                       "rmsea": 0.047 if scalar_ok else 0.065},
    }
    result = compute_verdict(fits)
    p = write_sidecar(result, tmp_dir)
    return str(p)


def test_gate_passes_when_scalar_ok():
    with tempfile.TemporaryDirectory() as td:
        sidecar = _make_invariance_sidecar(td, scalar_ok=True)
        res = check_artifact(sidecar, "invariance")
        assert res["passed"] is True
        assert not res["blocking"]


def test_gate_blocks_when_scalar_fails():
    with tempfile.TemporaryDirectory() as td:
        sidecar = _make_invariance_sidecar(td, scalar_ok=False)
        res = check_artifact(sidecar, "invariance")
        assert res["passed"] is False
        gate_ids = [b["gate"] for b in res["blocking"]]
        assert "MEASURE.invariance" in gate_ids


def test_gate_blocks_missing_sidecar():
    res = check_artifact("/nonexistent/invariance_check.json", "invariance")
    assert res["passed"] is False


def test_gate_blocks_untested():
    """sidecar 存在但 invariance_tested=False → block。"""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "invariance_check.json"
        p.write_text(json.dumps({"invariance_tested": False, "scalar_invariance": True}),
                     encoding="utf-8")
        res = check_artifact(str(p), "invariance")
        assert res["passed"] is False


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
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
