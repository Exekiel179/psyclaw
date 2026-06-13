"""A-2: 分析计划注册表 — 声明检验，偏离即审计，探索性强制标注。

计划文件: notes/analysis_plan.json
偏离日志: notes/audit_deviations.md
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

PLAN_FILE = "notes/analysis_plan.json"
DEVIATION_LOG = "notes/audit_deviations.md"


# ---------------------------------------------------------------------------
# 读/写计划文件
# ---------------------------------------------------------------------------

def _plan_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / PLAN_FILE


def load_plan(project_dir: str | Path = ".") -> dict:
    """加载分析计划注册表；不存在时返回空结构。"""
    p = _plan_path(project_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"analyses": []}


def save_plan(plan: dict, project_dir: str | Path = ".") -> None:
    p = _plan_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 声明一个计划分析
# ---------------------------------------------------------------------------

def declare(
    project_dir: str | Path = ".",
    dv: str = "",
    test: str = "",
    iv: str | None = None,
    hypothesis: str = "confirmatory",
    name: str | None = None,
) -> dict:
    """注册一个计划分析条目，写入 notes/analysis_plan.json。

    hypothesis: "confirmatory"（确证性）| "exploratory"（探索性）
    返回写入的条目 dict。
    """
    if not dv or not test:
        raise ValueError("dv 和 test 为必填项")
    if hypothesis not in ("confirmatory", "exploratory"):
        raise ValueError("hypothesis 需为 confirmatory 或 exploratory")

    plan = load_plan(project_dir)
    entry = {
        "name": name or f"{hypothesis[0].upper()}: {dv} × {test}" + (f" × {iv}" if iv else ""),
        "dv": dv.strip(),
        "test": _normalise_test(test),
        "iv": iv.strip() if iv else None,
        "hypothesis": hypothesis,
        "declared_at": str(date.today()),
    }
    plan["analyses"].append(entry)
    save_plan(plan, project_dir)
    return entry


# ---------------------------------------------------------------------------
# 检查当前分析是否在计划内
# ---------------------------------------------------------------------------

_TEST_ALIASES: dict[str, str] = {
    # normalize various test name spellings to a canonical form
    "两组比较": "ttest",
    "两组比较(mann-whitney)": "mann_whitney",
    "配对比较": "paired",
    "相关": "correlation",
    "方差分析": "anova",
    "pearson": "correlation",
    "t检验": "ttest",
    "独立样本t": "ttest",
    "配对t": "paired",
    "welch": "ttest",
    "student": "ttest",
    "mann-whitney": "mann_whitney",
    "mannwhitney": "mann_whitney",
    "f检验": "anova",
}


def _normalise_test(test: str) -> str:
    return _TEST_ALIASES.get(test.lower().replace(" ", ""), test.lower().replace(" ", "_"))


def check(
    project_dir: str | Path = ".",
    dv: str = "",
    test: str = "",
    iv: str | None = None,
) -> dict:
    """对照计划注册表检查本次分析。

    返回 {
      "status": "confirmatory" | "exploratory" | "undeclared",
      "entry": dict | None,   # 匹配到的计划条目
      "deviation": str | None, # 若测试类型不符，描述偏离
    }
    """
    plan = load_plan(project_dir)
    norm_test = _normalise_test(test)
    norm_dv = dv.strip().lower()

    matched_entry = None
    deviation = None

    for entry in plan.get("analyses", []):
        if entry.get("dv", "").lower() == norm_dv:
            planned_test = _normalise_test(entry.get("test", ""))
            planned_iv = (entry.get("iv") or "").lower()
            iv_match = (iv is None or iv.strip().lower() == planned_iv
                        or planned_iv == "")
            if iv_match:
                matched_entry = entry
                if planned_test != norm_test:
                    deviation = (f"计划检验 {planned_test}，实际运行 {norm_test}")
                break

    if matched_entry is None:
        return {"status": "undeclared", "entry": None, "deviation": None}

    hyp = matched_entry.get("hypothesis", "confirmatory")
    return {
        "status": hyp,
        "entry": matched_entry,
        "deviation": deviation,
    }


# ---------------------------------------------------------------------------
# 偏离记录
# ---------------------------------------------------------------------------

def log_deviation(
    project_dir: str | Path = ".",
    dv: str = "",
    actual_test: str = "",
    planned_test: str = "",
    note: str = "",
) -> None:
    """把偏离计划的分析追加到 notes/audit_deviations.md。"""
    log = Path(project_dir) / DEVIATION_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with log.open("a", encoding="utf-8") as f:
        f.write(
            f"\n## {ts} — DV: {dv}\n\n"
            f"- 计划检验: `{planned_test}`\n"
            f"- 实际检验: `{actual_test}`\n"
            f"- 备注: {note or '（无）'}\n"
            f"- 处置: 输出已标注 [UNPLANNED]，建议在论文方法节说明偏离原因。\n"
        )
