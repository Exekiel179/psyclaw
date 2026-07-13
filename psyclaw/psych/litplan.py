"""检索计划包(feat-103)——把「浏览器桥接文献检索」方法论产品化。

源自用户提供的《Claude + Kimi WebBridge 文献综述教学文档》:知网/万方/WoS 等
机构库没有公开 API,须经浏览器(登录学校代理)人机协作检索。psyclaw 自身
**不驱动浏览器**,但把这套流程沉淀为可复用的**检索计划包**:

① 中英布尔检索式(同义词 OR 块 × AND;provider 可用时定制,否则给模板骨架);
② 数据库路线:公开 API(``psyclaw lit`` 直检 OpenAlex/EuropePMC/arXiv)+
   机构库(浏览器桥接分步提示词,内嵌教学文档的六条纪律:一次一件事/给标准
   不给感觉/指定输出格式/明确禁止项/长输出写文件/卡住换思路);
③ 显式纳入/排除标准(编号列出,**检索前预先声明**——落 sidecar,防事后改
   标准挑结果,呼应 I.posthoc_exclusion 的诚信口径)。

产物:``notes/search_plan.md`` + ``notes/screening_criteria.json``(+ md)。
纯函数可单测;LLM 仅用于定制同义词/标准,失败回落模板,绝不阻塞。
"""

from __future__ import annotations

import json
from pathlib import Path

# 浏览器桥接分步提示词(逐步,每步可直接粘给带浏览器能力的 agent)
_BRIDGE_STEPS = [
    ("打开机构电子资源库",
     "使用浏览器桥接(如 Kimi WebBridge / 浏览器 MCP)打开我机构的电子资源库页面:"
     "<你的图书馆代理地址>。如果需要登录,我手动完成,登录后请继续。"),
    ("进入数据库",
     "请进入「中国知网」(或万方 / Web of Science / Google Scholar)。"
     "如果主页搜索按钮点击没跳转,请查看页面 form action,找到真实搜索 URL 直接跳转。"),
    ("输入检索式",
     "请在当前数据库中搜索下面的检索式(中文库用中文式,英文库用英文式),"
     "并优先筛选心理学、教育学、医学或社会科学相关结果。"),
    ("提取结果页信息(读当前页,不猜测)",
     "请读取当前结果页中**可见**的文献信息,提取:标题、作者、年份、来源、关键词、"
     "摘要、链接,整理成表格。页面上没有显示的项标注「未显示」,**不要猜测**。"
     "翻页继续提取,直到累计 {n_target} 条。"),
    ("保存检索结果(长输出写文件,别占上下文)",
     "把上面的文献表格写到文件 notes/bridge_results.md(Markdown 表格,"
     "字段:标题|作者|年份|来源|关键词|摘要|链接)。之后我会用 psyclaw 导入并生成文献矩阵。"),
]


def build_boolean_query(topic: str, synonyms_zh: list[str] | None = None,
                        synonyms_en: list[str] | None = None) -> dict:
    """主题 → 中英布尔检索式。纯函数:给定同义词就拼装,否则输出模板骨架。"""
    topic = (topic or "").strip()
    if synonyms_zh:
        zh = "(" + " OR ".join(f'"{s}"' for s in synonyms_zh) + ")"
        zh_domain = ' AND ("心理" OR "心理咨询" OR "心理治疗" OR "心理健康")'
    else:                               # 模板骨架:占位符提醒用户补词,不假装完整
        zh = f'("{topic}" OR "<同义词1>" OR "<同义词2>")'
        zh_domain = ' AND ("心理" OR "心理咨询" OR "心理治疗" OR "<限定域>")'
    if synonyms_en:
        en = "(" + " OR ".join(f'"{s}"' for s in synonyms_en) + ")"
        en_domain = ' AND ("psycholog*" OR "mental health" OR "counseling")'
    else:
        en = '("<english term>" OR "<synonym 1>" OR "<synonym 2>")'
        en_domain = ' AND ("psycholog*" OR "mental health" OR "<domain term>")'
    return {
        "topic": topic,
        "query_zh": zh + zh_domain,
        "query_en": en + en_domain,
    }


def default_criteria(topic: str) -> dict:
    """显式纳入/排除标准模板(编号;检索前声明,防事后改标准)。"""
    return {
        "topic": topic,
        "inclusion": [
            f"与「{topic}」的核心构念直接相关",
            "心理学/教育/医学/社会科学场景(理论、系统开发、应用或干预研究均可)",
            "提供可提取的研究信息(对象/方法/发现至少可判断其一)",
        ],
        "exclusion": [
            "仅涉及无关领域的同名概念(如工程展示/军事仿真等)",
            "与心理学或目标构念无实质关联",
            "信息过少,无法判断研究内容",
        ],
        "note": "标准在检索前声明;筛选时只输出「标题、纳入/排除、理由」,不改标准。",
    }


def _llm_customize(topic: str, provider) -> tuple[dict, dict] | None:
    """provider 可用时定制同义词与标准;任何失败回落模板(绝不阻塞)。"""
    if provider is None or not getattr(provider, "api_key", ""):
        return None
    from psyclaw.loop import _gen
    task = (
        "为下面的文献综述主题输出 JSON(不要任何其他文字):"
        '{"synonyms_zh": [3-6 个中文同义/近义检索词], "synonyms_en": [3-6 个英文检索词], '
        '"inclusion": [3-5 条编号纳入标准], "exclusion": [3 条排除标准]}。'
        "检索词要覆盖概念变体(全称/简称/相邻译名),标准要可机械执行。")
    try:
        raw = _gen(provider, "planner", task, f"# 主题\n{topic}")
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
        q = build_boolean_query(topic, data.get("synonyms_zh") or None,
                                data.get("synonyms_en") or None)
        crit = default_criteria(topic)
        if data.get("inclusion"):
            crit["inclusion"] = [str(x) for x in data["inclusion"]][:6]
        if data.get("exclusion"):
            crit["exclusion"] = [str(x) for x in data["exclusion"]][:6]
        return q, crit
    except Exception:  # noqa: BLE001  # LLM 定制失败 → 模板兜底
        return None


def build_search_plan(topic: str, provider=None, n_target: int = 20) -> dict:
    """组装检索计划(纯数据):检索式 + 公开 API 路线 + 桥接分步 + 标准。"""
    custom = _llm_customize(topic, provider)
    if custom:
        query, criteria = custom
    else:
        query, criteria = build_boolean_query(topic), default_criteria(topic)
    steps = [{"title": t, "prompt": p.replace("{n_target}", str(n_target))}
             for t, p in _BRIDGE_STEPS]
    return {
        "topic": topic,
        "n_target": n_target,
        "query": query,
        "public_api": f'psyclaw lit "{query["query_en"]}" --limit {n_target}',
        "bridge_steps": steps,
        "criteria": criteria,
        "llm_customized": bool(custom),
    }


def render_search_plan_md(plan: dict) -> str:
    q = plan["query"]
    lines = [
        f"# 检索计划 — {plan['topic']}",
        "",
        f"> 目标条数:{plan['n_target']};标准已预先声明(见 notes/screening_criteria.json)。",
        "",
        "## 一、布尔检索式",
        "",
        f"- 中文库(知网/万方):`{q['query_zh']}`",
        f"- 英文库(WoS/Scholar):`{q['query_en']}`",
        "",
        "## 二、路线 A:公开学术 API(psyclaw 直检,零依赖)",
        "",
        f"```\n{plan['public_api']}\n```",
        "",
        "覆盖 OpenAlex / Europe PMC / arXiv;OA 全文合法直取,付费墙不绕过。",
        "",
        "## 三、路线 B:机构库(知网/万方/WoS,浏览器桥接分步提示词)",
        "",
        "> **psyclaw 可亲自执行**(feat-107):本机有 node/npx 时,浏览器 MCP 已在",
        "> 目录中(`psyclaw mcp` 可见 browser 条目)。进 `psyclaw` 对话,`/agent on`",
        "> 切高级模式,说「按 notes/search_plan.md 路线 B 执行」——psyclaw 用",
        "> mcp__browser__* 工具逐步操作(每个动作过审批),登录环节由你在浏览器窗口",
        "> 人工完成。没有 npx 时,把下面提示词粘给任何带浏览器能力的外部 agent。",
        "",
        "> **复用已登录浏览器(附连模式,登录态跨会话保留)**:",
        "> ①带调试端口启动专用档案浏览器(登录一次,下次还在):",
        '> `"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \\',
        '>    --remote-debugging-port=9222 --user-data-dir="$HOME/.psyclaw/browser-profile" &`',
        "> ②在 `.psyclaw/mcp.yaml` 覆盖 browser 条目(用户目录优先于内置):",
        "> ```yaml",
        "> servers:",
        ">   - name: browser-attach",
        ">     category: literature",
        ">     enable_when: detect:npx",
        ">     command: npx -y chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222",
        "> ```",
        "> ③在该浏览器里登录机构代理后,psyclaw 的浏览器操作直接带登录态。",
        "",
        "> 心法:一次一件事 · 给标准不给感觉 · 指定输出格式 · 明确禁止项 ·",
        "> 长输出写文件 · 卡住换思路(来自浏览器桥接文献检索教学文档)。",
        "",
    ]
    for i, s in enumerate(plan["bridge_steps"], 1):
        lines += [f"### 步骤 {i}:{s['title']}", "", f"> {s['prompt']}", ""]
    c = plan["criteria"]
    lines += ["## 四、纳入 / 排除标准(检索前声明,筛选时不得更改)", "", "**纳入**:", ""]
    lines += [f"{i}. {x}" for i, x in enumerate(c["inclusion"], 1)]
    lines += ["", "**排除**:", ""]
    lines += [f"{i}. {x}" for i, x in enumerate(c["exclusion"], 1)]
    lines += ["", f"> {c['note']}", "",
              "## 五、下一步",
              "",
              "- 桥接结果表(notes/bridge_results.md)→ `psyclaw lit` 导入生成文献矩阵;",
              "- 公开 API 命中已自动落 notes/lit_search.json(cite-check 语料)。"]
    return "\n".join(lines) + "\n"


def write_search_plan(topic: str, project_dir: str = ".", provider=None,
                      n_target: int = 20) -> dict:
    """落盘:notes/search_plan.md + notes/screening_criteria.{json,md}。"""
    plan = build_search_plan(topic, provider=provider, n_target=n_target)
    notes = Path(project_dir) / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    plan_p = notes / "search_plan.md"
    plan_p.write_text(render_search_plan_md(plan), encoding="utf-8")
    crit_p = notes / "screening_criteria.json"
    crit_p.write_text(json.dumps(plan["criteria"], ensure_ascii=False, indent=2),
                      encoding="utf-8")
    return {"plan": plan, "plan_path": str(plan_p), "criteria_path": str(crit_p)}
