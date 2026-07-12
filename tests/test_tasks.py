"""任务追踪测试 — plan 抽取 / 状态机 / TASK_DONE 行首标记 / goal。

原则与质量检查测试一致:解析不到就是 0 条不猜;歧义引用不猜;
TASK_DONE 只认行首标记。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.tasks import (TaskStore, get_goal, parse_plan_tasks,  # noqa: E402
                           parse_task_done, set_goal)

PLAN = """# 计划

- [ ] 这行在 TASKS 章节之前,不该被抽取

## TASKS

- [ ] 诊断数据质量
- [ ] 跑描述统计
- [x] 勾选样式也算任务
- [ ] 跑描述统计

## 停止条件

- [ ] 这行在后续章节,不该被抽取
"""


# ---------------------------------------------------------------------------
# 计划解析
# ---------------------------------------------------------------------------

def test_parse_plan_prefers_tasks_section():
    assert parse_plan_tasks(PLAN) == ["诊断数据质量", "跑描述统计", "勾选样式也算任务"]


def test_parse_plan_fallback_all_checkboxes():
    md = "前言\n- [ ] A\n说明\n* [ ] B\n"
    assert parse_plan_tasks(md) == ["A", "B"]


def test_parse_plan_nothing_is_empty_not_guessed():
    assert parse_plan_tasks("没有任何复选框的计划") == []
    assert parse_plan_tasks("") == []


def test_task_done_line_start_only():
    text = ("TASK_DONE: 诊断数据质量\n"
            "正文里提到 TASK_DONE: 不算\n"
            "  TASK_DONE:跑描述统计\n")
    assert parse_task_done(text) == ["诊断数据质量", "跑描述统计"]


# ---------------------------------------------------------------------------
# 存储与状态机
# ---------------------------------------------------------------------------

def test_store_sync_status_and_persist(tmp_path):
    store = TaskStore(tmp_path)
    assert store.sync_from_plan(PLAN) == 3
    # 再同步幂等:同名不重复
    assert TaskStore(tmp_path).sync_from_plan(PLAN) == 0

    store = TaskStore(tmp_path)
    assert store.progress() == (0, 3)
    assert store.set_status(1, "doing")["status"] == "doing"
    assert store.set_status("描述统计", "done")["title"] == "跑描述统计"
    assert store.progress() == (1, 3)
    # 非法状态拒绝
    assert store.set_status(1, "finished") is None

    # 歧义子串不猜:两条任务都含「统计」时 find 返回 None
    store.add("跑推断统计")
    store.save()
    assert store.find("统计") is None
    # 编号定位仍然精确
    assert store.find(4)["title"] == "跑推断统计"

    # 持久化 roundtrip + 人读镜像
    again = TaskStore(tmp_path)
    assert again.find(1)["status"] == "doing"
    mirror = (tmp_path / "notes" / "tasks.md").read_text(encoding="utf-8")
    assert "- [x] 2. 跑描述统计" in mirror
    assert "(doing)" in mirror


def test_mark_done_from_skips_unmatched(tmp_path):
    store = TaskStore(tmp_path)
    store.sync_from_plan(PLAN)
    hits = store.mark_done_from(
        "脚本完成。\nTASK_DONE: 诊断数据质量\nTASK_DONE: 定位不到的任务\n")
    assert [t["title"] for t in hits] == ["诊断数据质量"]
    assert TaskStore(tmp_path).progress() == (1, 3)
    # 重复标记不重复计数
    assert store.mark_done_from("TASK_DONE: 诊断数据质量") == []


# ---------------------------------------------------------------------------
# goal
# ---------------------------------------------------------------------------

def test_goal_roundtrip(tmp_path):
    assert get_goal(tmp_path) == ""
    set_goal("考察正念训练对焦虑的效应", tmp_path)
    assert get_goal(tmp_path) == "考察正念训练对焦虑的效应"
    assert (tmp_path / "notes" / "goal.md").exists()
