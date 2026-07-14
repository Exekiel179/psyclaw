"""审稿模拟(Peer-Review Simulation)—— 多视角同行评审 + 回灌修复环。

对标 academic-research-skills:academic-paper-reviewer:让 provider 同时扮演
5 位独立评审(EIC 主编 + 3 位同行 R1/R2/R3 + Devil's Advocate),对产出稿做
结构化评审,产出:
  notes/review_panel.md   —— 人读的完整评审面板
  notes/review_panel.json —— 机器可解析结论(每位评审推荐 + 编辑决定 + 行动项)
  notes/response_letter.md —— 回应信骨架(R&R / revision-coach 用)

机器可判定的控制点(纯函数,fail-closed,可单测):
  parse_recommendations(text) -> 每位评审的 RECOMMENDATION(含是否同行)
  aggregate_decision(recs)    -> 编辑决定;保守规则:致命缺陷不可被平均成接收
  extract_action_items(text)  -> ## REQUIRED REVISIONS 的 [BLOCKING|MAJOR|MINOR]

设计与 loop.py 一致:解析不到推荐 → 不予接收(fail-closed),绝不靠关键词猜
"可能通过"。`--revise` 模式把 BLOCKING/MAJOR 项回灌 executor 修订并复审,
闭合「写作 → 评审 → 修复」回路。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

# 推荐等级,由轻到重(索引即严重度)。
RECOMMENDATIONS = ["ACCEPT", "MINOR", "MAJOR", "REJECT"]
_SEV = {r: i for i, r in enumerate(RECOMMENDATIONS)}
DECISION_PASS = "ACCEPT"  # 与 loop 的 VERDICT: PASS 对应:唯一"可发表"决定

# 行动项严重度,由重到轻。
SEVERITIES = ["BLOCKING", "MAJOR", "MINOR"]

_REC_RE = re.compile(
    r"RECOMMENDATION\s*[::]\s*([A-Za-z]+(?:\s+REVISION)?)", re.IGNORECASE)
# 评审标签识别:EIC/主编、R1/Reviewer 2/审稿人3、DA/Devil's Advocate/魔鬼代言人。
_LABEL_PATTERNS = [
    ("EIC", re.compile(r"\b(EIC|editor[\s-]*in[\s-]*chief)\b|主编", re.IGNORECASE)),
    ("DA", re.compile(r"devil'?s?\s*advocate|魔鬼代言人|\bDA\b", re.IGNORECASE)),
    ("R", re.compile(r"\b(?:R|reviewer\s*)(\d+)\b|(?:审稿人|评审)\s*(\d+)", re.IGNORECASE)),
]
# 修订清单章节标题(英文契约 + 中文兜底)。
_REVISIONS_HEADER = re.compile(
    r"^#{1,6}\s*(?:REQUIRED\s+REVISIONS|修订清单|必改项)", re.IGNORECASE)
_HEADER_RE = re.compile(r"^#{1,6}\s")
_BULLET_RE = re.compile(r"^\s*[-*]\s*(?:\[\s*([ xX])\s*\]\s*)?(.*)$")
_SEV_TAG_RE = re.compile(r"^\s*\[\s*(BLOCKING|MAJOR|MINOR)\s*\]\s*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 纯函数:机器可判定控制点(可单测,不依赖 LLM / IO)
# ---------------------------------------------------------------------------

def _normalize_rec(token: str) -> str:
    """把评审推荐 token 归一到 ACCEPT/MINOR/MAJOR/REJECT;无法识别返回 ''。"""
    t = token.upper()
    if "REJECT" in t:
        return "REJECT"
    if "ACCEPT" in t:
        return "ACCEPT"
    if "MAJOR" in t:
        return "MAJOR"
    if "MINOR" in t:
        return "MINOR"
    return ""


def _label_of(line: str) -> str | None:
    """从一行文本识别评审标签(EIC/DA/R<n>);识别不到返回 None。"""
    for name, pat in _LABEL_PATTERNS:
        m = pat.search(line)
        if m:
            if name == "R":
                num = next((g for g in m.groups() if g), "")
                return f"R{num}" if num else "R"
            return name
    return None


def _is_peer(label: str) -> bool:
    """同行评审 = R<n>;EIC(主编)综合、DA(魔鬼代言人)压力测试均不计入编辑决定的票数。"""
    return bool(re.fullmatch(r"R\d+", label or ""))


def parse_recommendations(text: str) -> list[dict]:
    """逐行解析每位评审的 RECOMMENDATION,关联到最近的评审标签。

    返回 [{reviewer, recommendation, is_peer}]。无法归一的推荐 token 跳过
    (fail-closed:宁可漏判为"无同行推荐"而触发保守决定,也不错认为 ACCEPT)。
    """
    out: list[dict] = []
    current: str | None = None
    auto_idx = 0
    for line in (text or "").splitlines():
        lab = _label_of(line)
        if lab is not None:
            current = lab
        m = _REC_RE.search(line)
        if not m:
            continue
        rec = _normalize_rec(m.group(1))
        if not rec:
            continue
        # 推荐行内若自带标签优先用之,否则用最近标签,再否则自动编号。
        label = _label_of(line) or current
        if label is None:
            auto_idx += 1
            label = f"R{auto_idx}"
        out.append({"reviewer": label, "recommendation": rec,
                    "is_peer": _is_peer(label)})
    return out


def aggregate_decision(recs: list[dict]) -> str:
    """从评审推荐计算编辑决定(保守 / fail-closed)。

    规则:
    - 仅**同行评审**(R<n>)进入票数平均;EIC 综合、DA 压力测试不计票
      (避免偏严的魔鬼代言人单方面主导决定)。
    - 无任何同行推荐 → 返回 MAJOR(不予接收,但可修订):非合规输出不能被当作通过。
    - ≥2 位同行判 REJECT → REJECT。
    - 否则按同行严重度均值映射:<.5 ACCEPT · <1.5 MINOR · <2.5 MAJOR · 否则 REJECT。
    - **致命缺陷不可被平均掉**:任一评审(含 DA)判 REJECT 时,决定至少为 MAJOR。
    """
    peers = [r for r in recs if r.get("is_peer")]
    if not peers:
        return "MAJOR"
    scores = [_SEV[p["recommendation"]] for p in peers]
    n_reject = sum(1 for p in peers if p["recommendation"] == "REJECT")
    if n_reject >= 2:
        return "REJECT"
    mean = sum(scores) / len(scores)
    if mean < 0.5:
        base = "ACCEPT"
    elif mean < 1.5:
        base = "MINOR"
    elif mean < 2.5:
        base = "MAJOR"
    else:
        base = "REJECT"
    if any(r["recommendation"] == "REJECT" for r in recs) and _SEV[base] < _SEV["MAJOR"]:
        base = "MAJOR"
    return base


def extract_action_items(text: str) -> list[dict]:
    """抽取 ## REQUIRED REVISIONS 章节里的复选框行动项。

    每项 {severity, text, done}。严重度由行首 [BLOCKING|MAJOR|MINOR] 决定,
    未标注 → MAJOR(fail-closed:默认当作需处理)。找不到章节时退回全文扫描
    带严重度标签的复选框行。
    """
    lines = (text or "").splitlines()
    items: list[dict] = []

    def _parse_bullet(raw: str) -> dict | None:
        bm = _BULLET_RE.match(raw)
        if not bm:
            return None
        done = (bm.group(1) or "").lower() == "x"
        body = bm.group(2).strip()
        sm = _SEV_TAG_RE.match(body)
        if sm:
            sev = sm.group(1).upper()
            body = body[sm.end():].strip()
        else:
            sev = "MAJOR"
        if not body:
            return None
        return {"severity": sev, "text": body, "done": done}

    # 优先:定位 REQUIRED REVISIONS 章节,只取其内的复选框直到下一个标题。
    in_section = False
    for line in lines:
        if _REVISIONS_HEADER.match(line):
            in_section = True
            continue
        if in_section and _HEADER_RE.match(line):
            break
        if in_section:
            it = _parse_bullet(line)
            if it:
                items.append(it)
    if items:
        return items

    # 兜底:全文扫描带严重度标签的复选框行。
    for line in lines:
        bm = _BULLET_RE.match(line)
        if not bm:
            continue
        if _SEV_TAG_RE.match((bm.group(2) or "").strip()):
            it = _parse_bullet(line)
            if it:
                items.append(it)
    return items


def blocking_items(items: list[dict]) -> list[dict]:
    """致命项(必须修复才能继续)。"""
    return [i for i in items if i.get("severity") == "BLOCKING"]


# ---------------------------------------------------------------------------
# 辩论式评审(feat-119):独立评审 → 交叉质证 → EIC 综合
# ---------------------------------------------------------------------------

# 评审档位:panel = 现状单次五 persona 生成(1 次调用/轮);
# debate = 独立评审 + 交叉质证 + EIC 综合(2×persona+1 = 9 次调用/轮)。
REVIEW_MODES = ("panel", "debate")

# 辩论档的四位评审(label, 职责描述;EIC 由综合阶段单独调用)。
DEBATE_PERSONAS = [
    ("R1", "方法学审稿人:聚焦设计与统计——抽样与功效、测量信效度、"
           "检验选择、效应量与置信区间、多重比较、因果断言是否越界"),
    ("R2", "理论/文献审稿人:聚焦理论贡献与文献定位——研究问题重要性、"
           "新意、与既有文献的对话是否充分、解释是否过度外推"),
    ("R3", "可复现性/透明审稿人:聚焦开放科学——数据与代码可得性、"
           "预注册与探索/确证区分、剔除规则与缺失数据处理、JARS 报告完整性"),
    ("DA", "Devil's Advocate 魔鬼代言人:刻意找致命缺陷——替代解释、"
           "混淆变量、统计陷阱;判断偏严,仅作压力测试不直接决定结论"),
]

_REC_CONTRACT = ("末尾**单独一行、行首**给出机器可解析的推荐:"
                 "`RECOMMENDATION: ACCEPT|MINOR|MAJOR|REJECT`。"
                 "不按格式输出会被系统按保守决定处理。")


def last_recommendation(text: str) -> str:
    """取一段文本(单个评审块)内**最后一个可归一**的 RECOMMENDATION。

    没有 → 返回 ''(fail-closed:该评审不计票,同行不足自然触发保守决定)。
    无法归一的 token 跳过,回落上一个可归一推荐——绝不猜。
    """
    rec = ""
    for m in _REC_RE.finditer(text or ""):
        r = _normalize_rec(m.group(1))
        if r:
            rec = r
    return rec


def debate_summary(blocks: dict, eic_text: str) -> dict:
    """由各评审最终块 + EIC 综合块生成结构化结论(与 summarize 同形)。

    与单次生成的 parse_recommendations 不同:每位评审的推荐取自**自己的块**
    (块内提及其他评审标签不会改推荐归属);行动项取自 EIC 综合块。
    聚合仍走 aggregate_decision(保守规则原样:致命缺陷不可被平均掉)。
    """
    recs: list[dict] = []
    for label, text in blocks.items():
        rec = last_recommendation(text)
        if rec:
            recs.append({"reviewer": label, "recommendation": rec,
                         "is_peer": _is_peer(label)})
    eic_rec = last_recommendation(eic_text)
    if eic_rec:
        recs.append({"reviewer": "EIC", "recommendation": eic_rec,
                     "is_peer": False})
    items = extract_action_items(eic_text)
    decision = aggregate_decision(recs)
    return {
        "decision": decision,
        "passed": decision == DECISION_PASS,
        "recommendations": recs,
        "n_peer_reviews": sum(1 for r in recs if r["is_peer"]),
        "action_items": items,
        "n_blocking": len(blocking_items(items)),
        "n_major": sum(1 for i in items if i["severity"] == "MAJOR"),
        "n_minor": sum(1 for i in items if i["severity"] == "MINOR"),
    }


def _persona_task(label: str, desc: str, rnd: int) -> str:
    return (f"你在本次评审中**只扮演一位评审:{label}({desc})**。"
            f"对下方研究稿做第 {rnd} 轮**独立**评审——你看不到其他评审的意见,"
            "只依据稿件本身与你的专长给出:简评 / 优点 / 问题(按严重度)。"
            + _REC_CONTRACT)


def _rebuttal_task(label: str, desc: str, rnd: int) -> str:
    return (f"你是评审 {label}({desc}),第 {rnd} 轮交叉质证阶段。"
            "下方附有其他评审的独立意见与你自己的独立意见:逐条审视——"
            "同意的吸收,不同意的**点名反驳并给出理由**;然后基于质证结果"
            "输出你的**最终**意见(可以维持,也可以修正;修正要说明被谁的"
            "哪条论据说服)。" + _REC_CONTRACT)


def _eic_task(rnd: int) -> str:
    return (f"你是主编(EIC),第 {rnd} 轮综合阶段。下方是四位评审经交叉质证"
            "后的最终意见:给出编辑层面的叙述性综合(分歧点如何裁决、以谁的"
            "论据为准),然后输出 `## REQUIRED REVISIONS` 复选框清单,每条"
            "**行首**标 `[BLOCKING]`/`[MAJOR]`/`[MINOR]`。" + _REC_CONTRACT)


def _debate_round(provider, draft_text: str, rnd: int,
                  project: Path) -> tuple[str, dict]:
    """跑一轮辩论式评审,返回 (面板文本, 结构化结论)。

    调用量 2×len(DEBATE_PERSONAS)+1(默认 9);任何一位评审生成失败
    (_gen 返回错误占位文本)都解析不出推荐 → 不计票,保守规则兜底。
    """
    from psyclaw.loop import _gen

    opinions: dict[str, str] = {}
    for label, desc in DEBATE_PERSONAS:
        opinions[label] = _gen(provider, "reviewer",
                               _persona_task(label, desc, rnd),
                               f"# 待审稿件\n{draft_text}")
    finals: dict[str, str] = {}
    for label, desc in DEBATE_PERSONAS:
        others = "\n\n".join(f"### {lb} 的独立意见\n{tx}"
                             for lb, tx in opinions.items() if lb != label)
        finals[label] = _gen(provider, "reviewer",
                             _rebuttal_task(label, desc, rnd),
                             f"# 待审稿件\n{draft_text}\n\n"
                             f"# 其他评审的独立意见\n{others}\n\n"
                             f"# 你({label})的独立意见\n{opinions[label]}")
    finals_md = "\n\n".join(f"### {lb}\n{tx}" for lb, tx in finals.items())
    eic = _gen(provider, "reviewer", _eic_task(rnd),
               f"# 待审稿件\n{draft_text}\n\n"
               f"# 四位评审经交叉质证后的最终意见\n{finals_md}")

    summary = debate_summary(finals, eic)

    parts = [f"# 评审面板(辩论档 · 第 {rnd} 轮)", ""]
    for label, desc in DEBATE_PERSONAS:
        parts += [f"### {label} {desc.split(':', 1)[0]}",
                  finals[label].strip(), ""]
    parts += ["### EIC 主编(综合)", eic.strip(), ""]
    panel = "\n".join(parts)

    t = [f"# 辩论式评审过程 · 第 {rnd} 轮", "",
         "## 第一阶段:独立评审(互相不可见)", ""]
    for label, _desc in DEBATE_PERSONAS:
        t += [f"### {label}", opinions[label].strip(), ""]
    t += ["## 第二阶段:交叉质证(可见他人意见后的最终立场)", ""]
    for label, _desc in DEBATE_PERSONAS:
        t += [f"### {label}", finals[label].strip(), ""]
    t += ["## 第三阶段:EIC 综合", "", eic.strip(), ""]
    (project / "notes" / "review_debate.md").write_text(
        "\n".join(t), encoding="utf-8")

    return panel, summary


def _resolve_mode(mode: str | None, conf: dict) -> str:
    """档位选择:显式 mode 参数 > 配置 review_mode > 默认 panel;未知值回落 panel。"""
    m = str(mode or conf.get("review_mode") or "panel").strip().lower()
    return m if m in REVIEW_MODES else "panel"


def summarize(panel_text: str) -> dict:
    """把一段评审面板文本汇总成结构化结论(供 JSON 落盘 / 程序判定)。"""
    recs = parse_recommendations(panel_text)
    items = extract_action_items(panel_text)
    decision = aggregate_decision(recs)
    return {
        "decision": decision,
        "passed": decision == DECISION_PASS,
        "recommendations": recs,
        "n_peer_reviews": sum(1 for r in recs if r["is_peer"]),
        "action_items": items,
        "n_blocking": len(blocking_items(items)),
        "n_major": sum(1 for i in items if i["severity"] == "MAJOR"),
        "n_minor": sum(1 for i in items if i["severity"] == "MINOR"),
    }


def response_letter_skeleton(items: list[dict]) -> str:
    """据行动项生成回应信(Response to Reviewers)骨架,逐条留待人工填写。"""
    out = ["# 回应信骨架(Response to Reviewers)", "",
           "> 每条对应一项评审意见。修订后在 Response 行写明「改了什么 + 位置」。", ""]
    if not items:
        out.append("（评审未给出可抽取的行动项;请人工核对 notes/review_panel.md。）")
        return "\n".join(out) + "\n"
    order = {"BLOCKING": 0, "MAJOR": 1, "MINOR": 2}
    for i, it in enumerate(sorted(items, key=lambda x: order.get(x["severity"], 9)), 1):
        out += [f"## Comment {i} [{it['severity']}]",
                f"- Reviewer point: {it['text']}",
                "- Response: [待填写：如何处理 / 为何不处理]",
                "- Change location: [稿件中的位置]", ""]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# 编排:跑评审 + 可选回灌修复环(依赖 provider / IO)
# ---------------------------------------------------------------------------

def _resolve_draft(project: Path, draft: str | None) -> Path | None:
    """定位待审稿件:显式路径 > outputs/report.md > notes/step1_outline.md。"""
    if draft:
        p = Path(draft)
        return p if p.exists() else None
    for cand in ("outputs/report.md", "notes/step1_outline.md", "outputs/draft.md"):
        p = project / cand
        if p.exists():
            return p
    return None


def _review_task(round_no: int) -> str:
    return (
        f"对下方研究稿做第 {round_no} 轮多视角同行评审。严格按 reviewer 角色约定的"
        "输出格式:R1/R2/R3/DA/EIC 各一个区块,每个区块末尾**单独一行**给出 "
        "`RECOMMENDATION: ACCEPT|MINOR|MAJOR|REJECT`;最后输出 `## REQUIRED REVISIONS` "
        "复选框清单,每条**行首**标 `[BLOCKING]`/`[MAJOR]`/`[MINOR]`。"
        "不合格式的输出会被系统按保守决定(不予接收)处理。")


def run_review(draft: str | None = None, project_dir: str = ".",
               auto: bool = False, revise: bool = False,
               rounds: int = 3, mode: str | None = None) -> int:
    """跑审稿模拟。revise=True 时把 BLOCKING/MAJOR 回灌 executor 修订并复审。

    mode 档位(None → 配置 review_mode → panel):
      panel  快评:单次生成五 persona 面板(1 次调用/轮,现状行为);
      debate 深评:R1/R2/R3/DA 独立评审 → 交叉质证 → EIC 综合
             (9 次调用/轮,评审推荐按块归属,防单次生成的锚定与附和)。

    返回:plain 模式恒 0(评审本身即产物);revise 模式若达最大轮次仍未到 ACCEPT
    返回 1(与 run_loop 的「修复环不收敛即停」一致)。
    """
    from psyclaw import config as cfg, ui
    from psyclaw.loop import _gen, _log, _ask_yn, _role_providers

    project = Path(project_dir)
    (project / "notes").mkdir(parents=True, exist_ok=True)
    src = _resolve_draft(project, draft)
    if src is None:
        print(ui.err("找不到待审稿件:psyclaw review <draft.md>,"
                     "或先跑 research 回路产出 outputs/report.md。"))
        return 1
    draft_text = src.read_text(encoding="utf-8", errors="replace")
    if not draft_text.strip():
        print(ui.err(f"稿件为空:{src}"))
        return 1

    conf = cfg.load_config()
    mode = _resolve_mode(mode, conf)
    prov = _role_providers(conf, ("reviewer", "executor"))
    provider = prov["reviewer"]
    mode_note = ("辩论档:独立评审→交叉质证→EIC 综合,"
                 f"每轮 {2 * len(DEBATE_PERSONAS) + 1} 次调用"
                 if mode == "debate" else "快评档:单次面板,每轮 1 次调用")
    print(ui.panel("Review — 审稿模拟(EIC + R1/R2/R3 + Devil's Advocate)",
                   f"稿件:{src}（{len(draft_text)} 字符）\n"
                   f"provider:{provider.name} · {mode_note}"))
    _log(project, f"review start · src={src.name} · provider={provider.name}"
                  f" · mode={mode}")

    summary: dict = {}
    current = draft_text
    max_rounds = max(1, rounds) if revise else 1
    for rnd in range(1, max_rounds + 1):
        if mode == "debate":
            panel, summary = _debate_round(provider, current, rnd, project)
        else:
            panel = _gen(provider, "reviewer", _review_task(rnd),
                         f"# 待审稿件\n{current}")
            summary = summarize(panel)
        summary["mode"] = mode
        (project / "notes" / "review_panel.md").write_text(panel, encoding="utf-8")
        (project / "notes" / "review_panel.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (project / "notes" / "response_letter.md").write_text(
            response_letter_skeleton(summary["action_items"]), encoding="utf-8")
        _log(project, f"review 第{rnd}轮 → 决定={summary['decision']} "
                      f"(同行{summary['n_peer_reviews']} · BLOCKING{summary['n_blocking']})")
        print(ui.panel(
            f"评审面板 第 {rnd} 轮 · 编辑决定:{summary['decision']}",
            f"同行评审 {summary['n_peer_reviews']} 位 · "
            f"BLOCKING {summary['n_blocking']} · MAJOR {summary['n_major']} · "
            f"MINOR {summary['n_minor']}\n\n"
            + panel[:900] + ("…" if len(panel) > 900 else "")))

        if summary["passed"]:
            print(ui.ok(f"✓ 第 {rnd} 轮:编辑决定 ACCEPT,评审通过。"))
            break
        if not revise:
            break
        if rnd >= max_rounds:
            print(ui.err(f"  达最大修订轮次({max_rounds})仍未到 ACCEPT"
                         f"(当前 {summary['decision']}),停止并交人工。"))
            _print_artifacts(project, ui)
            return 1
        # —— 回灌修复环:executor 针对 BLOCKING/MAJOR 修订,产出完整新稿 ——
        todo = [i for i in summary["action_items"]
                if i["severity"] in ("BLOCKING", "MAJOR")]
        todo_md = "\n".join(f"- [{i['severity']}] {i['text']}" for i in todo) \
            or "(评审未给出 BLOCKING/MAJOR 行动项;按面板叙述意见整体修订。)"
        print(ui.warn(f"  第 {rnd} 轮 {summary['decision']},executor 修订 "
                      f"{len(todo)} 条后复审…"))
        if not auto and not _ask_yn("进入修订并复审?"):
            print(ui.dim("已停在评审阶段。评审产物已落盘。"))
            break
        panel_text = (project / "notes" / "review_panel.md").read_text(encoding="utf-8")
        current = _gen(prov["executor"], "executor",
                       "按下列评审意见修订研究稿,只改被指出的问题,其余保持不变;"
                       "输出修订后的**完整稿件**(全文替换,不要引用或附加旧稿)。",
                       f"# 评审行动项(BLOCKING/MAJOR)\n{todo_md}\n\n"
                       f"# 完整评审面板\n{panel_text}\n\n"
                       f"# 当前稿件\n{current}")
        (project / "notes" / "revised_draft.md").write_text(current, encoding="utf-8")
        _log(project, f"executor 修订 → notes/revised_draft.md(第{rnd}轮后)")

    _print_artifacts(project, ui)
    return 0


def _print_artifacts(project: Path, ui) -> None:
    print(ui.ok("\n评审产物:"))
    for f in ("notes/review_panel.md", "notes/review_panel.json",
              "notes/response_letter.md", "notes/revised_draft.md"):
        p = project / f
        if p.exists():
            print(f"    {p}")


def review_cli(argv: list[str]) -> int:
    """供 cli.py / repl.py 调用的薄入口:
    review <draft> [--revise] [--auto] [--rounds N] [--debate | --mode panel|debate]。"""
    draft = None
    revise = auto = False
    rounds = 3
    mode: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--revise", "-r"):
            revise = True
        elif a == "--auto":
            auto = True
        elif a == "--debate":
            mode = "debate"
        elif a == "--mode":
            i += 1
            try:
                mode = argv[i]
            except IndexError:
                mode = None
        elif a == "--rounds":
            i += 1
            try:
                rounds = int(argv[i])
            except (IndexError, ValueError):
                rounds = 3
        elif not a.startswith("-"):
            draft = a
        i += 1
    return run_review(draft=draft, revise=revise, auto=auto, rounds=rounds,
                      mode=mode)
