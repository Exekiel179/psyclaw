"""项目脚手架 — `psyclaw setup` 的工程化部分。

三件确定性产物(可单测、幂等):
  ① 标准目录结构
  ② 据研究准备清单生成项目概览 md(按 A–F 分类组织已完成内容)
  ③ 项目记忆文档(据研究准备清单播种研究目标 + 关键方法学决策)

不联网、不装依赖——能力依赖/MCP/skill 由 cmd_setup 的能力阶段处理(联网 opt-in)。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_DIRS = [
    "notes", "outputs", "data/raw", "data/clean", "logs", "figures", "scripts",
]

# feat-140:产物归位软约定——按后缀给出建议目录。只引导不强制:chat/用户显式
# 指定路径时以其为准;二义类型(.md 可能是成稿也可能是笔记)返回 None 不武断。
_PLACEMENT_BY_SUFFIX = {
    ".png": "figures", ".jpg": "figures", ".jpeg": "figures", ".svg": "figures",
    ".py": "scripts", ".r": "scripts", ".jl": "scripts", ".sh": "scripts",
    ".docx": "outputs",
    ".csv": "data/clean", ".tsv": "data/clean",
}


def canonical_dir(filename: str) -> str | None:
    """文件名 → 约定目录(纯函数)。无法确定/二义返回 None。"""
    suffix = Path(str(filename or "")).suffix.lower()
    return _PLACEMENT_BY_SUFFIX.get(suffix)

# 研究准备项 sid → 概览里的短字段名
_LABELS = {
    "research_question": "研究问题", "theory_base": "理论框架", "novelty": "增量贡献",
    "iv": "自变量", "dv": "因变量", "covariates": "协变量",
    "population": "总体与抽样", "exclusion": "纳入/排除标准",
    "design_type": "设计类型", "randomization": "随机化/抵消平衡",
    "hypotheses": "假设", "effect_expectation": "预期效应量", "power": "功效/样本量",
    "analysis_plan": "分析计划", "ethics": "伦理与开放科学", "prereg": "预注册",
    "data_sharing": "数据共享",
}


def ensure_dirs(project_dir: str | Path = ".") -> list[str]:
    """创建标准项目目录(幂等)。返回本次新建的目录列表。"""
    root = Path(project_dir)
    created = []
    for d in PROJECT_DIRS:
        p = root / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(d)
    return created


def create_analysis(name: str, goal: str = "", base_dir: str | Path = ".") -> dict:
    """feat-159:在 base_dir 下新建一个**独立分析文件夹**(标准脚手架 + 全新状态)。

    分析基于文件夹组织:每个分析一个目录,状态(goal/tasks/clarify)都在各自
    目录内,天然隔离——不继承别处(如 psyclaw repo 根)的旧 goal。返回
    {"ok", "path", "created", "note"};名称非法/已存在非空 → ok=False,不动盘。
    """
    nm = (name or "").strip()
    if not nm:
        return {"ok": False, "path": "", "created": [], "note": "名称为空"}
    # 安全:只允许 base_dir 下的相对子目录,拒绝 .. 逃逸与绝对路径
    if nm.startswith(("/", "\\")) or ".." in Path(nm).parts or Path(nm).is_absolute():
        return {"ok": False, "path": "", "created": [],
                "note": f"名称非法(不可含 .. 或绝对路径):{name}"}
    root = Path(base_dir) / nm
    if root.exists() and any(root.iterdir()):
        return {"ok": False, "path": str(root), "created": [],
                "note": f"目录已存在且非空:{root}(换个名字,或直接 cd 进去开工)"}
    created = ensure_dirs(root)
    if goal.strip():
        from psyclaw.tasks import set_goal
        set_goal(goal.strip(), project_dir=str(root))
    return {"ok": True, "path": str(root), "created": created, "note": "已创建"}


def _read_clarify(project_dir: str | Path) -> dict:
    """读并解析研究准备清单;无清单/无已完成内容 → 空 dict。"""
    from psyclaw.psych.clarify import CARD_NAME
    from psyclaw.psych.preregister import parse_clarification
    card = Path(project_dir) / "notes" / CARD_NAME
    if not card.exists():
        return {}
    return parse_clarification(card.read_text(encoding="utf-8", errors="replace"))


def generate_overview(project_dir: str | Path = ".") -> Path | None:
    """据研究准备清单生成 notes/project_overview.md(按 A–F 分类组织)。

    无研究准备清单或无已完成内容 → 返回 None(由调用方提示先跑 prepare)。
    """
    from psyclaw.psych.clarify import SLOTS
    answers = _read_clarify(project_dir)
    if not answers:
        return None

    lines = ["# 研究项目概览", "",
             "> 据研究准备清单(notes/clarification.md)自动生成;更新后重跑 `psyclaw setup` 可刷新。",
             ""]
    seen_cat = None
    for sid, cat, _q, _why, _ex in SLOTS:
        if sid not in answers:
            continue
        if cat != seen_cat:
            lines += ["", f"## {cat}", ""]
            seen_cat = cat
        label = _LABELS.get(sid, sid)
        lines.append(f"- **{label}**：{answers[sid]}")

    n_total = len(SLOTS)
    lines += ["", f"---", f"*已完成 {len(answers)}/{n_total} 个研究准备项*"]
    out = Path(project_dir) / "notes" / "project_overview.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def init_project_memory(project_dir: str | Path = ".") -> Path:
    """写项目记忆 notes/project_memory.md(据研究准备清单播种;无清单则写骨架)。

    幂等但**不覆盖**已有记忆(避免抹掉用户手写的决策日志):已存在则原样返回。
    """
    out = Path(project_dir) / "notes" / "project_memory.md"
    if out.exists():
        return out

    a = _read_clarify(project_dir)
    goal = a.get("research_question", "（待补充:运行 psyclaw prepare）")

    def _seed(sid: str) -> str:
        return a.get(sid, "（待补充）")

    lines = [
        f"# 项目记忆 — {goal.splitlines()[0][:60]}",
        "",
        "> 每次会话先读本文件接续上下文。据研究准备清单播种,随研究推进**手动更新**。",
        "",
        "## 研究目标",
        goal,
        "",
        "## 关键方法学决策(据研究准备清单)",
        f"- 设计类型：{_seed('design_type')}",
        f"- 分析计划：{_seed('analysis_plan')}",
        f"- 功效/样本量：{_seed('power')}",
        f"- 预注册：{_seed('prereg')}",
        "",
        "## 决策日志",
        "（在此记录研究过程中的重要决策与理由）",
        "",
        "## 未决问题",
        "（在此记录待解决的问题）",
        "",
        "## 方法学偏好",
        "（沉淀本项目的方法学惯例,供跨会话复用）",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def scaffold_project(project_dir: str | Path = ".") -> dict:
    """跑①②③三件确定性脚手架。返回 {created_dirs, overview, memory}。"""
    return {
        "created_dirs": ensure_dirs(project_dir),
        "overview": generate_overview(project_dir),
        "memory": init_project_memory(project_dir),
    }
