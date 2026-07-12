"""psyclaw status(态势聚合)+ project_sense(本地目录感知)测试。"""

from __future__ import annotations

import json

from psyclaw.project_sense import project_brief, render_tree, scan_tree
from psyclaw.status import collect_status


# --- project_sense -----------------------------------------------------------

def _mkproj(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "lit_review.md").write_text("x", encoding="utf-8")
    (tmp_path / "data" / "clean").mkdir(parents=True)
    (tmp_path / "data" / "clean" / "scores.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "data" / "raw").mkdir()
    (tmp_path / "data" / "raw" / "P001_secret.csv").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_bytes(b"\x00")
    return tmp_path


def test_scan_tree_finds_files_skips_noise(tmp_path):
    t = scan_tree(str(_mkproj(tmp_path)))
    all_files = [f for fs in t["dirs"].values() for f in fs]
    assert "lit_review.md" in all_files and "scores.csv" in all_files
    assert "HEAD" not in all_files and "junk.pyc" not in all_files


def test_scan_tree_protects_raw_names(tmp_path):
    t = scan_tree(str(_mkproj(tmp_path)))
    all_files = [f for fs in t["dirs"].values() for f in fs]
    assert "P001_secret.csv" not in all_files          # 绝不列 raw 文件名
    assert "1 个文件" in t["raw_note"] and "受保护" in t["raw_note"]


def test_scan_tree_truncates(tmp_path):
    for i in range(60):
        (tmp_path / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    t = scan_tree(str(tmp_path), max_entries=20)
    assert t["truncated"] is True


def test_render_and_brief(tmp_path):
    _mkproj(tmp_path)
    out = render_tree(scan_tree(str(tmp_path)))
    assert "scores.csv" in out and "受保护" in out
    brief = project_brief(str(tmp_path))
    assert brief.startswith("# 当前项目结构")
    assert len(brief) < 2000


def test_brief_empty_project(tmp_path):
    assert project_brief(str(tmp_path)) == ""


def test_fold_collapses_many_files(tmp_path):
    for i in range(30):
        (tmp_path / f"n{i:02}.md").write_text("x", encoding="utf-8")
    out = render_tree(scan_tree(str(tmp_path)))
    assert "+18个.md" in out or "个.md" in out           # 折叠计数出现


# --- list_dir 工具 ------------------------------------------------------------

def test_list_dir_tool(tmp_path):
    _mkproj(tmp_path)
    from psyclaw.toolloop import build_tools
    tools = build_tools(str(tmp_path))
    assert tools["list_dir"]["side_effect"] is False
    out = tools["list_dir"]["run"]({})
    assert "scores.csv" in out and "P001_secret" not in out
    assert "目录不存在" in tools["list_dir"]["run"]({"path": str(tmp_path / "nope")})


# --- collect_status -----------------------------------------------------------

def test_status_empty_project(tmp_path):
    st = collect_status(str(tmp_path))
    assert st["goal"] == ""
    assert st["decision_request"] == ""
    assert st["next"] is None or isinstance(st["next"], dict)


def test_status_aggregates(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "goal.md").write_text("正念与焦虑", encoding="utf-8")
    (notes / "decision_request.md").write_text("# 决策请求\n- 需要你确认", encoding="utf-8")
    (notes / "blocked.md").write_text("\n## t1 — A 验收未过\n- x\n\n## t2 — B 验收未过\n- y\n",
                                      encoding="utf-8")
    (notes / "autoloop_state.json").write_text(json.dumps(
        {"iteration": 2, "completed_actions": ["analysis-loop"], "skipped": ["meta-loop"],
         "history": [], "started": "t", "updated": "t"}), encoding="utf-8")
    (notes / "workflow_summary.json").write_text(json.dumps(
        {"workflow": "analysis", "verdict": {"overall_passed": True, "reasons": []}}),
        encoding="utf-8")
    st = collect_status(str(tmp_path))
    assert st["goal"] == "正念与焦虑"
    assert "需要你确认" in st["decision_request"]
    assert st["last_blocked"].startswith("## t2")         # 只留最后一条
    assert st["loop"]["iteration"] == 2
    assert st["loop"]["skipped"] == []
    assert st["loop"]["needs_attention"] == ["meta-loop"]
    assert "✓ 通过" in st["workflow_verdict"]
    assert "goal.md" in " ".join(st["recent_artifacts"])


def test_status_next_suggestion(tmp_path):
    # 数据表 + 完整澄清卡 → next 应指向公开的 run analysis
    from psyclaw.psych.clarify import SLOTS
    notes = tmp_path / "notes"
    notes.mkdir()
    lines = ["| 研究准备项 | 状态 | 内容 |", "|---|---|---|"] + \
            [f"| {s[0]} | resolved | x |" for s in SLOTS]
    (notes / "clarification.md").write_text("\n".join(lines), encoding="utf-8")
    (tmp_path / "scores.csv").write_text("g,y\na,1\nb,2\n", encoding="utf-8")
    st = collect_status(str(tmp_path))
    assert st["next"] and "run analysis" in st["next"]["title"]
    assert st["next"]["blocker"] is False
