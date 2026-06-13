"""预注册模板生成(D-2)—— OSF / AsPredicted 双格式。

把研究澄清卡(``notes/clarification.md``,17 槽位,见 ``clarify.py``)抽取为两份
**可直接粘贴提交**的预注册文稿:

  - **OSF Preregistration**(6 节标准模板:研究信息 / 设计计划 / 抽样计划 /
    变量 / 分析计划 / 其他)
  - **AsPredicted**(标准 8 问 + 题名 / 研究类型)

学术诚信(对应 gates/PSYCLAW.md 的"区分探索/确证、不 HARKing"):

  - 假设自动按 **确证性(confirmatory)** vs **探索性(exploratory)** 归类;
    未显式标注的假设 **fail-closed 一律按探索性处理**(数据到手后不得反标确证),
    并在告警里点名,提示补标。
  - 样本量依据可**复用 D-1 功效分析**(``power.compute``):给定检验类型+效应量即在
    预注册里嵌入确定性的功效/N 计算,并保留"发表偏倚高估"告警。
  - 缺失的关键槽位渲染为 ``[待补充：…]`` 占位并汇总告警,绝不替用户编造内容。

纯函数(可单测,无 IO/网络/LLM):
  ``parse_clarification`` / ``split_hypotheses`` / ``build_prereg`` /
  ``render_osf`` / ``render_aspredicted`` / ``power_justification_md``。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from psyclaw.psych.clarify import CARD_NAME, SLOTS

# 合法槽位 id 集合(单一真源:与 clarify 的 17 槽位一致)。
_VALID_SIDS = {s[0] for s in SLOTS}

# 预注册的关键槽位:缺失即 fail-closed 告警(数据收集前必须补齐)。
_CRITICAL = [
    ("research_question", "一句可检验的研究问题"),
    ("hypotheses", "逐条假设,每条标 [确证]/[探索]"),
    ("iv", "自变量(操纵/测量)与操作化"),
    ("dv", "因变量测量工具与信效度证据"),
    ("design_type", "设计类型(被试间/内/混合/纵向…)"),
    ("exclusion", "纳入/排除标准与离群处理(先验声明)"),
    ("power", "样本量与功效依据"),
    ("analysis_plan", "每条假设 → 检验的映射"),
]

# 表格行解析:`| sid | status | content |`;content 内 `|` 被 clarify 转义为 `\|`。
_ROW_RE = re.compile(r"^\|([^|]+)\|([^|]+)\|(.*)\|\s*$")

# 假设切分:分号/换行,或在下一个 H<n>/RQ<n>/假设/研究问题 标签前(且非行首)。
_HYP_SPLIT_RE = re.compile(
    r"[;；]\s*|\n+|(?<=\S)\s+(?=(?:H|RQ|假设|研究问题)\s*\d)", re.IGNORECASE)
_HYP_LABEL_RE = re.compile(
    r"^\s*((?:RQ|H|假设|研究问题)\s*\d*[a-zA-Z]?)", re.IGNORECASE)
_HYP_TAG_RE = re.compile(
    r"[\[（(]\s*(确证性?|探索性?|confirmatory|exploratory)\s*[\])）]", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 一、澄清卡解析(纯函数)
# ---------------------------------------------------------------------------

def parse_clarification(text: str) -> dict:
    """把澄清卡 markdown 表格解析为 ``{sid: 内容}``(仅含已 resolved 的非空值)。

    只保留合法 sid 的行,自然滤掉表头 / 分隔行;还原被转义的 ``\\|``。
    """
    answers: dict = {}
    for line in (text or "").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        sid = m.group(1).strip()
        if sid not in _VALID_SIDS:
            continue
        status = m.group(2).strip()
        content = m.group(3).replace("\\|", "|").strip()
        if status.lower() == "resolved" and content:
            answers[sid] = content
    return answers


def _detect_kind(frag: str) -> tuple[str, bool]:
    """判定假设类型 → (kind, tagged)。

    显式 [确证]/[探索]/confirmatory/exploratory → 对应类型(tagged=True);
    RQ/研究问题 前缀 → 探索性(tagged=True);
    否则 **fail-closed 默认探索性**(tagged=False:不得事后反标确证)。
    """
    low = frag.lower()
    if "确证" in frag or "confirmatory" in low:
        return "confirmatory", True
    if "探索" in frag or "exploratory" in low:
        return "exploratory", True
    if re.match(r"^\s*(?:RQ|研究问题)", frag, re.IGNORECASE):
        return "exploratory", True
    return "exploratory", False


def split_hypotheses(text: str) -> list[dict]:
    """把 hypotheses 槽位文本切分为 ``[{label, text, kind, tagged}]``。

    支持 ``H1[确证]:…;H2[探索]:…;RQ1:…`` 这类一行多假设(换行已被澄清卡压成空格)。
    """
    text = (text or "").strip()
    if not text:
        return []
    items: list[dict] = []
    for frag in _HYP_SPLIT_RE.split(text):
        if not frag:
            continue
        frag = frag.strip(" 　.。,，:：-—")
        if not frag:
            continue
        kind, tagged = _detect_kind(frag)
        lm = _HYP_LABEL_RE.match(frag)
        label = lm.group(1).strip() if lm else None
        rest = frag[lm.end():] if lm else frag
        rest = _HYP_TAG_RE.sub("", rest).lstrip(" :：-—、.。").strip()
        if not rest and not label:
            continue
        items.append({"label": label, "text": rest, "kind": kind, "tagged": tagged})
    return items


# ---------------------------------------------------------------------------
# 二、样本量依据(复用 D-1 功效分析)
# ---------------------------------------------------------------------------

def power_justification_md(res: dict | None) -> str | None:
    """把 ``power.compute`` 的结果渲染成 markdown 样本量依据(无 ANSI)。"""
    if not res or "error" in res:
        return None
    lines = [f"- 检验类型：{res.get('analysis', '')}"]
    eff = res.get("effect") or {}
    if eff:
        mag = eff.get("magnitude", "")
        mag_s = f"（{mag}）" if mag not in ("", "—") else ""
        lines.append(f"- 效应量：{eff.get('name', '')} = {eff.get('value')}{mag_s}")
    a_line = f"- α = {res.get('alpha')}"
    if res.get("tails"):
        a_line += f"，{res.get('tails')} 尾"
    lines.append(a_line)
    unit = res.get("n_unit", "")
    n = res.get("n")
    has_total = "n_total" in res
    if res.get("solve") == "n":
        lines.append(f"- 目标功效 = {res.get('power')}")
        if n is None:
            lines.append("- **所需 N 超出上限**：效应过小，请复核效应量假设后重算。")
        else:
            tot = f"（总 N = {res['n_total']}）" if has_total else ""
            lines.append(f"- **所需样本量 N（{unit}）= {n}**{tot}")
    else:
        tot = f"（总 N = {res['n_total']}）" if has_total else ""
        lines.append(f"- 计划样本量 N（{unit}）= {n}{tot}")
        pw = res.get("power")
        if isinstance(pw, float) and pw == pw:
            flag = " ✓ 充分" if pw >= 0.80 else " ⚠ 不足（<.80）"
            lines.append(f"- 据此功效 = {pw:.4f}{flag}")
    for note in res.get("notes", []):
        lines.append(f"- ⚠ {note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 三、组装结构化预注册数据
# ---------------------------------------------------------------------------

def build_prereg(answers: dict, power_res: dict | None = None) -> dict:
    """据澄清卡答案 + 可选功效结果,组装结构化预注册数据 + 告警。"""
    hyps = split_hypotheses(answers.get("hypotheses", ""))
    confirmatory = [h for h in hyps if h["kind"] == "confirmatory"]
    exploratory = [h for h in hyps if h["kind"] == "exploratory"]
    untagged = [h for h in hyps if not h["tagged"]]

    missing = [(sid, hint) for sid, hint in _CRITICAL if not answers.get(sid)]

    warnings: list[str] = []
    for sid, hint in missing:
        warnings.append(f"关键槽位「{sid}」缺失：{hint}（数据收集前必须补齐）。")
    if hyps and not confirmatory:
        warnings.append("无确证性假设：所有结论将只能作探索性陈述（不可声称验证）。")
    if untagged:
        labs = "、".join(h["label"] or h["text"][:12] for h in untagged)
        warnings.append(f"{len(untagged)} 条假设未标 [确证]/[探索]，已 fail-closed "
                        f"按探索性处理：{labs}。如属确证须显式补标后重生成。")
    if not hyps:
        warnings.append("未解析到任何假设：请在澄清卡 hypotheses 槽位逐条列出并标注类型。")

    rq = (answers.get("research_question") or "").strip()
    title = rq if rq else ""

    return {
        "title": title,
        "answers": answers,
        "hypotheses": hyps,
        "confirmatory": confirmatory,
        "exploratory": exploratory,
        "untagged": untagged,
        "missing": [sid for sid, _ in missing],
        "warnings": warnings,
        "power_md": power_justification_md(power_res),
        "power_res": power_res,
    }


# ---------------------------------------------------------------------------
# 四、渲染器
# ---------------------------------------------------------------------------

def _placeholder(hint: str) -> str:
    return f"_[待补充：{hint}]_"


def _slot(answers: dict, sid: str, hint: str) -> str:
    v = (answers.get(sid) or "").strip()
    return v if v else _placeholder(hint)


def _render_hyp_list(hyps: list[dict], empty: str) -> str:
    if not hyps:
        return empty
    out = []
    for h in hyps:
        prefix = f"**{h['label']}** " if h["label"] else ""
        flag = "" if h["tagged"] else "  _（未标注，按探索性处理）_"
        out.append(f"- {prefix}{h['text']}{flag}")
    return "\n".join(out)


def render_osf(prereg: dict) -> str:
    """渲染 OSF Preregistration(6 节标准模板)。"""
    a = prereg["answers"]
    title = prereg["title"] or _placeholder("研究标题（可由研究问题概括）")
    conf_md = _render_hyp_list(
        prereg["confirmatory"], "_（无确证性假设；如有请在澄清卡补标 [确证]）_")
    exp_md = _render_hyp_list(
        prereg["exploratory"], "_（无探索性假设/研究问题）_")
    power_block = prereg.get("power_md") or _slot(
        a, "power", "功效分析：检验/α/功效/效应量/所得N（可跑 psyclaw power 生成）")
    eff_just = _slot(a, "effect_expectation", "预期效应量及其文献依据（注意发表偏倚高估）")

    return f"""# 预注册（OSF Preregistration）

> 自动据研究澄清卡（notes/{CARD_NAME}）生成 · date: {date.today().isoformat()}
> 平台：OSF（https://osf.io/prereg） · **数据收集前**注册；提交前请人工逐节核校。

## 1. 研究信息（Study Information）

### 1.1 标题（Title）
{title}

### 1.2 研究背景与问题（Description）
{_slot(a, "research_question", "一句可检验的研究问题")}

- 理论框架：{_slot(a, "theory_base", "依托理论 + 竞争理论的不同预测")}
- 增量贡献：{_slot(a, "novelty", "相对已有文献的新关系/边界/人群/方法")}

### 1.3 假设（Hypotheses）
**确证性假设（confirmatory，预注册锁定）**
{conf_md}

**探索性假设 / 研究问题（exploratory，结论需独立样本验证）**
{exp_md}

## 2. 设计计划（Design Plan）

### 2.1 研究类型与设计（Study type / Design）
{_slot(a, "design_type", "被试间/内/混合/纵向/ESM…及选它的理由")}

### 2.2 盲法（Blinding）
{_placeholder("是否对被试/实验者/分析者设盲及如何实现")}

### 2.3 随机化（Randomization）
{_slot(a, "randomization", "序列生成 + 分配隐藏；被试内须写抵消平衡")}

## 3. 抽样计划（Sampling Plan）

### 3.1 既有数据（Existing Data）
{_placeholder("数据收集状态：尚未开始 / 已收集未分析 / 已分析（如实声明）")}

### 3.2 目标总体与抽样（Data collection procedures）
{_slot(a, "population", "目标总体 / 抽样框 / 代表性局限")}

### 3.3 样本量与依据（Sample Size & Rationale）
{power_block}

预期效应量依据：{eff_just}

### 3.4 停止规则（Stopping Rule）
{_placeholder("达到目标 N 即停；序贯/可选停止须预先声明并校正")}

## 4. 变量（Variables）

### 4.1 操纵 / 自变量（Manipulated variables）
{_slot(a, "iv", "自变量是操纵还是测量；如何操作化；操纵检查计划")}

### 4.2 测量变量（Measured variables）
- 因变量：{_slot(a, "dv", "量表名+版本+条目数+目标人群信效度证据")}
- 协变量：{_slot(a, "covariates", "逐个写纳入的先验理由（避免研究者自由度）")}

## 5. 分析计划（Analysis Plan）

### 5.1 统计模型（Statistical models：每条确证假设 → 检验）
{_slot(a, "analysis_plan", "逐假设映射检验；前提违反时的稳健替代预案")}

### 5.2 数据剔除与缺失（Data Exclusion / Missing Data）
{_slot(a, "exclusion", "纳入/排除标准、草率作答处理、缺失数据策略（先验）")}

### 5.3 推断标准（Inference Criteria）
- α = {(prereg.get("power_res") or {}).get("alpha", 0.05)}；效应量 + 95% CI 必报（不以 p 值论英雄）。
- 多重比较校正：{_placeholder("如 Holm / FDR；或说明为何不需")}。

### 5.4 探索性分析（Exploratory Analysis）
{exp_md}

> 探索性结果只作假设生成，不得反标为确证；建议 split-half / 独立样本验证。

## 6. 其他（Other）

- 伦理审查（IRB）：{_slot(a, "ethics", "IRB 批号或豁免依据；敏感测量的危机转介流程")}
- 数据/代码/材料共享：{_slot(a, "data_sharing", "OSF 仓库；可开放项与隐私限制及理由")}
"""


def render_aspredicted(prereg: dict) -> str:
    """渲染 AsPredicted(标准 8 问 + 题名/研究类型)。"""
    a = prereg["answers"]
    title = prereg["title"] or _placeholder("预注册题名")
    conf_md = _render_hyp_list(
        prereg["confirmatory"], "_（无确证性假设）_")
    exp_md = _render_hyp_list(
        prereg["exploratory"], "_（无探索性假设）_")
    power_block = prereg.get("power_md") or _slot(
        a, "power", "样本量如何确定（精确说明：目标 N / 停止规则）")

    return f"""# 预注册（AsPredicted · 标准 8 问 + 题名/类型）

> 自动据研究澄清卡（notes/{CARD_NAME}）生成 · date: {date.today().isoformat()}
> 平台：AsPredicted（https://aspredicted.org） · **数据收集前**注册；提交前人工核校。

**题名（Name）**：{title}

**研究类型（Study type）**：{_placeholder("实验 / 观察（相关）/ 其他")}

**1) 数据收集（Data collection）** — 是否已为本研究收集任何数据？
{_placeholder("默认「尚未开始收集」；若已收集须如实声明（影响确证资格）")}

**2) 假设（Hypothesis）** — 本研究的主要问题/假设是什么？
{_slot(a, "research_question", "一句可检验的研究问题")}

确证性假设：
{conf_md}

**3) 因变量（Dependent variable）** — 关键因变量及其测量方式。
{_slot(a, "dv", "量表名+版本+条目数+目标人群信效度证据")}

**4) 条件（Conditions）** — 被试分到几个/哪些条件（或自变量水平）？
{_slot(a, "iv", "自变量水平/分组；操纵还是测量；操作化")}

**5) 分析（Analyses）** — 将进行哪些分析来检验主假设？
{_slot(a, "analysis_plan", "逐假设映射的具体检验（含模型设定）")}

**6) 离群与剔除（Outliers and Exclusions）** — 如何定义离群、精确的剔除规则？
{_slot(a, "exclusion", "纳入/排除标准、离群定义与处理、草率作答阈值（先验）")}

**7) 样本量（Sample Size）** — 将收集多少观测 / 样本量如何确定？
{power_block}

**8) 其他（Other）** — 还想预注册什么？（次要分析、探索性变量、非常规分析）
探索性假设 / 分析：
{exp_md}

协变量：{_slot(a, "covariates", "纳入的协变量及其先验理由")}

伦理审查（IRB）：{_slot(a, "ethics", "IRB 批号或豁免依据；敏感测量应对流程")}
"""


# ---------------------------------------------------------------------------
# 五、编排(IO)
# ---------------------------------------------------------------------------

OSF_NAME = "preregistration_osf.md"
ASPREDICTED_NAME = "preregistration_aspredicted.md"


def run_preregister(project_dir: str | Path = ".", fmt: str = "both",
                    test: str | None = None,
                    power_opts: dict | None = None) -> int:
    """读澄清卡 → 生成预注册文稿(可选嵌入 D-1 功效计算)。

    fmt: osf | aspredicted | both(默认)。test 给定时用 ``power.compute`` 算样本量。
    返回 0;澄清卡缺失返回 1(fail-closed)。
    """
    project = Path(project_dir)
    card = project / "notes" / CARD_NAME
    if not card.exists():
        print("找不到研究澄清卡：先跑 `psyclaw clarify` 完成 17 槽位澄清，"
              f"再生成预注册（应在 {card}）。")
        return 1

    answers = parse_clarification(card.read_text(encoding="utf-8", errors="replace"))

    power_res = None
    if test:
        try:
            from psyclaw.psych.power import compute
            power_res = compute(test, **(power_opts or {}))
        except Exception as exc:  # noqa: BLE001  # 功效计算失败不阻断预注册生成
            print(f"  ⚠ 功效计算失败（{exc}），改用澄清卡 power 槽位文本。")
            power_res = None

    prereg = build_prereg(answers, power_res=power_res)

    notes = project / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if fmt in ("osf", "both"):
        p = notes / OSF_NAME
        p.write_text(render_osf(prereg), encoding="utf-8")
        written.append(p)
    if fmt in ("aspredicted", "both"):
        p = notes / ASPREDICTED_NAME
        p.write_text(render_aspredicted(prereg), encoding="utf-8")
        written.append(p)

    from psyclaw import ui
    body = [f"槽位已解析：{len(answers)}/{len(_VALID_SIDS)}",
            f"假设：确证 {len(prereg['confirmatory'])} · "
            f"探索 {len(prereg['exploratory'])}"]
    if power_res and "error" not in power_res:
        body.append(f"样本量依据：已嵌入 {power_res.get('analysis', '')}（D-1 功效分析）")
    print(ui.panel("Preregister — 预注册模板", "\n".join(body)))
    for p in written:
        print(f"    {p}")
    if prereg["warnings"]:
        print(ui.warn(f"\n  ⚠ {len(prereg['warnings'])} 条告警（数据收集前请处理）："))
        for w in prereg["warnings"]:
            print(ui.dim(f"    · {w}"))
    else:
        print(ui.ok("\n  ✓ 关键槽位齐备，假设均已标注确证/探索。"))
    return 0


def preregister_cli(argv: list[str]) -> int:
    """薄入口:preregister [--osf|--aspredicted] [--test <t> 及功效参数]。"""
    fmt = "both"
    test = None
    opts: dict = {}
    float_flags = {"--d": "d", "--r": "r", "--f": "f", "--f2": "f2",
                   "--a": "a", "--b": "b", "--cp": "cp", "--alpha": "alpha",
                   "--rmsea0": "rmsea0", "--rmsea1": "rmsea1"}
    int_flags = {"--k": "k", "--u": "u", "-n": "n", "--n": "n",
                 "--tails": "tails", "--df": "df", "--sims": "sims"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--osf":
            fmt = "osf"
        elif a == "--aspredicted":
            fmt = "aspredicted"
        elif a == "--both":
            fmt = "both"
        elif a == "--test":
            i += 1
            test = argv[i] if i < len(argv) else None
        elif a == "--power-target":   # 目标功效(反解 N)
            i += 1
            try:
                opts["power"] = float(argv[i])
            except (IndexError, ValueError):
                pass
        elif a == "--kind":
            i += 1
            if i < len(argv):
                opts["kind"] = argv[i]
        elif a in float_flags:
            i += 1
            try:
                opts[float_flags[a]] = float(argv[i])
            except (IndexError, ValueError):
                pass
        elif a in int_flags:
            i += 1
            try:
                opts[int_flags[a]] = int(argv[i])
            except (IndexError, ValueError):
                pass
        i += 1
    return run_preregister(fmt=fmt, test=test, power_opts=opts or None)
