"""任务追踪 — goal / plan / task 三层进度管理(stdlib only)。

分层(与 DESIGN.md §8 项目布局一致):
- goal  : notes/goal.md            研究目标(与 loop.py 共用同一真源)
- plan  : notes/plan.md            planner 产出,末尾带 `## TASKS` 章节
- tasks : .psyclaw/tasks.json      机器状态(真源)
          notes/tasks.md           人读镜像(每次保存自动再生,勿手改)

机制(沿用 loop.py 的行首标记纪律):
- 任务从计划**自动抽取**:`## TASKS` 章节下的 `- [ ]` 复选框行;
  没有该章节时回落到全篇 checkbox 行 —— 解析不到就是 0 条,不猜。
- 执行进度用行首 `TASK_DONE: <编号或标题>` 标记机器识别,
  定位不到或歧义的标记直接跳过(与 DECISION_REQUEST 同款纪律)。

状态机:todo → doing → done;blocked 可从任意态进入/退出。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from psyclaw import ui

STATUSES = ("todo", "doing", "done", "blocked")
_ICONS = {"todo": "·", "doing": "▶", "done": "✓", "blocked": "✗"}

_SECTION_RE = re.compile(r"(?mi)^#{2,3}\s*TASKS\s*$")
_HEADING_RE = re.compile(r"(?m)^#{1,3}\s")
_CHECKBOX_RE = re.compile(r"(?m)^\s*[-*]\s*\[(?:[ xX])?\]\s*(.+?)\s*$")
_TASK_DONE_RE = re.compile(r"(?m)^\s*TASK_DONE\s*[::]\s*(.+?)\s*$")

PLAN_MODE_SYSTEM = (
    "# 规划模式(plan mode)\n"
    "当前是规划模式:只讨论与产出计划,不执行分析、不下统计结论。\n"
    "1. 输出可审计执行计划:任务/输入输出/依赖/审批节点/停止条件/最小可交付。\n"
    "2. 计划末尾必须有单独的 `## TASKS` 章节:`- [ ] 任务` 复选框列表,"
    "每行一条、动词开头、可独立验收,5-12 条为宜。\n"
    "3. 等用户退出规划模式(/plan off)并确认后才进入执行。"
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# goal(真源 notes/goal.md,loop.py 已读取同一文件)
# ---------------------------------------------------------------------------

def goal_path(project_dir: str | Path = ".") -> Path:
    return Path(project_dir) / "notes" / "goal.md"


def get_goal(project_dir: str | Path = ".") -> str:
    p = goal_path(project_dir)
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def set_goal(text: str, project_dir: str | Path = ".") -> Path:
    p = goal_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 计划解析(纯函数,可单测)
# ---------------------------------------------------------------------------

def parse_plan_tasks(plan_md: str) -> list[str]:
    """抽取任务标题。优先 `## TASKS` 章节;无章节回落全篇 checkbox;都没有 → []。"""
    text = plan_md or ""
    m = _SECTION_RE.search(text)
    if m:
        rest = text[m.end():]
        nxt = _HEADING_RE.search(rest)
        if nxt:
            rest = rest[: nxt.start()]
        text = rest
    seen: set[str] = set()
    out: list[str] = []
    for t in _CHECKBOX_RE.findall(text):
        key = t.lower()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def parse_task_done(text: str) -> list[str]:
    """只认行首 TASK_DONE 标记;正文提及不算。"""
    return list(_TASK_DONE_RE.findall(text or ""))


# ---------------------------------------------------------------------------
# 任务存储
# ---------------------------------------------------------------------------

class TaskStore:
    """真源 .psyclaw/tasks.json;notes/tasks.md 为自动再生镜像。"""

    def __init__(self, project_dir: str | Path = ".") -> None:
        self.project = Path(project_dir)
        self.path = self.project / ".psyclaw" / "tasks.json"
        self.tasks: list[dict] = []
        if self.path.exists():
            try:
                self.tasks = json.loads(
                    self.path.read_text(encoding="utf-8")).get("tasks", [])
            except (json.JSONDecodeError, OSError):
                self.tasks = []

    # -- 持久化 ------------------------------------------------------------
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"tasks": self.tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self._write_mirror()

    def _write_mirror(self) -> None:
        done, total = self.progress()
        lines = [
            "# 任务进度",
            "",
            "> 自动生成(真源 `.psyclaw/tasks.json`),勿手改;",
            "> 用 `psyclaw tasks` 或 REPL `/tasks` 更新。",
            "",
            f"**进度:{done}/{total} 完成** · 更新:{_now()}",
            "",
        ]
        for t in self.tasks:
            box = "x" if t["status"] == "done" else " "
            suffix = "" if t["status"] in ("done", "todo") else f" ({t['status']})"
            lines.append(f"- [{box}] {t['id']}. {t['title']}{suffix}")
        p = self.project / "notes" / "tasks.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # -- 增改查 --------------------------------------------------------------
    def add(self, title: str) -> dict | None:
        """新增任务;同名(忽略大小写)已存在 → 不重复,返回 None。"""
        title = title.strip()
        if not title:
            return None
        if any(t["title"].lower() == title.lower() for t in self.tasks):
            return None
        task = {"id": max((t["id"] for t in self.tasks), default=0) + 1,
                "title": title, "status": "todo",
                "created": _now(), "updated": _now()}
        self.tasks.append(task)
        return task

    def sync_from_plan(self, plan_md: str) -> int:
        """从计划自动写任务:只增不删,同名保留原状态。返回新增条数。"""
        new = [t for t in (self.add(x) for x in parse_plan_tasks(plan_md)) if t]
        if new:
            self.save()
        return len(new)

    def find(self, ref: str | int) -> dict | None:
        """按编号或标题定位;子串匹配必须唯一,歧义不猜。"""
        s = str(ref).strip()
        if s.isdigit():
            return next((t for t in self.tasks if t["id"] == int(s)), None)
        low = s.lower()
        exact = [t for t in self.tasks if t["title"].lower() == low]
        if len(exact) == 1:
            return exact[0]
        hits = [t for t in self.tasks if low in t["title"].lower()]
        return hits[0] if len(hits) == 1 else None

    def set_status(self, ref: str | int, status: str) -> dict | None:
        if status not in STATUSES:
            return None
        t = self.find(ref)
        if t:
            t["status"] = status
            t["updated"] = _now()
            self.save()
        return t

    def mark_done_from(self, text: str) -> list[dict]:
        """按行首 TASK_DONE 标记置 done;定位不到的标记跳过,不猜。"""
        hits: list[dict] = []
        for ref in parse_task_done(text):
            t = self.find(ref)
            if t and t["status"] != "done":
                t["status"] = "done"
                t["updated"] = _now()
                hits.append(t)
        if hits:
            self.save()
        return hits

    # -- 展示 ----------------------------------------------------------------
    def progress(self) -> tuple[int, int]:
        return (sum(1 for t in self.tasks if t["status"] == "done"),
                len(self.tasks))

    def board(self) -> str:
        if not self.tasks:
            return ("  (无任务)/plan 进入规划模式自动生成,"
                    "或 /tasks add <标题> 手动添加。")
        done, total = self.progress()
        width = 20
        filled = round(width * done / total) if total else 0
        bar = "█" * filled + "░" * (width - filled)
        lines = [ui.accent(f"  任务进度 {bar} {done}/{total}")]
        goal = get_goal(self.project)
        if goal:
            lines.append(ui.dim(f"  目标:{goal.splitlines()[0][:70]}"))
        for t in self.tasks:
            line = f"  {_ICONS[t['status']]} {t['id']:>2}. {t['title']}"
            if t["status"] == "done":
                line = ui.dim(line)
            elif t["status"] == "doing":
                line = ui.accent(line)
            elif t["status"] == "blocked":
                line = ui.warn(line + "  (blocked)")
            lines.append(line)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI(psyclaw tasks … / REPL /tasks …)
# ---------------------------------------------------------------------------

def tasks_cli(argv: list[str] | None = None,
              project_dir: str | Path = ".") -> int:
    """list | add <标题> | start/done/block/todo <编号|标题> | sync | clear"""
    argv = list(argv or ["list"])
    store = TaskStore(project_dir)
    cmd, rest = argv[0].lower(), " ".join(argv[1:]).strip()

    if cmd in ("list", ""):
        print(store.board())
        return 0
    if cmd == "add":
        if not rest:
            print("  用法:tasks add <标题>")
            return 1
        t = store.add(rest)
        if t:
            store.save()
            print(ui.ok(f"  ✓ 新任务 {t['id']}. {t['title']}"))
            return 0
        print(ui.warn("  已存在同名任务,未重复添加"))
        return 0
    if cmd == "sync":
        plan = Path(project_dir) / "notes" / "plan.md"
        if not plan.exists():
            print(ui.err("  notes/plan.md 不存在,先 /plan(或 psyclaw plan)生成计划"))
            return 1
        n = store.sync_from_plan(plan.read_text(encoding="utf-8"))
        _, total = store.progress()
        print(ui.ok(f"  ✓ 从 plan.md 同步:新增 {n} 条,共 {total} 条"))
        return 0
    if cmd == "clear":
        store.tasks = []
        store.save()
        print(ui.ok("  ✓ 任务已清空(notes/tasks.md 同步更新)"))
        return 0
    alias = {"start": "doing", "doing": "doing", "done": "done",
             "block": "blocked", "blocked": "blocked",
             "todo": "todo", "reset": "todo"}
    if cmd in alias:
        if not rest:
            print(f"  用法:tasks {cmd} <编号|标题>")
            return 1
        t = store.set_status(rest, alias[cmd])
        if t:
            print(ui.ok(f"  ✓ {t['id']}. {t['title']} → {t['status']}"))
            print(store.board())
            return 0
        print(ui.err(f"  定位不到唯一任务:{rest}(用编号或唯一标题子串;歧义不猜)"))
        return 1
    print("  用法:tasks list | add <标题> | start/done/block/todo <编号|标题> | sync | clear")
    return 1
