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
_OPEN_TOOL_RE = re.compile(r"```tool\s*\r?\n")

# 连续截断续写上限:防 provider 反复截断导致死循环(计入 max_iters,额外再设短路)
_MAX_TRUNC_STREAK = 2

_TRUNC_NUDGE = ("你上一条输出在 ```tool 块中被截断,没有形成完整的工具调用。"
                "请重新输出**完整**的 tool 块(可拆小任务、缩短 args);"
                "若无需工具,直接给出最终答案。")

# v0.6 feat-044:无进展检测——空回复 / 连续相同调用不再空转到 max_iters。
_MAX_NOPROGRESS = 2
_EMPTY_NUDGE = ("你上一条回复为空。请继续:要么输出一个完整的 ```tool 块调用工具,"
                "要么直接给出最终答案。")


def sanitize_messages(messages: list) -> list:
    """把消息序列规整成 provider 能接受的形状(v0.6 feat-045)。纯函数,可单测。

    Anthropic/OpenAI 对以下会 400:空 content 消息、连续同角色、首条非 user。
    多轮工具循环里回灌/续写/空回复处理可能引入这些,故每次调 provider 前统一规整:
    - 丢弃非 user/assistant 角色与空(纯空白)content 的消息;
    - 合并连续同角色消息(content 以空行相接);
    - 丢弃开头的 assistant,保证首条是 user。
    """
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        raw = m.get("content")
        content = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        if not content.strip():
            continue
        if out and out[-1]["role"] == role:
            out[-1] = {"role": role, "content": out[-1]["content"] + "\n\n" + content}
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _calls_signature(calls: list) -> tuple:
    """一轮工具调用的规范签名(name+排序后的 args),用于识别「反复调同一个」。"""
    return tuple(sorted(
        (str(c.get("name") or ""),
         json.dumps(c.get("args") or {}, sort_keys=True, ensure_ascii=False))
        for c in calls))


def has_truncated_tool_block(reply: str) -> bool:
    """检测未闭合的 ```tool 块——输出被 max_tokens 截断的典型特征。纯函数,可单测。

    修复「工具调用中途提前停止」:截断的回复解析不出完整 tool 块,
    若不检测会被误判成最终答案而静默终止任务。
    """
    text = reply or ""
    return len(_OPEN_TOOL_RE.findall(text)) > len(_TOOL_RE.findall(text))


def _normalize_args(raw) -> tuple[dict, str | None]:
    """把模型给的 args 规范成 dict。返回 (args, error)。

    v0.6 feat-043:模型常把 args 写成双重编码的 JSON 字符串("args":"{...}"),或误写成
    list/数字。此前原样传给工具 → a.get(...) 崩(且被误标成功)。这里统一收口:
    - None/缺省 → {};dict → 原样;
    - 字符串:尝试 JSON 解析,得 dict 才用,否则报错引导;
    - 其余(list/数字/bool)→ 报错,让模型重发 JSON 对象。
    """
    if raw is None:
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}, None
        try:
            parsed = json.loads(s)
        except json.JSONDecodeError:
            return {}, "args 必须是 JSON 对象(如 {\"query\": \"...\"}),收到无法解析的字符串"
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "args 必须是 JSON 对象,不能是数组/标量"
    return {}, "args 必须是 JSON 对象(键值对),不能是数组/标量"


def parse_tool_calls(reply: str) -> list[dict]:
    """从模型回复解析 ```tool JSON 块 → [{name, args}]。纯函数,可单测。

    非法 JSON / 缺 name / args 非对象的块 → {name:None|name, error:...},
    由执行层回报给模型纠正(而非静默崩在工具里)。
    """
    calls: list[dict] = []
    for m in _TOOL_RE.finditer(reply or ""):
        body = m.group("body").strip()
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            calls.append({"name": None, "args": {}, "error": "工具调用不是合法 JSON"})
            continue
        if not isinstance(obj, dict) or not obj.get("name"):
            calls.append({"name": None, "args": {}, "error": "工具调用缺 name 字段"})
            continue
        name = obj["name"]
        if not isinstance(name, str):
            calls.append({"name": None, "args": {}, "error": "name 必须是字符串"})
            continue
        args, err = _normalize_args(obj.get("args"))
        if err:
            calls.append({"name": name, "args": {}, "error": err})
        else:
            calls.append({"name": name, "args": args})
    return calls


# v0.3 安全加固(外审 MEDIUM):save_file 路径允许清单。凭据类文件与目录一律拒写。
_CRED_DIR_PARTS = frozenset({".ssh", ".aws", ".gnupg", ".kube", ".docker"})
_CRED_NAMES = frozenset({".netrc", ".env", ".npmrc", ".pypirc", "credentials",
                         "id_rsa", "id_ed25519", "authorized_keys", "known_hosts"})
_CRED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")


def save_path_denied(raw_path: str, project_dir: str = ".") -> str | None:
    """save_file 目标路径护栏:返回拒绝原因(带完整解析路径),None=放行。纯函数,可单测。

    - 解析(resolve,消解 ../ 与途径软链)后必须落在项目根内——拒相对逃逸与项目外绝对路径;
    - 目标已存在且是软链接 → 拒(不经软链写,防指向别处的覆盖);
    - 凭据类文件名/后缀/目录段(.ssh/.aws/.env/*.pem/id_rsa…) → 拒(纵深防御,即使在根内);
    - data/raw 铁律仍由 apply_save_block 内部把关,这里不重复。
    """
    from pathlib import Path
    raw = (raw_path or "").strip()
    if not raw:
        return "拒绝写入:路径为空"
    root = Path(project_dir).expanduser().resolve()
    p = Path(raw).expanduser()
    target = p if p.is_absolute() else root / p
    try:
        resolved = target.resolve()
    except OSError as exc:  # 极端路径(过长/非法字符)
        return f"拒绝写入:路径无法解析({exc})"
    if not resolved.is_relative_to(root):
        return f"拒绝写入:目标在项目根之外({resolved})"
    if target.exists() and target.is_symlink():
        return f"拒绝写入:目标是软链接({target} → {resolved})"
    name = resolved.name.lower()
    if (name in _CRED_NAMES or name.endswith(_CRED_SUFFIXES)
            or _CRED_DIR_PARTS & {part.lower() for part in resolved.parts}):
        return f"拒绝写入:凭据类路径({resolved})"
    return None


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
        from psyclaw.repl import read_denied
        p = Path(str(a.get("path", ""))).expanduser()
        denial = read_denied(p)          # 评审修复:此前缺 data/raw/密钥守卫(铁律)
        if denial:
            return f"拒绝读取 {p}:{denial}"
        if not p.exists() or not p.is_file():
            return f"文件不存在:{p}"
        return smart_excerpt(p)[:4000]
    _t("read_file", "读本地文件(含 PDF 抽取;csv 只给结构;绝不读 data/raw 原始行/密钥)",
       "path:str", _read)

    def _save(a):
        from psyclaw.repl import apply_save_block
        raw = str(a.get("path", ""))
        denial = save_path_denied(raw, project_dir)   # v0.3:项目根允许清单+凭据护栏
        if denial:
            return denial
        r = apply_save_block(
            {"path": raw, "content": str(a.get("content", ""))},
            confirm=lambda p: True)   # 副作用批准已在循环层做,此处允许覆盖
        tail = f"({r.get('chars')} 字符)" if r.get("chars") is not None else ""
        out = f"{r['status']} {r.get('path', '')} {tail}".strip()
        # feat-140 归位软提示:裸文件名落根且类型明确才附一句约定;不搬文件不改路径
        if Path(raw).parent == Path("."):
            from psyclaw.scaffold import canonical_dir
            hint_dir = canonical_dir(raw)
            if hint_dir:
                out += f"\n(归位约定:这类文件通常放 {hint_dir}/,下次可直接写入)"
        return out
    _t("save_file", "保存文件到磁盘(仅项目根内;绝不写 data/raw/凭据路径;覆盖需批准;"
       "产物按归位约定目录存放,用户显式指定为准)",
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

    # 文献工具(对话原生:检索/引用滚雪球/下载全文,模型直接调,无需用户记 CLI)
    def _fmt_papers(header, papers):
        lines = [header]
        for i, p in enumerate(papers, 1):
            au = ", ".join(p.get("authors", [])[:3]) + (" 等" if len(p.get("authors", [])) > 3 else "")
            cit = f" · 被引{p['citations']}" if p.get("citations") else ""
            oa = f" · {p['oa_status']}" if p.get("oa_status") and p["oa_status"] != "unknown" else ""
            doi = f" · doi:{p['doi']}" if p.get("doi") else ""
            lines.append(f"{i}. {(p.get('title') or '')[:96]} — {au} "
                         f"({p.get('year') or '?'}){oa}{cit}{doi}")
        return "\n".join(lines)

    def _lit_search(a):
        from psyclaw.psych import litsearch
        q = str(a.get("query", "")).strip()
        if not q:
            return "需要 query"
        srcs = a.get("sources")
        srcs = [s.strip() for s in srcs.split(",") if s.strip()] if isinstance(srcs, str) and srcs else None
        limit = int(a.get("limit", 8))
        r = litsearch.search(q, sources=srcs, limit=limit)
        return _fmt_papers(f"检索「{q}」· 来源 {r['per_source']} · 去重后 {r['n_deduped']} 条:",
                           r["results"][:limit])
    _t("lit_search",
       "文献检索(OpenAlex/Crossref/EuropePMC 多源,覆盖中英文核心期刊;返回题录+DOI 供下载/滚雪球)",
       "query:str, limit?:int, sources?:str(逗号:openalex,crossref,europepmc,semanticscholar,arxiv)",
       _lit_search)

    def _lit_snowball(a):
        from psyclaw.psych import litsearch
        doi = str(a.get("doi", "")).strip()
        if not doi:
            return "需要 doi(种子文献)"
        direction = a.get("direction") or "citations"
        hits = litsearch.snowball(doi, direction=direction, limit=int(a.get("limit", 20)))
        if not hits:
            return f"没拿到(DOI「{doi}」不在 OpenAlex / 无引用数据 / 网络失败)"
        return _fmt_papers(f"引用滚雪球「{doi}」· {direction} · {len(hits)} 条:", hits)
    _t("lit_snowball",
       "引用滚雪球:从种子 DOI 沿引用网络扩展(citations 往前追前沿 / references 往回追源头 / both)——综述正道,比关键词精准",
       "doi:str, direction?:citations|references|both, limit?:int", _lit_snowball)

    def _lit_download(a):
        from psyclaw.psych import litsearch
        out_dir = str(Path(project_dir) / "outputs" / "pdfs")
        doi = str(a.get("doi", "")).strip()
        if doi:
            papers = [{"doi": doi}]
        else:
            q = str(a.get("query", "")).strip()
            if not q:
                return "需要 query(批量检索下载)或 doi(下单篇)"
            papers = litsearch.search(q, limit=int(a.get("limit", 8)))["results"][:int(a.get("limit", 8))]
        got, walled, failed = [], 0, []
        for p in papers:
            res = litsearch.fetch_and_save(p, out_dir=out_dir)
            dl = res.get("downloaded") or {}
            if dl.get("ok"):
                got.append(f"{Path(dl['path']).name} ({dl['bytes'] // 1024}KB · {res.get('channel', '')})")
            elif res.get("status") == "fulltext" and res.get("saved"):
                got.append(f"{Path(res['saved']).name} (全文文本)")
            elif res.get("status") == "closed":
                walled += 1
            else:
                failed.append((p.get("title") or p.get("doi") or "?")[:40] + ":"
                              + (dl.get("browser_hint") or dl.get("note") or "")[:70])
        lines = [f"下载 {len(got)} 篇 → {out_dir}"]
        lines += [f"  ⬇ {g}" for g in got]
        if walled:
            lines.append(f"  付费墙无权限跳过 {walled} 篇(配机构权限:auth --set 后可下)")
        lines += [f"  ✗ {f}" for f in failed]
        return "\n".join(lines)
    _t("lit_download",
       "下载文献全文 PDF 到 outputs/pdfs(OA + 机构权限[LibKey/IP];给 query 批量检索下载 或 给 doi 下单篇;付费墙不绕过,如实跳过)",
       "query?:str, doi?:str, limit?:int", _lit_download, side_effect=True)

    # 全部 CLI 命令自动工具化(goal:所有 cli 命令工具化)——从 argparse 自省,新命令自动覆盖。
    try:
        _register_cli_tools(tools, project_dir)
    except Exception:  # noqa: BLE001 — 自动工具化失败不拖垮内置工具集
        pass

    # 插件工具(用户项目/全局插件注册;内置同名优先,加载失败不拖垮工具集)
    try:
        from psyclaw.plugins import load_plugins, merge_plugin_tools
        merge_plugin_tools(tools, load_plugins(project_dir))
    except Exception:  # noqa: BLE001
        pass
    # MCP 工具(v0.5 feat-040:已启用+健康的 MCP 服务器工具,mcp__ 前缀,fail-closed)
    try:
        from psyclaw.mcp.agent_tools import merge_mcp_tools
        merge_mcp_tools(tools, project_dir)
    except Exception:  # noqa: BLE001
        pass
    # Kimi WebBridge(feat-108:真实浏览器登录态,web__ 前缀,逐动作审批)
    try:
        from psyclaw.webbridge import merge_webbridge_tools
        merge_webbridge_tools(tools)
    except Exception:  # noqa: BLE001
        pass

    # feat-114:语义记忆写入(研究语境概念/约定;冲突协议见 docs/MEMORY.md)
    def _remember_fact(a):
        from psyclaw.memory import record_fact
        r = record_fact(str(a.get("concept", "")), str(a.get("statement", "")),
                        scope=str(a.get("scope", "project")),
                        source=str(a.get("source", "agent")))
        if r["status"] == "conflict":
            old = (r["card"].get("history") or [{}])[-1].get("statement", "")
            return (f"⚠ 记下了,但与既有说法冲突:曾「{old}」→ 现「{a.get('statement')}」。"
                    "已时近生效并降置信,请向用户确认哪个是对的。")
        return {"created": "✓ 已记入语义记忆", "reinforced": "✓ 再现,强化既有卡",
                "rejected": "✗ 概念/陈述为空"}.get(r["status"], r["status"])
    _t("remember_fact", "把研究语境的概念/约定/事实记入长期语义记忆"
       "(如「缺失码=99/-999」「构念 X 的操作定义」;同概念冲突会如实报告)",
       "concept:str, statement:str, scope?:project|global", _remember_fact,
       side_effect=True)

    # feat-113:按需展开——目录里未展开的扩展组,模型先查这个再调用。
    # 闭包引用同一 tools dict(上面的 MCP/WebBridge 合并结果都看得见)。
    def _tool_help(a):
        pat = str(a.get("prefix") or a.get("name") or "").strip()
        if not pat:
            return "用法:tool_help({'prefix': 'web__'}) 或 {'name': '工具名'}"
        hits = {n: t for n, t in tools.items()
                if n.startswith(pat) or pat in n}
        if not hits:
            return f"无匹配工具:{pat}(现有前缀:" + ", ".join(sorted(
                {g for n in tools if (g := _tool_group(n))})) + ")"
        return "\n".join(_tool_line(n, t) for n, t in list(hits.items())[:40])
    _t("tool_help", "取工具/工具组的完整参数说明(目录中未展开的组先查这个)",
       "prefix:str 或 name:str", _tool_help)
    return tools


# 全部 CLI 命令自动工具化(argparse 自省)——用户以对话工作,所有 cli 命令都当工具暴露给模型。
_CLI_TOOL_SKIP = {
    # 交互向导 / 系统运维 / REPL 自身 / 已手工优化(lit_* 等),不自动工具化
    "repl", "chat", "setup", "doctor", "config", "update", "eval", "commands",
    "help", "guide", "resume", "mcp", "plugins", "webbridge", "auth", "assist",
    "start", "version", "status", "sleep", "init", "lit", "clarify",
}
_CLI_TOOL_SIDE_EFFECT = {
    # 写盘 / 改状态 / 外部副作用 → 需批准(HITL)
    "export", "score", "scale", "preregister", "declare-test", "provenance",
    "journal", "memory", "kg", "new", "prepare", "jars", "run", "research",
    "auto", "goal", "tasks", "sync", "annotate", "skill",
}


def _make_cli_run(sub, func):
    """把一个 argparse 子命令包成工具 run:构造 Namespace(默认值+模型参数)→ 调 cmd_* → 捕获 stdout。"""
    import argparse
    import contextlib
    import io

    def _run(a):
        ns = argparse.Namespace()
        for act in sub._actions:                 # 先铺 parser 默认值
            if act.dest and act.dest != "help":
                setattr(ns, act.dest, act.default)
        for k, v in (a or {}).items():           # 再用模型给的参数覆盖
            setattr(ns, k, v)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                func(ns)
        except SystemExit:
            pass
        except (EOFError, OSError):
            return (buf.getvalue()
                    + "\n(该命令需交互输入,工具环境已跳过;请把所需参数直接传入)").strip()
        except Exception as e:  # noqa: BLE001 — 单个工具执行失败回报模型,不崩循环
            return (buf.getvalue() + f"\n(执行中断:{e})").strip()
        return buf.getvalue().strip() or "(完成,无输出)"
    return _run


def _register_cli_tools(tools: dict, project_dir: str = ".") -> None:
    """从 argparse 自省,把每个 CLI 子命令自动注册为对话工具(排除交互/系统类;不覆盖已有)。"""
    import argparse
    from psyclaw.cli import build_parser

    parser = build_parser()
    subs = next((act for act in parser._actions
                 if isinstance(act, argparse._SubParsersAction)), None)
    if subs is None:
        return
    helps = {ca.dest: (ca.help or "") for ca in subs._choices_actions}
    for name, sub in subs.choices.items():
        if name in _CLI_TOOL_SKIP or name in tools:      # 跳过排除 & 已手工工具化
            continue
        func = sub._defaults.get("func")
        if func is None:
            continue
        pos, opt = [], []
        for act in sub._actions:
            if not act.dest or act.dest == "help":
                continue
            (opt if act.option_strings else pos).append(act.dest)
        arg_desc = ", ".join([f"{p}:str" for p in pos] + [f"{o}?" for o in opt]) or "(无参数)"
        desc = ((helps.get(name) or name).strip()[:110]) + "(CLI 工具)"
        tools[name] = {"desc": desc, "args": arg_desc,
                       "side_effect": name in _CLI_TOOL_SIDE_EFFECT,
                       "run": _make_cli_run(sub, func)}


# feat-113:工具目录路由——实测 agent 模式工具目录占 system 79%(8.7k 字符)
# 且随 MCP/WebBridge 集成线性增长,与教训卡同病(全量常驻),同方治理:
# 内置工具常驻详情;扩展组(mcp__<server>__ / web__)按当前消息意图命中才展开,
# 未命中收成一行索引,模型可用 tool_help 按需取完整说明。
_EXT_PREFIXES = ("mcp__", "web__")
_GROUP_INTENTS: dict[str, tuple] = {
    "web__": ("浏览器", "网页", "网站", "页面", "打开", "登录", "知网", "万方",
              "browser", "url", "http", "点击", "截图", "标签", "webbridge"),
    "mcp__browser__": ("浏览器", "网页", "网站", "页面", "打开", "登录", "知网",
                       "browser", "url", "http", "点击", "截图"),
    "mcp__pystat__": ("统计", "检验", "ttest", "anova", "回归", "相关分析", "中介",
                      "效应量", "描述统计", "方差", "pystat", "pingouin"),
    "mcp__mne__": ("eeg", "erp", "脑电", "事件相关", "mne"),
}


def _tool_group(name: str) -> str | None:
    """扩展工具的组前缀(mcp__<server>__ / web__);内置工具返回 None。"""
    if name.startswith("web__"):
        return "web__"
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            return f"mcp__{parts[1]}__"
    return None


def _intent_hit(group: str, task_text: str) -> bool:
    low = (task_text or "").lower()
    kws = _GROUP_INTENTS.get(group)
    if kws is None:                      # 未登记的组:server 名出现即展开
        kws = (group.strip("_").split("__")[-1],)
    return any(k in low for k in kws)


def _tool_line(name: str, t: dict) -> str:
    se = " [副作用·需批准]" if t["side_effect"] else ""
    return f"- {name}({t['args']}){se} — {t['desc']}"


IDLE_EVICT_ROUNDS = 3   # 连续未命中/未调用 N 轮 → 从注入完全清走(feat-133)


def update_idle(prev_idle: dict, tools: dict, task_text: str,
                used_names: list[str] | None = None) -> tuple[dict, set]:
    """更新扩展工具组的闲置计数,返回 (new_idle, evicted_groups)。纯函数(feat-133)。

    - 本轮意图命中(_intent_hit)或有工具被实际调用(used_names)的组 → 计数清零;
    - 其余组 → 计数 +1;计数 ≥ IDLE_EVICT_ROUNDS 的组进 evicted(连索引都不给);
    - 意图再命中会清零 → 自动复活。内置工具不计(始终常驻)。
    """
    used_groups = {g for n in (used_names or [])
                   if (g := _tool_group(n))}
    groups = {g for n in tools if (g := _tool_group(n))}
    new_idle = dict(prev_idle or {})
    evicted = set()
    for g in groups:
        if g in used_groups or _intent_hit(g, task_text or ""):
            new_idle[g] = 0
        else:
            new_idle[g] = new_idle.get(g, 0) + 1
        if new_idle[g] >= IDLE_EVICT_ROUNDS:
            evicted.add(g)
    # 清掉已不存在的组的计数
    for g in list(new_idle):
        if g not in groups:
            del new_idle[g]
    return new_idle, evicted


def render_tool_catalog(tools: dict, task_text: str | None = None,
                        evicted: set | None = None) -> str:
    """工具目录 + 调用约定,拼进 system 提示。

    task_text 给定时启用意图路由(feat-113):扩展组未命中只给一行索引,
    附 tool_help 取详情的指引;None 保持全量(向后兼容)。
    """
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
    if task_text is None:
        for name, t in tools.items():
            lines.append(_tool_line(name, t))
        return "\n".join(lines)

    evicted = evicted or set()
    indexed: dict[str, list[str]] = {}
    n_evicted = 0
    for name, t in tools.items():
        group = _tool_group(name)
        if group is None or _intent_hit(group, task_text):
            lines.append(_tool_line(name, t))     # 内置常驻 / 本轮意图命中→展开
        elif group in evicted:
            n_evicted += 1                        # feat-133:长期闲置→完全清走,连索引都不给
        else:
            indexed.setdefault(group, []).append(name)
    if indexed:
        lines.append("其他工具组(与当前任务弱相关,未展开参数):")
        for group, names in indexed.items():
            head = tools[names[0]]["desc"].split("]")[0].lstrip("[") \
                if tools[names[0]]["desc"].startswith("[") else group
            lines.append(f"- {group}*({len(names)} 个,{head}):"
                         + " ".join(n.removeprefix(group) for n in names[:12]))
        lines.append('要用未展开的组:先调 {"name":"tool_help","args":{"prefix":"<组前缀>"}} '
                     "取完整参数说明,再按说明调用。")
    if n_evicted:
        lines.append(f"(另有 {n_evicted} 个长期未用的工具组已隐藏;需要时说出用途即可唤回)")
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
        # v0.6 feat-043:异常如实标 ok=False(此前误标 True 掩盖崩溃,模型无从自纠)
        return {"name": name, "ok": False, "output": f"工具执行异常:{exc}"}
    return {"name": name, "ok": True, "output": str(out)[:6000]}


def _render_results(results: list[dict]) -> str:
    parts = ["# 工具结果"]
    for r in results:
        flag = "" if r["ok"] else "(失败)"
        parts.append(f"## {r['name']}{flag}\n{r['output']}")
    parts.append("据以上结果继续,或给出最终答案(不再输出 tool 块)。")
    return "\n\n".join(parts)


# --- 长会话上下文修剪(v0.3 feat-033) -------------------------------------------
# 24 轮 × 每轮 ≤6000 字符/工具的回灌若原样保留,长任务会撑爆 provider 上下文、
# 也更易触发 max_tokens 截断。滚动修剪:最近 _KEEP_RECENT_RESULTS 轮工具结果保留完整,
# 更早的压缩为「工具名 + 输出首行」摘要——模型如需详情可重新调用工具(幂等只读工具居多)。

_RESULT_HEAD = "# 工具结果"
_COMPRESSED_HEAD = "# 工具结果(旧轮次已压缩;如需详情请重新调用对应工具)"
_KEEP_RECENT_RESULTS = 3
_COMPRESS_LINE_CHARS = 160


def _compress_result_msg(content: str) -> str:
    """把一条工具结果回灌压缩为:每个工具保留 `## 名字` + 输出首行(限长)。纯函数。"""
    out = [_COMPRESSED_HEAD]
    take_next = False
    for ln in content.splitlines():
        if ln.startswith("## "):
            out.append(ln)
            take_next = True
        elif take_next and ln.strip():
            out.append(ln[:_COMPRESS_LINE_CHARS]
                       + ("…" if len(ln) > _COMPRESS_LINE_CHARS else ""))
            take_next = False
    return "\n".join(out)


def trim_convo(convo: list, base_len: int) -> None:
    """就地滚动修剪循环内追加的工具结果消息(最近 _KEEP_RECENT_RESULTS 条保完整)。

    只动 base_len 之后、以 _RESULT_HEAD 开头的 user 消息——调用方传入的原始
    messages(REPL 历史等)与 assistant 回复、续写提示一概不碰。幂等:已压缩的跳过。
    """
    idxs = [i for i in range(base_len, len(convo))
            if convo[i].get("role") == "user"
            and str(convo[i].get("content", "")).startswith(_RESULT_HEAD)
            and not str(convo[i].get("content", "")).startswith(_COMPRESSED_HEAD)]
    for i in idxs[:-_KEEP_RECENT_RESULTS] if len(idxs) > _KEEP_RECENT_RESULTS else []:
        convo[i] = {"role": "user",
                    "content": _compress_result_msg(convo[i]["content"])}


# --- agent 运行痕迹持久化(v0.4 feat-037) ---------------------------------------
# trace/final 只活在当轮终端会跑完即失——落 .psyclaw/agent_runs.jsonl 供回看
# (psyclaw agent --history),也是复现溯源的输入。单行 JSON 追加,坏行读取时跳过。

_RUNS_FILE = "agent_runs.jsonl"
_RUNS_MAX_HEAD = 200


def log_agent_run(project_dir: str, task: str, res: dict) -> None:
    """把一次 run_tool_loop 结果追加到 .psyclaw/agent_runs.jsonl。失败静默(不拖垮主流程)。"""
    import json as _json
    import time as _time
    from pathlib import Path
    try:
        d = Path(project_dir) / ".psyclaw"
        d.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "task": (task or "")[:_RUNS_MAX_HEAD],
            "iters": res.get("iters"),
            "stopped": res.get("stopped"),
            "tools": [t.get("name") for t in res.get("trace", [])],
            "final_head": str(res.get("final", ""))[:_RUNS_MAX_HEAD],
        }
        with open(d / _RUNS_FILE, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_agent_runs(project_dir: str, limit: int = 10) -> list[dict]:
    """读最近 limit 条运行痕迹(新→旧)。坏行跳过;文件缺失返回 []。"""
    import json as _json
    from pathlib import Path
    p = Path(project_dir) / ".psyclaw" / _RUNS_FILE
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for ln in reversed(lines):
        if len(out) >= limit:
            break
        try:
            rec = _json.loads(ln)
        except _json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


# --- 错误自学习接入 agent 模式(v0.12 feat-065) ---------------------------------
# REPL 的错误学习(feat-058)只覆盖命令执行路径;agent 循环里工具失败(缺模块/命令/
# API 改名)同样值得蒸馏。只看 ok=False 的结果——ok 输出可能是 read_file 读到的日志/
# 源码,里面的报错字样是**内容**不是本机事实,学了会误伤(纯函数,可单测)。

_LESSON_FEEDBACK_HEAD = "# 环境教训(本次运行已确认的本机限制,调整方案别重复踩)"


def collect_env_lessons(results: list[dict], seen_keys: set) -> list[dict]:
    """从失败的工具结果蒸馏环境教训(去重靠调用方传入的 seen_keys,跨轮累积)。"""
    try:
        from psyclaw.repl import distill_env_lessons
    except Exception:  # noqa: BLE001  # 蒸馏不可用不拖垮循环
        return []
    fresh: list[dict] = []
    for r in results:
        if r.get("ok"):
            continue
        for les in distill_env_lessons(str(r.get("output", ""))):
            key = (les["trigger"], les["lesson"])
            if key not in seen_keys:
                seen_keys.add(key)
                fresh.append(les)
    return fresh


def run_tool_loop(provider, system: str, messages: list, tools: dict | None = None,
                  project_dir: str = ".", max_iters: int = 24,
                  approve=None, emit=None, idle_state: dict | None = None) -> dict:
    """跑纯工具层循环。返回 {final, iters, stopped, trace, lessons}。

    每轮:provider.chat → 解析 tool 块;无块=最终答案;有块=执行(副作用需 approve)→ 回灌 → 续。

    截断防护(修「工具调用中途提前停止」):输出含未闭合 ```tool 块、或 provider 报
    stop_reason=max_tokens 且无完整调用时,**不**当最终答案——回灌续写提示让模型重发完整
    tool 块;连续截断 > _MAX_TRUNC_STREAK 次才放弃(stopped="truncated",不静默)。

    错误自学习(feat-065):失败的工具结果蒸馏出环境教训后,当轮回灌给模型止损,
    并累积在返回的 lessons 里,由调用方(REPL/CLI)落会话记忆与跨会话待确认卡。
    """
    tools = tools if tools is not None else build_tools(project_dir)
    # feat-113:目录按当前任务意图路由(最后一条用户消息),弱相关扩展组收索引
    task_text = next((m.get("content", "") for m in reversed(messages)
                      if m.get("role") == "user"), "")
    # feat-133:据历史闲置状态(调用方传入,跨消息累积)清走长期未用组
    idle_in = (idle_state or {}).get("idle", {})
    new_idle, evicted = update_idle(idle_in, tools, task_text)
    if idle_state is not None:
        idle_state["idle"] = new_idle       # 持久化预增计数;工具执行时下方按组清零
    full_system = system + "\n" + render_tool_catalog(tools, task_text, evicted)
    convo = [dict(m) for m in messages]
    base_len = len(convo)   # 修剪只动此后循环追加的消息,不碰调用方原始历史
    trace: list[dict] = []
    lessons: list[dict] = []
    lesson_keys: set = set()
    trunc_streak = 0
    empty_streak = 0
    repeat_streak = 0
    prev_sig: tuple | None = None
    from psyclaw.ui_input import EscapeWatch, stream_interruptible
    for it in range(1, max_iters + 1):
        # feat-045:每次调 provider 前规整消息序列(去空 content/合并同角色/首条 user),
        # 防多轮回灌引入的非法序列触发 provider 400。
        # feat-090:流式消费期监听孤立 ESC——多步 agent 循环也能即时取消,
        # KeyboardInterrupt 上抛由调用方(REPL 深处捕获)取消本轮;监听只罩
        # provider 流式段,不罩工具审批 input()(cbreak 会破坏行编辑回显)。
        with EscapeWatch() as _esc:
            reply = "".join(stream_interruptible(
                provider.chat(sanitize_messages(convo), system=full_system), _esc))
        calls = parse_tool_calls(reply)
        cut = has_truncated_tool_block(reply) or (
            not calls and getattr(provider, "last_stop_reason", "") == "max_tokens")
        if not calls and not cut:
            # 空/纯空白回复不是有效答案(feat-044):有限追问,而非当最终答案静默收工
            if not reply.strip():
                empty_streak += 1
                if empty_streak > _MAX_NOPROGRESS:
                    return {"final": "(模型连续多轮返回空回复,已停止;请重述任务或换 provider)",
                            "iters": it, "stopped": "no_progress", "trace": trace,
                            "lessons": lessons}
                convo.append({"role": "assistant", "content": "(空回复)"})
                convo.append({"role": "user", "content": _EMPTY_NUDGE})
                continue
            return {"final": reply, "iters": it, "stopped": "answered", "trace": trace,
                    "lessons": lessons}
        empty_streak = 0
        # 连续相同 (name,args) 调用 → 判定卡住,收敛而非空转(feat-044)
        if calls:
            sig = _calls_signature(calls)
            repeat_streak = repeat_streak + 1 if sig == prev_sig else 0
            prev_sig = sig
            if repeat_streak >= _MAX_NOPROGRESS:
                return {"final": f"(检测到连续 {repeat_streak + 1} 轮重复相同的工具调用且无新"
                        "进展,已停止以免空转;请换思路或缩小任务)",
                        "iters": it, "stopped": "no_progress", "trace": trace,
                        "lessons": lessons}
        convo.append({"role": "assistant", "content": reply})
        if not calls:  # 截断且无一个完整调用 → 请求续写,不执行任何工具
            trunc_streak += 1
            if trunc_streak > _MAX_TRUNC_STREAK:
                return {"final": reply + f"\n\n(输出连续 {trunc_streak} 次在 tool 块中被"
                        "截断,已停止;可调高 PSYCLAW_MAX_TOKENS 或缩小任务)",
                        "iters": it, "stopped": "truncated", "trace": trace,
                        "lessons": lessons}
            if emit:
                emit("输出被截断,请求模型重发完整 tool 块…")
            convo.append({"role": "user", "content": _TRUNC_NUDGE})
            continue
        trunc_streak = 0
        results = [_exec_tool(c, tools, approve, emit) for c in calls]
        trace.extend(results)
        if idle_state is not None:          # feat-133:被调用组的闲置计数清零(复活)
            for r in results:
                g = _tool_group(r.get("name") or "")
                if g:
                    idle_state["idle"][g] = 0
        feedback = _render_results(results)
        fresh = collect_env_lessons(results, lesson_keys)
        if fresh:
            lessons.extend(fresh)
            if emit:
                emit(f"记下环境教训 {len(fresh)} 条")
        if lessons:
            # feat-088(评审修复):每轮把**全量**教训重放进最新反馈——教训此前
            # 只随首次出现的那条结果消息注入一次,trim_convo 在 3 条更新的结果
            # 消息后把它压缩掉,而 lesson_keys 去重让它永不再注入:长任务(20+ 轮)
            # 恰在最需要止损时失忆重踩。旧副本会被 trim 压掉,最新消息恒携带全量,
            # 上下文里始终只有 ~3 份活副本,不失控。
            feedback += ("\n\n" + _LESSON_FEEDBACK_HEAD + "\n"
                         + "\n".join(f"- [{le['trigger']}] {le['lesson']}"
                                     for le in lessons))
        if cut:  # 有完整调用但尾部还挂着截断的残块 → 一并告知,避免模型以为已发出
            feedback += "\n\n(注意:你上一条输出末尾有一个被截断的 tool 块未被执行,如仍需要请重发完整块。)"
        convo.append({"role": "user", "content": feedback})
        trim_convo(convo, base_len)   # feat-033:旧轮次工具结果滚动压缩,防上下文无界增长
    return {"final": f"(达到工具调用上限 {max_iters},未收敛;可提高上限或缩小任务)",
            "iters": max_iters, "stopped": "max_iters", "trace": trace,
            "lessons": lessons}
