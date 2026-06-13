"""W-1: JARS 检查清单 — tests (stdlib only, 自带自跑块)."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

from psyclaw.output.jars import (
    check_draft,
    format_report,
    write_sidecar,
    load_jars_check,
    VALID_RESEARCH_TYPES,
)
from psyclaw.gates.checker import check_artifact, KIND_TRIGGERS


# ---------------------------------------------------------------------------
# 测试文本素材
# ---------------------------------------------------------------------------

_GOOD_QUANT = """
# 方法

## 被试

采用分层随机抽样，纳入标准为 18–65 岁成年人，排除标准包括 DSM-5 轴一诊断。
功效分析结果（G*Power 3.1）表明，基于先验 d = 0.40、α = .05、power = .80，
所需每组 N = 100（双尾 t 检验）。

## 程序

共排除了 12 名被试，其中 8 名因草率作答（longstring > 10），
4 名因未完成所有量表作答，剔除标准与预注册一致。
缺失数据采用 FIML 处理（MCAR 检验 p = .43）。

## 测量

TIPI 量表 Cronbach α = .78，内部一致性良好。

## 分析

报告效应量 Cohen's d 及 95% CI；Bonferroni 校正用于多重比较。
"""

_MISSING_DATA_ABSENT = """
# 方法
## 被试
纳入标准为 18-60 岁成人，排除标准为精神科诊断史。先验功效分析 N = 120。
剔除了 5 名被试，因未完成作答。

## 测量
α = .82，内部一致性可接受。

## 分析
Cohen's d = 0.45, 95% CI [0.12, 0.78], p < .001; Bonferroni 校正。
"""

_EXCLUSIONS_ABSENT = """
# 方法
## 被试
纳入标准：18-65 岁，中文母语者。排除标准：有精神病史。
功效分析(G*Power):N = 80/组。

## 程序
缺失数据采用 multiple imputation 处理（缺失率 < 5%）。

## 分析
效应量 η² = .12, 95% CI [.03, .22]; 多重比较 Bonferroni 校正。
"""

_BOTH_BLOCKING_ABSENT = """
# 方法
## 被试
纳入标准为在校大学生，先验 sample size 依据 N=60。

## 分析
效应量 Cohen's d 及置信区间均已报告；multiple comparison 校正已做。
"""

_QUAL_GOOD = """
# 研究方法
本研究采用现象学(phenomenological)质性研究范式，探索参与者体验。
编码过程(coding)遵循主题分析(thematic)程序，建立了主要类别(category)。
访谈持续至数据饱和(saturation)。
通过三角验证(triangulation)和成员核查(member check)确保可信度。
作者对研究者立场(positionality)进行了充分反思(reflexivity)。
"""

_MIXED_GOOD = """
本研究采用混合方法(mixed method)聚敛设计，整合(integration)定量与定性数据。
定量：缺失数据(missing data)采用 FIML；排除了 3 名被试(excluded 3 participants)因草率作答。
定性：编码(coding)采用主题分析，数据饱和(saturation)。
联合展示(joint display)整合两种数据。
"""


# ---------------------------------------------------------------------------
# check_draft — Quant 路径
# ---------------------------------------------------------------------------

def test_good_quant_passes():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["passed"] is True

def test_good_quant_no_blocking():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["n_blocking"] == 0

def test_good_quant_research_type():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["research_type"] == "quant"

def test_good_quant_n_present():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["n_present"] >= 4

def test_missing_data_blocking_id():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    ids = [b["id"] for b in r["blocking"]]
    assert "Q.procedure.missing_data" in ids

def test_exclusions_blocking_id():
    r = check_draft(_EXCLUSIONS_ABSENT, "quant")
    ids = [b["id"] for b in r["blocking"]]
    assert "Q.procedure.exclusions" in ids

def test_both_blocking_absent_fails():
    r = check_draft(_BOTH_BLOCKING_ABSENT, "quant")
    assert r["passed"] is False

def test_both_blocking_absent_count():
    r = check_draft(_BOTH_BLOCKING_ABSENT, "quant")
    assert r["n_blocking"] == 2

def test_blocking_has_fix():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    for b in r["blocking"]:
        assert b.get("fix"), f"blocking item {b['id']} has no fix"

def test_jars_missing_data_ok_true():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["jars_missing_data_ok"] is True

def test_jars_exclusions_ok_true():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["jars_exclusions_ok"] is True

def test_jars_missing_data_ok_false():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    assert r["jars_missing_data_ok"] is False

def test_jars_exclusions_ok_false():
    r = check_draft(_EXCLUSIONS_ABSENT, "quant")
    assert r["jars_exclusions_ok"] is False

def test_warnings_is_list():
    r = check_draft(_BOTH_BLOCKING_ABSENT, "quant")
    assert isinstance(r["warnings"], list)

def test_present_ids_good():
    r = check_draft(_GOOD_QUANT, "quant")
    present_ids = [p["id"] for p in r["present"]]
    assert "Q.procedure.missing_data" in present_ids
    assert "Q.procedure.exclusions" in present_ids

def test_unknown_type_defaults_quant():
    r = check_draft(_GOOD_QUANT, "foobar")
    assert r["research_type"] == "quant"

def test_empty_text_fails():
    r = check_draft("", "quant")
    assert r["passed"] is False
    assert r["n_present"] == 0

def test_empty_text_n_total_correct():
    from psyclaw.output.jars import _QUANT_ITEMS
    r = check_draft("", "quant")
    assert r["n_total"] == len(_QUANT_ITEMS)

def test_n_blocking_n_warnings_n_present_sum():
    r = check_draft(_GOOD_QUANT, "quant")
    assert r["n_blocking"] + r["n_warnings"] + r["n_present"] == r["n_total"]


# ---------------------------------------------------------------------------
# check_draft — Qual & Mixed 路径
# ---------------------------------------------------------------------------

def test_qual_good_passes():
    r = check_draft(_QUAL_GOOD, "qual")
    assert r["passed"] is True

def test_qual_no_blocking():
    r = check_draft(_QUAL_GOOD, "qual")
    assert r["n_blocking"] == 0

def test_qual_items_detected():
    r = check_draft(_QUAL_GOOD, "qual")
    ids = [p["id"] for p in r["present"]]
    assert "L.design.paradigm" in ids
    assert "L.analysis.coding" in ids
    assert "L.data.saturation" in ids
    assert "L.reflexivity" in ids
    assert "L.trustworthiness" in ids

def test_mixed_good_passes():
    r = check_draft(_MIXED_GOOD, "mixed")
    assert r["passed"] is True

def test_mixed_n_total_larger_than_quant():
    rq = check_draft("", "quant")
    rm = check_draft("", "mixed")
    assert rm["n_total"] > rq["n_total"]

def test_valid_research_types_set():
    assert set(VALID_RESEARCH_TYPES) == {"quant", "qual", "mixed"}


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

def test_format_report_pass_label():
    r = check_draft(_GOOD_QUANT, "quant")
    report = format_report(r)
    assert "通过" in report

def test_format_report_block_label():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    report = format_report(r)
    assert "阻断" in report

def test_format_report_blocking_item():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    report = format_report(r)
    assert "缺失数据" in report

def test_format_report_fix_marker():
    r = check_draft(_MISSING_DATA_ABSENT, "quant")
    report = format_report(r)
    assert "→" in report


# ---------------------------------------------------------------------------
# sidecar IO
# ---------------------------------------------------------------------------

def test_write_sidecar_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_GOOD_QUANT, "quant")
        p = write_sidecar(r, tmpdir)
        assert p.exists()

def test_write_sidecar_json_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_GOOD_QUANT, "quant")
        p = write_sidecar(r, tmpdir)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["passed"] is True

def test_load_jars_check_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert load_jars_check(tmpdir) is None

def test_load_jars_check_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_GOOD_QUANT, "quant")
        write_sidecar(r, tmpdir)
        loaded = load_jars_check(tmpdir)
        assert loaded is not None
        assert loaded["research_type"] == "quant"
        assert loaded["passed"] is True


# ---------------------------------------------------------------------------
# Gate 集成
# ---------------------------------------------------------------------------

def test_jars_kind_in_kind_triggers():
    assert "jars" in KIND_TRIGGERS

def test_jars_kind_triggers_paper_output():
    assert "paper_output" in KIND_TRIGGERS["jars"]

def test_gate_passes_on_good_sidecar():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_GOOD_QUANT, "quant")
        sidecar = write_sidecar(r, tmpdir)
        result = check_artifact(str(sidecar), "jars")
        gate_ids = [b["gate"] for b in result["blocking"]]
        assert "WRITE.jars" not in gate_ids

def test_gate_blocks_on_missing_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_MISSING_DATA_ABSENT, "quant")
        sidecar = write_sidecar(r, tmpdir)
        result = check_artifact(str(sidecar), "jars")
        gate_ids = [b["gate"] for b in result["blocking"]]
        assert "WRITE.jars" in gate_ids

def test_gate_blocks_on_exclusions_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_EXCLUSIONS_ABSENT, "quant")
        sidecar = write_sidecar(r, tmpdir)
        result = check_artifact(str(sidecar), "jars")
        gate_ids = [b["gate"] for b in result["blocking"]]
        assert "WRITE.jars" in gate_ids

def test_gate_fail_closed_missing_file():
    result = check_artifact("/nonexistent/jars_check.json", "jars")
    assert result["passed"] is False
    assert len(result["blocking"]) > 0

def test_gate_both_blocking_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        r = check_draft(_BOTH_BLOCKING_ABSENT, "quant")
        sidecar = write_sidecar(r, tmpdir)
        result = check_artifact(str(sidecar), "jars")
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# 自跑块
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        sig = inspect.signature(fn)
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
