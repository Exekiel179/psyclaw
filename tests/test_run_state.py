from __future__ import annotations

import json

from psyclaw.run_state import RunState, infer_artifacts


def test_run_state_persists_goal_context_receipts_and_evidence(tmp_path):
    state = RunState.load(tmp_path, goal="检索并下载", conversation=[
        {"role": "user", "content": "下载刚才的论文"},
    ])
    receipt = state.record_receipt({"name": "lit_search", "ok": True,
                                    "output": "notes/lit_search.json"})
    state.add_artifacts(["notes/lit_search.json"])
    saved = json.loads((tmp_path / ".psyclaw" / "run_state.json").read_text(encoding="utf-8"))
    assert saved["goal"] == "检索并下载"
    assert saved["tool_receipts"][0]["receipt_id"] == receipt["receipt_id"]
    assert saved["artifacts"] == ["notes/lit_search.json"]
    assert (tmp_path / ".psyclaw" / "evidence_index.jsonl").read_text(encoding="utf-8").strip()


def test_infer_artifacts_only_returns_existing_project_files(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "report.md").write_text("ok", encoding="utf-8")
    found = infer_artifacts("已保存 outputs/report.md 和 outputs/missing.md", tmp_path)
    assert found == ["outputs/report.md"]
