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
            r"\b[dgr]\s*=\s*[-−\.0-9]",   # 裸报 d = 0.29 / r = -.21 也算已报告
        ],
        "blocking": True,   # BLOCKING(feat-096)— 效应量必报是铁律,缺失不是"建议补充"
        "fix": "在结果部分为每个主要检验报告效应量(Cohen's d / Hedges' g / η² / r 等)——"
               "效应量必报(gates/PSYCLAW.md 铁律)。",
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
        "blocking": True,   # BLOCKING(feat-096)— 效应量+CI 成对必报
        "fix": "为效应量报告 95% 置信区间(如 d = 0.29, 95% CI [-0.02, 0.60])——"
               "效应量+CI 成对必报(gates/PSYCLAW.md 铁律)。",
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
# 学术诚信启发式(feat-096)——quant/mixed 适用的越界信号,对抗评估实测四类漏网
# ---------------------------------------------------------------------------

_CAUSAL_CLAIM_PAT = [
    r"证明[了]?[^。\n]{0,20}?(?:导致|降低|提升|改善|减少|增加|有效)",
    r"(?:导致|引起)[了]?[^。\n]{0,12}(?:下降|上升|降低|提升|改善|减少|增加)",
    r"(?:显著)?(?:降低|提升|改善|减少|增加)[了]?[^。\n]{0,15}(?:水平|症状|得分|风险|抑郁|焦虑)",
    r"因果性?(?:作用|效应|保护)",
    r"\bcaus(?:es?|al(?:ly)?|ed)\b",
    r"\b(?:reduc|improv|decreas|increas)(?:es?|ed)\b[^.\n]{0,30}"
    r"\b(?:depression|anxiety|symptom|level)s?\b",
]
_CROSS_DESIGN_PAT = [r"横断面", r"cross.?sectional", r"相关(?:设计|研究|数据|调查)",
                     r"correlational"]
_RANDOMIZED_PAT = [r"随机分配", r"随机对照", r"随机分组", r"随机化",
                   r"randomi[sz]ed\s+(?:controlled|assignment|allocation)", r"\bRCT\b"]

_EXCLUSION_N_PAT = [r"剔除[了的]?\s*\d", r"排除[了的]?\s*\d", r"excluded?\s+\d",
                    r"\d+\s*(?:participants?|被试|人|名)[^。\n]{0,12}excluded"]
_PRESPECIFIED_PAT = [r"预注册", r"pre.?regist", r"预先(?:定义|设定|确定|规定)",
                     r"事先(?:定义|设定|确定|规定)", r"a\s?priori",
                     r"预定(?:的)?(?:剔除|排除)?标准", r"预设标准",
                     r"3\s*(?:个)?(?:SD|标准差)"]

_SUBGROUP_PAT = [r"亚组", r"分层分析", r"subgroup"]
_SIG_PAT = [r"显著", r"significant", r"p\s*[<=≤]"]
_CORRECTION_PAT = [r"Bonferroni", r"Holm", r"FDR\b", r"Benjamini", r"Šidák", r"Sidak",
                   r"multiple comparison correction", r"校正", r"familywise"]
# 否定短语(「未/无/没/不…校正」)在匹配前剥除,防止「未进行多重比较校正」被当已校正
_NEGATED_CORRECTION = re.compile(r"[未无没不][^。\n]{0,8}?校正")
_CONFIRMATORY_PAT = [r"验证了[^。\n]{0,10}假设", r"证实了[^。\n]{0,10}假设",
                     r"(?:支持|验证)了\s*H\s*\d", r"得到确证",
                     r"confirm(?:ed|s)?\s+(?:our\s+)?hypothes"]

_MARGINAL_PAT = [r"边缘显著", r"边际显著", r"临界显著", r"(?:呈|存在)?显著趋势",
                 r"接近显著", r"趋于显著", r"marginal(?:ly)?\s+significant",
                 r"trend(?:ing|ed)?\s+toward", r"approach(?:ed|ing)\s+significance"]

# ---- 数值 × 措辞矛盾(feat-098)——第二轮对抗评估实测三类漏网 ------------------
# p 值抓取:p = .051 / p=0.06 / p = .10(排除 p < .05 之类的不等式,只看等号报告)
_P_VALUE_RE = re.compile(r"\bp\s*=\s*(0?\.\d+)", re.IGNORECASE)
# 命中 p 值后,同句 ±60 字符内的显著宣称(否定式「不显著/未达显著」先剥除)
_SIG_CLAIM_RE = re.compile(r"显著|得到确证|significant", re.IGNORECASE)
_NEGATED_SIG = re.compile(r"(?:不|未|没有|未达(?:到)?(?:统计)?|无)[^。\n]{0,6}?显著"
                          r"|not\s+significant|non.?significant", re.IGNORECASE)
# 效应量抓取(d/g;r 的口径不同不混判)与夸大措辞
_D_VALUE_RE = re.compile(r"\b[dg]\s*=\s*(-?0?\.\d+)", re.IGNORECASE)
_OVERCLAIM_PAT = [r"强效应", r"效应(?:确凿|显著且|巨大)", r"意义重大", r"效果显著且",
                  r"(?:建议|应当?)[^。\n]{0,10}(?:全国|大规模|全面)?推广",
                  r"large effect", r"substantial effect"]
# 信度抓取与洗白措辞
_ALPHA_VALUE_RE = re.compile(r"(?:Cronbach\s*)?(?:α|alpha)\s*=\s*(0?\.\d+)",
                             re.IGNORECASE)
_RELIABLE_CLAIM_PAT = [r"信度(?:良好|较好|可靠|理想)", r"内部一致性(?:良好|较好|高)",
                       r"good reliability", r"acceptable reliability"]


def _hit(text: str, pats: list[str]) -> str | None:
    """返回第一个命中片段(供报告展示定位),无命中返回 None。"""
    for kw in pats:
        m = re.search(kw, text, re.IGNORECASE)
        if m:
            return m.group(0)[:60]
    return None


def integrity_flags(text: str) -> list[dict]:
    """学术诚信启发式:返回 [{id,label,severity,fix,evidence}](feat-096)。

    关键词层的**信号检测**,不是审稿判决——目的是把「相关≠因果 / p-hacking /
    HARKing / 边缘显著话术」这类铁律级越界从「静默放行」变成「有痕拦截」;
    误报由人工复核消化,漏报比误报贵得多(fail-closed 取向)。
    """
    flags: list[dict] = []
    causal = _hit(text, _CAUSAL_CLAIM_PAT)
    cross = _hit(text, _CROSS_DESIGN_PAT)
    randomized = _hit(text, _RANDOMIZED_PAT)
    if causal and cross and not randomized:
        flags.append({
            "id": "I.causal_language_design", "severity": "block",
            "label": "因果结论越界:横断面/相关设计使用因果表述",
            "evidence": causal,
            "fix": "横断面/相关设计不支持因果结论:把「导致/降低/证明有效」改为"
                   "「相关/预测/与…有关」,或补充随机分配等因果识别设计并如实描述。"})

    # 剔除声明的预先标准按 ±200 字符**邻近窗口**找:引言里一句「已预注册」
    # 不能给结果节的事后剔除背书(对抗评估实测:假预注册声明吸收了全局信号)
    excl_hits = [m for kw in _EXCLUSION_N_PAT
                 for m in re.finditer(kw, text, re.IGNORECASE)]
    if excl_hits and not any(
            _hit(text[max(0, m.start() - 200):m.end() + 200], _PRESPECIFIED_PAT)
            for m in excl_hits):
        flags.append({
            "id": "I.posthoc_exclusion", "severity": "warn",
            "label": "剔除被试未见预先定义标准(研究者自由度信号)",
            "evidence": excl_hits[0].group(0)[:60],
            "fix": "在剔除声明处说明标准是否在数据收集前预先定义(预注册/±3SD 等);"
                   "事后剔除需附敏感性分析(含/不含两套结果)。"})

    subgroup = _hit(text, _SUBGROUP_PAT)
    corr_text = _NEGATED_CORRECTION.sub("", text)
    if subgroup and _hit(text, _SIG_PAT) and not _hit(corr_text, _CORRECTION_PAT):
        confirmatory = _hit(text, _CONFIRMATORY_PAT)
        flags.append({
            "id": "I.subgroup_harking", "severity": "block" if confirmatory else "warn",
            "label": ("亚组结果冒充确证假设且无多重比较校正(HARKing 信号)"
                      if confirmatory else "亚组分析无多重比较校正"),
            "evidence": confirmatory or subgroup,
            "fix": "多个亚组仅个别显著且无校正时,不得表述为「验证了事先假设」——"
                   "如实标注探索性,做 Bonferroni/FDR 校正或交互效应检验。"})

    marginal = _hit(text, _MARGINAL_PAT)
    if marginal:
        flags.append({
            "id": "I.marginal_significance", "severity": "block",   # feat-098:用户明令必须避免,升阻断
            "label": "「边缘显著/显著趋势」话术",
            "evidence": marginal,
            "fix": "p 值不显著就是不显著:删除「趋势/边缘/边际/接近显著」表述,"
                   "如实报告精确 p+效应量+CI,把解释留给区间。"})

    # ---- 数值 × 措辞矛盾(feat-098,第二轮对抗评估实测三类漏网)----------
    for m in _P_VALUE_RE.finditer(text):
        try:
            pv = float(m.group(1))
        except ValueError:
            continue
        if pv < 0.05:
            continue
        window = _NEGATED_SIG.sub("", text[max(0, m.start() - 60):m.end() + 60])
        if _SIG_CLAIM_RE.search(window):
            flags.append({
                "id": "I.p_overstate", "severity": "block",
                "label": f"p = {m.group(1)} ≥ .05 却宣称「显著/得到确证」",
                "evidence": text[m.start():m.end() + 40].split("\n")[0][:60],
                "fix": "p ≥ .05 不得称显著,四舍五入到阈值即数据不诚实:如实报告"
                       "精确 p 值与效应量+CI,结论按未达显著撰写。"})
            break

    for m in _D_VALUE_RE.finditer(text):
        try:
            dv = abs(float(m.group(1)))
        except ValueError:
            continue
        if dv < 0.2 and _hit(text, _OVERCLAIM_PAT):
            flags.append({
                "id": "I.effect_overclaim", "severity": "warn",
                "label": f"效应量 |d| = {dv:g} < 0.2(不足小效应)却用「强效应/意义重大/推广」措辞",
                "evidence": _hit(text, _OVERCLAIM_PAT),
                "fix": "按 Cohen 基准 d<0.2 连小效应都不到:删除夸大措辞,"
                       "讨论实际意义时以效应量与 CI 为准,不以 p 值背书重要性。"})
            break

    for m in _ALPHA_VALUE_RE.finditer(text):
        try:
            av = float(m.group(1))
        except ValueError:
            continue
        if av < 0.60:
            window = text[max(0, m.start() - 60):m.end() + 60]
            if _hit(window, _RELIABLE_CLAIM_PAT):
                flags.append({
                    "id": "I.reliability_overclaim", "severity": "warn",
                    "label": f"α = {m.group(1)} < .60 却称「信度良好」",
                    "evidence": window.strip()[:60],
                    "fix": "α<.60 低于常规可接受线(.70):如实描述信度不足,"
                           "报告对结论的影响或改用/补验更可靠的测量。"})
                break
    return flags


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

    # 学术诚信启发式(feat-096)——独立于 JARS 条目计数(n_* 求和不变式不动),
    # 但 severity=block 的信号参与 passed 判定:铁律越界不放行。
    integrity = integrity_flags(text) if rt in ("quant", "mixed") else []
    n_integrity_block = sum(1 for f in integrity if f["severity"] == "block")

    return {
        "research_type": rt,
        "n_total": len(items),
        "n_present": len(present),
        "n_blocking": len(missing_blocking),
        "n_warnings": len(missing_warnings),
        "passed": len(missing_blocking) == 0 and n_integrity_block == 0,
        "present": present,
        "blocking": missing_blocking,
        "warnings": missing_warnings,
        "integrity": integrity,
        "n_integrity_block": n_integrity_block,
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
    for f in result.get("integrity") or []:
        mark = "✗" if f["severity"] == "block" else "⚠"
        if "【诚信启发式】" not in "\n".join(lines):
            lines.append("\n【诚信启发式】— 疑似铁律越界(block 阻断投稿;人工复核可推翻):")
        lines.append(f"  {mark} [{f['id']}] {f['label']}")
        if f.get("evidence"):
            lines.append(f"       命中:「{f['evidence']}」")
        lines.append(f"       → {f['fix']}")
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
