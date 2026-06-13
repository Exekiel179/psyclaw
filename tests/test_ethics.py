"""D-3 伦理提示测试 — 量表 notes 关键词触发 / 数据感知条目检查 / 软门禁。"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.ethics import (  # noqa: E402
    check_scale_ethics,
    check_item_level_ethics,
    ethics_summary,
    format_ethics_report,
)
from psyclaw.psych.scales import get_scale, score_datafile  # noqa: E402
from psyclaw.gates.checker import load_rules, check_artifact  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_scale(scale_id: str, notes: str = "") -> dict:
    return {"id": scale_id, "name": f"测试量表-{scale_id}", "items": 3,
            "subscales": {}, "reverse": [], "notes": notes}


def _phq9_participants(item9_vals: list[float]) -> list[dict]:
    """构造只含条目 9 的伪 PHQ-9 参与者列表。"""
    return [{"items": {9: v}, "subscales": {}, "total": v, "missing_items": []}
            for v in item9_vals]


def _make_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# check_scale_ethics — notes 关键词触发
# ---------------------------------------------------------------------------

def test_phq9_ethics_warning():
    """PHQ-9 notes 包含自伤意念 → 触发 suicidal_ideation 告警。"""
    scale = get_scale("phq-9")
    assert scale is not None
    warns = check_scale_ethics(scale)
    assert len(warns) >= 1
    assert any("自伤" in w or "suicidal" in w.lower() or "意念" in w for w in warns)


def test_phq9_warn_contains_irb_requirement():
    """PHQ-9 伦理告警必须提及 IRB。"""
    scale = get_scale("phq-9")
    warns = check_scale_ethics(scale)
    combined = "\n".join(warns)
    assert "IRB" in combined or "irb" in combined.lower()


def test_phq9_warn_mentions_crisis_referral():
    """PHQ-9 伦理告警必须提及危机转介或对应措施。"""
    scale = get_scale("phq-9")
    warns = check_scale_ethics(scale)
    combined = "\n".join(warns)
    assert "危机" in combined or "转介" in combined


def test_tipi_no_ethics_warning():
    """TIPI notes 不含伦理敏感词 → 无告警。"""
    scale = get_scale("tipi")
    assert scale is not None
    assert check_scale_ethics(scale) == []


def test_gad7_no_ethics_warning():
    """GAD-7 notes 含筛查/非诊断但不含伦理敏感词 → 无告警。"""
    scale = get_scale("gad-7")
    assert scale is not None
    warns = check_scale_ethics(scale)
    assert warns == [], f"GAD-7 不应触发伦理警告: {warns}"


def test_rses_no_ethics_warning():
    scale = get_scale("rses")
    assert check_scale_ethics(scale) == []


def test_custom_scale_suicidal_notes():
    """自定义量表 notes 含自伤意念 → 触发告警。"""
    scale = _make_scale("custom-dep", notes="本量表条目涉及自伤意念，使用时提示危机转介")
    warns = check_scale_ethics(scale)
    assert len(warns) >= 1
    combined = "\n".join(warns)
    assert "必须" in combined


def test_custom_scale_crisis_referral_notes():
    """notes 含危机转介关键词 → 触发 crisis_referral 告警。"""
    scale = _make_scale("cust", notes="高分者须进行危机转介评估")
    warns = check_scale_ethics(scale)
    assert any("危机" in w for w in warns)


def test_custom_scale_irb_notes():
    """notes 含伦理审查关键词 → 触发 ethics_required 告警。"""
    scale = _make_scale("cust2", notes="使用前须通过伦理审查委员会批准")
    warns = check_scale_ethics(scale)
    assert len(warns) >= 1


def test_empty_notes_no_warning():
    scale = _make_scale("neutral", notes="")
    assert check_scale_ethics(scale) == []


def test_no_notes_field_no_warning():
    scale = {"id": "bare", "name": "裸量表"}
    assert check_scale_ethics(scale) == []


def test_irb_lowercase_match():
    """notes 含小写 irb → 也应触发告警（大小写不敏感）。"""
    scale = _make_scale("cust3", notes="本研究需提交 irb 审批")
    warns = check_scale_ethics(scale)
    assert len(warns) >= 1


def test_category_dedup():
    """同一类别仅报一条告警，不重复输出。"""
    scale = _make_scale("dup", notes="自伤意念 自杀意念 自杀")
    warns = check_scale_ethics(scale)
    categories_hit = sum(1 for w in warns if "自伤" in w or "意念" in w)
    assert categories_hit <= 1, f"同类别重复告警: {warns}"


# ---------------------------------------------------------------------------
# check_item_level_ethics — 数据感知检查
# ---------------------------------------------------------------------------

def test_phq9_item9_endorsement_triggers_warning():
    """PHQ-9 条目 9 ≥ 1 时触发数据感知告警。"""
    scale = get_scale("phq-9")
    participants = _phq9_participants([0, 1, 2, 0])
    warns = check_item_level_ethics(participants, scale)
    assert len(warns) == 1
    assert "PHQ-9" in warns[0]
    assert "自伤" in warns[0]
    assert "2" in warns[0]  # 2 名被试有作答


def test_phq9_item9_all_zero_no_warning():
    """PHQ-9 条目 9 全零 → 无数据感知告警。"""
    scale = get_scale("phq-9")
    participants = _phq9_participants([0, 0, 0])
    warns = check_item_level_ethics(participants, scale)
    assert warns == []


def test_phq9_item9_single_endorser():
    """PHQ-9 仅 1 名被试作答条目 9 → 告警含正确计数。"""
    scale = get_scale("phq-9")
    participants = _phq9_participants([3])
    warns = check_item_level_ethics(participants, scale)
    assert "1" in warns[0]


def test_non_phq9_no_item_level_warning():
    """非 PHQ-9 量表不触发条目级检查。"""
    scale = get_scale("gad-7")
    participants = [{"items": {i: 3.0 for i in range(1, 8)},
                     "subscales": {}, "total": 21.0, "missing_items": []}]
    warns = check_item_level_ethics(participants, scale)
    assert warns == []


def test_empty_participants_no_item_warning():
    scale = get_scale("phq-9")
    assert check_item_level_ethics([], scale) == []


# ---------------------------------------------------------------------------
# ethics_summary
# ---------------------------------------------------------------------------

def test_ethics_summary_phq9_with_data():
    """PHQ-9 + 条目 9 应答 → ethics_level=required, ethics_prompted=True。"""
    scale = get_scale("phq-9")
    participants = _phq9_participants([0, 2])
    summary = ethics_summary(scale, participants)
    assert summary["ethics_prompted"] is True
    assert summary["ethics_level"] == "required"
    assert len(summary["ethics_warnings"]) >= 1


def test_ethics_summary_tipi_no_issues():
    """TIPI → ethics_prompted=False, ethics_level=none。"""
    scale = get_scale("tipi")
    participants = [{"items": {i: 4.0 for i in range(1, 11)},
                     "subscales": {}, "total": 40.0, "missing_items": []}]
    summary = ethics_summary(scale, participants)
    assert summary["ethics_prompted"] is False
    assert summary["ethics_level"] == "none"
    assert summary["ethics_warnings"] == []


def test_ethics_summary_without_participants():
    """只有 notes 触发（无参与者数据）。"""
    scale = get_scale("phq-9")
    summary = ethics_summary(scale)
    assert summary["ethics_prompted"] is True
    assert summary["ethics_level"] == "required"


# ---------------------------------------------------------------------------
# format_ethics_report
# ---------------------------------------------------------------------------

def test_format_ethics_report_phq9_contains_keys():
    """PHQ-9 报告应包含 IRB、危机、转介关键信息。"""
    scale = get_scale("phq-9")
    report = format_ethics_report(scale)
    assert "IRB" in report
    assert "危机" in report or "转介" in report
    assert "必须" in report


def test_format_ethics_report_no_issue_scale():
    """无伦理敏感内容的量表报告应提示"未检测到"。"""
    scale = get_scale("tipi")
    report = format_ethics_report(scale)
    assert "未检测到" in report


# ---------------------------------------------------------------------------
# 集成：score_datafile 包含伦理字段
# ---------------------------------------------------------------------------

def test_score_datafile_phq9_ethics_in_result(tmp_path):
    """score_datafile 对 PHQ-9 应在 warnings 中包含伦理信息，且 ethics_prompted=True。"""
    rows = [{"Q" + str(i): "0" for i in range(1, 10)} for _ in range(3)]
    rows[0]["Q9"] = "2"  # 条目 9 有作答
    f = tmp_path / "phq9.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    assert any("PHQ-9" in w and "自伤" in w for w in result["warnings"])
    assert result.get("ethics_prompted") is True


def test_score_datafile_phq9_all_zero_no_ethics_warn(tmp_path):
    """PHQ-9 条目 9 全零 → 不触发数据感知伦理警告，但 notes 警告仍在。"""
    rows = [{"Q" + str(i): "0" for i in range(1, 10)} for _ in range(3)]
    f = tmp_path / "phq9_zero.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "phq-9", prefix="Q", suffix="")
    # notes 中含自伤意念 → 依然会有 notes-based 告警
    assert result.get("ethics_prompted") is True


def test_score_datafile_tipi_no_ethics_warn(tmp_path):
    """TIPI 量表 → ethics_prompted=False，warnings 无伦理内容。"""
    rows = [{"Q" + str(i): "4" for i in range(1, 11)} for _ in range(3)]
    f = tmp_path / "tipi.csv"
    _make_csv(rows, f)

    result = score_datafile(str(f), "tipi", prefix="Q", suffix="")
    assert result.get("ethics_prompted") is False
    assert not any("IRB" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 门禁: MEASURE.ethics 在 rules.yaml 中存在且为 warn 级别
# ---------------------------------------------------------------------------

def test_measure_ethics_gate_exists():
    """MEASURE.ethics 门禁应在 rules.yaml 中注册。"""
    rules = load_rules()
    ids = {g["id"] for g in rules}
    assert "MEASURE.ethics" in ids


def test_measure_ethics_gate_is_warn():
    rules = load_rules()
    gate = next(g for g in rules if g["id"] == "MEASURE.ethics")
    assert gate.get("action") == "warn"


def test_measure_ethics_gate_trigger():
    rules = load_rules()
    gate = next(g for g in rules if g["id"] == "MEASURE.ethics")
    assert gate.get("trigger") == "scale_score_used"


def test_scale_artifact_with_ethics_prompted_passes_gate(tmp_path):
    """sidecar JSON 含 ethics_prompted 键 → MEASURE.ethics 门禁通过（warn 中无该条）。"""
    sidecar = {"ethics_prompted": True, "reliability_reported": True}
    p = tmp_path / "scale_result.json"
    p.write_text(json.dumps(sidecar), encoding="utf-8")
    result = check_artifact(str(p), "scale")
    # warn 级别门禁不计入 blocking；ethics_reviewed 应通过（key 存在）
    warn_gates = {w["gate"] for w in result["warnings"]}
    assert "MEASURE.ethics" not in warn_gates


def test_scale_artifact_without_ethics_key_warns(tmp_path):
    """sidecar JSON 缺 ethics_prompted → MEASURE.ethics 发出 warn。"""
    sidecar = {"reliability_reported": True}
    p = tmp_path / "scale_result.json"
    p.write_text(json.dumps(sidecar), encoding="utf-8")
    result = check_artifact(str(p), "scale")
    warn_gates = {w["gate"] for w in result["warnings"]}
    assert "MEASURE.ethics" in warn_gates


def test_measure_ethics_gate_does_not_block(tmp_path):
    """MEASURE.ethics 是软门禁，不应出现在 blocking 列表。"""
    sidecar = {}  # 无任何键
    p = tmp_path / "scale_result.json"
    p.write_text(json.dumps(sidecar), encoding="utf-8")
    result = check_artifact(str(p), "scale")
    block_gates = {b["gate"] for b in result["blocking"]}
    assert "MEASURE.ethics" not in block_gates


if __name__ == "__main__":
    import inspect
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    with tempfile.TemporaryDirectory() as _td:
        for name, fn in fns:
            try:
                sig = inspect.signature(fn)
                if "tmp_path" in sig.parameters:
                    p = Path(_td) / name
                    p.mkdir(exist_ok=True)
                    fn(p)
                else:
                    fn()
                print(f"  ✓ {name}")
            except Exception as exc:
                failed += 1
                print(f"  ✗ {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
