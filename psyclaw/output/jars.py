"""JARS (Journal Article Reporting Standards, APA 2018) 检查清单 — W-1。

按研究类型(quant / qual / mixed)校验论文草稿是否包含 JARS 必报条目。
阻断项：缺失数据处理、剔除人数与理由（两者缺失时阻断投稿流程）。

公开接口:
  check_draft(text, research_type) → dict
  format_report(result)           → str
  jars_cli(argv)                  → int  (psyclaw jars 入口)
  load_jars_check(base_dir)       → dict | None  (gate 读 sidecar)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# JARS 条目定义
# ---------------------------------------------------------------------------

# 每个条目：id, label, keywords(忽略大小写 regex), blocking, research_types
# keywords 中只要命中任意一条即视为"已报告"。

_QUANT_ITEMS: list[dict] = [
    {
        "id": "Q.participants.eligibility",
        "label": "被试纳入/排除标准",
        "keywords": [
            r"eligibilit",
            r"inclusion criter",
            r"exclusion criter",
            r"纳入标准",
            r"排除标准",
            r"入组标准",
            r"入选标准",
        ],
        "blocking": False,
    },
    {
        "id": "Q.participants.power",
        "label": "样本量依据 / 先验功效分析",
        "keywords": [
            r"power analy",
            r"功效分析",
            r"G\*Power",
            r"sample size",
            r"样本量",
            r"样本容量",
            r"先验",
        ],
        "blocking": False,
    },
    {
        "id": "Q.procedure.missing_data",
        "label": "缺失数据处理方式",
        "keywords": [
            r"missing data",
            r"缺失数据",
            r"缺失值",
            r"imputation",
            r"插补",
            r"listwise",
            r"pairwise deletion",
            r"FIML",
            r"full information maximum likelihood",
            r"multiple imputation",
            r"complete case",
            r"missing at random",
            r"MAR\b",
            r"MCAR\b",
            r"MNAR\b",
        ],
        "blocking": True,   # BLOCKING — 缺失则阻断
        "fix": "在「方法/统计分析」部分说明缺失数据处理方式，如 FIML、多重插补或完整案例分析，"
               "并报告缺失比例。",
    },
    {
        "id": "Q.procedure.exclusions",
        "label": "剔除人数及剔除理由",
        "keywords": [
            r"excluded?\s+\d",
            r"排除[了的]?\s*\d",
            r"剔除[了的]?\s*\d",
            r"\d+\s*(?:participants?|被试|人|名)\s*(?:were?\s+)?excluded",
            r"exclusion criter",
            r"attrition",
            r"dropouts?",
            r"withdrawn",
            r"participant flow",
            r"CONSORT",
            r"数据清洗",
            r"数据筛选",
        ],
        "blocking": True,   # BLOCKING — 缺失则阻断
        "fix": "在「被试」或「程序」部分报告各阶段剔除人数及剔除理由（如不符纳入标准、"
               "草率作答、退出等），建议附 CONSORT 流程图。",
    },
    {
        "id": "Q.measures.reliability",
        "label": "测量信度报告",
        "keywords": [
            r"Cronbach",
            r"α\s*=",
            r"omega\b",
            r"ω\s*=",
            r"reliability",
            r"信度",
            r"internal consistency",
            r"McDonald",
            r"test.?retest",
            r"重测信度",
        ],
        "blocking": False,
    },
    {
        "id": "Q.results.effect_size",
        "label": "效应量报告",
        "keywords": [
            r"Cohen'?s?\s*[dfghr]",
            r"effect size",
            r"效应量",
            r"η\s*[²2]",
            r"ω\s*[²2]",
            r"[Cc]ram[eé]r'?s?\s*V",
            r"rank.biserial",
            r"R\s*[²2]\s*=",
            r"Glass'? delta",
            r"Hedges'?\s*g",
        ],
        "blocking": False,
    },
    {
        "id": "Q.results.ci",
        "label": "置信区间报告",
        "keywords": [
            r"confidence interval",
            r"置信区间",
            r"95%\s*CI",
            r"CI\s*[\[\(]",
            r"\[\s*[\-\d\.]+\s*,\s*[\-\d\.]+\s*\]",
        ],
        "blocking": False,
    },
    {
        "id": "Q.results.multiple_comparison",
        "label": "多重比较校正说明",
        "keywords": [
            r"Bonferroni",
            r"Holm",
            r"FDR\b",
            r"Benjamini",
            r"multiple comparison",
            r"多重比较",
            r"familywise",
            r"family.?wise error",
            r"Šidák",
            r"Sidak",
            r"correction",
            r"校正",
        ],
        "blocking": False,
    },
]

_QUAL_ITEMS: list[dict] = [
    {
        "id": "L.design.paradigm",
        "label": "研究范式 / 方法论说明",
        "keywords": [
            r"qualitative",
            r"phenomenolog",
            r"grounded theory",
            r"ethnograph",
            r"discourse analy",
            r"narrative inquiry",
            r"质性",
            r"定性",
            r"现象学",
            r"扎根理论",
            r"话语分析",
        ],
        "blocking": False,
    },
    {
        "id": "L.data.saturation",
        "label": "数据饱和",
        "keywords": [
            r"saturation",
            r"饱和",
            r"theoretical saturation",
            r"data saturation",
            r"信息饱和",
        ],
        "blocking": False,
    },
    {
        "id": "L.analysis.coding",
        "label": "编码 / 分析程序",
        "keywords": [
            r"cod(?:ing|ed|es?)\b",
            r"thematic",
            r"category",
            r"编码",
            r"主题分析",
            r"内容分析",
            r"类别",
        ],
        "blocking": False,
    },
    {
        "id": "L.trustworthiness",
        "label": "可信度 / 效度策略",
        "keywords": [
            r"trustworthiness",
            r"credibility",
            r"transferability",
            r"member check",
            r"triangulation",
            r"peer debrief",
            r"可信度",
            r"三角验证",
            r"成员核查",
        ],
        "blocking": False,
    },
    {
        "id": "L.reflexivity",
        "label": "研究者反思 / 立场声明",
        "keywords": [
            r"reflexivity",
            r"positionality",
            r"researcher background",
            r"反思",
            r"立场",
            r"研究者角色",
        ],
        "blocking": False,
    },
]

_MIXED_EXTRA_ITEMS: list[dict] = [
    {
        "id": "M.integration.rationale",
        "label": "混合方法整合理由",
        "keywords": [
            r"mixed.?method",
            r"convergent",
            r"sequential explanatory",
            r"sequential exploratory",
            r"混合方法",
            r"整合设计",
            r"定量定性",
        ],
        "blocking": False,
    },
    {
        "id": "M.integration.procedure",
        "label": "定量/定性整合程序",
        "keywords": [
            r"joint display",
            r"meta.?inference",
            r"triangulation",
            r"联合展示",
            r"元推断",
        ],
        "blocking": False,
    },
]

_RESEARCH_TYPE_ITEMS: dict[str, list[dict]] = {
    "quant": _QUANT_ITEMS,
    "qual": _QUAL_ITEMS,
    "mixed": _QUANT_ITEMS + _QUAL_ITEMS + _MIXED_EXTRA_ITEMS,
}

VALID_RESEARCH_TYPES = list(_RESEARCH_TYPE_ITEMS)


# ---------------------------------------------------------------------------
# 核心检查
# ---------------------------------------------------------------------------

def _item_present(text: str, item: dict) -> bool:
    for kw in item["keywords"]:
        if re.search(kw, text, re.IGNORECASE):
            return True
    return False


def check_draft(text: str, research_type: str = "quant") -> dict:
    """对论文文本跑 JARS 检查，返回结构化结果。

    result 字段:
      research_type   : 实际使用的研究类型
      n_total         : 检查条目总数
      n_present       : 已报告条目数
      n_blocking      : 阻断缺失数（缺失→投稿阻断）
      n_warnings      : 警告缺失数
      passed          : bool（无阻断缺失 → True）
      present         : [{id, label}]
      blocking        : [{id, label, fix}]  — 缺失的阻断条目
      warnings        : [{id, label}]       — 缺失的警告条目
      jars_missing_data_ok  : bool  — 缺失数据处理已报告
      jars_exclusions_ok    : bool  — 剔除信息已报告
    """
    rt = research_type.lower().strip()
    if rt not in _RESEARCH_TYPE_ITEMS:
        rt = "quant"

    items = _RESEARCH_TYPE_ITEMS[rt]
    present: list[dict] = []
    missing_blocking: list[dict] = []
    missing_warnings: list[dict] = []

    for item in items:
        found = _item_present(text, item)
        if found:
            present.append({"id": item["id"], "label": item["label"]})
        elif item["blocking"]:
            missing_blocking.append({
                "id": item["id"],
                "label": item["label"],
                "fix": item.get("fix", "补充相关报告内容"),
            })
        else:
            missing_warnings.append({"id": item["id"], "label": item["label"]})

    # 便于 gate requirement check 直接读
    md_ok = _item_present(text, _id_to_item("Q.procedure.missing_data"))
    ex_ok = _item_present(text, _id_to_item("Q.procedure.exclusions"))

    return {
        "research_type": rt,
        "n_total": len(items),
        "n_present": len(present),
        "n_blocking": len(missing_blocking),
        "n_warnings": len(missing_warnings),
        "passed": len(missing_blocking) == 0,
        "present": present,
        "blocking": missing_blocking,
        "warnings": missing_warnings,
        "jars_missing_data_ok": md_ok,
        "jars_exclusions_ok": ex_ok,
    }


def _id_to_item(item_id: str) -> dict:
    """从所有条目列表中按 id 查找（仅用于内部辅助）。"""
    for items in _RESEARCH_TYPE_ITEMS.values():
        for it in items:
            if it["id"] == item_id:
                return it
    return {"id": item_id, "label": item_id, "keywords": [], "blocking": False}


# ---------------------------------------------------------------------------
# 人读报告
# ---------------------------------------------------------------------------

def format_report(result: dict) -> str:
    lines: list[str] = []
    rt = result["research_type"].upper()
    status = "✓ JARS 检查通过" if result["passed"] else "✗ JARS 检查阻断"
    lines.append(
        f"{status}  [{rt}]  "
        f"已报告 {result['n_present']}/{result['n_total']}  "
        f"阻断 {result['n_blocking']}  警告 {result['n_warnings']}"
    )
    if result["blocking"]:
        lines.append("\n【阻断缺失项】— 必须补充后方可投稿:")
        for b in result["blocking"]:
            lines.append(f"  ✗ [{b['id']}] {b['label']}")
            lines.append(f"       → {b['fix']}")
    if result["warnings"]:
        lines.append("\n【警告缺失项】— 建议补充（APA JARS-2018 推荐）:")
        for w in result["warnings"]:
            lines.append(f"  ⚠ [{w['id']}] {w['label']}")
    if result["present"]:
        labels = [p["label"] for p in result["present"]]
        lines.append(f"\n【已报告】{', '.join(labels)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sidecar IO（供 gate 读取）
# ---------------------------------------------------------------------------

_SIDECAR_NAME = "jars_check.json"


def write_sidecar(result: dict, base_dir: str | Path = ".") -> Path:
    """把检查结果写到 notes/jars_check.json。"""
    notes = Path(base_dir) / "notes"
    notes.mkdir(exist_ok=True)
    out = notes / _SIDECAR_NAME
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_jars_check(base_dir: str | Path = ".") -> dict | None:
    """读 notes/jars_check.json；文件不存在返回 None。"""
    p = Path(base_dir) / "notes" / _SIDECAR_NAME
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def jars_cli(argv: list[str]) -> int:
    """psyclaw jars <draft.md> [--type quant|qual|mixed] [--json] [--no-sidecar]"""
    import argparse

    p = argparse.ArgumentParser(prog="psyclaw jars",
                                description="JARS 检查清单(APA 2018)")
    p.add_argument("draft", nargs="?", default=None,
                   help="论文草稿 Markdown 文件（留空从 stdin 读）")
    p.add_argument("--type", "-t", dest="research_type",
                   choices=VALID_RESEARCH_TYPES, default="quant",
                   help="研究类型(默认 quant)")
    p.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    p.add_argument("--no-sidecar", action="store_true",
                   help="不写 notes/jars_check.json sidecar")
    args = p.parse_args(argv)

    if args.draft:
        src = Path(args.draft)
        if not src.exists():
            print(f"文件不存在: {args.draft}", file=sys.stderr)
            return 1
        text = src.read_text(encoding="utf-8")
        base_dir = src.parent
    else:
        text = sys.stdin.read()
        base_dir = Path(".")

    result = check_draft(text, args.research_type)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))

    if not args.no_sidecar:
        sidecar = write_sidecar(result, base_dir)
        if not args.json:
            print(f"\n  sidecar 已写: {sidecar}")

    return 0 if result["passed"] else 1
