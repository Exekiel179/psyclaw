"""研究澄清协议(grill-me 式)— 正式研究前置检查的实现。

原则:**不澄清完,不开工**。
- 17 个研究准备项覆盖:研究问题/变量/抽样/设计/假设与分析/伦理与开放科学
- 交互模式逐题问询(一次一题,带"为什么重要"和推荐默认),REPL 中由 LLM 自然追问
- 产出 notes/clarification.md(研究准备清单):机器可校验,任何研究准备项 unresolved
  → 前置检查 CLARIFY.complete 未通过,/research 暂不启动
- 完成的研究准备清单同时喂给记忆系统(决策惯性学习)
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# (id, 分组, 问题, 为什么重要, 推荐/示例)
SLOTS: list = [
    ("research_question", "A.问题与理论", "用一句可检验的话说出研究问题(谁/什么关系/什么条件)?",
     "问题模糊则后面全部白做;'探究X与Y的关系'不够,要能推出统计假设",
     "示例:大学生群体中,正念干预(vs 等待组)能否降低 4 周后的焦虑水平?"),
    ("theory_base", "A.问题与理论", "依托什么理论框架?有没有竞争理论给出不同预测?",
     "有竞争预测的研究比'验证显而易见'的研究贡献大一个量级",
     "写明理论名+关键文献;没有理论就承认是描述性/探索性"),
    ("novelty", "A.问题与理论", "相对已有文献,增量贡献是什么(新关系/新边界条件/新人群/方法改进)?",
     "审稿人第一问;'前人没做过'本身不是贡献",
     "用一句话:本研究首次检验了___在___条件下的___"),
    ("iv", "B.变量与测量", "自变量是什么?实验操纵还是测量?如何操作化?",
     "操纵→可谈因果;测量→只能谈关联,写作时态完全不同",
     "操纵要附操纵检查计划;测量要附工具与信度证据"),
    ("dv", "B.变量与测量", "因变量用什么工具测?该工具在你的人群中有信效度证据吗?",
     "工具不行全盘皆输;信度上限锁死了可观测的效应量",
     "量表名+版本+条目数+目标人群信度文献(psyclaw scale 可查)"),
    ("covariates", "B.变量与测量", "纳入哪些协变量?每个的纳入依据是什么?",
     "乱放协变量=研究者自由度;协变量必须有先验理由",
     "逐个写'纳入因为文献X表明它与DV相关且与IV相关'"),
    ("population", "C.总体与抽样", "目标总体是谁?实际抽样框是什么?两者差距多大?",
     "大学生样本推断'人类'是最常见的外推越界",
     "写明:目标总体/抽样方式/预期代表性局限"),
    ("exclusion", "C.总体与抽样", "纳入/排除标准是什么?(先验声明,含草率作答处理)",
     "事后排除=p-hacking 高发区;必须先说清楚",
     "建议直接引用 psyclaw screen 的指标与阈值,写进预注册"),
    ("design_type", "D.设计", "什么设计类型?(被试间/内/混合/纵向/ESM…)为什么是它?",
     "设计定了,分析、功效、效度威胁全跟着定",
     "psyclaw design 查目录;每个备选设计的取舍写一句"),
    ("randomization", "D.设计", "随机化/抵消平衡方案具体怎么做?",
     "'随机分组'四个字不够:怎么生成序列?谁分配?盲不盲?",
     "被试内必答抵消平衡(拉丁方?);被试间答序列生成+分配隐藏"),
    ("hypotheses", "E.假设与分析", "逐条列出假设,每条标注[确证性]或[探索性]?",
     "确证/探索的区分是预注册的灵魂;事后改标=HARKing",
     "H1[确证]:…;H2[确证]:…;RQ1[探索]:…"),
    ("effect_expectation", "E.假设与分析", "预期效应量多大?依据是什么(元分析/相似研究/最小关注效应)?",
     "凭感觉猜'中等效应'是功效分析失败的头号原因;文献效应量还普遍被发表偏倚高估",
     "心理学现实先验:r≈.20/d≈.40(Richard et al., 2003);引用 psyclaw cite power_priors"),
    ("power", "E.假设与分析", "功效分析结果:多大 N?按哪个效应算的(交互要按交互算)?",
     "样本量没有先验依据→DESIGN.power 质量检查未通过",
     "写明:检验类型/α/功效/效应量/所得N/流失余量"),
    ("analysis_plan", "E.假设与分析", "每条假设对应什么检验?前提假设违反时的预案是什么?",
     "分析计划先于数据=确证;数据到手再选=探索",
     "逐假设映射(psyclaw assume 查前提);写明稳健替代预案"),
    ("ethics", "F.伦理与开放科学", "伦理审查状态?有敏感测量(自伤/创伤)时的应对流程?",
     "PHQ-9 条目9 这类条目必须有危机转介预案",
     "IRB 批号或豁免依据;敏感条目处理流程"),
    ("prereg", "F.伦理与开放科学", "在哪预注册(OSF/AsPredicted)?何时(数据收集前)?",
     "确证性结论的资格证;不预注册就全部标探索",
     "平台+计划时间;模板可由 /preregister 生成"),
    ("data_sharing", "F.伦理与开放科学", "数据/代码/材料共享计划?",
     "越来越多期刊强制;提前规划匿名化方案",
     "OSF 仓库;写明哪些能开放、哪些因隐私不能及理由"),
]

CARD_NAME = "clarification.md"


# ---------------------------------------------------------------------------
# CLAR-1：LLM 驱动追问 —— 对空泛回答评估并生成针对性追问
#   评估标准取自各研究准备项的 `why`（重要性）。无 provider / mock / 异常 → fail-safe
#   降级为「照单收集」（视为 PASS，绝不卡住用户）。
# ---------------------------------------------------------------------------

# 冒号类含 ASCII ':' 与全角 '：'(U+FF1A);用显式转义避免编辑器归一化歧义
_COLON = "[:：]"
_EVAL_RE = re.compile("(?im)^\\s*CLARIFY_VERDICT\\s*" + _COLON + "\\s*(PASS|PROBE)")
_FOLLOWUP_RE = re.compile("(?im)^\\s*FOLLOWUP\\s*" + _COLON + "\\s*(.+)$")


def _build_eval_prompt(slot, answer: str) -> str:
    _sid, _group, q, why, _hint = slot
    return (
        "判断研究者对下面澄清问题的回答是否【足够具体、可检验】。\n\n"
        f"问题：{q}\n"
        f"评估标准（此槽为何重要）：{why}\n"
        f"研究者回答：{answer}\n\n"
        "判据：能据此推出统计假设 / 操作化 / 可复现设计 → 足够；"
        "空泛、缺关键信息（对象/工具/数值/操作化）→ 不够。\n"
        "只输出以下标记行，不要寒暄、不要解释：\n"
        "CLARIFY_VERDICT: PASS\n"
        "或\n"
        "CLARIFY_VERDICT: PROBE\n"
        "FOLLOWUP: <一句针对性追问，点明缺什么、该怎么补>"
    )


def _ask_provider(provider, task: str) -> str:
    """调 provider 取整段文本；任何异常 fail-safe 视为通过（PASS）。"""
    sysmsg = "你是严格的研究方法学审稿人，只按要求的标记行输出。"
    try:
        return "".join(provider.chat([{"role": "user", "content": task}], system=sysmsg))
    except Exception:  # noqa: BLE001
        return "CLARIFY_VERDICT: PASS"


def _parse_eval(text: str) -> tuple[str, str]:
    """解析评估结果。fail-safe：解析不到裁决 → PASS（不卡用户）。取最后一个裁决。"""
    verdict = "PASS"
    for m in _EVAL_RE.finditer(text or ""):
        verdict = m.group(1).upper()
    fm = _FOLLOWUP_RE.search(text or "")
    followup = fm.group(1).strip() if fm else ""
    return verdict, followup


def evaluate_answer(provider, slot, answer: str) -> dict:
    """评估单个回答。返回 {verdict: PASS|PROBE|SKIP, followup}。空回答 → SKIP。"""
    if not (answer or "").strip():
        return {"verdict": "SKIP", "followup": ""}
    verdict, followup = _parse_eval(_ask_provider(provider, _build_eval_prompt(slot, answer)))
    if verdict == "PROBE" and not followup:
        followup = "请把回答说得更具体、可检验（点明对象/变量/工具/操作化/数值）。"
    return {"verdict": verdict, "followup": followup}


def clarify_one(provider, slot, ask, max_probes: int = 2,
                out=print, probing: bool = True) -> dict:
    """澄清单个研究准备项（含 `?` 看缘由 / `skip` 跳过 / LLM 追问环）。

    ask(prompt)->str 为输入回调（便于测试/非 TTY 注入）。
    返回 {answer, rounds, resolved}。probing=False 时退化为一问一答（不追问）。
    """
    _sid, _group, q, why, hint = slot
    ans = ask(f"\n▶ {q}\n  ({hint})\n  > ")
    while (ans or "").strip() == "?":
        out(f"  ※ 为什么重要：{why}")
        ans = ask("  > ")
    ans = (ans or "").strip()
    if ans.lower() in ("skip", ""):
        return {"answer": "", "rounds": 0, "resolved": False}

    rounds = 0
    while probing and rounds < max_probes:
        ev = evaluate_answer(provider, slot, ans)
        if ev["verdict"] != "PROBE":
            break
        out(f"  ↪ 追问[{rounds + 1}/{max_probes}]：{ev['followup']}")
        more = (ask("  > ") or "").strip()
        rounds += 1
        if more.lower() in ("skip", ""):
            break
        ans = f"{ans}；{more}"
    return {"answer": ans, "rounds": rounds, "resolved": True}


def _default_ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "skip"


def run_clarify_interactive(project_dir: str | Path = ".", provider=None,
                            ask=None, max_probes: int = 2) -> int:
    """交互式澄清问询（一次一题；`?` 看缘由；`skip` 留空=未解决）。

    配置了真实 provider 时启用 LLM 追问（空泛回答最多追问 max_probes 轮）；
    无 provider / mock / 异常时 fail-safe 降级为照单收集。
    provider/ask 可注入便于测试。
    """
    if provider is None:
        try:
            from psyclaw import config as cfg
            from psyclaw.providers import get_provider
            provider = get_provider(cfg.load_config())
        except Exception:  # noqa: BLE001
            provider = None
    probing = provider is not None and getattr(provider, "name", "mock") != "mock"
    if ask is None:
        ask = _default_ask

    answers: dict = {}
    probe_rounds: dict = {}
    print("PsyClaw 研究澄清(grill-me 式) — 不澄清完不开工")
    print("=" * 56)
    if probing:
        print(f"已启用 LLM 追问：空泛回答最多追问 {max_probes} 轮；? 看缘由；skip 跳过。")
    else:
        print("未配真实 provider，降级为照单收集（配 provider 后启用 LLM 追问）；? 看缘由；skip 跳过。")

    cur_group = None
    total = len(SLOTS)
    for idx, slot in enumerate(SLOTS, 1):
        sid, group = slot[0], slot[1]
        if group != cur_group:
            cur_group = group
            print(f"\n── [{idx}/{total}] {group} " + "─" * max(0, 44 - len(group)))
        r = clarify_one(provider, slot, ask, max_probes=max_probes, probing=probing)
        answers[sid] = r["answer"]
        probe_rounds[sid] = r["rounds"]

    path = write_card(answers, project_dir)
    unresolved = [sid for sid, *_ in SLOTS if not answers.get(sid)]
    print(f"\n研究准备清单已写入 {path}")
    probed = sum(1 for v in probe_rounds.values() if v)
    if probing and probed:
        print(f"  （LLM 对 {probed} 个研究准备项进行了追问，以提高可检验性）")
    if unresolved:
        print(f"⚠ 未完成的研究准备项有 {len(unresolved)} 个：{', '.join(unresolved)}")
        print("  前置检查 CLARIFY.complete 未通过，正式研究流程暂不启动。继续填写：psyclaw prepare")
        return 1
    print("✓ 全部研究准备项已完成，可以开始正式研究流程。")
    return 0


def write_card(answers: dict, project_dir: str | Path = ".") -> Path:
    notes = Path(project_dir) / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    path = notes / CARD_NAME
    lines = [
        "# 研究准备清单(Research Preparation Checklist)",
        f"date: {date.today().isoformat()}",
        "",
        "| 研究准备项 | 状态 | 内容 |",
        "|------|------|------|",
    ]
    for sid, group, q, _why, _hint in SLOTS:
        val = (answers.get(sid) or "").replace("|", "\\|").replace("\n", " ")
        status = "resolved" if val else "UNRESOLVED"
        lines.append(f"| {sid} | {status} | {val} |")
    lines += ["", "> 规则:存在 UNRESOLVED 研究准备项时，前置检查 CLARIFY.complete 未通过，/research 暂不启动。"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def check_card(project_dir: str | Path = ".") -> dict:
    """供前置检查调用:返回 {exists, total, resolved, unresolved:[...]}"""
    path = Path(project_dir) / "notes" / CARD_NAME
    if not path.exists():
        return {"exists": False, "total": len(SLOTS), "resolved": 0,
                "unresolved": [s[0] for s in SLOTS]}
    text = path.read_text(encoding="utf-8")
    unresolved = []
    resolved = 0
    for sid, *_ in SLOTS:
        if f"| {sid} | resolved |" in text:
            resolved += 1
        else:
            unresolved.append(sid)
    return {"exists": True, "total": len(SLOTS),
            "resolved": resolved, "unresolved": unresolved}


def print_clarify_status(project_dir: str | Path = ".") -> int:
    r = check_card(project_dir)
    if not r["exists"]:
        print("  尚无研究准备清单。运行 psyclaw prepare 开始(notes/clarification.md)。")
        return 1
    print(f"  澄清进度:{r['resolved']}/{r['total']}")
    if r["unresolved"]:
        print(f"  未解决:{', '.join(r['unresolved'])}")
        print("  → CLARIFY.complete 阻断中")
        return 1
    print("  ✓ 全部研究准备项已完成")
    return 0
