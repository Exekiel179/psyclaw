"""伦理门控 — D-3: 量表 notes 驱动的 IRB/危机转介提示(软门禁, warn)。

敏感量表的 notes 字段是触发源；数据感知检查在 score_datafile 中调用。
所有逻辑纯 stdlib，无外部依赖。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# notes 字段关键词 → 伦理类别（精确匹配，避免误触发）
# ---------------------------------------------------------------------------

_SENSITIVE_KEYWORDS: dict[str, str] = {
    "自伤意念": "suicidal_ideation",
    "自杀意念": "suicidal_ideation",
    "自杀": "suicidal_ideation",
    "自伤行为": "self_harm",
    "危机转介": "crisis_referral",
    "心理危机": "crisis",
    "伦理审查": "ethics_required",
    "irb": "ethics_required",
}

# 每个类别只取第一个匹配（优先级从上到下），避免重复告警。
_CATEGORY_PRIORITY = [
    "suicidal_ideation",
    "self_harm",
    "crisis",
    "crisis_referral",
    "ethics_required",
]

_ETHICS_MESSAGES: dict[str, str] = {
    "suicidal_ideation": (
        "⚠ [伦理-必须] 该量表包含自伤/自杀意念相关条目\n"
        "  · IRB 批准须明确涵盖此类敏感内容\n"
        "  · 制定危机转介流程（可提供心理援助热线 400-161-9995）\n"
        "  · 不得直接向被试报告个人条目得分\n"
        "  · 数据须去标识化处理"
    ),
    "self_harm": (
        "⚠ [伦理-必须] 该量表包含自伤行为相关条目\n"
        "  · IRB 批准须覆盖自伤相关内容\n"
        "  · 制定保护与转介流程；数据匿名化"
    ),
    "crisis_referral": (
        "⚠ [伦理-必须] 该量表可能识别高风险被试\n"
        "  · 须制定危机转介流程\n"
        "  · 研究人员须受训识别风险迹象"
    ),
    "crisis": (
        "⚠ [伦理-必须] 该量表涉及心理危机相关测量\n"
        "  · IRB 批准；制定危机响应方案\n"
        "  · 告知被试紧急转介渠道"
    ),
    "ethics_required": (
        "⚠ [伦理-注意] 该量表使用需特别关注伦理合规\n"
        "  · 确认 IRB 批准已涵盖量表使用范围\n"
        "  · 知情同意书说明相关测量内容"
    ),
}

# ---------------------------------------------------------------------------
# 数据感知检查：特定量表的条目级伦理触发
# 格式: {scale_id: [(item_num, min_value, message_template)]}
# message_template 中 {n} 替换为触发被试数
# ---------------------------------------------------------------------------

_ITEM_ETHICS: dict[str, list[tuple[int, float, str]]] = {
    "phq-9": [
        (
            9, 1.0,
            "PHQ-9 条目 9（自伤意念）在 {n} 名被试中有作答（≥ 1）。"
            "请确认 IRB 批准并建立危机转介流程；"
            "不得直接向被试报告个人评分。",
        ),
    ],
}


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def check_scale_ethics(scale: dict) -> list[str]:
    """从量表 notes 字段检测伦理敏感关键词，返回告警文本列表。

    每个类别只报一条告警（优先级：suicidal_ideation > self_harm > ...）。
    匹配大小写不敏感。
    """
    notes = (scale.get("notes") or "").lower()
    if not notes:
        return []

    triggered: set[str] = set()
    for kw, category in _SENSITIVE_KEYWORDS.items():
        if kw.lower() in notes:
            triggered.add(category)

    msgs: list[str] = []
    for cat in _CATEGORY_PRIORITY:
        if cat in triggered and cat in _ETHICS_MESSAGES:
            msgs.append(_ETHICS_MESSAGES[cat])
    return msgs


def check_item_level_ethics(participants: list, scale: dict) -> list[str]:
    """数据感知伦理检查：检测特定量表的高风险条目应答。

    participants: score_datafile 返回的 participants 列表（含 items 字典，已反向翻转）
    """
    sid = (scale.get("id") or "").lower()
    rules = _ITEM_ETHICS.get(sid, [])
    msgs: list[str] = []
    for item_num, threshold, template in rules:
        n = sum(
            1 for p in participants
            if p.get("items", {}).get(item_num, -1) >= threshold
        )
        if n > 0:
            msgs.append(template.format(n=n))
    return msgs


def ethics_summary(scale: dict, participants: list | None = None) -> dict:
    """生成综合伦理摘要，可写入 sidecar JSON 供门禁系统查验。

    返回 {ethics_prompted, ethics_warnings, ethics_level}
    ethics_level: "required" | "advisory" | "none"
    """
    notes_warnings = check_scale_ethics(scale)
    item_warnings = (
        check_item_level_ethics(participants, scale) if participants is not None else []
    )
    all_warnings = notes_warnings + item_warnings
    level = (
        "required" if any("必须" in w for w in all_warnings) else
        "advisory" if all_warnings else
        "none"
    )
    return {
        "ethics_prompted": bool(all_warnings),
        "ethics_warnings": all_warnings,
        "ethics_level": level,
    }


def format_ethics_report(scale: dict, participants: list | None = None) -> str:
    """生成人读伦理审查报告（用于 psyclaw ethics 命令）。"""
    summary = ethics_summary(scale, participants)
    name = scale.get("name", scale.get("id", "未知量表"))
    lines = [f"伦理审查报告 — {name}"]
    if summary["ethics_warnings"]:
        for w in summary["ethics_warnings"]:
            lines.append(f"\n{w}")
        lines.append("\n建议操作：")
        lines.append("  1. 确认 IRB 批准已明确涵盖上述内容")
        lines.append("  2. 知情同意书中说明相关风险及应对资源")
        lines.append("  3. 制定危机识别与转介流程（如适用）")
        lines.append("  4. 数据去标识化与安全存储")
    else:
        lines.append("  未检测到高伦理敏感内容。常规研究伦理要求仍适用。")
    if scale.get("notes"):
        lines.append(f"\n  量表说明: {scale['notes']}")
    return "\n".join(lines)
