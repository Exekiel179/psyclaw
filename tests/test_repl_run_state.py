from __future__ import annotations

import json


def test_repl_run_state_sync_is_non_blocking(tmp_path, monkeypatch):
    from psyclaw.run_state import RunState
    state = RunState.load(tmp_path, conversation=[
        {"role": "user", "content": "检查"},
    ])
    state.add_pending("检查")
    data = json.loads((tmp_path / ".psyclaw" / "run_state.json").read_text(encoding="utf-8"))
    assert "检查" in data["pending_actions"]
