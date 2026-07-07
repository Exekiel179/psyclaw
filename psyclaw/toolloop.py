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


def has_truncated_tool_block(reply: str) -> bool:
    """检测未闭合的 ```tool 块——输出被 max_tokens 截断的典型特征。纯函数,可单测。

    修复「工具调用中途提前停止」:截断的回复解析不出完整 tool 块,
    若不检测会被误判成最终答案而静默终止任务。
    """
    text = reply or ""
    return len(_OPEN_TOOL_RE.findall(text)) > len(_TOOL_RE.findall(text))


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
        return f"{r['status']} {r.get('path', '')} {tail}".strip()
    _t("save_file", "保存文件到磁盘(仅项目根内;绝不写 data/raw/凭据路径;覆盖需批准)",
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


def run_tool_loop(provider, system: str, messages: list, tools: dict | None = None,
                  project_dir: str = ".", max_iters: int = 24,
                  approve=None, emit=None) -> dict:
    """跑纯工具层循环。返回 {final, iters, stopped, trace}。

    每轮:provider.chat → 解析 tool 块;无块=最终答案;有块=执行(副作用需 approve)→ 回灌 → 续。

    截断防护(修「工具调用中途提前停止」):输出含未闭合 ```tool 块、或 provider 报
    stop_reason=max_tokens 且无完整调用时,**不**当最终答案——回灌续写提示让模型重发完整
    tool 块;连续截断 > _MAX_TRUNC_STREAK 次才放弃(stopped="truncated",不静默)。
    """
    tools = tools if tools is not None else build_tools(project_dir)
    full_system = system + "\n" + render_tool_catalog(tools)
    convo = [dict(m) for m in messages]
    base_len = len(convo)   # 修剪只动此后循环追加的消息,不碰调用方原始历史
    trace: list[dict] = []
    trunc_streak = 0
    for it in range(1, max_iters + 1):
        reply = "".join(provider.chat(convo, system=full_system))
        calls = parse_tool_calls(reply)
        cut = has_truncated_tool_block(reply) or (
            not calls and getattr(provider, "last_stop_reason", "") == "max_tokens")
        if not calls and not cut:
            return {"final": reply, "iters": it, "stopped": "answered", "trace": trace}
        convo.append({"role": "assistant", "content": reply})
        if not calls:  # 截断且无一个完整调用 → 请求续写,不执行任何工具
            trunc_streak += 1
            if trunc_streak > _MAX_TRUNC_STREAK:
                return {"final": reply + f"\n\n(输出连续 {trunc_streak} 次在 tool 块中被"
                        "截断,已停止;可调高 PSYCLAW_MAX_TOKENS 或缩小任务)",
                        "iters": it, "stopped": "truncated", "trace": trace}
            if emit:
                emit("输出被截断,请求模型重发完整 tool 块…")
            convo.append({"role": "user", "content": _TRUNC_NUDGE})
            continue
        trunc_streak = 0
        results = [_exec_tool(c, tools, approve, emit) for c in calls]
        trace.extend(results)
        feedback = _render_results(results)
        if cut:  # 有完整调用但尾部还挂着截断的残块 → 一并告知,避免模型以为已发出
            feedback += "\n\n(注意:你上一条输出末尾有一个被截断的 tool 块未被执行,如仍需要请重发完整块。)"
        convo.append({"role": "user", "content": feedback})
        trim_convo(convo, base_len)   # feat-033:旧轮次工具结果滚动压缩,防上下文无界增长
    return {"final": f"(达到工具调用上限 {max_iters},未收敛;可提高上限或缩小任务)",
            "iters": max_iters, "stopped": "max_iters", "trace": trace}
