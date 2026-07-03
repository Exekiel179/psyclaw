"""纯工具层循环 —— 让模型**自主多步调用工具**,作为 provider 无关的保底。

为什么是文本约定而非 provider 原生 function-calling:PsyClaw 赌"provider 无关 + 优雅降级"
(mock 无 key 也能跑),原生 tool-calling 只在部分 provider 上有。故这里用**文本约定的工具协议**——
模型在回复里输出 ```tool JSON 块,循环解析→执行→把结果回灌→模型继续,直到给出不含 tool 块的最终答案。
任何文本模型都能跑,这就是"保底";以后要为支持原生 tool-calling 的 provider 叠加高性能通道,可另接。

纪律(守 PsyClaw fail-closed):
- **副作用工具(save_file…)需批准**:approve(call)→True 才执行,否则拒(HITL 留在环里)。
- **上限防打转**:max_iters 到顶即停,不无限调。
- **只读工具**(search/read_file/kg_query/recall)自动执行;data/raw 等硬护栏在工具内部继续生效。
- **emit 事件流**:每步调用可推事件(对接"流式中间结果":正在 search…、调用 save_file…)。

控制流可单测:parse_tool_calls 纯函数;run_tool_loop 注入 fake provider/tools/approve 即可离线验证。
"""

from __future__ import annotations

import json
import re

_TOOL_RE = re.compile(r"```tool\s*\r?\n(?P<body>.*?)```", re.S)


def parse_tool_calls(reply: str) -> list[dict]:
    """从模型回复解析 ```tool JSON 块 → [{name, args}]。纯函数,可单测。

    非法 JSON / 缺 name 的块 → {name:None, error:...},由执行层回报给模型纠正。
    """
    calls: list[dict] = []
    for m in _TOOL_RE.finditer(reply or ""):
        body = m.group("body").strip()
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            calls.append({"name": None, "args": {}, "error": "工具调用不是合法 JSON"})
            continue
        if isinstance(obj, dict) and obj.get("name"):
            calls.append({"name": obj["name"], "args": obj.get("args") or {}})
        else:
            calls.append({"name": None, "args": {}, "error": "工具调用缺 name 字段"})
    return calls


def build_tools(project_dir: str = ".") -> dict:
    """内置工具集:把既有能力(检索/读文件/存文件/KG/召回)暴露为可调用工具。"""
    from pathlib import Path
    tools: dict = {}

    def _t(name, desc, args, run, side_effect=False):
        tools[name] = {"desc": desc, "args": args, "run": run,
                       "side_effect": side_effect}

    def _search(a):
        from psyclaw.search_router import execute_route, route
        q = str(a.get("query", ""))
        plan = route(q, a.get("type"))
        res = execute_route(plan, q, project_dir=project_dir,
                            limit=int(a.get("limit", 8)))
        head = (f"[{plan['task_type']} · {res['used']['source']}/{res['used']['mode']}"
                + ("(兜底)" if res["used_fallback"] else "") + f"] 命中 {len(res['results'])}")
        lines = [head] + ["- " + (r.get("title") or "")[:100] for r in res["results"][:8]]
        return "\n".join(lines)
    _t("search", "来源路由检索(事实/概念/趋势/回忆自动路由,主通道+兜底)",
       "query:str, type?:factual|conceptual|trend|local, limit?:int", _search)

    def _read(a):
        from psyclaw.context import smart_excerpt
        p = Path(str(a.get("path", ""))).expanduser()
        if not p.exists() or not p.is_file():
            return f"文件不存在:{p}"
        return smart_excerpt(p)[:4000]
    _t("read_file", "读本地文件(含 PDF 抽取;csv 只给结构;绝不读 data/raw 原始行)",
       "path:str", _read)

    def _save(a):
        from psyclaw.repl import apply_save_block
        r = apply_save_block(
            {"path": str(a.get("path", "")), "content": str(a.get("content", ""))},
            confirm=lambda p: True)   # 副作用批准已在循环层做,此处允许覆盖
        tail = f"({r.get('chars')} 字符)" if r.get("chars") is not None else ""
        return f"{r['status']} {r.get('path', '')} {tail}".strip()
    _t("save_file", "保存文件到磁盘(绝不写 data/raw;覆盖需批准)",
       "path:str, content:str", _save, side_effect=True)

    def _kg(a):
        from psyclaw.kg import KnowledgeGraph, render_mermaid
        kg = KnowledgeGraph(project_dir)
        sub = kg.subgraph(str(a.get("entity", "")), depth=int(a.get("depth", 1)))
        if not sub["nodes"]:
            return f"KG 无实体「{a.get('entity', '')}」(先 psyclaw kg seed)"
        return render_mermaid(sub)
    _t("kg_query", "查带引用的知识图谱子图", "entity:str, depth?:int", _kg)

    def _recall(a):
        from psyclaw.recall import ContextArchive
        hits = ContextArchive(project_dir).search(str(a.get("query", "")),
                                                  limit=int(a.get("limit", 5)))
        return "\n".join(f"- [{h['session']}] {h['user_text'][:100]}"
                         for h in hits) or "无历史命中"
    _t("recall", "检索历史对话(跨会话全文)", "query:str, limit?:int", _recall)

    def _list_dir(a):
        from psyclaw.project_sense import render_tree, scan_tree
        target = str(a.get("path", "") or project_dir)
        p = Path(target).expanduser()
        if not p.is_dir():
            return f"目录不存在:{p}"
        return render_tree(scan_tree(str(p)))
    _t("list_dir", "看目录结构(有界树;data/raw 只报数不列名)", "path?:str", _list_dir)

    # 插件工具(用户项目/全局插件注册;内置同名优先,加载失败不拖垮工具集)
    try:
        from psyclaw.plugins import load_plugins, merge_plugin_tools
        merge_plugin_tools(tools, load_plugins(project_dir))
    except Exception:  # noqa: BLE001
        pass
    return tools


def render_tool_catalog(tools: dict) -> str:
    """工具目录 + 调用约定,拼进 system 提示。"""
    lines = [
        "\n# 工具(可自主多步调用)",
        "要调用工具时,在回复里输出一个或多个 JSON 块(可与说明文字并存):",
        "```tool",
        '{"name": "工具名", "args": {…}}',
        "```",
        "我会执行并把结果回给你,你可据此继续调用或给出最终答案。"
        "**得到最终答案时,直接正常回复、不要再输出 tool 块。**",
        "可用工具:",
    ]
    for name, t in tools.items():
        se = " [副作用·需批准]" if t["side_effect"] else ""
        lines.append(f"- {name}({t['args']}){se} — {t['desc']}")
    return "\n".join(lines)


def _short(args: dict, n: int = 60) -> str:
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def _exec_tool(call: dict, tools: dict, approve, emit) -> dict:
    name = call.get("name")
    if not name or call.get("error"):
        return {"name": name, "ok": False, "output": call.get("error", "缺少工具名")}
    tool = tools.get(name)
    if not tool:
        return {"name": name, "ok": False,
                "output": f"未知工具 {name}(可用:{', '.join(tools)})"}
    if tool["side_effect"]:
        ok = bool(approve(call)) if approve else False
        if not ok:
            return {"name": name, "ok": False, "output": "用户未批准该副作用工具,已跳过"}
    if emit:
        emit(f"调用 {name}({_short(call.get('args') or {})})")
    try:
        out = tool["run"](call.get("args") or {})
    except Exception as exc:  # noqa: BLE001  # 单个工具异常不炸循环
        out = f"工具执行异常:{exc}"
    return {"name": name, "ok": True, "output": str(out)[:6000]}


def _render_results(results: list[dict]) -> str:
    parts = ["# 工具结果"]
    for r in results:
        flag = "" if r["ok"] else "(失败)"
        parts.append(f"## {r['name']}{flag}\n{r['output']}")
    parts.append("据以上结果继续,或给出最终答案(不再输出 tool 块)。")
    return "\n\n".join(parts)


def run_tool_loop(provider, system: str, messages: list, tools: dict | None = None,
                  project_dir: str = ".", max_iters: int = 6,
                  approve=None, emit=None) -> dict:
    """跑纯工具层循环。返回 {final, iters, stopped, trace}。

    每轮:provider.chat → 解析 tool 块;无块=最终答案;有块=执行(副作用需 approve)→ 回灌 → 续。
    """
    tools = tools if tools is not None else build_tools(project_dir)
    full_system = system + "\n" + render_tool_catalog(tools)
    convo = [dict(m) for m in messages]
    trace: list[dict] = []
    for it in range(1, max_iters + 1):
        reply = "".join(provider.chat(convo, system=full_system))
        calls = parse_tool_calls(reply)
        if not calls:
            return {"final": reply, "iters": it, "stopped": "answered", "trace": trace}
        convo.append({"role": "assistant", "content": reply})
        results = [_exec_tool(c, tools, approve, emit) for c in calls]
        trace.extend(results)
        convo.append({"role": "user", "content": _render_results(results)})
    return {"final": f"(达到工具调用上限 {max_iters},未收敛;可提高上限或缩小任务)",
            "iters": max_iters, "stopped": "max_iters", "trace": trace}
