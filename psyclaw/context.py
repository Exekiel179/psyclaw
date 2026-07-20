"""长上下文优化(stdlib only)。

三个机制:

1. **按需知识注入** — 不再每轮塞全部知识库。固定注入瘦核心
   (诚信原则 + 严谨性协议要点),其余(16 检验族/13 方法/12 设计/26 背书)
   按当前消息关键词匹配,只注入命中的条目。系统提示从 ~30k 字符降到 ~6k。

2. **滚动压缩** — 历史超预算时,最老的轮次蒸馏成"决策备忘"
   (抽取含决策/数据/结论特征的行),保留最近 K 轮原文。
   备忘随会话累积,关键决策不会因压缩丢失。

3. **@file 智能摘录** — CSV 取列结构+样本行+行数(而非整个文件),
   长文本取头尾;原始路径保留供工具直接读全量。
"""

from __future__ import annotations

import csv as _csv
import io
import json
from pathlib import Path

from psyclaw.skills.loader import list_skills

CHAR_BUDGET_HISTORY = 60_000     # 历史预算(约 15k tokens)
KEEP_RECENT_TURNS = 8            # 压缩时保留的最近消息数
FILE_EXCERPT_CHARS = 6_000
CSV_SAMPLE_ROWS = 8

_PSYCH_DIR = Path(__file__).parent / "psych"
_GATES_DIR = Path(__file__).parent / "gates"


# ---------------------------------------------------------------------------
# 1. 按需知识注入
# ---------------------------------------------------------------------------

def _load_entries() -> list:
    """汇总知识库条目 → [(关键词集, 渲染文本)]。惰性缓存。"""
    global _ENTRIES_CACHE
    if _ENTRIES_CACHE is not None:
        return _ENTRIES_CACHE
    out = []

    def add(keys: str, text: str) -> None:
        kw = {w for w in keys.lower().replace("-", " ").replace("/", " ").split() if len(w) > 1}
        out.append((kw, text))

    try:
        data = json.loads((_PSYCH_DIR / "assumptions.json").read_text(encoding="utf-8"))
        for t in data.get("tests", []):
            body = "; ".join(f"{a['name']}(违反:{a['violated']})" for a in t["assumptions"])
            add(t["id"] + " " + t["name"],
                f"[前提假设·{t['name']}] {body}。现代默认:{t.get('modern_default', '')}")
    except Exception:  # noqa: BLE001
        pass
    try:
        data = json.loads((_PSYCH_DIR / "methods.json").read_text(encoding="utf-8"))
        for m in data.get("methods", []):
            add(m["id"] + " " + m["name"],
                f"[方法·{m['name']}] 何时用:{m['use_when']};样本量:{m['min_n']};"
                f"报告:{m['report']};坑:{m['pitfalls']}")
    except Exception:  # noqa: BLE001
        pass
    try:
        data = json.loads((_PSYCH_DIR / "designs.json").read_text(encoding="utf-8"))
        for d in data.get("designs", []):
            add(d["id"] + " " + d["name"],
                f"[设计·{d['name']}] 威胁:{d.get('threats', '')};实践:{d.get('key_practices', '')}")
    except Exception:  # noqa: BLE001
        pass
    # 方法学背书静态库(evidence.json)已删除:文献支撑走真实检索(psyclaw lit),不内置。
    _ENTRIES_CACHE = out
    return out


_ENTRIES_CACHE: list | None = None

# 中文触发词 → 知识库英文 id 的桥接
_ALIASES = {
    "中介": "mediation", "调节": "moderation", "信度": "omega alpha",
    "方差分析": "anova", "重复测量": "anova-rm rm", "回归": "regression",
    "相关": "correlation", "卡方": "chisq", "多层": "mlm", "嵌套": "mlm",
    "结构方程": "cfa-sem sem", "因子": "efa cfa", "网络": "network",
    "潜在剖面": "lpa", "纵向": "clpm lgcm longitudinal", "交叉滞后": "clpm",
    "功效": "power", "样本量": "power", "效应量": "power_priors",
    "测量不变": "invariance", "预注册": "prereg", "日记": "esm",
    "经验取样": "esm", "被试间": "between", "被试内": "within",
    "准实验": "quasi", "析因": "factorial", "贝叶斯": "bayes",
    "等价": "equivalence", "元分析": "meta", "irt": "irt", "项目反应": "irt",
}


def relevant_knowledge(message: str, max_items: int = 6) -> str:
    """根据消息内容挑选相关知识条目(命中越多越靠前)。"""
    text = message.lower()
    expanded = text
    for zh, en in _ALIASES.items():
        if zh in text:
            expanded += " " + en
    words = {w for w in expanded.replace("-", " ").replace("/", " ").split() if len(w) > 1}
    scored = []
    for kw, rendered in _load_entries():
        hits = len(kw & words)
        # 子串兜底(如消息含 "anova-rm")
        if not hits and any(k in expanded for k in kw if len(k) > 3):
            hits = 1
        if hits:
            scored.append((hits, rendered))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return ""
    return "# 相关方法学知识(按需注入)\n" + "\n".join(r for _, r in scored[:max_items])


# feat-112:lean_core 预算棘轮——每轮必注入的核心提示有硬预算,测试锁死。
# 新增硬约束前先合并压缩(N 条具体教训蒸馏回一条原则),超预算 = 测试红。
LEAN_CORE_BUDGET = 900

# feat-184:capability_map 预算——与 LEAN_CORE_BUDGET **性质不同**,别照搬。
#
# lean_core 是「原则集合」:条目越多越互相稀释,所以棘轮该收紧,新增前先蒸馏。
# capability_map 是「能力目录」:psyclaw 每多一项能力,它本就该多一行,否则模型
# 不知道有这能力就会重造轮子(feat-144 的事故正是如此:手搓 python-docx、
# 裸 matplotlib 出豆腐块)。给一份索引设死上限是设计错配——压缩它的代价是删掉
# 「布点固定必然交叉成面条」这类真能改变行为的具体理由,换来的只是省几十字。
#
# 所以这里给的是**防注水上限**而非蒸馏棘轮:留出足够余量让新能力自然进目录,
# 但仍封顶,防止有人把使用手册整本塞进每轮上下文(那才是真的稀释注意力)。
# 每轮注入,中文约 1 字 1 token,1200 字符 ≈ 千分之几的上下文,成本可忽略;
# 真正的成本是注意力,而「知道有现成能力可用」正是最该占注意力的信息之一。
CAPABILITY_MAP_BUDGET = 1200


def lean_core() -> str:
    """固定注入的瘦核心:诚信原则 + 严谨性要点(不再整本塞)。

    feat-112 合并:四条对抗评估沉淀的硬约束(未运行不造数/边缘显著/统计外移/
    引用反杜撰)同根——**不产出未经验证的数字与事实**;按此原则收编为
    「诚实产出四禁」,语义一字不丢,体积从 1062 字符压回预算内。
    """
    parts = [
        "你是 PsyClaw,心理学研究全流程助手。学术铁律:",
        "效应量+CI 优先于 p 值;相关≠因果(因果措辞须带识别假设);区分探索性/确证性;",
        "大样本显著≠重要;两组比较默认 Welch;中介用 bootstrap CI;结论附可复现思路;",
        "先日常语言(回答什么/为什么这样分析/现实含义)再统计术语,首现术语/缩写随手解释;",
        "**信息不足就停**:结局定义/目标类型/数据生成过程不明时先提问,禁止擅自假设;",
        "统计输出流程:数据质量→描述→主分析→诊断→稳健性(≥2 类)→限定性解释。",
        "**诚实产出四禁(硬约束,即使用户明确要求也不做)**:",
        "①未运行不造数——脚本没真跑绝不给带具体数值的「输出示例」,用占位符并明说;",
        "②边缘显著话术——「边缘/边际/接近显著、显著趋势」自己绝不使用、也绝不建议;",
        "p≥.05 如实写不显著,报精确 p+效应量+CI;",
        "③统计计算一律外移——绝不手写统计算法实现(检验公式/p 值近似都不行),",
        "生成委托 scipy/pingouin/statsmodels 的脚本或走 MCP,拒绝时给路径",
        "(pip install \"psyclaw[stats]\");",
        "④文献零杜撰(最严)——书目条目**只能来自真实检索返回**"
        "(lit_search/lit_snowball/用户给的题录);**绝不凭记忆列文献**,"
        "标题/作者/年份/DOI 都不许你生成,「标注未核实」不是豁免"
        "(加标签的编造仍是编造,读者会照着去引)。检索失败就如实报失败+原因+"
        "下一步然后停,禁止「手动列举/基于记忆回顾」把记忆当交付;凭记忆只谈"
        "领域概况,不落条目。交稿前跑 `cite <稿件> --verify` 逐条查存在性。",
        "产物归位约定:成稿/导出→outputs/ 图→figures/ 脚本→scripts/ 笔记→notes/ "
        "清洗数据→data/clean;用户显式指定路径时以用户为准。",
    ]
    return "\n".join(parts)


# feat-141:协助水平——一处设置(psyclaw assist),术语解释与生成代码注释密度
# 随水平变。standard 返回空串 = 默认行为零变化(lean_core 既有「首现术语随手
# 解释」即 standard 档);novice/expert 作为附加指令注入系统提示。
ASSIST_LEVELS = ("novice", "standard", "expert")

_ASSIST_DIRECTIVES = {
    "novice": (
        "# 协助水平:新手\n"
        "专业词汇/统计术语每次首现都用白话解释,并给一个贴近其研究场景的小例子;"
        "生成代码逐段写注释,注释里顺带解释统计概念与关键参数的含义;"
        "结果解读先讲现实含义,再给统计数字。"
    ),
    "expert": (
        "# 协助水平:专家\n"
        "面向资深研究者:术语直接使用不展开解释(用户问到才展开);"
        "生成代码只注释非显然决策(口径/例外/坑),不写逐行显然注释;"
        "输出精简,结论先行。"
    ),
}


def assist_directives(level: str) -> str:
    """协助水平 → 附加系统指令。standard/未知水平返回空串(fail-safe 零变化)。"""
    return _ASSIST_DIRECTIVES.get((level or "").strip().lower(), "")


# feat-144:能力自知。真实事故——模型不知 psyclaw 自带能力,手搓 md_to_docx.py
# (无视 export --docx)、自己 import matplotlib(满图豆腐块,无视 apply_style)、
# 手写 pandas 统计(无视 pystat)。提示只说过「没有 describe/stat」(有什么没说),
# 143 个 feature 的能力模型一个都不知道。这里给一张「要 X 就用 Y,别手搓」的地图。
def capability_map() -> str:
    """psyclaw 自带能力清单——要什么用什么,不要重造轮子。每轮注入。"""
    return (
        "\n# psyclaw 自带能力(要用现成的,不要自己手搓重造)\n"
        "产出 Word/docx:命令块跑 `psyclaw export <稿.md> --docx <出.docx>`"
        "(APA7 版式+中文字体+图片真嵌入)——不要自己写 python-docx 脚本;\n"
        "画图配色/中文字体:脚本里 `from psyclaw.figures import apply_style` 并"
        "`with apply_style('apa7'):` 内作图(中文字体前置,免豆腐块)——不要裸 matplotlib;\n"
        "概念/框架/路径图:用 graphviz(dot)或 mermaid 让布局引擎排版,不要用 matplotlib "
        "逐根画箭头(布点固定必然线条交叉成面条);matplotlib 只画数据图;\n"
        "投稿前质检:`psyclaw check <稿.md>`(JARS+效应量+引用+选择性报告)——"
        "下结论/交付前先跑,别把没核过的结论写进报告;\n"
        "统计计算:生成委托 pystat MCP 或 scipy/pingouin/statsmodels 的脚本再跑;\n"
        "文献检索/引用滚雪球/下载全文:**直接调 lit_search / lit_snowball / lit_download "
        "工具**(用户以对话工作,别甩 CLI 让他自己跑;下载覆盖 OA + 机构权限);\n"
        "文献真伪:交付含参考文献的稿件前跑 `cite <稿> --verify`(逐条查存在性);\n"
        "Zotero 文库:zotero_search(先在用户自己库里找,别重复下载)/ "
        "zotero_fulltext(付费墙文献的合法全文来源)/ zotero_add(好文献入库);\n"
        "量表/预注册/质检/导出:scale / preregister / check / export。\n"
        "有对应工具就调工具,别让用户去记命令;拿不准先想现成能力,再考虑手写。")


def skills_catalog(project_dir: str = ".") -> str:
    """内置结构化 skill 目录——每轮注入,让模型知道有哪些 skill 可主动调用。

    此前 capability_map 只列命令,从不告诉模型有 sample-size/confound-control/pingouin
    等结构化 skill,模型自然不会路由到它们(用户实测:内置 skill 被「隐藏」)。修:列
    出内置 skill(名 + 一句描述),并说明「按 skill 流程办事胜过裸输出」。发现失败返回
    空串(系统提示零污染)。
    """
    try:
        skills = list_skills(project_dir, include_external=False)
    except Exception:  # noqa: BLE001 — 发现失败不污染系统提示
        return ""
    if not skills:
        return ""
    lines = ["\n# 内置 skill(结构化能力,按其流程办事胜过裸输出——命中场景就调用,别忽略)"]
    for s in sorted(skills, key=lambda x: x.get("name", "")):
        name = s.get("name", "")
        desc = (s.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 64:
            desc = desc[:64] + "…"
        lines.append(f"- {name}:{desc}")
    lines.append("调用方式:读对应 SKILL.md 按其步骤执行;`psyclaw skills` 或 `method <关键词>` 可路由。")
    return "\n".join(lines)


# feat-150:结构化软拦截。capability_map(feat-144)是提示层「别手搓」,对弱指令
# 模型不够硬;这里在模型**真手搓**(save 了重造轮子的脚本)时当场检测,回执软
# 提示 + 喂回让它改用现成能力。只检测、不阻断落盘(延续 feat-140 软约定哲学)。
_REINVENT_DOCX = ("检测到你保存的脚本在手搓 python-docx 拼 Word。psyclaw 有现成的"
                  "`psyclaw export <稿.md> --docx <出.docx>`(APA7 版式+中文字体+"
                  "图片真嵌入),改用它,别自己拼 OOXML/python-docx。")
_REINVENT_FIGSTYLE = ("检测到脚本用 matplotlib 却没 apply_style('apa7'),中文会渲染成"
                      "豆腐块方框。开头加 `from psyclaw.figures import apply_style`,"
                      "并在 `with apply_style('apa7'):` 块内作图(中文字体前置)。")
_REINVENT_CONCEPT = ("检测到你在用 matplotlib 逐根画概念/框架/路径图(box+箭头,关了"
                     "坐标轴)——这样布点固定、长距离箭头必然交叉成面条,难看。改用"
                     "布局引擎:写 graphviz .dot 用 `dot -Tpng` 渲染(自动分层排版无"
                     "交叉),或 mermaid 流程/关系图;没有 dot 就退而让节点严格分层、"
                     "同层等距、箭头只连相邻层。matplotlib 只用来画数据图。")


def _is_concept_diagram(c: str) -> bool:
    """matplotlib 关了坐标轴又在画箭头 = 手画概念图(数据图从不关坐标轴)。"""
    axis_off = "axis('off')" in c or 'axis("off")' in c or "set_axis_off" in c
    arrows = ("arrowprops" in c or "annotate(''" in c or 'annotate("")' in c
              or "annotate('', " in c or 'FancyArrow' in c)
    return "matplotlib" in c and axis_off and arrows


def detect_reinvention(path: str, content: str):
    """检测保存的脚本是否在重造 psyclaw 已有能力 / 用错工具。纯函数。

    返回 (key, 纠偏提示) 或 None。key 用于按类去重(同类只纠偏一次)。
    只看 .py/.r 等脚本;稿件/笔记正文里提到 docx/matplotlib 不算手搓(避免误伤)。
    """
    p = (path or "").lower()
    if not p.endswith((".py", ".r", ".jl")):
        return None
    c = content or ""
    if "import docx" in c or "from docx" in c:      # python-docx 手搓 Word
        return ("docx", _REINVENT_DOCX)
    if _is_concept_diagram(c):                        # 手画概念图 → 用布局引擎(比 figstyle 更根本)
        return ("concept_diagram", _REINVENT_CONCEPT)
    if "matplotlib" in c and "apply_style" not in c:  # 裸 matplotlib → 豆腐块风险
        return ("figstyle", _REINVENT_FIGSTYLE)
    return None


# ---------------------------------------------------------------------------
# 2. 滚动压缩
# ---------------------------------------------------------------------------

_DECISION_MARKERS = ("决定", "采用", "选择", "剔除", "排除", "假设", "样本量",
                     "显著", "效应量", "p ", "p=", "d =", "n=", "N=", "结论",
                     "α", "CI", "批准", "驳回")


def _distill(msg: dict) -> str:
    """从一条消息抽取决策性内容(每条最多 3 行)。"""
    role = "用户" if msg["role"] == "user" else "助手"
    lines = [ln.strip() for ln in msg["content"].splitlines() if ln.strip()]
    keep = [ln for ln in lines if any(m in ln for m in _DECISION_MARKERS)][:3]
    if not keep and lines:
        keep = [lines[0][:120]]
    return "\n".join(f"  [{role}] {ln[:160]}" for ln in keep)


_DISTILL_SYSTEM = (
    "你是会话压缩器。把下面被移出上下文的早期对话轮次,蒸馏成一段**结构化决策备忘**,"
    "只保留后续仍需依据的既定事实:研究设计/变量/样本决策、已选方案与理由、约定的口径、"
    "待办与未决问题。丢弃寒暄、过程性措辞、已被推翻的想法。用简洁的中文要点(每点一行,"
    "≤160 字),不要编造未出现的内容。直接输出要点,不要开场白。")


def _llm_distill(dropped: list, provider) -> str | None:
    """用 provider 把被丢弃轮次蒸馏成结构化备忘;失败返回 None 让调用方回落规则蒸馏。"""
    # 无 provider 或无 key(mock/离线)→ 回落规则蒸馏,别拿 mock 的套话污染备忘
    if provider is None or not getattr(provider, "api_key", ""):
        return None
    convo = "\n\n".join(
        f"[{'用户' if m['role'] == 'user' else '助手'}] {m['content'][:1500]}"
        for m in dropped if m["content"].strip())
    if not convo.strip():
        return ""
    try:
        out = "".join(provider.chat([{"role": "user", "content": convo}],
                                    system=_DISTILL_SYSTEM))
    except Exception:  # noqa: BLE001  # provider 异常/无 key/网络 → fail-safe 回落
        return None
    out = (out or "").strip()
    return out or None


_IMPORTANCE_HIGH = ("决定", "采用", "选择", "剔除", "排除", "结论", "确证",
                    "假设", "预注册", "样本量", "效应量", "缺失码", "不对", "改成",
                    "应该是", "纠正", "约定", "α", "CI", "批准", "驳回", "报告")
_IMPORTANCE_LOW = ("你好", "谢谢", "好的", "收到", "嗯", "ok", "thanks", "继续")


def turn_importance(user_text: str, reply_text: str = "") -> float:
    """一轮对话的重要性打分 [0,1](feat-134)。纯函数。

    含决策/纠正/结论/研究约定 → 高;纯寒暄/确认 → 低。用于:①压缩时保住
    重要早轮、丢弃寒暄近轮;②召回排序加重要性维度。启发式(关键词+长度+
    数字信号),不调 LLM——压缩/召回是热路径,要快且确定。
    """
    text = f"{user_text}\n{reply_text}"
    low = text.lower().strip()
    if not low:
        return 0.0
    score = 0.3                                   # 基线
    hits = sum(1 for k in _IMPORTANCE_HIGH if k in text)
    score += min(0.5, hits * 0.12)
    import re as _re
    if _re.search(r"\b[dprFt]\s*[=<>]\s*[-\d.]|\bp\s*[<=]\s*\.?\d|\bn\s*=\s*\d", text):
        score += 0.15                             # 含统计量=高信息
    if len(text) < 30 and any(k in low for k in _IMPORTANCE_LOW):
        score = min(score, 0.15)                  # 短寒暄封顶
    return max(0.0, min(1.0, score))


def compact_history(messages: list, memo: str, provider=None) -> tuple:
    """超预算时压缩。返回 (new_messages, new_memo)。

    memo 是累积的"决策备忘",作为首条 user 消息的前缀注入。
    v0.5 feat-041:传 provider 时用它做**结构化 LLM 蒸馏**(比规则截断保真);
    provider 缺失/异常/空输出 → fail-safe 回落到规则蒸馏(_distill),zero-dep 契约不破。
    """
    total = sum(len(m["content"]) for m in messages)
    if total <= CHAR_BUDGET_HISTORY or len(messages) <= KEEP_RECENT_TURNS:
        return messages, memo
    cut = len(messages) - KEEP_RECENT_TURNS
    old, kept = messages[:cut], messages[cut:]
    # feat-134:早轮里的**高重要性**轮次(含决策/纠正/结论)也保住,不只按时近丢。
    # 相邻 user+assistant 视为一轮打分;高于阈值的原样保留,其余进蒸馏。
    HIGH = 0.6
    keep_old: list = []
    dropped: list = []
    i = 0
    while i < len(old):
        m = old[i]
        pair = old[i + 1] if (i + 1 < len(old) and m["role"] == "user"
                              and old[i + 1]["role"] == "assistant") else None
        imp = turn_importance(m["content"], pair["content"] if pair else "")
        if imp >= HIGH:
            keep_old.append(m)
            if pair:
                keep_old.append(pair)
        else:
            dropped.append(m)
            if pair:
                dropped.append(pair)
        i += 2 if pair else 1
    kept = keep_old + kept                        # 高重要早轮 + 最近 K 轮
    new_notes = _llm_distill(dropped, provider)
    if new_notes is None:   # 回落规则蒸馏
        new_notes = "\n".join(_distill(m) for m in dropped if m["content"].strip())
    memo = (memo + "\n" + new_notes).strip()
    # memo 本身限长:保最近 4000 字符
    if len(memo) > 4000:
        memo = "…(更早备忘已截断)\n" + memo[-4000:]
    return kept, memo


def render_memo(memo: str) -> str:
    if not memo:
        return ""
    return ("# 会话决策备忘(早期轮次压缩而来,作为既定事实参考)\n" + memo)


# ---------------------------------------------------------------------------
# 3. @file 智能摘录
# ---------------------------------------------------------------------------

def _binary_note(path: Path, head: bytes) -> str | None:
    """二进制嗅探:PK(zip/xlsx 改名)、NUL 字节等 → 诚实说明,绝不把乱码注入上下文。"""
    if head[:4] == b"PK\x03\x04":
        return (f"<file path={path} 格式=zip/office>\n该文件是 ZIP 压缩格式"
                "(很可能是 xlsx/docx 改了扩展名)。不能当文本读;"
                "请先另存为真正的 CSV(UTF-8),或告知我用 shell 解压查看。\n</file>")
    if b"\x00" in head:
        return (f"<file path={path} 格式=二进制>\n检测到二进制内容,不注入乱码。"
                "若是数据文件请转成 CSV/文本后再引用。\n</file>")
    return None


def smart_excerpt(path: Path) -> str:
    """文件 → 上下文友好的摘录。CSV 给结构,PDF 抽正文,文本给头尾;二进制诚实拒绝。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_excerpt(path)
    try:
        head = path.open("rb").read(512)
    except OSError as exc:
        return f"<file path={path} error={exc}/>"
    note = _binary_note(path, head)    # 评审+实测修复:伪装成 .csv 的 zip 曾被读成乱码
    if note:
        return note
    try:
        if suffix in (".csv", ".tsv"):
            return _csv_excerpt(path)
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"<file path={path} error={exc}/>"
    if len(text) <= FILE_EXCERPT_CHARS:
        return f"<file path={path}>\n{text}\n</file>"
    head = text[: FILE_EXCERPT_CHARS // 2]
    tail = text[-FILE_EXCERPT_CHARS // 2:]
    return (f"<file path={path} chars={len(text)} excerpt=head+tail>\n"
            f"{head}\n…(中部省略 {len(text) - FILE_EXCERPT_CHARS} 字符,"
            f"需全文请用工具直接读)…\n{tail}\n</file>")


def _pdf_excerpt(path: Path) -> str:
    """PDF → 抽取正文摘录;抽不到则给诚实提示(绝不注入二进制乱码)。"""
    from psyclaw.pdf_extract import extract_pdf_text
    res = extract_pdf_text(path)
    if res["ok"]:
        return (f"<pdf path={path} 抽取={res['method']}>\n"
                f"{res['text']}\n</pdf>")
    return (f"<pdf path={path} 抽取失败>\n{res['note']}\n</pdf>")


CSV_FULL_CHARS = 4_096   # feat-102:小 CSV 全量注入阈值


def _csv_excerpt(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    # feat-102:小 CSV **全量注入**——第三轮评估实测 21 行 (~600B) 数据只给 5 行
    # 样例,模型明说「只能看到 5 行训练组样本」,后续统计全在半个数据集上打转。
    if len(raw) <= CSV_FULL_CHARS:
        n_rows = max(0, len([ln for ln in raw.splitlines() if ln.strip()]) - 1)
        return (f"<csv path={path} rows={n_rows} 全量注入>\n"
                f"{raw.rstrip()}\n</csv>")
    sniff = raw[:4096]
    try:
        dialect = _csv.Sniffer().sniff(sniff, delimiters=",\t;")
    except _csv.Error:
        dialect = _csv.excel
    reader = _csv.reader(io.StringIO(raw), dialect)
    rows = []
    for i, row in enumerate(reader):
        if i <= CSV_SAMPLE_ROWS:
            rows.append(row)
        else:
            pass
    n_rows = max(0, len([ln for ln in raw.splitlines() if ln.strip()]) - 1)  # 数据行数
    header = rows[0] if rows else []
    sample = rows[1:CSV_SAMPLE_ROWS + 1]
    # 粗略列类型
    types = []
    for ci in range(len(header)):
        vals = [r[ci] for r in sample if ci < len(r) and r[ci].strip()]
        if vals and all(_is_num(v) for v in vals):
            types.append("num")
        else:
            types.append("str")
    lines = [f"<csv path={path} rows≈{n_rows} cols={len(header)}>",
             "列: " + ", ".join(f"{h}({t})" for h, t in zip(header, types))]
    for r in sample[:5]:
        lines.append("  " + " | ".join(x[:18] for x in r))
    lines.append(f"(⚠ 已截断:仅样例 {min(5, len(sample))} 行 / 共 {n_rows} 行——"
                 "任何计数/统计都不要基于此样例,请用工具直接读全量)")
    lines.append("</csv>")
    return "\n".join(lines)


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
