"""确定性离线评测框架(eval harness,feat-073)。

评的是 psyclaw 自身的**编排 / 门禁 / 自学习契约**是否仍然成立——不调 LLM、
不联网、不依赖统计库(统计外移铁律),全部用例离线秒级可复跑,结果确定。
pytest 保证"函数各自正确",eval harness 保证"关键链路端到端仍守约",
且产出结构化 scorecard 供发布评估 / 回归对比。

用法:
    python -m psyclaw eval                       # 全部用例
    python -m psyclaw eval --case gates_enforcement
    python -m psyclaw eval --json                # 机器可读输出

每个用例 = 函数 `case_<id>(tmp: Path) -> list[check]`,check 为
{name, passed, detail};run_evals 汇总 scorecard 并由 CLI 落
<项目>/.psyclaw/eval_report.json。新增用例:写函数并注册进 CASES。
用例自身崩溃 → 记为失败 check(fail-closed),绝不静默跳过。
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


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
# 用例 4:门禁执行 —— 合规 sidecar 放行;缺效应量阻断;文件缺失 fail-closed
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
    checks.append(_check("门禁:合规统计产出放行(无 blocking)",
                         res["passed"] and not res["blocking"],
                         json.dumps(res["blocking"], ensure_ascii=False)[:300]))

    bad = dict(good)
    bad.pop("effect_size")
    bp = tmp / "stat_bad.json"
    bp.write_text(json.dumps(bad), encoding="utf-8")
    res2 = check_artifact(str(bp), "stat")
    hit = [b for b in res2["blocking"] if b["requirement"] in
           ("effect_size", "confidence_interval")]
    checks.append(_check("门禁:缺效应量+CI 被阻断(学术诚信铁律)",
                         not res2["passed"] and bool(hit),
                         json.dumps(res2["blocking"], ensure_ascii=False)[:300]))

    res3 = check_artifact(str(tmp / "missing.json"), "stat")
    checks.append(_check("门禁:产出物缺失 fail-closed 不放行",
                         not res3["passed"] and res3["blocking"]))

    (tmp / "broken.json").write_text("{not json", encoding="utf-8")
    res4 = check_artifact(str(tmp / "broken.json"), "stat")
    checks.append(_check("门禁:产出物不可解析 fail-closed 不放行",
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
                          "门禁:合规放行/违规阻断/缺失 fail-closed"),
    "error_learning": (case_error_learning,
                       "错误自学习:三类蒸馏;ok 输出不误学;去重"),
    "toolloop_discipline": (case_toolloop_discipline,
                            "toolloop:失败回灌教训;重复止损;副作用需批准"),
}


def run_evals(case_ids: list[str] | None = None) -> dict:
    """跑指定(默认全部)用例 → scorecard。用例崩溃记失败 check,不静默。"""
    import tempfile
    ids = case_ids or list(CASES)
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
    return {"cases": cases, "total": total, "passed": passed_n,
            "failed": total - passed_n, "all_passed": passed_n == total}


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
    return "\n".join(lines)
