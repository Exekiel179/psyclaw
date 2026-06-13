"""Mplus MCP 服务器 — 语法生成 + 批处理执行。

两种能力:
1. 语法生成(始终可用):把分析意图翻译为 Mplus .inp 文件,
   即使没装 Mplus 也能给可直接粘贴运行的脚本,且内置严谨性默认
   (全拟合指数、标准化输出、修正指数、种子随机数)。
2. 批处理执行(检测到 mplus 才启用):通过 `mplus` 命令跑 .inp 出 .out。

启动:python -m psyclaw.mcp.servers.mplus_server
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-mplus", "0.1.0")


def _mplus_exe() -> str | None:
    for name in ("mplus", "mplus.exe", "Mplus"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _footer(exe: str | None) -> str:
    if exe:
        return f"\n\n— 检测到 Mplus({exe}),可用 mplus_run 执行此 .inp —"
    return "\n\n— 未检测到 Mplus;以上语法可直接粘贴至 Mplus GUI 或命令行 `mplus file.inp` 运行 —"


@srv.tool(
    "mplus_syntax",
    "把分析意图翻译为 Mplus .inp 文件,内置全拟合指数/标准化/修正指数默认",
    {"properties": {
        "analysis": {
            "type": "string",
            "description": (
                "cfa — 验证性因子分析\n"
                "sem — 结构方程模型\n"
                "lgm — 潜变量增长模型\n"
                "mixture — LPA/GMM 潜类别/潜剖面"
            ),
        },
        "indicators": {
            "type": "string",
            "description": "观测变量列表(逗号分隔),如 'x1,x2,x3,y1,y2'",
        },
        "factors": {
            "type": "string",
            "description": "因子名及其指标(逗号分隔 'F1:x1 x2 x3,F2:y1 y2'),CFA/SEM 必填",
        },
        "structural": {
            "type": "string",
            "description": "结构路径(逗号分隔 'F2 ON F1,F3 ON F1 F2'),SEM 可选",
        },
        "time_points": {
            "type": "string",
            "description": "纵向测量时间点变量列表(空格/逗号分隔),LGM 必填,如 't1 t2 t3 t4'",
        },
        "n_classes": {
            "type": "integer",
            "description": "潜类别数(Mixture 必填,建议 2-6 比较)",
        },
        "data_file": {
            "type": "string",
            "description": "数据文件路径(.dat/.csv),默认 data.dat",
        },
        "estimator": {
            "type": "string",
            "description": "估计器:MLR(默认稳健;缺失数据自动 FIML) / ML / WLSMV(有序分类)",
        },
        "missing": {
            "type": "string",
            "description": "缺失值代码(默认 999)",
        },
    }, "required": ["analysis"]},
)
def mplus_syntax(args: dict) -> str:  # noqa: C901
    analysis = args.get("analysis", "").lower()
    indicators = args.get("indicators", "y1 y2 y3")
    if "," in indicators:
        indicators = " ".join(v.strip() for v in indicators.split(","))
    factors_raw = args.get("factors", "")
    structural_raw = args.get("structural", "")
    time_points_raw = args.get("time_points", "t1 t2 t3 t4")
    n_classes = int(args.get("n_classes", 2))
    data_file = args.get("data_file", "data.dat")
    estimator = args.get("estimator", "MLR")
    missing_code = args.get("missing", "999")

    # --- 因子定义解析 ---
    def _parse_factors(raw: str) -> list[tuple[str, str]]:
        """'F1:x1 x2,F2:y1 y2' -> [('F1','x1 x2'),('F2','y1 y2')]"""
        res = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if ":" in chunk:
                fname, inds = chunk.split(":", 1)
                res.append((fname.strip(), inds.strip()))
            elif chunk:
                res.append(("F", chunk))
        return res if res else [("F", indicators)]

    factor_list = _parse_factors(factors_raw) if factors_raw else [("F", indicators)]

    # --- 构建语法 ---
    title_map = {
        "cfa": "验证性因子分析(CFA)",
        "sem": "结构方程模型(SEM)",
        "lgm": "潜变量增长模型(LGM)",
        "mixture": "潜剖面/潜类别分析(LPA/GMM)",
    }
    title = title_map.get(analysis, analysis.upper())

    # 所有观测变量
    all_vars = indicators if not factors_raw else " ".join(inds for _, inds in factor_list)
    if analysis == "lgm":
        all_vars = " ".join(
            v.strip() for v in time_points_raw.replace(",", " ").split()
        )

    header = (
        f"TITLE: PsyClaw 生成 — {title};\n"
        f"\nDATA:\n"
        f"  FILE = \"{data_file}\";\n"
        f"\nVARIABLE:\n"
        f"  NAMES ARE {all_vars};\n"
        f"  USEVARIABLES ARE {all_vars};\n"
        f"  MISSING ARE ALL ({missing_code});\n"
    )

    if analysis == "cfa":
        model_lines = "\n".join(
            f"  {fname} BY {inds};"
            for fname, inds in factor_list
        )
        ana_block = (
            f"\nANALYSIS:\n"
            f"  TYPE = GENERAL;\n"
            f"  ESTIMATOR = {estimator};  ! FIML 处理缺失,MLR=稳健标准误\n"
        )
        model_block = f"\nMODEL:\n{model_lines}\n"
        output_block = (
            "\nOUTPUT:\n"
            "  STANDARDIZED SAMPSTAT MODINDICES(3.84);\n"
            "  ! 拟合指数报告:CFI>.95, RMSEA<.08(90%CI), SRMR<.08\n"
            "  ! 因子负荷≥.40,标准化残差查局部失拟\n"
        )
        notes = (
            "* 注:CFI>.95/RMSEA<.08 为可接受阈值(Hu & Bentler 1999);\n"
            "* MODINDICES 修正指数≥3.84(p<.05)才考虑添加路径/残差相关;\n"
            "* 跨组分析:加 GROUPING 参数并序贯检验不变性(见 M-3)。"
        )
        body = header + ana_block + model_block + output_block

    elif analysis == "sem":
        model_lines = "\n".join(
            f"  {fname} BY {inds};"
            for fname, inds in factor_list
        )
        struct_lines = ""
        if structural_raw:
            for path in structural_raw.split(","):
                struct_lines += f"\n  {path.strip()};"
        else:
            if len(factor_list) >= 2:
                struct_lines = f"\n  {factor_list[-1][0]} ON {factor_list[0][0]};"
        ana_block = (
            f"\nANALYSIS:\n"
            f"  TYPE = GENERAL;\n"
            f"  ESTIMATOR = {estimator};\n"
        )
        model_block = f"\nMODEL:\n{model_lines}{struct_lines}\n"
        output_block = (
            "\nOUTPUT:\n"
            "  STANDARDIZED SAMPSTAT MODINDICES(3.84) CINTERVAL;\n"
            "  ! CINTERVAL=95% 置信区间(含直/间接效应 Bootstrap CI 见 MODEL INDIRECT)\n"
        )
        notes = (
            "* 间接效应:MODEL INDIRECT 部分指定 y IND x,BOOTSTRAP=5000;\n"
            "* 有序指标:CATEGORICAL = var1 var2;ESTIMATOR = WLSMV;\n"
            "* 拟合指数:CFI>.95/RMSEA<.08/SRMR<.10(已有路径约束时 RMSEA 更严格)。"
        )
        body = header + ana_block + model_block + output_block

    elif analysis == "lgm":
        tp_list = time_points_raw.replace(",", " ").split()
        n_tp = len(tp_list)
        tp_str = " ".join(tp_list)
        time_scores = " ".join(f"{tp}@{i}" for i, tp in enumerate(tp_list))
        ana_block = (
            f"\nANALYSIS:\n"
            f"  TYPE = GENERAL;\n"
            f"  ESTIMATOR = {estimator};\n"
        )
        model_block = (
            f"\nMODEL:\n"
            f"  i s | {time_scores};\n"
            f"  ! i=截距(初始水平),s=斜率(增长速率)\n"
            f"  ! 线性增长假定:时间分数 0,1,...,{n_tp - 1}\n"
            f"  ! 非线性增长:自由估计 s | t1@0 t2* t3* t4@1 或改用二次项 q\n"
        )
        output_block = (
            "\nOUTPUT:\n"
            "  STANDARDIZED SAMPSTAT MODINDICES(3.84) CINTERVAL;\n"
        )
        notes = (
            f"* {n_tp} 个时间点;时间编码已设为 0-{n_tp - 1}(等间隔);\n"
            "* 显著斜率均值=整体增长,斜率方差=个体差异;\n"
            "* 多组/条件:ON 命令引入时间不变/变时间预测元。"
        )
        body = header + ana_block + model_block + output_block

    elif analysis == "mixture":
        tp_vars = ""
        tp_note = ""
        if time_points_raw and time_points_raw.strip():
            tp_list = time_points_raw.replace(",", " ").split()
            time_scores = " ".join(f"{tp}@{i}" for i, tp in enumerate(tp_list))
            tp_vars = f"\n  i s | {time_scores};  ! GMM=潜增长混合模型"
            tp_note = "* 去掉 i/s 行则为 LPA(无增长项的潜剖面分析);\n"
            all_vars = " ".join(tp_list)
            header = (
                f"TITLE: PsyClaw 生成 — {title};\n"
                f"\nDATA:\n"
                f"  FILE = \"{data_file}\";\n"
                f"\nVARIABLE:\n"
                f"  NAMES ARE {all_vars};\n"
                f"  USEVARIABLES ARE {all_vars};\n"
                f"  MISSING ARE ALL ({missing_code});\n"
                f"  CLASSES = c({n_classes});\n"
            )
        else:
            header = (
                f"TITLE: PsyClaw 生成 — {title};\n"
                f"\nDATA:\n"
                f"  FILE = \"{data_file}\";\n"
                f"\nVARIABLE:\n"
                f"  NAMES ARE {all_vars};\n"
                f"  USEVARIABLES ARE {all_vars};\n"
                f"  MISSING ARE ALL ({missing_code});\n"
                f"  CLASSES = c({n_classes});\n"
            )
        class_blocks = "  %OVERALL%\n"
        for k in range(1, n_classes + 1):
            class_blocks += f"\n  %c#{k}%\n  [{all_vars.split()[0]}] (mean{k});\n"
        ana_block = (
            f"\nANALYSIS:\n"
            f"  TYPE = MIXTURE;\n"
            f"  ESTIMATOR = {estimator};\n"
            f"  STARTS = 20 4;  ! 随机起始值(正式分析用 STARTS = 100 20)\n"
            f"  PROCESSORS = 4;\n"
        )
        model_block = f"\nMODEL:\n{class_blocks}{tp_vars}\n"
        output_block = (
            "\nOUTPUT:\n"
            "  STANDARDIZED SVALUES TECH11 TECH14;\n"
            "  ! TECH11=LMR-LRT 检验k vs k-1 类;TECH14=BLRT Bootstrap 检验\n"
        )
        notes = (
            f"* 比较 {n_classes} 类模型:BIC 越小越好(ABIC 更稳健);\n"
            f"{tp_note}"
            "* 剖面判读:Entropy>.80 表示分类清晰;各类 PP>0.70;\n"
            "* 决定类别数:BIC+BLRT(TECH14)+实质可解释性三角互证。"
        )
        body = header + ana_block + model_block + output_block

    else:
        avail = "cfa / sem / lgm / mixture"
        return f"未收录分析类型 '{analysis}'。可用:{avail}"

    exe = _mplus_exe()
    return f"{body}\n! === 使用说明 ===\n! {notes}\n" + _footer(exe)


@srv.tool(
    "mplus_run",
    "执行 Mplus .inp 文件(需本地安装 Mplus;未装时返回安装提示)",
    {"properties": {
        "inp_file": {"type": "string", "description": ".inp 路径(与 inp 参数二选一)"},
        "inp": {"type": "string", "description": "直接传入 .inp 语法字符串"},
        "work_dir": {"type": "string", "description": "工作目录(默认与 inp_file 同级)"},
    }, "required": []},
)
def mplus_run(args: dict) -> str:
    exe = _mplus_exe()
    if not exe:
        return (
            "未找到 Mplus 可执行文件。\n"
            "安装说明:购买并安装 Mplus(https://www.statmodel.com),"
            "确保 `mplus` 在 PATH 中;\n"
            "或使用 mplus_syntax 生成 .inp 后手动在 Mplus GUI 运行。"
        )
    inp_file = args.get("inp_file")
    if not inp_file:
        raw = args.get("inp")
        if not raw:
            return "需提供 inp_file 路径或 inp 语法字符串。"
        tmp = Path(tempfile.gettempdir()) / "psyclaw_mplus.inp"
        tmp.write_text(raw, encoding="utf-8")
        inp_file = str(tmp)
    inp_path = Path(inp_file)
    work_dir = args.get("work_dir") or str(inp_path.parent)
    try:
        r = subprocess.run(
            [exe, inp_path.name],
            cwd=work_dir,
            capture_output=True, text=True, timeout=600,
        )
        out_file = inp_path.with_suffix(".out")
        out_text = ""
        if out_file.exists():
            out_text = out_file.read_text(encoding="utf-8", errors="replace")[:8000]
        combined = (r.stdout or "") + (r.stderr or "")
        return (
            f"[Mplus 退出码 {r.returncode}]\n"
            f"{combined[:2000]}\n"
            f"--- .out 文件(前 8000 字符) ---\n{out_text}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Mplus 执行失败:{exc}"


if __name__ == "__main__":
    raise SystemExit(srv.run())
