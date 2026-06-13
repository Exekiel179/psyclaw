"""A-2: 分析计划注册表 — tests (stdlib only)."""
from __future__ import annotations

import inspect
import json
import math
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:
    class _Approx:
        def __init__(self, v, abs=1e-6, rel=None):
            self._v = v
            self._abs = abs
        def __eq__(self, other):
            return abs(other - self._v) <= self._abs
        def __repr__(self):
            return f"approx({self._v})"
    class pytest:  # type: ignore[no-redef]
        @staticmethod
        def approx(v, abs=1e-6, rel=None):
            return _Approx(v, abs=abs)

from psyclaw.psych.analysis_plan import (
    declare,
    check,
    load_plan,
    save_plan,
    log_deviation,
    _normalise_test,
)


# ---------------------------------------------------------------------------
# _normalise_test
# ---------------------------------------------------------------------------

def test_normalise_test_aliases():
    assert _normalise_test("两组比较") == "ttest"
    assert _normalise_test("相关") == "correlation"
    assert _normalise_test("配对比较") == "paired"
    assert _normalise_test("方差分析") == "anova"
    assert _normalise_test("Mann-Whitney") == "mann_whitney"


def test_normalise_test_passthrough():
    assert _normalise_test("ttest") == "ttest"
    assert _normalise_test("anova") == "anova"


# ---------------------------------------------------------------------------
# load_plan / save_plan
# ---------------------------------------------------------------------------

def test_load_plan_empty(tmp_path):
    plan = load_plan(tmp_path)
    assert plan == {"analyses": []}


def test_load_plan_invalid_json(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "analysis_plan.json").write_text("not json", encoding="utf-8")
    plan = load_plan(tmp_path)
    assert plan == {"analyses": []}


def test_save_and_load_roundtrip(tmp_path):
    original = {"analyses": [{"dv": "score", "test": "ttest"}]}
    save_plan(original, tmp_path)
    loaded = load_plan(tmp_path)
    assert loaded == original


# ---------------------------------------------------------------------------
# declare
# ---------------------------------------------------------------------------

def test_declare_basic(tmp_path):
    entry = declare(tmp_path, dv="income", test="correlation", iv="age",
                    hypothesis="confirmatory", name="H1")
    assert entry["dv"] == "income"
    assert entry["test"] == "correlation"
    assert entry["iv"] == "age"
    assert entry["hypothesis"] == "confirmatory"
    assert entry["name"] == "H1"

    plan = load_plan(tmp_path)
    assert len(plan["analyses"]) == 1
    assert plan["analyses"][0]["dv"] == "income"


def test_declare_multiple(tmp_path):
    declare(tmp_path, dv="score", test="ttest", hypothesis="confirmatory")
    declare(tmp_path, dv="anxiety", test="correlation", hypothesis="exploratory")
    plan = load_plan(tmp_path)
    assert len(plan["analyses"]) == 2


def test_declare_missing_dv_raises(tmp_path):
    try:
        declare(tmp_path, dv="", test="ttest")
        assert False, "should have raised"
    except ValueError:
        pass


def test_declare_bad_hypothesis_raises(tmp_path):
    try:
        declare(tmp_path, dv="x", test="ttest", hypothesis="unknown")
        assert False, "should have raised"
    except ValueError:
        pass


def test_declare_auto_name(tmp_path):
    entry = declare(tmp_path, dv="stress", test="anova")
    assert "stress" in entry["name"]


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def test_check_undeclared(tmp_path):
    result = check(tmp_path, dv="score", test="ttest")
    assert result["status"] == "undeclared"
    assert result["entry"] is None
    assert result["deviation"] is None


def test_check_confirmatory_match(tmp_path):
    declare(tmp_path, dv="score", test="ttest", hypothesis="confirmatory", name="H1")
    result = check(tmp_path, dv="score", test="两组比较")  # alias for ttest
    assert result["status"] == "confirmatory"
    assert result["entry"]["name"] == "H1"
    assert result["deviation"] is None


def test_check_exploratory_match(tmp_path):
    declare(tmp_path, dv="depression", test="correlation",
            hypothesis="exploratory")
    result = check(tmp_path, dv="depression", test="相关")
    assert result["status"] == "exploratory"
    assert result["deviation"] is None


def test_check_deviation_detected(tmp_path):
    declare(tmp_path, dv="income", test="correlation", hypothesis="confirmatory")
    result = check(tmp_path, dv="income", test="ttest")  # planned correlation, ran ttest
    assert result["status"] == "confirmatory"
    assert result["deviation"] is not None
    assert "correlation" in result["deviation"]
    assert "ttest" in result["deviation"]


def test_check_dv_case_insensitive(tmp_path):
    declare(tmp_path, dv="Income", test="ttest")
    result = check(tmp_path, dv="income", test="ttest")
    assert result["status"] == "confirmatory"


def test_check_with_iv_match(tmp_path):
    declare(tmp_path, dv="score", test="ttest", iv="group")
    result = check(tmp_path, dv="score", test="ttest", iv="group")
    assert result["status"] == "confirmatory"


# ---------------------------------------------------------------------------
# log_deviation
# ---------------------------------------------------------------------------

def test_log_deviation_creates_file(tmp_path):
    log_deviation(tmp_path, dv="score", actual_test="ttest",
                  planned_test="correlation", note="used group instead")
    log_file = tmp_path / "notes" / "audit_deviations.md"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "score" in content
    assert "ttest" in content
    assert "correlation" in content


def test_log_deviation_appends(tmp_path):
    log_deviation(tmp_path, dv="x", actual_test="anova", planned_test="ttest")
    log_deviation(tmp_path, dv="y", actual_test="correlation", planned_test="anova")
    log_file = tmp_path / "notes" / "audit_deviations.md"
    content = log_file.read_text(encoding="utf-8")
    assert content.count("## ") == 2


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cmd_declare_test(tmp_path):
    from psyclaw.cli import cmd_declare_test
    import argparse
    args = argparse.Namespace(
        dv="score", test="ttest", iv="group",
        hypothesis="confirmatory", name="H1",
        project_dir=str(tmp_path),
    )
    rc = cmd_declare_test(args)
    assert rc == 0
    plan = load_plan(tmp_path)
    assert len(plan["analyses"]) == 1
    assert plan["analyses"][0]["dv"] == "score"


def test_cmd_declare_test_exploratory(tmp_path):
    from psyclaw.cli import cmd_declare_test
    import argparse
    args = argparse.Namespace(
        dv="anxiety", test="correlation", iv=None,
        hypothesis="exploratory", name=None,
        project_dir=str(tmp_path),
    )
    rc = cmd_declare_test(args)
    assert rc == 0


# ---------------------------------------------------------------------------
# Self-run block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as d:
                    fn(Path(d))
            else:
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
