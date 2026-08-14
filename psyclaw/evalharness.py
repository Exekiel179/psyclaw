"""确定性离线评测框架(eval harness,feat-073)。

评的是 psyclaw 自身的**编排 / 质量检查 / 自学习契约**是否仍然成立——不调 LLM、
不联网、不依赖统计库(统计外移铁律),全部用例离线秒级可复跑,结果确定。
pytest 保证"函数各自正确",eval harness 保证"关键链路端到端仍守约",
且产出结构化 scorecard 供版本评估 / 回归对比。

用法:
    python -m psyclaw eval                       # 全部用例
    python -m psyclaw eval --case gates_enforcement
    python -m psyclaw eval --json                # 机器可读输出

每个用例 = 函数 `case_<id>(tmp: Path) -> list[check]`,check 为
{name, passed, detail};run_evals 汇总 scorecard 并由 CLI 落
<项目>/deliverables/eval_report.json。新增用例:写函数并注册进 CASES。
用例自身崩溃 → 记为失败 check(fail-closed),绝不静默跳过。
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def validate_agent_case_spec(spec: dict) -> tuple[bool, list[str]]:
    """Reject single-turn tasks from the agent-capability benchmark.

    A text-only answer can test a model, but it cannot test orchestration.
    Effective cases must exercise at least two model decisions plus evidence
    and verification/recovery.
    """
    reasons: list[str] = []
    try:
        if int(spec.get("min_model_turns", 0)) < 2:
            reasons.append("min_model_turns must be >= 2")
    except (TypeError, ValueError):
        reasons.append("min_model_turns must be an integer")
    try:
        if int(spec.get("min_tool_calls", 0)) < 1:
            reasons.append("min_tool_calls must be >= 1")
    except (TypeError, ValueError):
        reasons.append("min_tool_calls must be an integer")
    if not spec.get("requires_verification", False):
        reasons.append("requires_verification must be true")
    checks = spec.get("checks")
    if not isinstance(checks, list) or len(checks) < 2:
        reasons.append("at least two orchestration checks are required")
    if not spec.get("expected_tools"):
        reasons.append("expected_tools is required")
    return not reasons, reasons


# ---------------------------------------------------------------------------
# 用例 1:实证分析编排链 —— 画像 → 推荐 → 出脚本(委托外部库,不在仓内算)
# ---------------------------------------------------------------------------

def _write_csv(path: Path, header: list[str], rows: list[list]) -> str:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def case_analysis_pipeline(tmp: Path) -> list[dict]:
    from psyclaw.workflows.steps_analysis import (
        generate_analysis_script, profile_data, recommend_analysis)
    checks: list[dict] = []

    csv2 = _write_csv(tmp / "two_group.csv", ["cond", "score"],
                      [["A", 3.1], ["A", 2.8], ["A", 3.4], ["A", 2.9],
                       ["B", 4.6], ["B", 4.9], ["B", 4.4], ["B", 4.8]])
    prof = profile_data(csv2)
    checks.append(_check("画像:行数与列型判定", prof["n"] == 8
                         and "score" in prof["numeric"]
                         and "cond" in prof["categorical"],
                         f"n={prof['n']} numeric={prof['numeric']}"))
    rec = recommend_analysis(prof)
    checks.append(_check("推荐:二分类+连续 → ttest",
                         rec["analysis"] == "ttest" and rec["group"] == "cond",
                         str(rec)))
    script = generate_analysis_script(csv2, rec)
    ok_compile = True
    try:
        compile(script, "<eval>", "exec")
    except SyntaxError as exc:
        ok_compile = False
        checks.append(_check("脚本:语法可编译", False, str(exc)))
    if ok_compile:
        checks.append(_check("脚本:语法可编译", True))
    checks.append(_check("脚本:统计委托外部库(pingouin),不在仓内算",
                         "pingouin" in script and "import pg" not in script))
    checks.append(_check("脚本:效应量+CI 已随检验给出(gates 要求)",
                         "cohen_d" in script and "CI95" in script))

    csv3 = _write_csv(tmp / "three_group.csv", ["group", "rt"],
                      [["low", 320], ["low", 310], ["mid", 305],
                       ["mid", 300], ["high", 280], ["high", 275]])
    rec3 = recommend_analysis(profile_data(csv3))
    checks.append(_check("推荐:三水平分类 → anova",
                         rec3["analysis"] == "anova", str(rec3)))

    bad = tmp / "no_such.csv"
    try:
        profile_data(str(bad))
        checks.append(_check("画像:文件缺失 fail-closed 抛错", False, "未抛 ValueError"))
    except ValueError:
        checks.append(_check("画像:文件缺失 fail-closed 抛错", True))
    return checks


# ---------------------------------------------------------------------------
# 用例 2:元分析编排链 —— 效应量表校验 → 出脚本;致命缺陷 fail-closed
# ---------------------------------------------------------------------------

def case_meta_pipeline(tmp: Path) -> list[dict]:
    from psyclaw.workflows.steps_meta import generate_meta_script, validate_effects
    checks: list[dict] = []

    eff = _write_csv(tmp / "effects.csv", ["study", "yi", "vi"],
                     [["Smith2019", 0.42, 0.0225], ["Li2020", 0.31, 0.0144],
                      ["Garcia2021", 0.55, 0.04], ["Chen2022", 0.18, 0.01],
                      ["Kim2023", 0.47, 0.0324]])
    info = validate_effects(eff)
    checks.append(_check("校验:定位效应量列与方差来源",
                         info["n_studies"] == 5 and info["effect_col"] == "yi"
                         and info["variance_kind"] == "variance", str(info)))
    script = generate_meta_script(eff, info)
    try:
        compile(script, "<eval>", "exec")
        checks.append(_check("脚本:语法可编译", True))
    except SyntaxError as exc:
        checks.append(_check("脚本:语法可编译", False, str(exc)))
    checks.append(_check("脚本:委托 statsmodels 随机效应(DL)+异质性+Egger",
                         "combine_effects" in script and "statsmodels" in script
                         and "Egger" in script))

    one = _write_csv(tmp / "one_study.csv", ["study", "yi", "vi"],
                     [["Only2024", 0.3, 0.02]])
    try:
        validate_effects(one)
        checks.append(_check("校验:单研究 fail-closed 抛错", False, "未抛 ValueError"))
    except ValueError:
        checks.append(_check("校验:单研究 fail-closed 抛错", True))

    novar = _write_csv(tmp / "no_var.csv", ["study", "yi"],
                       [["A", 0.3], ["B", 0.4]])
    try:
        validate_effects(novar)
        checks.append(_check("校验:无方差来源 fail-closed 抛错", False, "未抛 ValueError"))
    except ValueError:
        checks.append(_check("校验:无方差来源 fail-closed 抛错", True))
    return checks


# ---------------------------------------------------------------------------
# 用例 3:文献初筛 —— 相关性筛选计数一致;跨语言零重叠时诚实降级不假装筛过
# ---------------------------------------------------------------------------

def case_lit_screen(tmp: Path) -> list[dict]:  # noqa: ARG001
    from psyclaw.workflows.steps import screen_papers
    checks: list[dict] = []

    topic = "working memory training transfer effects"
    rel = [{"title": "Working memory training and transfer effects in adults",
            "abstract": "training improves working memory with transfer"},
           {"title": "Does working memory training generalize? transfer effects",
            "abstract": "meta-analytic evidence on training transfer"}]
    irr = [{"title": f"Unrelated paper {i} about botany",
            "abstract": "plant photosynthesis chlorophyll leaves"} for i in range(6)]
    r = screen_papers(rel + irr, topic)
    c = r["counts"]
    checks.append(_check("初筛:相关题录保留、无关排除",
                         all(p in r["included"] for p in rel) and c["excluded"] > 0,
                         str(c)))
    checks.append(_check("初筛:PRISMA 计数自洽",
                         c["screened"] == 8
                         and c["included"] + c["excluded"] == c["screened"], str(c)))

    zh_topic = "工作记忆训练的迁移效应"
    r2 = screen_papers(irr, zh_topic)
    checks.append(_check("初筛:跨语言零重叠 → 诚实降级全纳入待人工复核",
                         len(r2["included"]) == len(irr) and not r2["excluded"]
                         and "人工复核" in r2["method"], r2["method"]))
    return checks


# ---------------------------------------------------------------------------
# 用例 4:质量检查 —— 合规 sidecar 通过;缺效应量未通过;文件缺失 fail-closed
# ---------------------------------------------------------------------------

def case_gates_enforcement(tmp: Path) -> list[dict]:
    from psyclaw.gates.checker import check_artifact
    checks: list[dict] = []

    (tmp / "analysis.py").write_text("print('repro')", encoding="utf-8")
    good = {
        "effect_size": {"name": "cohen_d", "value": 0.52, "ci": [0.10, 0.94]},
        "assumptions_checked": [{"name": "normality"}, {"name": "homogeneity"},
                                {"name": "independence"}],
        "repro_script": "analysis.py",
        "data_fingerprint": "sha256:abcd1234",
    }
    gp = tmp / "stat_ok.json"
    gp.write_text(json.dumps(good), encoding="utf-8")
    res = check_artifact(str(gp), "stat")
    checks.append(_check("质量检查:合规统计产出通过(无 blocking)",
                         res["passed"] and not res["blocking"],
                         json.dumps(res["blocking"], ensure_ascii=False)[:300]))

    bad = dict(good)
    bad.pop("effect_size")
    bp = tmp / "stat_bad.json"
    bp.write_text(json.dumps(bad), encoding="utf-8")
    res2 = check_artifact(str(bp), "stat")
    hit = [b for b in res2["blocking"] if b["requirement"] in
           ("effect_size", "confidence_interval")]
    checks.append(_check("质量检查:缺效应量+CI 未通过(学术诚信铁律)",
                         not res2["passed"] and bool(hit),
                         json.dumps(res2["blocking"], ensure_ascii=False)[:300]))

    res3 = check_artifact(str(tmp / "missing.json"), "stat")
    checks.append(_check("质量检查:产出物缺失时 fail-closed",
                         not res3["passed"] and res3["blocking"]))

    (tmp / "broken.json").write_text("{not json", encoding="utf-8")
    res4 = check_artifact(str(tmp / "broken.json"), "stat")
    checks.append(_check("质量检查:产出物不可解析时 fail-closed",
                         not res4["passed"] and res4["blocking"]))
    return checks


# ---------------------------------------------------------------------------
# 用例 5:错误自学习 —— 三类环境教训蒸馏;ok=True 输出绝不误学
# ---------------------------------------------------------------------------

def case_error_learning(tmp: Path) -> list[dict]:  # noqa: ARG001
    from psyclaw.repl import distill_env_lessons
    from psyclaw.toolloop import collect_env_lessons
    checks: list[dict] = []

    out = ("zsh: command not found: rscript\n"
           "ModuleNotFoundError: No module named 'pandas'\n"
           "AttributeError: module 'scipy' has no attribute 'interp'")
    lessons = distill_env_lessons(out)
    kinds = {le["kind"]: le["trigger"] for le in lessons}
    checks.append(_check("蒸馏:cmd/module/attr 三类都识别",
                         kinds.get("cmd") == "rscript"
                         and kinds.get("module") == "pandas"
                         and kinds.get("attr") == "scipy.interp", str(kinds)))

    seen: set = set()
    ok_res = [{"name": "read_file", "ok": True,
               "output": "文档里写着:command not found: fakecmd"}]
    checks.append(_check("自学习:ok=True 的输出不蒸馏(防把读到的文件内容当环境事实)",
                         collect_env_lessons(ok_res, seen) == [] and not seen))

    fail_res = [{"name": "shell", "ok": False,
                 "output": "zsh: command not found: rscript"}]
    fresh = collect_env_lessons(fail_res, seen)
    checks.append(_check("自学习:ok=False 的失败输出蒸馏出教训",
                         len(fresh) == 1 and fresh[0]["trigger"] == "rscript"))
    again = collect_env_lessons(fail_res, seen)
    checks.append(_check("自学习:同一教训跨调用去重", again == []))
    return checks


# ---------------------------------------------------------------------------
# 用例 6:toolloop 纪律 —— 失败教训回灌、重复调用止损、副作用未批准不执行
# ---------------------------------------------------------------------------

class _ScriptedProvider:
    """按脚本逐轮回放的假 provider(评测专用,决不联网)。"""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.last_stop_reason = ""

    def chat(self, messages: list, system: str = "") -> Iterator[str]:  # noqa: ARG002
        reply = self._replies.pop(0) if self._replies else self._replies_exhausted()
        yield reply

    @staticmethod
    def _replies_exhausted() -> str:
        return "(脚本已放完)"


def _tool_block(name: str, args: dict | None = None) -> str:
    return "```tool\n" + json.dumps({"name": name, "args": args or {}}) + "\n```"


def case_toolloop_discipline(tmp: Path) -> list[dict]:  # noqa: ARG001
    from psyclaw.toolloop import run_tool_loop
    checks: list[dict] = []

    def _probe(a):  # noqa: ARG001
        raise RuntimeError("zsh: command not found: rscript")
    tools = {"probe": {"desc": "评测探针", "args": "", "run": _probe,
                       "side_effect": False}}

    prov = _ScriptedProvider([_tool_block("probe"), "最终答案:改用 python 方案。"])
    res = run_tool_loop(prov, "sys", [{"role": "user", "content": "任务"}],
                        tools=tools, max_iters=6)
    checks.append(_check("循环:工具失败后仍收敛为最终答案",
                         res["stopped"] == "answered" and res["iters"] == 2,
                         f"stopped={res['stopped']} iters={res['iters']}"))
    checks.append(_check("循环:失败结果如实标 ok=False",
                         res["trace"] and res["trace"][0]["ok"] is False))
    checks.append(_check("循环:环境教训被蒸馏并随结果返回",
                         any(le["trigger"] == "rscript" for le in res["lessons"]),
                         str(res["lessons"])[:200]))

    def _echo(a):  # noqa: ARG001
        return "同样的结果"
    tools2 = {"echo": {"desc": "回显", "args": "", "run": _echo,
                       "side_effect": False}}
    prov2 = _ScriptedProvider([_tool_block("echo", {"q": "x"})] * 10)
    res2 = run_tool_loop(prov2, "sys", [{"role": "user", "content": "任务"}],
                         tools=tools2, max_iters=10)
    checks.append(_check("循环:连续重复相同调用 → 止损停止(不空转烧 token)",
                         res2["stopped"] == "no_progress" and res2["iters"] < 10,
                         f"stopped={res2['stopped']} iters={res2['iters']}"))

    ran = {"flag": False}

    def _write(a):  # noqa: ARG001
        ran["flag"] = True
        return "写入完成"
    tools3 = {"write": {"desc": "写文件", "args": "", "run": _write,
                        "side_effect": True}}
    prov3 = _ScriptedProvider([_tool_block("write"), "收到,不写了。"])
    res3 = run_tool_loop(prov3, "sys", [{"role": "user", "content": "任务"}],
                         tools=tools3, max_iters=6, approve=None)
    checks.append(_check("循环:副作用工具无批准回调 → 拒执行(fail-closed)",
                         ran["flag"] is False and res3["trace"]
                         and res3["trace"][0]["ok"] is False
                         and "未批准" in res3["trace"][0]["output"]))
    return checks


# ---------------------------------------------------------------------------
# 用例 7:交付与入口 —— DOCX 契约、资料转换、两入口不分叉
# ---------------------------------------------------------------------------

def case_delivery_contract(tmp: Path) -> list[dict]:
    """Exercise the artifact surface without Word, a model, or network access."""
    from psyclaw.materials import convert_to_markdown
    from psyclaw.knowledge_compile import compile_materials, promote_compiled_skill
    from psyclaw.handoff import write_handoff
    from psyclaw.modes import RUN_TYPES, normalize_run_type
    from psyclaw.output.apa7 import APA7Document
    from psyclaw.output.docx_contract import inspect_docx
    from psyclaw.toolloop import build_tools

    checks: list[dict] = []
    doc = APA7Document(title="稳定样稿", authors="Li, M.", affiliation="PsyClaw")
    doc.set_abstract("含有 **粗体** 和 *斜体* 的中文摘要。", keywords=["fixture"])
    doc.add_heading("方法", 1)
    doc.add_heading("参与者", 2)
    doc.add_heading("材料", 3)
    doc.add_paragraph_with_footnote("正文。", "脚注来源说明。")
    doc.add_stat_table("Table 1", ["变量", "M"], [["焦虑", "3.20"]])
    doc.add_reference("Li, M. (2026). *Stable fixture*. Journal, 1, 1-2.")
    left, right = tmp / "fixture-a.docx", tmp / "fixture-b.docx"
    doc.to_docx(left)
    doc.to_docx(right)
    a, b = inspect_docx(left), inspect_docx(right)
    checks.append(_check("DOCX:结构契约通过", a["ok"], "; ".join(a["errors"])))
    checks.append(_check("DOCX:连续导出字节稳定", a.get("sha256") == b.get("sha256")))

    csv_path = tmp / "materials.csv"
    _write_csv(csv_path, ["id", "score"], [["1", "3"]])
    converted = convert_to_markdown(csv_path)
    checks.append(_check("资料转换:Markdown 与 SHA-256 审计均落盘",
                         converted.get("ok") and Path(converted["output"]).is_file()
                         and Path(converted["sidecar"]).is_file(), str(converted)))
    source_dir = tmp / "source-materials"
    source_dir.mkdir()
    (source_dir / "notes.md").write_text("# Evidence\n\nA staged claim.\n", encoding="utf-8")
    bundle = tmp / "compiled-skill"
    compiled = compile_materials(source_dir, bundle, skill_name="Eval Skill")
    checks.append(_check("资料编译:索引、manifest、账本与 staged Skill 均落盘",
                         compiled.get("ok") and all((bundle / name).is_file() for name in
                         ("INDEX.md", "manifest.json", "claims.json", "validation.json", "SKILL.md"))))
    blocked = promote_compiled_skill(bundle, reviewer="eval")
    checks.append(_check("Skill 晋升:无 verified claim/四类验证时 fail-closed",
                         blocked.get("ok") is False and blocked.get("status") == "not_ready", str(blocked)))
    handoff = write_handoff(tmp, goal="Continue", next_steps=["Review claims"],
                            generated_at="2026-08-07T00:00:00+00:00")
    checks.append(_check("会话交接:Markdown 与可重放 JSON 同时落盘",
                         Path(handoff["path"]).is_file() and Path(handoff["sidecar"]).is_file()))
    agent_tools = build_tools(str(tmp))
    native = {"academic_orchestrate", "material_convert", "material_compile", "skill_claim_record", "skill_validate",
              "skill_promote", "skill_bundle_status", "session_handoff_write", "figure_compose",
              "skill_search", "skill_get", "skill_categories", "skill_registry_rebuild"}
    checks.append(_check("Agent 工具面:学术能力原生注册且不暴露重复 CLI 包装",
                         native <= set(agent_tools)
                         and not ({"convert", "compile", "handoff", "figures"} & set(agent_tools))))
    planned = json.loads(agent_tools["academic_orchestrate"]["run"]({
        "task": "蒸馏导师材料", "execute": False
    }))
    checks.append(_check("Agent 编排:先路由并生成停止条件，不直接宣称完成",
                         planned.get("status") == "planned"
                         and planned.get("route", {}).get("mode") == "distill"
                         and any(s.get("stop_if") for s in planned.get("steps", []))))
    checks.append(_check("入口路由:只公开四种明确 workflow",
                         RUN_TYPES == ("analysis", "meta", "literature", "qualitative")
                         and normalize_run_type("lit") == "literature"))
    return checks


def case_continuous_tasks(tmp: Path) -> list[dict]:
    """连续任务契约：检索→下载、分析→写方法、生成→质检。"""
    from psyclaw.agent_runtime import CompletionContract, TaskSpec, verify_task
    from psyclaw.psych.litsearch import save_search_record
    checks: list[dict] = []

    record = save_search_record({"query": "fixture", "results": [
        {"title": "Fixture paper", "doi": "10.1000/fixture"}]}, tmp)
    checks.append(_check("连续链:检索产出可供下载复用",
                         (tmp / "notes" / "lit_search.json").is_file()
                         and "lit_search.json" in record))
    download = TaskSpec("download", "下载检索到的论文",
                        completion=CompletionContract(
                            required_tools=("lit_download",),
                            required_artifacts=("outputs/pdfs/fixture.pdf",),
                            min_successful_tool_calls=1,
                            allow_reasoning_only=False))
    (tmp / "outputs" / "pdfs").mkdir(parents=True)
    (tmp / "outputs" / "pdfs" / "fixture.pdf").write_bytes(b"%PDF fixture")
    ok, reasons = verify_task(download, {
        "stopped": "answered", "final": "已下载",
        "trace": [{"name": "lit_download", "ok": True}],
    }, str(tmp))
    checks.append(_check("连续链:下载必须有工具回执和真实 PDF", ok, str(reasons)))

    method = TaskSpec("method", "写方法部分",
                      completion=CompletionContract(
                          required_tools=("save_file",),
                          required_artifacts=("outputs/method.md",),
                          min_successful_tool_calls=1,
                          allow_reasoning_only=False))
    checks.append(_check("连续链:分析→写方法缺产物时不算完成",
                         not verify_task(method, {
                             "stopped": "answered", "final": "已写方法", "trace": [
                                 {"name": "save_file", "ok": True}]}, str(tmp))[0]))
    checks.append(_check("连续链:生成→质检拒绝纯文字宣称",
                         not verify_task(TaskSpec("check", "生成并质检报告"), {
                             "stopped": "answered", "final": "已完成", "trace": []}, str(tmp))[0]))
    return checks


def case_langgraph_path(tmp: Path) -> list[dict]:
    """LangGraph 真路径：四节点实际运行，共享 RunState，未调用 legacy 入口。"""
    from psyclaw.langgraph_runtime import run_langgraph_agent
    checks: list[dict] = []

    class Provider:
        name = "eval"
        base_url = ""
        api_key = "test"
        last_stop_reason = ""

        def __init__(self, role="executor"):
            self.role = role

        def chat(self, messages, system=""):
            if "Planner" in system:
                yield json.dumps({"tasks": [{"id": "answer", "objective": "回答问题",
                                               "mainline": True}]})
            elif "Finisher" in system or "只汇总" in system:
                yield "已根据验收结果汇总。"
            else:
                yield "执行任务完成。"

    result = run_langgraph_agent(
        Provider("planner"), "系统", [{"role": "user", "content": "回答问题"}],
        executor_factory=lambda: Provider("executor"),
        finisher_provider=Provider("writer"), project_dir=str(tmp),
        max_iters=4, max_workers=1, approve=lambda _call: True)
    checks.append(_check("LangGraph:四节点真实执行", result.get("backend") == "langgraph"
                         and result.get("graph_nodes") == ["planner", "executor", "verifier", "finisher"],
                         str(result.get("graph_nodes"))))
    checks.append(_check("LangGraph:任务经 Verifier 验收后才汇总",
                         result.get("stopped") == "completed"
                         and result.get("task_results", {}).get("answer", {}).get("passed") is True))
    state = json.loads((tmp / ".psyclaw" / "run_state.json").read_text(encoding="utf-8"))
    checks.append(_check("LangGraph:四节点共享同一 RunState",
                         state.get("goal") == "回答问题"
                         and state.get("schema") == "psyclaw-run-state/v1"))
    return checks


def case_agent_capability_multiturn(tmp: Path) -> list[dict]:
    """有效智能体题：规划→工具→回灌→验收→依赖核验。"""
    from psyclaw.langgraph_runtime import run_langgraph_agent
    checks: list[dict] = []

    class Provider:
        name = "agent-capability-eval"
        base_url = ""
        api_key = "test"
        last_stop_reason = ""

        def __init__(self, role="executor"):
            self.role = role
            self.turns = 0
            self.recovered = False
            self.saved = False

        def chat(self, messages, system=""):
            self.turns += 1
            if "Planner" in system:
                yield json.dumps({"tasks": [
                    {"id": "collect", "objective": "读取输入并保存证据",
                     "mainline": True, "owned_paths": ["outputs/evidence.md"],
                     "completion": {"required_tools": ["save_file"],
                                    "required_artifacts": ["outputs/evidence.md"],
                                    "min_successful_tool_calls": 1,
                                    "allow_reasoning_only": False}},
                    {"id": "verify", "objective": "核验产物目录",
                     "depends_on": ["collect"],
                     "completion": {"required_tools": ["list_dir"],
                                    "min_successful_tool_calls": 1,
                                    "allow_reasoning_only": False}},
                ]})
                return
            if "Finisher" in system or "只汇总" in system:
                yield "已根据工具回执和验收结果完成交接。"
                return
            prompt = str(messages[-1].get("content", ""))
            if "读取输入并保存证据" in prompt and "工具结果" not in prompt:
                yield ('```tool\n{"name":"save_file","args":{"path":"outputs/evidence.md",'
                       '"content":"fixture evidence"}}\n```')
            elif "核验产物目录" in prompt and "工具结果" not in prompt:
                yield '```tool\n{"name":"list_dir","args":{"path":"outputs"}}\n```'
            else:
                yield "已依据最新工具回执完成本步骤。"

    planner = Provider("planner")
    executors: list[Provider] = []

    def factory():
        provider = Provider("executor")
        executors.append(provider)
        return provider

    result = run_langgraph_agent(
        planner, "系统", [{"role": "user", "content": "完成证据收集并核验"}],
        executor_factory=factory, finisher_provider=Provider("writer"),
        source_provider=planner, project_dir=str(tmp), max_iters=4, max_workers=1,
        approve=lambda _call: True)
    results = result.get("task_results", {})
    checks.append(_check("智能体:至少两步依赖任务均通过",
                         result.get("stopped") == "completed"
                         and all(item.get("passed") for item in results.values())))
    checks.append(_check("智能体:每个执行器经历工具回灌后的第二轮决策",
                         len(executors) == 2 and all(p.turns >= 2 for p in executors),
                         str([p.turns for p in executors])))
    checks.append(_check("智能体:工具回执和真实产物存在",
                         [item.get("name") for item in result.get("trace", [])]
                         == ["save_file", "list_dir"]
                         and (tmp / "outputs" / "evidence.md").is_file()))
    checks.append(_check("智能体:下游任务收到上游验收结果",
                         "collect" in str(results["verify"].get("task", {}))
                         and results["verify"].get("passed") is True))
    return checks


def case_agent_capability_recovery(tmp: Path) -> list[dict]:
    """有效智能体题：工具失败回灌→换策略→真实产物验收。"""
    from psyclaw.langgraph_runtime import run_langgraph_agent
    checks: list[dict] = []

    class Provider:
        name = "agent-recovery-eval"
        base_url = ""
        api_key = "test"
        last_stop_reason = ""

        def __init__(self, role="executor"):
            self.role = role
            self.turns = 0

        def chat(self, messages, system=""):
            self.turns += 1
            if "Planner" in system:
                yield json.dumps({"tasks": [{
                    "id": "recover", "objective": "创建并核验恢复报告",
                    "mainline": True, "owned_paths": ["outputs/recovery.md"],
                    "completion": {"required_tools": ["list_dir"],
                                   "required_artifacts": ["outputs/recovery.md"],
                                   "min_successful_tool_calls": 1,
                                   "allow_reasoning_only": False},
                }]})
                return
            if "Finisher" in system or "只汇总" in system:
                yield "已依据恢复后的验收结果汇总。"
                return
            prompt = str(messages[-1].get("content", ""))
            if self.turns == 1:
                yield '```tool\n{"name":"missing_tool","args":{}}\n```'
            elif "工具结果" in prompt and "失败" in prompt:
                self.recovered = True
                self.saved = True
                yield ('```tool\n{"name":"save_file","args":{"path":"outputs/recovery.md",'
                       '"content":"recovered"}}\n```')
            elif self.saved and "save_file" in prompt and "list_dir" not in prompt:
                yield '```tool\n{"name":"list_dir","args":{"path":"outputs"}}\n```'
            elif self.recovered and "list_dir" in prompt:
                yield "已核验恢复报告并完成本步骤。"
            else:
                yield '```tool\n{"name":"list_dir","args":{"path":"outputs"}}\n```'

    executor = Provider("executor")
    planner = Provider("planner")
    result = run_langgraph_agent(
        planner, "系统", [{"role": "user", "content": "完成恢复报告并核验"}],
        executor_factory=lambda: executor, finisher_provider=Provider("writer"),
        source_provider=planner, project_dir=str(tmp), max_iters=5, max_workers=1,
        approve=lambda _call: True)
    trace = result.get("trace", [])
    checks.append(_check("智能体恢复:失败回执后继续决策", executor.turns >= 3
                         and any(item.get("ok") is False for item in trace)))
    checks.append(_check("智能体恢复:换用工具并完成验收",
                         result.get("stopped") == "completed"
                         and result.get("task_results", {}).get("recover", {}).get("passed") is True))
    checks.append(_check("智能体恢复:真实产物存在",
                         (tmp / "outputs" / "recovery.md").is_file()
                         and (tmp / "outputs" / "recovery.md").read_text(encoding="utf-8").strip() == "recovered"))
    checks.append(_check("智能体恢复:失败工具未被无意义重复调用",
                         [item.get("name") for item in trace].count("missing_tool") == 1,
                         str([item.get("name") for item in trace])))
    return checks


# ---------------------------------------------------------------------------
# 注册表 + 运行器
# ---------------------------------------------------------------------------

CASES: dict = {
    "analysis_pipeline": (case_analysis_pipeline,
                          "实证分析编排:画像→推荐→脚本(统计外移)"),
    "meta_pipeline": (case_meta_pipeline,
                      "元分析编排:效应量表校验→脚本;致命缺陷 fail-closed"),
    "lit_screen": (case_lit_screen,
                   "文献初筛:计数自洽;零重叠诚实降级"),
    "gates_enforcement": (case_gates_enforcement,
                          "质量检查:合规通过/违规不通过/缺失 fail-closed"),
    "error_learning": (case_error_learning,
                       "错误自学习:三类蒸馏;ok 输出不误学;去重"),
    "toolloop_discipline": (case_toolloop_discipline,
                            "toolloop:失败回灌教训;重复止损;副作用需批准"),
    "delivery_contract": (case_delivery_contract,
                          "交付:确定性 DOCX、资料编译/交接审计、两入口路由"),
    "continuous_tasks": (case_continuous_tasks,
                          "连续任务:检索→下载、分析→写方法、生成→质检"),
    "langgraph_path": (case_langgraph_path,
                        "LangGraph:planner/executor/verifier/finisher 真路径"),
    "agent_capability_multiturn": (case_agent_capability_multiturn,
                                    "智能体能力:多轮工具回灌/依赖/验收"),
    "agent_capability_recovery": (case_agent_capability_recovery,
                                   "智能体能力:失败回灌/换策略/产物验收"),
}

# 面向发布的测评元数据。单项用例仍保持原有契约；元数据只负责把
# 回归结果聚合成可解释的质量维度，不把“测试通过率”冒充真实研究效果。
CASE_DIMENSIONS: dict[str, dict[str, object]] = {
    "analysis_pipeline": {"dimension": "研究编排", "weight": 1.2},
    "meta_pipeline": {"dimension": "研究编排", "weight": 1.2},
    "lit_screen": {"dimension": "证据与文献", "weight": 1.0},
    "gates_enforcement": {"dimension": "学术规范", "weight": 1.5},
    "error_learning": {"dimension": "可靠性", "weight": 1.0},
    "toolloop_discipline": {"dimension": "安全与可控", "weight": 1.5},
    "delivery_contract": {"dimension": "交付与复现", "weight": 1.0},
    "continuous_tasks": {"dimension": "可靠性", "weight": 1.5},
    "langgraph_path": {"dimension": "LangGraph 路径", "weight": 2.0},
    "agent_capability_multiturn": {"dimension": "智能体能力", "weight": 2.0},
    "agent_capability_recovery": {"dimension": "智能体能力", "weight": 2.0},
}


def _score_dimensions(cases: dict) -> dict:
    """按用例权重聚合维度分数；缺失/崩溃按 0 分处理。"""
    grouped: dict[str, dict[str, float]] = {}
    for cid, result in cases.items():
        meta = CASE_DIMENSIONS.get(cid, {"dimension": "未分类", "weight": 1.0})
        dim = str(meta["dimension"])
        weight = float(meta["weight"])
        bucket = grouped.setdefault(dim, {"earned": 0.0, "possible": 0.0})
        bucket["earned"] += result["passed"] * weight
        bucket["possible"] += result["total"] * weight
    out = {}
    for dim, vals in grouped.items():
        ratio = vals["earned"] / vals["possible"] if vals["possible"] else 0.0
        out[dim] = {"score": round(ratio * 100, 2),
                    "passed": int(vals["earned"]),
                    "total": int(vals["possible"])}
    return out


def run_evals(case_ids: list[str] | None = None) -> dict:
    """跑指定(默认全部)用例 → scorecard。用例崩溃记失败 check,不静默。"""
    import tempfile
    # 去重保序(feat-084):重复 --case 曾把 total/passed 记两遍而 cases 字典
    # 只留一份,合计与分项自相矛盾;同一用例跑两遍也不产生新信息。
    ids = list(dict.fromkeys(case_ids or list(CASES)))
    unknown = [i for i in ids if i not in CASES]
    if unknown:
        raise ValueError(f"未知评测用例:{unknown};可用:{list(CASES)}")

    cases: dict = {}
    total = passed_n = 0
    for cid in ids:
        fn, desc = CASES[cid]
        with tempfile.TemporaryDirectory(prefix=f"psyclaw_eval_{cid}_") as td:
            try:
                checks = fn(Path(td))
            except Exception as exc:  # noqa: BLE001  # 用例崩溃 = 失败,fail-closed
                checks = [_check(f"用例执行崩溃:{type(exc).__name__}", False, str(exc))]
        ok = sum(1 for c in checks if c["passed"])
        cases[cid] = {"description": desc, "checks": checks,
                      "passed": ok, "total": len(checks)}
        total += len(checks)
        passed_n += ok
    dimensions = _score_dimensions(cases)
    score = round((passed_n / total) * 100, 2) if total else 0.0
    # 发布门槛：总分 >= 90，且学术规范/安全与可控两个关键维度不能失守。
    critical_ok = all(dimensions.get(d, {}).get("score", 0) >= 90
                       for d in ("学术规范", "安全与可控", "LangGraph 路径"))
    return {"cases": cases, "total": total, "passed": passed_n,
            "failed": total - passed_n, "all_passed": passed_n == total,
            "score": score, "dimensions": dimensions,
            "release_verdict": bool(score >= 90 and critical_ok),
            "release_threshold": 90}


def format_report(report: dict) -> str:
    """人读 scorecard(确定性文本,不依赖终端宽度)。"""
    lines = ["评测 scorecard(确定性离线,不调 LLM/不联网/无统计库):", ""]
    for cid, c in report["cases"].items():
        mark = "✅" if c["passed"] == c["total"] else "❌"
        lines.append(f"{mark} {cid}({c['passed']}/{c['total']})—{c['description']}")
        for chk in c["checks"]:
            if not chk["passed"]:
                detail = f":{chk['detail']}" if chk["detail"] else ""
                lines.append(f"   ✗ {chk['name']}{detail}")
    lines.append("")
    lines.append(f"合计 {report['passed']}/{report['total']} 项通过"
                 + ("" if report["all_passed"] else f",{report['failed']} 项失败"))
    if report.get("dimensions"):
        lines.append(f"加权总分 {report.get('score', 0):.2f}/100")
        for dim, value in report["dimensions"].items():
            lines.append(f"  {dim}: {value['score']:.2f}/100")
        verdict = "可发布" if report.get("release_verdict") else "不可发布"
        lines.append(f"发布判定: {verdict}(门槛 {report.get('release_threshold', 90)})")
    return "\n".join(lines)
