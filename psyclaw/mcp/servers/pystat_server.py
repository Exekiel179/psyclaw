"""pingouin/statsmodels MCP 服务器 — 常规统计后端(描述/t 检验/相关/方差/回归)。

闭环「统计外移到 MCP」:psyclaw 本体不算统计,把常规推断委托给成熟库。pingouin/pandas
在则真跑并返回带**效应量 + 95% CI**的结果(符合 gates STAT.effect_size);不在则返回
可直接运行的脚本骨架(确定性,不假装算出结果),装好即可跑。

启动:python -m psyclaw.mcp.servers.pystat_server
依赖:pip install 'psyclaw[stats]'(pingouin/pandas/scipy;可选,未装时工具返回脚本模板)

铁律:本文件顶层**不 import 任何统计库**——统计只在工具被调、且库存在时惰性发生。
"""

from __future__ import annotations

import json

from psyclaw.mcp.server_base import MCPServer

srv = MCPServer("psyclaw-pystat", "0.1.0")


def _has_pingouin() -> bool:
    try:
        import pingouin  # noqa: F401
        import pandas  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


_INSTALL = "pip install 'psyclaw[stats]'(pingouin/pandas/scipy)"


def _script_reply(script: str, note: str = "") -> str:
    head = ("pingouin 已就绪,以下脚本可直接运行:\n" if _has_pingouin()
            else f"统计库未安装({_INSTALL})。脚本骨架(装好可直接运行):\n")
    return head + "```python\n" + script + "\n```" + (("\n\n" + note) if note else "")


def _run(fn):
    """有 pingouin 就真跑返回 JSON;否则返回脚本骨架。fn() -> (result_obj, script, note)。"""
    obj, script, note = fn()
    if not _has_pingouin() or obj is None:
        return _script_reply(script, note)
    payload = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return payload + (("\n\n" + note) if note else "")


_CI_NOTE = ("严谨性:效应量 + 95% CI 已随结果给出(gates 要求);报告前请核前提"
            "(正态/方差齐/独立),不满足改稳健替代(Welch/非参/bootstrap);"
            "p 值不单独下结论,区分探索/确证。")


@srv.tool("pystat_describe", "描述统计(M/SD/n/偏度/峰度/95%CI 均值),按列或分组",
          {"properties": {
              "csv_path": {"type": "string"},
              "columns": {"type": "string", "description": "逗号分隔列名;省略=全部数值列"},
          }, "required": ["csv_path"]})
def pystat_describe(args: dict) -> str:
    csv_path = args["csv_path"]
    cols = args.get("columns", "")
    sel = ("[" + ", ".join(f"'{c.strip()}'" for c in cols.split(",") if c.strip()) + "]"
           if cols else "df.select_dtypes('number').columns.tolist()")
    script = (f"import pandas as pd, pingouin as pg\n"
              f"df = pd.read_csv('{csv_path}')\n"
              f"cols = {sel}\n"
              f"print(df[cols].describe().T)\n"
              f"for c in cols:\n"
              f"    ci = pg.compute_bootci(df[c].dropna(), func='mean', n_boot=5000, seed=42)\n"
              f"    print(c, 'mean 95%CI', ci)")

    def _do():
        if not _has_pingouin():
            return None, script, _CI_NOTE
        import pandas as pd
        import pingouin as pg
        df = pd.read_csv(csv_path)
        columns = ([c.strip() for c in cols.split(",") if c.strip()] if cols
                   else df.select_dtypes("number").columns.tolist())
        out = {}
        for c in columns:
            s = df[c].dropna()
            ci = pg.compute_bootci(s, func="mean", n_boot=5000, seed=42)
            out[c] = {"n": int(s.size), "mean": float(s.mean()), "sd": float(s.std()),
                      "skew": float(s.skew()), "kurtosis": float(s.kurtosis()),
                      "mean_ci95": [float(ci[0]), float(ci[1])]}
        return out, script, _CI_NOTE
    return _run(_do)


@srv.tool("pystat_ttest", "t 检验(独立/配对),含 Cohen's d + 95%CI + 前提检验",
          {"properties": {
              "csv_path": {"type": "string"},
              "dv": {"type": "string", "description": "因变量列(数值)"},
              "group": {"type": "string", "description": "分组列(独立样本,2 组)"},
              "paired_with": {"type": "string", "description": "配对第二列(配对样本)"},
          }, "required": ["csv_path", "dv"]})
def pystat_ttest(args: dict) -> str:
    csv_path, dv = args["csv_path"], args["dv"]
    group, paired = args.get("group", ""), args.get("paired_with", "")
    if paired:
        body = (f"a, b = df['{dv}'], df['{paired}']\n"
                f"res = pg.ttest(a, b, paired=True)")
    else:
        body = (f"grp = df['{group}'].dropna().unique()\n"
                f"a = df[df['{group}']==grp[0]]['{dv}']\n"
                f"b = df[df['{group}']==grp[1]]['{dv}']\n"
                f"res = pg.ttest(a, b, correction='auto')  # Welch 自动")
    script = (f"import pandas as pd, pingouin as pg\n"
              f"df = pd.read_csv('{csv_path}')\n{body}\n"
              f"print(res[['T','dof','p-val','cohen-d','CI95%']])")

    def _do():
        if not _has_pingouin():
            return None, script, _CI_NOTE
        import pandas as pd
        import pingouin as pg
        df = pd.read_csv(csv_path)
        if paired:
            res = pg.ttest(df[dv], df[paired], paired=True)
        else:
            grp = df[group].dropna().unique()
            if len(grp) != 2:
                return {"error": f"分组列 {group} 需恰好 2 组,得到 {len(grp)}"}, script, _CI_NOTE
            a = df[df[group] == grp[0]][dv]
            b = df[df[group] == grp[1]][dv]
            res = pg.ttest(a, b, correction="auto")
        row = res.iloc[0].to_dict()
        return {k: (list(v) if hasattr(v, "__iter__") and not isinstance(v, str)
                    else v) for k, v in row.items()}, script, _CI_NOTE
    return _run(_do)


@srv.tool("pystat_correlation", "相关(pearson/spearman),含 r + 95%CI + p",
          {"properties": {
              "csv_path": {"type": "string"},
              "x": {"type": "string"}, "y": {"type": "string"},
              "method": {"type": "string", "description": "pearson(默认)/spearman"},
          }, "required": ["csv_path", "x", "y"]})
def pystat_correlation(args: dict) -> str:
    csv_path, x, y = args["csv_path"], args["x"], args["y"]
    method = args.get("method", "pearson")
    script = (f"import pandas as pd, pingouin as pg\n"
              f"df = pd.read_csv('{csv_path}')\n"
              f"res = pg.corr(df['{x}'], df['{y}'], method='{method}')\n"
              f"print(res[['n','r','CI95%','p-val']])")

    def _do():
        if not _has_pingouin():
            return None, script, _CI_NOTE
        import pandas as pd
        import pingouin as pg
        df = pd.read_csv(csv_path)
        res = pg.corr(df[x], df[y], method=method)
        row = res.iloc[0].to_dict()
        return {k: (list(v) if hasattr(v, "__iter__") and not isinstance(v, str)
                    else v) for k, v in row.items()}, script, _CI_NOTE
    return _run(_do)


@srv.tool("pystat_anova", "单因素方差分析(between),含 eta²/omega² + 事后",
          {"properties": {
              "csv_path": {"type": "string"},
              "dv": {"type": "string"},
              "between": {"type": "string", "description": "组别列"},
          }, "required": ["csv_path", "dv", "between"]})
def pystat_anova(args: dict) -> str:
    csv_path, dv, between = args["csv_path"], args["dv"], args["between"]
    script = (f"import pandas as pd, pingouin as pg\n"
              f"df = pd.read_csv('{csv_path}')\n"
              f"aov = pg.anova(data=df, dv='{dv}', between='{between}', detailed=True)\n"
              f"print(aov)   # np2 = partial eta-squared 效应量\n"
              f"ph = pg.pairwise_tests(data=df, dv='{dv}', between='{between}', "
              f"padjust='holm', effsize='hedges')\nprint(ph)")

    def _do():
        if not _has_pingouin():
            return None, script, _CI_NOTE
        import pandas as pd
        import pingouin as pg
        df = pd.read_csv(csv_path)
        aov = pg.anova(data=df, dv=dv, between=between, detailed=True)
        return {"anova": aov.to_dict("records")}, script, _CI_NOTE
    return _run(_do)


@srv.tool("pystat_regression", "多元线性回归(OLS),含标准化 β + 95%CI + R²",
          {"properties": {
              "csv_path": {"type": "string"},
              "dv": {"type": "string"},
              "predictors": {"type": "string", "description": "逗号分隔自变量列"},
          }, "required": ["csv_path", "dv", "predictors"]})
def pystat_regression(args: dict) -> str:
    csv_path, dv = args["csv_path"], args["dv"]
    preds = [p.strip() for p in args["predictors"].split(",") if p.strip()]
    plist = "[" + ", ".join(f"'{p}'" for p in preds) + "]"
    script = (f"import pandas as pd, pingouin as pg\n"
              f"df = pd.read_csv('{csv_path}')\n"
              f"res = pg.linear_regression(df[{plist}], df['{dv}'])\n"
              f"print(res[['names','coef','se','T','pval','r2','CI[2.5%]','CI[97.5%]']])")

    def _do():
        if not _has_pingouin():
            return None, script, _CI_NOTE
        import pandas as pd
        import pingouin as pg
        df = pd.read_csv(csv_path)
        res = pg.linear_regression(df[preds], df[dv])
        return {"coefficients": res.to_dict("records")}, script, _CI_NOTE
    return _run(_do)


@srv.tool("pystat_guidance", "选检验/查前提指引(不算数,给方法学建议)",
          {"properties": {"question": {"type": "string"}}, "required": []})
def pystat_guidance(args: dict) -> str:
    return (
        "选检验速查:\n"
        "- 两组均值:独立→pystat_ttest(Welch 稳健);配对→paired_with。前提不满足→"
        "Mann-Whitney/Wilcoxon(非参)。\n"
        "- 3+ 组均值:pystat_anova(+Holm 事后);方差不齐→Welch ANOVA;非正态→Kruskal-Wallis。\n"
        "- 两连续变量关系:pystat_correlation(非正态/序数→spearman)。相关≠因果。\n"
        "- 多自变量预测:pystat_regression(报标准化 β+CI+R²;查多重共线/残差/杠杆)。\n"
        "通则(gates):效应量 + 95%CI 必报;先验功效定样本量;确证研究先预注册;"
        "多重比较须校正;不 p-hacking、不 HARKing。")


if __name__ == "__main__":
    raise SystemExit(srv.run())
