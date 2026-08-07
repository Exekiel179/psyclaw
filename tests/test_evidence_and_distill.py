from __future__ import annotations

import json

from psyclaw.evidence import build_ledger, normalize_claim, write_ledger
from psyclaw.skill_distill import promote_lesson, stage_lesson


def test_claim_ledger_is_explicit_and_deduplicated(tmp_path):
    assert normalize_claim("结论") ["status"] == "unverified"
    ledger = build_ledger(["结论", {"claim": "结论", "source": "paper"},
                           {"text": "结论", "source": "paper"}])
    assert len(ledger) == 2
    path = write_ledger(tmp_path / "claims.json", ledger)
    assert json.loads(path.read_text(encoding="utf-8"))[0]["claim"] == "结论"


def test_skill_distill_requires_replay_before_promotion(tmp_path):
    path = tmp_path / "lessons.jsonl"
    stage_lesson(path, source="run-1", lesson="先检查前置", passed=True, evidence=["gate.json"])
    assert promote_lesson(path, source="run-1", replay_passed=False)["ok"] is False
    stage_lesson(path, source="run-2", lesson="复现后再晋升", passed=True, evidence=["test.log"])
    result = promote_lesson(path, source="run-2", replay_passed=True)
    assert result["ok"] and result["record"]["status"] == "promoted"
