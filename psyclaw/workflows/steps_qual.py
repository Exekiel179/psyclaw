"""质性研究流程(qualitative)的 Step 与子功能。

质性分析是解释性的(非统计):L3 实现层 = LLM 辅助编码/主题分析(后续可升级为
质性分析 skill / CAQDAS-MCP),不涉及"统计外移"。PsyClaw 编排:质性设计 → 载入转录稿
→ LLM 辅助开放编码 + 主题分析 → COREQ 报告 → 评审;人类研究者复核编码与主题(HITL)。

`load_transcripts` 是独立纯函数(可单测/单用)。编码/主题步委托 provider(LLM)。
"""

from __future__ import annotations

from pathlib import Path

_TEXT_SUFFIX = (".txt", ".md")
_MAX_CONTEXT_CHARS = 9000   # 注入 LLM 的转录稿上限(超出截断,诚实标注)


def load_transcripts(path: str) -> dict:
    """载入转录稿:单个 .txt/.md 文件,或包含它们的目录。

    返回 {n, total_chars, transcripts:[{name, text, n_chars}]}。
    fail-closed:路径不存在 / 非 txt|md / 无非空转录稿 → ValueError。
    """
    p = Path(path)
    if not p.exists():
        raise ValueError(f"转录稿路径不存在:{path}")
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.suffix.lower() in _TEXT_SUFFIX)
    elif p.suffix.lower() in _TEXT_SUFFIX:
        files = [p]
    else:
        raise ValueError("转录稿需为 .txt/.md 文件,或包含它们的目录")

    transcripts = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            transcripts.append({"name": f.name, "text": text, "n_chars": len(text)})
    if not transcripts:
        raise ValueError("未找到非空转录稿(.txt/.md)")
    return {
        "n": len(transcripts),
        "total_chars": sum(t["n_chars"] for t in transcripts),
        "transcripts": transcripts,
    }


def _context_blob(transcripts: list[dict]) -> tuple[str, bool]:
    """把转录稿拼成注入 LLM 的上下文;超 _MAX_CONTEXT_CHARS 截断并返回 truncated 标志。"""
    parts, used, truncated = [], 0, False
    for t in transcripts:
        head = f"\n=== 转录稿:{t['name']} ===\n"
        budget = _MAX_CONTEXT_CHARS - used - len(head)
        if budget <= 0:
            truncated = True
            break
        body = t["text"]
        if len(body) > budget:
            body = body[:budget]
            truncated = True
        parts.append(head + body)
        used += len(head) + len(body)
    return "".join(parts), truncated


# ---------------------------------------------------------------------------
# Step(薄壳)
# ---------------------------------------------------------------------------


def step_qual_design(ctx) -> dict:
    """生成质性研究设计备忘(取样·访谈提纲·方法论·反身性)。委托 provider(LLM)。"""
    from psyclaw import ui
    from psyclaw.loop import _gen
    task = ("据研究主题与研究准备清单,写一份简洁的**质性**研究设计备忘:"
            "①研究取向(主题分析/扎根理论/IPA/现象学等,给理由)②取样策略与目标样本"
            "③访谈/观察提纲要点④反身性(researcher positionality)⑤资料可信性策略"
            "(三角验证/成员检验/审计轨迹)。只依据给定信息,不杜撰资料或发现。")
    memo = _gen(ctx.provider, "planner", task,
                f"# 主题\n{ctx.topic}\n\n# 研究准备清单\n{ctx.clar}")
    (ctx.project / "notes" / "qual_design.md").write_text(
        memo or "(质性设计备忘待补)", encoding="utf-8")
    ctx.artifacts["design"] = "notes/qual_design.md"
    print(ui.dim("  质性研究设计备忘 → notes/qual_design.md"))
    return {}


def step_load_transcripts(ctx) -> dict:
    """载入转录稿(单文件或目录)。fail-closed。"""
    from psyclaw import ui
    path = ctx.data.get("transcripts")
    if not path:
        raise ValueError("未提供转录稿:用 `psyclaw qualitative <转录稿.txt|目录>`。")
    data = load_transcripts(path)
    ctx.data["corpus"] = data
    ctx.artifacts["load_transcripts"] = path
    print(ui.dim(f"  {data['n']} 份转录稿 · 合计 {data['total_chars']} 字"))
    return {"n": data["n"], "total_chars": data["total_chars"]}


def step_thematic_analysis(ctx) -> dict:
    """LLM 辅助开放编码 + 主题分析 → notes/thematic_analysis.md。

    人类研究者须复核编码与主题(HITL);LLM 仅作辅助,不代替研究者判断。
    """
    from psyclaw import ui
    from psyclaw.loop import _gen
    corpus = ctx.data.get("corpus", {})
    blob, truncated = _context_blob(corpus.get("transcripts", []))
    task = ("对下列转录稿做**辅助性**质性分析(研究者须复核):"
            "①开放编码:列出编码(code)+ 定义 + 一条代表性引文(注明出处转录稿);"
            "②主题归纳:把编码聚成 3–6 个主题(theme),每个主题给名称 + 内涵 + 所含编码 + 简述;"
            "③标注饱和度与局限。严禁杜撰引文——只引用转录稿中真实出现的话。")
    if truncated:
        task += "(注意:转录稿已截断,分析仅基于可见部分,请在局限里说明。)"
    out = _gen(ctx.provider, "executor", task, blob)
    (ctx.project / "notes" / "thematic_analysis.md").write_text(
        (out or "(主题分析待补)")
        + "\n\n> ⚠ LLM 辅助编码,研究者须逐条复核引文与主题归属(HITL)。",
        encoding="utf-8")
    ctx.artifacts["thematic_analysis"] = "notes/thematic_analysis.md"
    print(ui.dim("  主题分析(LLM 辅助,待研究者复核) → notes/thematic_analysis.md"))
    return {"truncated": truncated}


def step_write_qual(ctx) -> dict:
    """据质性设计 + 主题分析写质性报告骨架(COREQ)。复用 writing_backend.write_paper。"""
    from psyclaw import ui
    from psyclaw.output.writing_backend import write_paper
    notes = ctx.project / "notes"
    design = (notes / "qual_design.md")
    themes = (notes / "thematic_analysis.md")
    context = (
        f"# 质性研究设计\n{design.read_text(encoding='utf-8') if design.exists() else ''}\n\n"
        f"# 主题分析(LLM 辅助,研究者已复核)\n"
        f"{themes.read_text(encoding='utf-8') if themes.exists() else ''}\n\n"
        "# 写作要求\n按 COREQ/质性 JARS 组织(研究团队与反身性、设计、分析、发现);"
        "只引用 thematic_analysis.md 中的真实引文与主题,不杜撰;明确质性研究不作因果/可推广宣称。\n\n"
        f"# 研究准备清单\n{ctx.clar}")
    draft, _meta = write_paper(ctx.topic, context, ctx.provider, ctx.project)
    if not draft.strip():
        raise ValueError("写作阶段未产出稿(provider 返回空)")
    ctx.artifacts["write"] = "outputs/report.md"
    ctx.data["draft_path"] = str(ctx.project / "outputs" / "report.md")
    print(ui.dim("  质性报告骨架(COREQ) → outputs/report.md"))
    return {}
