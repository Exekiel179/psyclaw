"""SPSS MCP 服务器 — 语法生成 + 批处理执行。

两种能力:
1. 语法生成(始终可用):把分析意图翻译成 SPSS 语法(.sps),
   即使没装 SPSS 也能给可粘贴到 SPSS 的代码,且内置严谨性默认
   (效应量、稳健选项、假设检查)。
2. 批处理执行(检测到 SPSS 才启用):通过 `pythonx`/`spssjob` 或
   IBM Statistics Batch Facility(stats / statisticsb)跑 .sps 出 .spv/输出。

启动:python -m psyclaw.mcp.servers.spss_server
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-spss", "0.1.0")


def _spss_exe() -> str | None:
    for name in ("stats", "statisticsb", "spss", "pasw"):
        p = shutil.which(name)
        if p:
            return p
    return None


@srv.tool("spss_syntax",
          "把分析意图翻译为 SPSS 语法(.sps),内置效应量/假设检查/稳健选项默认",
          {"properties": {
              "analysis": {"type": "string",
                           "description": "ttest_ind | ttest_paired | anova_oneway | "
                                          "ancova | regression | correlation | "
                                          "reliability | factor | chisquare | descriptives"},
              "dv": {"type": "string", "description": "因变量(或条目列表,逗号分隔)"},
              "iv": {"type": "string", "description": "自变量/分组变量(可空)"},
              "covariates": {"type": "string", "description": "协变量,逗号分隔(可空)"},
          }, "required": ["analysis"]})
def spss_syntax(args: dict) -> str:
    a = args["analysis"].lower()
    dv = args.get("dv", "DV")
    iv = args.get("iv", "")
    cov = args.get("covariates", "")
    cov_list = " ".join(c.strip() for c in cov.split(",") if c.strip())

    gen = {
        "descriptives":
            f"EXAMINE VARIABLES={dv}\n  /PLOT BOXPLOT HISTOGRAM NPPLOT\n"
            f"  /STATISTICS DESCRIPTIVES\n  /MISSING LISTWISE.\n"
            f"* 含正态性检验(Shapiro)、偏度峰度、箱线图查异常值。",
        "ttest_ind":
            f"T-TEST GROUPS={iv}\n  /VARIABLES={dv}\n  /CRITERIA=CI(.95).\n"
            f"* SPSS 同时输出 Levene 检验与方差不齐校正行(看 Levene 显著则取下行)。\n"
            f"* 效应量:SPSS≥27 勾选 Estimate effect sizes(Cohen's d + 95%CI)。",
        "ttest_paired":
            f"T-TEST PAIRS={dv} WITH {iv} (PAIRED)\n  /CRITERIA=CI(.95).\n"
            f"* 报告 Cohen's dz;先对差值查正态(EXAMINE 差值变量)。",
        "anova_oneway":
            f"ONEWAY {dv} BY {iv}\n  /STATISTICS DESCRIPTIVES HOMOGENEITY WELCH\n"
            f"  /POSTHOC=GH ALPHA(.05).\n"
            f"* HOMOGENEITY=Levene;WELCH=方差不齐稳健 F;GH=Games-Howell 事后。\n"
            f"* 效应量 eta²:改用 UNIANOVA {dv} BY {iv} /PRINT=ETASQ。",
        "ancova":
            f"UNIANOVA {dv} BY {iv} WITH {cov_list}\n"
            f"  /PRINT=ETASQ HOMOGENEITY PARAMETER\n"
            f"  /EMMEANS=TABLES({iv}) WITH({cov_list} MEAN) COMPARE ADJ(BONFERRONI)\n"
            f"  /DESIGN={cov_list} {iv} {iv}*{cov_list.split()[0] if cov_list else ''}.\n"
            f"* 最后一行交互项=检验回归斜率同质性(应不显著);确认后删交互项重跑。",
        "regression":
            f"REGRESSION\n  /STATISTICS COEFF OUTS CI(95) R ANOVA COLLIN TOL\n"
            f"  /DEPENDENT {dv}\n  /METHOD=ENTER {iv} {cov_list}\n"
            f"  /RESIDUALS DURBIN\n  /CASEWISE PLOT(ZRESID) OUTLIERS(3)\n"
            f"  /SAVE COOK ZRESID.\n"
            f"* COLLIN TOL=共线性(VIF=1/TOL,>5 警惕);DURBIN=残差独立;COOK=影响点。",
        "correlation":
            f"CORRELATIONS\n  /VARIABLES={dv} {iv}\n  /PRINT=TWOTAIL NOSIG\n"
            f"  /STATISTICS DESCRIPTIVES.\n"
            f"* 先看散点(GRAPH /SCATTERPLOT)判线性;非线性或离群多改 NONPAR CORR(Spearman)。",
        "reliability":
            f"RELIABILITY\n  /VARIABLES={dv}\n  /SCALE('量表') ALL\n"
            f"  /MODEL=ALPHA\n  /STATISTICS=DESCRIPTIVE SCALE CORR\n"
            f"  /SUMMARY=TOTAL.\n"
            f"* SUMMARY=TOTAL 给逐题删除后 α(定位坏条目);反向题先 RECODE。\n"
            f"* α 仅 tau 等价下准确;条件允许时改报 ω(需 OMEGA 或 R)。",
        "factor":
            f"FACTOR\n  /VARIABLES={dv}\n  /PRINT=KMO INITIAL EXTRACTION ROTATION\n"
            f"  /CRITERIA=FACTORS(0)\n  /EXTRACTION=PAF\n"
            f"  /ROTATION=PROMAX\n  /PLOT=EIGEN.\n"
            f"* KMO≥.60 才宜做;PAF=主轴因子(非主成分);PROMAX=斜交旋转。\n"
            f"* 因子数用平行分析定(SPSS 需额外宏/插件),碎石图仅参考。",
        "chisquare":
            f"CROSSTABS\n  /TABLES={dv} BY {iv}\n  /STATISTICS=CHISQ PHI\n"
            f"  /CELLS=COUNT EXPECTED.\n"
            f"* 查期望频次<5 的单元格(>20% 则用 Fisher);PHI/Cramér's V=效应量。",
    }
    syntax = gen.get(a)
    if not syntax:
        return f"未收录分析 '{a}'。可用:{', '.join(gen)}"
    avail = _spss_exe()
    foot = (f"\n\n— 检测到 SPSS 批处理({avail}),可用 spss_run 执行此语法 —"
            if avail else
            "\n\n— 未检测到 SPSS 批处理;以上语法可直接粘贴进 SPSS 语法窗口运行 —")
    return f"* PsyClaw 生成的 SPSS 语法({a}),含严谨性默认 *\n{syntax}{foot}"


@srv.tool("spss_run",
          "执行 .sps 语法文件(需本地 IBM SPSS Statistics Batch Facility)",
          {"properties": {
              "syntax_file": {"type": "string", "description": ".sps 路径(留空则用 syntax 参数)"},
              "syntax": {"type": "string", "description": "直接传入语法字符串"},
          }, "required": []})
def spss_run(args: dict) -> str:
    exe = _spss_exe()
    if not exe:
        return ("未找到 SPSS 批处理可执行文件(stats/statisticsb)。"
                "请装 IBM SPSS Statistics 并确保其 bin 在 PATH;"
                "或把 spss_syntax 生成的语法手动粘进 SPSS 运行。")
    sps = args.get("syntax_file")
    if not sps:
        if not args.get("syntax"):
            return "需提供 syntax_file 或 syntax。"
        tmp = Path(tempfile.gettempdir()) / "psyclaw_job.sps"
        tmp.write_text(args["syntax"], encoding="utf-8")
        sps = str(tmp)
    try:
        r = subprocess.run([exe, "-f", sps], capture_output=True, text=True, timeout=600)
        out = (r.stdout or "") + (r.stderr or "")
        return f"[SPSS 退出码 {r.returncode}]\n{out[:6000]}"
    except Exception as exc:  # noqa: BLE001
        return f"SPSS 执行失败:{exc}"


if __name__ == "__main__":
    raise SystemExit(srv.run())
