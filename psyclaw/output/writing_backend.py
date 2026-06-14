"""Writing backend — 优先对接 academic-research-skills 插件，缺失时降级到内置写作。

academic-research-skills 插件提供能力（对接后可用）：
  - 结构化学术论文写作（APA7/JARS 规范，含全部必填章节）
  - 双语摘要生成（中英文 + 关键词）
  - 自动 JARS 检查（与 output/jars.py 协同）

评审能力已由 review.py（P0-1）实现，本模块不重复造轮子，保持单一契约。

插件发现顺序（按优先级）：
  1. 环境变量 PSYCLAW_ARS_BACKEND=plugin|ars|ars_plugin → BACKEND_ARS
     PSYCLAW_ARS_BACKEND=builtin|simple            → BACKEND_BUILTIN
  2. 检查标准 Claude Code 插件路径（Windows: %APPDATA%/Claude/; Unix: ~/.claude/）
  3. 回落：BACKEND_BUILTIN
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_BUILTIN = "builtin"
BACKEND_ARS = "ars_plugin"

# ---------------------------------------------------------------------------
# 插件探测（纯函数，可单测）
# ---------------------------------------------------------------------------

def _ars_plugin_paths() -> list[Path]:
    """返回所有可能的 academic-research-skills 插件候选路径。"""
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "Claude"
        for sub in ("plugins", "skills"):
            candidates.append(base / sub / "academic-research-skills")
    home = Path.home()
    for sub in ("plugins", "skills"):
        candidates.append(home / ".claude" / sub / "academic-research-skills")
    return candidates


def _ars_plugin_installed() -> bool:
    """检查 academic-research-skills 插件是否已在标准路径安装。"""
    return any(p.exists() for p in _ars_plugin_paths())


def detect_backend(project_dir: str = ".") -> str:  # noqa: ARG001
    """检测可用的写作后端，返回 BACKEND_ARS 或 BACKEND_BUILTIN。"""
    env = os.environ.get("PSYCLAW_ARS_BACKEND", "").strip().lower()
    if env in ("plugin", "ars", "ars_plugin"):
        return BACKEND_ARS
    if env in ("builtin", "simple"):
        return BACKEND_BUILTIN
    if _ars_plugin_installed():
        return BACKEND_ARS
    return BACKEND_BUILTIN


# ---------------------------------------------------------------------------
# 写作任务提示（各后端返回不同 LLM 提示）
# ---------------------------------------------------------------------------

def _builtin_write_task() -> str:
    """内置写作提示（与 pipeline 原始 _write_task 一致，保持契约稳定）。"""
    return (
        "据背景综述、研究设计与统计结果,写一篇 **APA-JARS 结构**的研究稿:\n"
        "标题 / 摘要 / 引言(含假设) / 方法(被试·测量·程序·分析计划) / "
        "结果 / 讨论(限定性措辞,相关≠因果,区分探索/确证,讨论局限) / 参考。\n"
        "**只引用 outputs/ 中已存在的表图与 result_* 统计量,不存在的结果不得"
        "编造**;每个显著性检验必报效应量 + 95% CI。"
    )


def _ars_write_task(goal: str = "") -> str:
    """ARS 插件写作提示：完整 APA7/JARS 结构，含双语摘要与学术诚信规则。"""
    prefix = f"研究目标:{goal}\n\n" if goal else ""
    return (
        prefix
        + "你是资深心理学学术写作助手。请据背景综述、研究设计与统计结果，"
        "写一篇完整的 **APA7/JARS** 结构研究稿，并在摘要后附**中文摘要+关键词**（双语）。\n\n"
        "## 必须包含的章节\n"
        "1. **标题**（简洁、包含核心变量与研究人群）\n"
        "2. **Abstract**（≤250词，目的/方法/结果/结论四要素）\n"
        "   **中文摘要**（200字以内，附关键词5个）\n"
        "3. **引言**（背景→研究空白→理论框架→假设；每个假设标注确证[H]或探索性[EH]）\n"
        "4. **方法**\n"
        "   - 被试（n、抽样方法、纳排标准、功效分析依据、伦理声明）\n"
        "   - 测量（每个测量工具：全称、题目数、计分方式、内部一致性/效度证据）\n"
        "   - 程序（含知情同意、随机化方法）\n"
        "   - 数据分析（检验族/软件版本/α水平/多重比较处理/探索-确证划分）\n"
        "5. **结果**（每个统计量报效应量+95%CI，APA7格式；"
        "异常值与缺失数据处理须明述——JARS硬要求）\n"
        "6. **讨论**（对应假设逐一评述、限定性措辞、相关≠因果、"
        "探索/确证区分、局限性、未来研究方向）\n"
        "7. **参考文献**（APA7格式，悬挂缩进）\n\n"
        "## 学术诚信规则（违反即重写）\n"
        "- **只引用 outputs/ 中已存在的表图与 result_* 统计量**，不得编造数值\n"
        "- 每个显著性检验必报效应量 + 95% CI（APA7 §7.36）\n"
        "- 相关不等因果；探索性结论须明确标注「探索性发现」\n"
        "- 局限性部分不得省略（JARS必项）\n"
        "- 缺失数据处理须明确描述（JARS硬要求）\n\n"
        "## 格式要求\n"
        "- Markdown 结构：# 标题，## 章节，### 小节\n"
        "- 统计量：*t*(df) = x.xx, *p* = .xxx, Cohen's *d* = x.xx, 95% CI [x.xx, x.xx]\n"
        "- 表格用 Markdown 三线表；图以 [图N 说明] 占位（若 outputs/ 存在对应文件则引用路径）"
    )


def get_write_task(backend: str, goal: str = "") -> str:
    """按后端返回写作阶段的 LLM 任务提示。"""
    if backend == BACKEND_ARS:
        return _ars_write_task(goal)
    return _builtin_write_task()


# ---------------------------------------------------------------------------
# 双语摘要生成（ARS 插件后端附加能力）
# ---------------------------------------------------------------------------

_ABSTRACT_TASK = """\
从以下论文草稿中提取并生成**双语摘要**：
1. 英文摘要（≤250词，目的/方法/结果/结论四要素）
2. 中文摘要（200字以内）
3. 英文关键词（5个，分号分隔）
4. 中文关键词（5个，分号分隔）

输出格式（严格遵守，便于程序解析）：
## Abstract
<英文摘要正文>

## 中文摘要
<中文摘要正文>

**Keywords:** kw1; kw2; kw3; kw4; kw5

**关键词：** 词1; 词2; 词3; 词4; 词5

---
仅根据草稿内容，不得添加未在草稿中出现的结论。
"""


def write_abstract(draft: str, provider, bilingual: bool = True) -> dict:
    """从草稿生成摘要，ARS 后端时产出双语；builtin 后端只产出英文摘要段落。

    Args:
        draft:     论文草稿文本。
        provider:  LLM provider（需实现 .chat(messages, system="")）。
        bilingual: True（ARS 默认）产出双语；False 只提取英文段。

    Returns:
        dict 含 "en"（英文摘要）、"zh"（中文，若 bilingual）、
             "keywords_en"（英文关键词列表）、"keywords_zh"（中文关键词列表）、
             "raw"（完整 LLM 输出）。
    """
    if not bilingual:
        return _extract_abstract_builtin(draft)

    try:
        from psyclaw.loop import _gen
        raw = _gen(provider, "executor", _ABSTRACT_TASK,
                   f"# 论文草稿\n{draft[:8000]}")
    except Exception as exc:  # noqa: BLE001
        raw = f"[abstract 生成失败] {exc}"

    return _parse_abstract_output(raw)


def _extract_abstract_builtin(draft: str) -> dict:
    """从草稿中直接切割已有的摘要段（不调用 LLM，内置降级）。"""
    import re
    pattern = re.compile(
        r"(?:^|\n)#{1,3}\s*(?:Abstract|摘要)\s*\n+(.*?)(?=\n#{1,3}|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(draft)
    text = m.group(1).strip() if m else ""
    return {"en": text, "zh": "", "keywords_en": [], "keywords_zh": [], "raw": text}


def _parse_abstract_output(raw: str) -> dict:
    """解析 LLM 双语摘要输出为结构化 dict。"""
    import re

    def _between(header_re: str, text: str) -> str:
        m = re.search(
            rf"(?:^|\n)##\s*{header_re}\s*\n+(.*?)(?=\n##|\n\*\*Keywords|\n\*\*关键词|\Z)",
            text, re.DOTALL | re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    def _keywords(pattern: str, text: str) -> list[str]:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return []
        return [k.strip() for k in re.split(r"[;；]", m.group(1)) if k.strip()]

    en = _between("Abstract", raw)
    zh = _between("中文摘要", raw)
    kw_en = _keywords(r"\*\*Keywords[:：]\*\*\s*(.+)", raw)
    kw_zh = _keywords(r"\*\*关键词[：:]\*\*\s*(.+)", raw)

    return {"en": en, "zh": zh, "keywords_en": kw_en, "keywords_zh": kw_zh, "raw": raw}


# ---------------------------------------------------------------------------
# JARS 自动检查（写作后可选，不阻断调用方）
# ---------------------------------------------------------------------------

def run_jars_check(draft_path: Path, study_type: str = "quant") -> dict:
    """对产出稿运行 JARS 检查；出错时返回 {'error': ...} 而非抛出。"""
    try:
        from psyclaw.output.jars import check_draft
        text = draft_path.read_text(encoding="utf-8")
        return check_draft(text, study_type=study_type)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "passed": False, "blocking": [], "warnings": []}


# ---------------------------------------------------------------------------
# 主写作函数（pipeline ④ 写作阶段调用入口）
# ---------------------------------------------------------------------------

def write_paper(
    goal: str,
    context: str,
    provider,
    project: Path,
    backend: str | None = None,
    run_jars: bool = True,
) -> tuple[str, dict]:
    """ARS/内置双路写作入口，返回 (draft_text, meta)。

    Args:
        goal:      研究目标（字符串）。
        context:   综述/设计/统计等上下文（注入 LLM 提示）。
        provider:  LLM provider。
        project:   项目根路径。
        backend:   None → 自动探测；'ars_plugin' / 'builtin' → 强制指定。
        run_jars:  True → 写作完成后运行 JARS 检查并写 notes/jars_check.json。

    Returns:
        draft:  草稿文本（空字符串表示生成失败）。
        meta:   {backend, jars, abstract} dict（供 pipeline 记录）。
    """
    if backend is None:
        backend = detect_backend(str(project))

    from psyclaw.loop import _gen

    task = get_write_task(backend, goal)
    draft = _gen(provider, "executor", task, context)

    meta: dict = {"backend": backend, "jars": None, "abstract": None}

    if not draft.strip():
        return draft, meta

    # 落稿
    report_path = project / "outputs" / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(draft, encoding="utf-8")

    # ARS 后端：附加双语摘要
    if backend == BACKEND_ARS:
        abstract_info = write_abstract(draft, provider, bilingual=True)
        meta["abstract"] = abstract_info
        if abstract_info.get("zh"):
            abs_path = project / "notes" / "abstract_bilingual.md"
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(
                f"## Abstract\n{abstract_info['en']}\n\n"
                f"**Keywords:** {'; '.join(abstract_info['keywords_en'])}\n\n"
                f"---\n\n## 中文摘要\n{abstract_info['zh']}\n\n"
                f"**关键词：** {'; '.join(abstract_info['keywords_zh'])}\n",
                encoding="utf-8",
            )

    # JARS 检查
    if run_jars:
        jars = run_jars_check(report_path)
        meta["jars"] = jars
        jars_path = project / "notes" / "jars_check.json"
        jars_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        jars_path.write_text(json.dumps(jars, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    return draft, meta
