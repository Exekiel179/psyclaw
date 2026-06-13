"""Stata MCP 服务器 — do-file 生成 + 批处理执行。

两种能力:
1. do-file 生成(始终可用):把分析意图翻译为 Stata do-file(.do),
   即使没装 Stata 也能给可直接运行的代码,且内置严谨性默认
   (稳健标准误 robust/cluster、效应量、假设检查)。
2. 批处理执行(检测到 Stata 才启用):通过 `stata -b do file.do` 跑 .do 出 .log。

启动:python -m psyclaw.mcp.servers.stata_server
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-stata", "0.1.0")


def _stata_exe() -> str | None:
    for name in ("stata", "stata-mp", "stata-se", "stata-be", "StataMP", "StataSE"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _footer(exe: str | None) -> str:
    if exe:
        return f"\n\n* — 检测到 Stata({exe}),可用 stata_run 执行此 do-file —"
    return (
        "\n\n* — 未检测到 Stata;以上 do-file 可直接粘贴至 Stata 命令窗口,"
        "\n*   或保存为 .do 文件后 `do file.do` / File → Do 运行 —"
    )


@srv.tool(
    "stata_dofile",
    "把分析意图翻译为 Stata do-file,内置稳健标准误/效应量/假设检查默认",
    {"properties": {
        "analysis": {
            "type": "string",
            "description": (
                "regression — OLS 回归(稳健/聚类标准误)\n"
                "panel — 面板数据(FE/RE/Hausman 检验)\n"
                "iv — 工具变量(2SLS/弱工具变量检验)\n"
                "logistic — 二元 Logistic 回归(OR + 边际效应)\n"
                "survival — 生存分析(KM + Cox 比例风险)\n"
                "poisson — 泊松/负二项回归(IRR)"
            ),
        },
        "dv": {"type": "string", "description": "因变量列名"},
        "iv": {"type": "string", "description": "自变量/预测变量(空格分隔)"},
        "controls": {"type": "string", "description": "控制变量(空格分隔,可空)"},
        "cluster": {"type": "string", "description": "聚类变量(面板/聚类标准误,可空)"},
        "panel_id": {"type": "string", "description": "个体 ID 变量(面板必填)"},
        "panel_time": {"type": "string", "description": "时间变量(面板必填)"},
        "instruments": {"type": "string", "description": "工具变量(IV 必填)"},
        "endog": {"type": "string", "description": "内生变量(IV 必填)"},
        "time_var": {"type": "string", "description": "时间/生存时间变量(生存分析必填)"},
        "event_var": {"type": "string", "description": "事件指示变量 0/1(生存分析必填)"},
        "data_file": {"type": "string", "description": "数据文件路径(.dta/.csv),可空"},
    }, "required": ["analysis"]},
)
def stata_dofile(args: dict) -> str:  # noqa: C901
    analysis = args.get("analysis", "").lower()
    dv = args.get("dv", "y")
    iv_raw = args.get("iv", "x").strip()
    controls_raw = args.get("controls", "").strip()
    cluster = args.get("cluster", "").strip()
    panel_id = args.get("panel_id", "id").strip()
    panel_time = args.get("panel_time", "t").strip()
    instruments = args.get("instruments", "z").strip()
    endog = args.get("endog", "x").strip()
    time_var = args.get("time_var", "time").strip()
    event_var = args.get("event_var", "event").strip()
    data_file = args.get("data_file", "").strip()

    preamble = "* PsyClaw 生成的 Stata do-file — 含严谨性默认\n"
    if data_file:
        ext = Path(data_file).suffix.lower()
        if ext == ".dta":
            preamble += f'use "{data_file}", clear\n'
        elif ext == ".csv":
            preamble += f'import delimited "{data_file}", clear\n'
        else:
            preamble += f'use "{data_file}", clear\n'
    preamble += "\nset more off\n"

    xvars = " ".join(filter(None, [iv_raw, controls_raw]))
    se_opt = f"vce(cluster {cluster})" if cluster else "robust"

    if analysis == "regression":
        body = (
            f"\n* --- OLS 回归 ---\n"
            f"regress {dv} {xvars}, {se_opt}\n"
            f"est store ols_1\n"
            f"\n* 效应量:标准化 β(ssc install estout 后可用 estadd)\n"
            f"* Stata≥17:estat esize 报 Cohen's f²\n"
            f"* 假设检查:\n"
            f"predict resid, residuals\n"
            f"predict yhat, xb\n"
            f"scatter resid yhat, yline(0) title(\"残差 vs 拟合值\")  // 检查异方差\n"
            f"swilk resid                              // Shapiro-Wilk 正态检验\n"
            f"estat vif                                // VIF 共线性\n"
            f"estat hettest                            // Breusch-Pagan 异方差\n"
            f"estat dwatson                            // Durbin-Watson 自相关(截面数据忽略)\n"
            f"\n* 报告格式:esttab ols_1, beta se label\n"
        )
        notes = (
            "* robust/cluster 标准误使用 HC3 稳健修正;\n"
            "* VIF>5 → 共线性警惕,>10 → 严重;\n"
            "* hettest 显著 → 已用稳健标准误,可加 vce(hc3)。"
        )

    elif analysis == "panel":
        body = (
            f"\n* --- 面板数据 ---\n"
            f"xtset {panel_id} {panel_time}\n"
            f"\n* 固定效应(FE):控制不可观测的个体异质性\n"
            f"xtreg {dv} {xvars}, fe {se_opt}\n"
            f"est store fe\n"
            f"\n* 随机效应(RE)\n"
            f"xtreg {dv} {xvars}, re {se_opt}\n"
            f"est store re\n"
            f"\n* Hausman 检验:拒 H0 → 选 FE;不拒 → RE 更有效\n"
            f"hausman fe re\n"
            f"\n* 组内相关(ICC)\n"
            f"xtreg {dv} {xvars}, re\n"
            f"display e(sigma_u)^2 / (e(sigma_u)^2 + e(sigma_e)^2)  // ICC\n"
        )
        notes = (
            "* Hausman p<.05 → 选 FE(RE 有偏);\n"
            "* 时间固定效应:加 i.year;\n"
            "* 动态面板(Arellano-Bond):xtabond2(ssc install xtabond2)。"
        )

    elif analysis == "iv":
        body = (
            f"\n* --- 工具变量 2SLS ---\n"
            f"* 内生变量:{endog};工具变量:{instruments}\n"
            f"ivregress 2sls {dv} ({endog} = {instruments}) {controls_raw}, {se_opt}\n"
            f"est store iv_2sls\n"
            f"\n* 弱工具变量检验(First-stage F≥10 为经验阈值)\n"
            f"estat firststage\n"
            f"\n* Cragg-Donald/Kleibergen-Paap F 统计量(Stock-Yogo 临界值)\n"
            f"ivregress 2sls {dv} ({endog} = {instruments}) {controls_raw}, {se_opt} first\n"
            f"\n* Hausman/Durbin-Wu-Hausman 内生性检验\n"
            f"estat endogenous\n"
            f"\n* Sargan/Hansen 过度识别检验(工具数>内生数时才有)\n"
            f"estat overid\n"
        )
        notes = (
            "* First-stage F<10 → 弱工具变量,结论不稳定;\n"
            "* overid 显著 → 至少一个工具不外生;\n"
            f"* 有效工具须与 {endog} 相关(相关性),且仅通过 {endog} 影响 {dv}(排除性)。"
        )

    elif analysis == "logistic":
        body = (
            f"\n* --- Logistic 回归 ---\n"
            f"logit {dv} {xvars}, {se_opt}\n"
            f"est store logit_1\n"
            f"\n* 优势比(OR)+ 95% CI\n"
            f"logit {dv} {xvars}, {se_opt} or\n"
            f"\n* 平均边际效应(AME)\n"
            f"margins, dydx(*)\n"
            f"\n* 模型拟合:Pseudo R²(McFadden) + Hosmer-Lemeshow\n"
            f"estat gof, group(10) table   // Hosmer-Lemeshow\n"
            f"lroc                         // ROC 曲线 + AUC\n"
            f"\n* 多分类 Logistic(有序):ologit {dv} {xvars}, {se_opt}\n"
            f"* 无序多分类:mlogit {dv} {xvars}, base(1) {se_opt}\n"
        )
        notes = (
            "* OR 不等于 RR(风险比);高发生率时需 Poisson 或对数二项估计;\n"
            "* AME 更易解读于 OR;报告 AME 时需说明连续变量对应 1 单位增量;\n"
            "* Pseudo R²<.2 常见,重要的是分类精度(ROC/AUC)。"
        )

    elif analysis == "survival":
        body = (
            f"\n* --- 生存分析 ---\n"
            f"stset {time_var}, failure({event_var}==1)\n"
            f"\n* Kaplan-Meier 生存曲线\n"
            f"sts graph, by({iv_raw}) risktable\n"
            f"sts test {iv_raw}    // log-rank 检验\n"
            f"\n* Cox 比例风险模型\n"
            f"stcox {xvars}, {se_opt}\n"
            f"est store cox_1\n"
            f"\n* 比例风险假定检验\n"
            f"estat phtest, detail    // Schoenfeld 残差检验\n"
            f"\n* 风险比(HR)+ 95% CI\n"
            f"stcox {xvars}, {se_opt} hr\n"
        )
        notes = (
            "* Cox HR 假定比例风险(Schoenfeld p>.05);\n"
            "* 违反比例假定:时间依赖协变量(stcox ... tvc(var))或分层 strata(var);\n"
            "* 竞争风险:stcrprep + stcox 或 stcompet(ssc)。"
        )

    elif analysis == "poisson":
        body = (
            f"\n* --- 泊松/负二项回归 ---\n"
            f"poisson {dv} {xvars}, {se_opt} irr\n"
            f"est store poisson_1\n"
            f"\n* 过离散检验(Cameron & Trivedi 1990)\n"
            f"estat gof\n"
            f"* 若 alpha 显著 → 改用负二项\n"
            f"nbreg {dv} {xvars}, {se_opt} irr\n"
            f"est store nbreg_1\n"
            f"\n* 零膨胀:若零过多 → zip/zinb\n"
            f"zip {dv} {xvars}, inflate({iv_raw}) {se_opt}\n"
        )
        notes = (
            "* irr 参数输出发生率比(IRR = exp(β));\n"
            "* 过离散(alpha 显著)→ 负二项更适合;\n"
            "* 零膨胀(零比例>>理论)→ zip/zinb。"
        )

    else:
        avail = "regression / panel / iv / logistic / survival / poisson"
        return f"未收录分析类型 '{analysis}'。可用:{avail}"

    exe = _stata_exe()
    return preamble + body + f"\n{notes}\n" + _footer(exe)


@srv.tool(
    "stata_run",
    "批处理执行 Stata do-file(需本地安装 Stata;未装时返回安装提示)",
    {"properties": {
        "do_file": {"type": "string", "description": ".do 路径(与 do_code 参数二选一)"},
        "do_code": {"type": "string", "description": "直接传入 do-file 代码字符串"},
    }, "required": []},
)
def stata_run(args: dict) -> str:
    exe = _stata_exe()
    if not exe:
        return (
            "未找到 Stata 可执行文件(stata/stata-mp/stata-se)。\n"
            "安装说明:购买并安装 Stata(https://www.stata.com),"
            "确保其可执行文件在 PATH 中;\n"
            "或使用 stata_dofile 生成 do-file 后手动在 Stata 中运行。"
        )
    do_file = args.get("do_file")
    if not do_file:
        raw = args.get("do_code")
        if not raw:
            return "需提供 do_file 路径或 do_code 字符串。"
        tmp = Path(tempfile.gettempdir()) / "psyclaw_stata.do"
        tmp.write_text(raw, encoding="utf-8")
        do_file = str(tmp)
    do_path = Path(do_file)
    log_path = do_path.with_suffix(".log")
    try:
        r = subprocess.run(
            [exe, "-b", "do", str(do_path)],
            cwd=str(do_path.parent),
            capture_output=True, text=True, timeout=600,
        )
        log_text = ""
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")[:8000]
        combined = (r.stdout or "") + (r.stderr or "")
        return (
            f"[Stata 退出码 {r.returncode}]\n"
            f"{combined[:2000]}\n"
            f"--- .log 文件(前 8000 字符) ---\n{log_text}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Stata 执行失败:{exc}"


if __name__ == "__main__":
    raise SystemExit(srv.run())
