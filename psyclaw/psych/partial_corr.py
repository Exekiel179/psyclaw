"""偏相关分析（Partial Correlation）— APA-7 格式（stdlib only）。

提供：
  - partial_correlation: 控制一个或多个协变量后的偏相关系数 r
  - semipartial_correlation: 半偏相关（part correlation，仅对 x 或 y 去除控制变量影响）
  - partial_correlation_matrix: 偏相关矩阵（对所有变量对控制同一协变量集）
  - APA-7 Markdown 汇总表 + 文字段落
  - CSV 主入口 + MD/JSON sidecar + CLI

理论依据：
  Cohen, J., Cohen, P., West, S. G., & Aiken, L. S. (2003). Applied multiple regression/
    correlation analysis for the behavioral sciences (3rd ed.). Lawrence Erlbaum.
  Olkin, I., & Finn, J. D. (1995). Correlations redux.
    Psychological Bulletin, 118(1), 155–164. https://doi.org/10.1037/0033-2909.118.1.155
  Pearson, K. (1896). Mathematical contributions to the theory of evolution.
    Proceedings of the Royal Society of London, 60, 489–498.

CLI:
  psyclaw partial-corr <data.csv> --x col --y col [--controls c1,c2,...]
          [--semi] [--which x|y] [--matrix col1,col2,...]
          [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import special, stats


# ---------------------------------------------------------------------------
# 矩阵工具（Gauss-Jordan，stdlib only）
# ---------------------------------------------------------------------------

def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
    return np.asarray(A, dtype=float).T.tolist()


def _mat_mult(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return (np.asarray(A, dtype=float) @ np.asarray(B, dtype=float)).tolist()


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return (np.asarray(A, dtype=float) @ np.asarray(v, dtype=float)).tolist()


def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    try:
        return np.linalg.inv(np.asarray(M, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        return None


# ---------------------------------------------------------------------------
# 统计工具（t 分布、正态分布分位数，stdlib only）
# ---------------------------------------------------------------------------

def _t_sf2(t: float, df: float) -> float:
    """t 分布双尾 p 值 —— scipy.stats.t.sf。"""
    if df <= 0:
        return float("nan")
    return 2.0 * float(stats.t.sf(abs(t), df))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


# ---------------------------------------------------------------------------
# OLS 残差（用于偏相关核心计算）
# ---------------------------------------------------------------------------

def _ols_residuals(y: list[float], controls: list[list[float]]) -> list[float]:
    """OLS 回归 y ~ 1 + controls，返回残差 e = y - ŷ。

    当 controls 为空时，退化为去均值（等价于截距模型的残差）。
    """
    n = len(y)
    k = len(controls[0]) if controls else 0

    if k == 0:
        mean_y = sum(y) / n
        return [yi - mean_y for yi in y]

    if len(controls) != n:
        raise ValueError(f"controls 行数 {len(controls)} 与 y 长度 {n} 不一致")

    Xd = [[1.0] + [controls[i][j] for j in range(k)] for i in range(n)]
    Xt = _mat_transpose(Xd)
    XtX = _mat_mult(Xt, Xd)
    XtX_inv = _mat_invert(XtX)
    if XtX_inv is None:
        raise ValueError("控制变量设计矩阵奇异（多重共线），无法计算 OLS 残差")

    Xty = _mat_vec(Xt, y)
    betas = _mat_vec(XtX_inv, Xty)
    y_hat = [sum(betas[j] * Xd[i][j] for j in range(k + 1)) for i in range(n)]
    return [y[i] - y_hat[i] for i in range(n)]


def _pearson_r_raw(xs: list[float], ys: list[float]) -> float:
    """Pearson r，从原始列表计算（含去均值）。"""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in xs))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in ys))
    if sx < 1e-14 or sy < 1e-14:
        return float("nan")
    return num / (sx * sy)


def _r_to_stats(r: float, n: int, k: int, alpha: float) -> dict[str, Any]:
    """给定偏相关 r、样本量 n、控制变量数 k，计算 t、p、CI。"""
    df = n - 2 - k
    if not math.isfinite(r) or df <= 0:
        return {"t": None, "p": None, "df": df, "ci_lower": None, "ci_upper": None}

    denom = 1.0 - r * r
    if denom <= 1e-14:
        t = math.copysign(float("inf"), r)
        p_val = 0.0
    else:
        t = r * math.sqrt(df) / math.sqrt(denom)
        p_val = _t_sf2(abs(t), df)

    # Fisher z CI（控制变量修正：SE = 1/sqrt(n - k - 3)，Olkin & Finn 1995）
    n_adj = n - k  # n 减去控制变量数
    if n_adj > 3 and abs(r) < 1.0:
        z_r = math.atanh(r)
        se_z = 1.0 / math.sqrt(n_adj - 3)
        z_crit = _norm_ppf(1.0 - alpha / 2.0)
        ci_lower: float | None = math.tanh(z_r - z_crit * se_z)
        ci_upper: float | None = math.tanh(z_r + z_crit * se_z)
    else:
        ci_lower = ci_upper = None

    return {
        "t": round(t, 6) if math.isfinite(t) else None,
        "p": round(p_val, 6) if math.isfinite(p_val) else None,
        "df": df,
        "ci_lower": round(ci_lower, 6) if ci_lower is not None else None,
        "ci_upper": round(ci_upper, 6) if ci_upper is not None else None,
    }


# ---------------------------------------------------------------------------
# 偏相关
# ---------------------------------------------------------------------------

def partial_correlation(
    x: list[float],
    y: list[float],
    controls: list[list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """偏相关系数 r_xy.controls（控制一个或多个协变量）。

    算法：回归残差法 — OLS 残差 e_x, e_y，r = Pearson(e_x, e_y)。
    当 controls=[] 时退化为 Pearson r。

    参数
    ----
    x, y       : 等长数值列表
    controls   : [[z1_obs1, z2_obs1, ...], [z1_obs2, ...], ...] — 每行一个观测
                 传 [] 表示无控制变量
    alpha      : 显著性水平（双尾 CI，默认 .05）

    返回
    ----
    {r, df, t, p, ci_lower, ci_upper, n, k_controls, alpha}
    """
    n = len(x)
    if n != len(y):
        raise ValueError(f"x 长度 {n} 与 y 长度 {len(y)} 不一致")

    k = len(controls[0]) if controls else 0
    df = n - 2 - k

    if controls:
        if len(controls) != n:
            raise ValueError(f"controls 行数 {len(controls)} 与 x 长度 {n} 不一致")
        try:
            e_x = _ols_residuals(x, controls)
            e_y = _ols_residuals(y, controls)
            r = _pearson_r_raw(e_x, e_y)
        except ValueError:
            if df > 0:
                raise  # df 充足却奇异属真实错误，照常抛
            r = float("nan")  # df<=0 且控制变量共线 → 无法推断，优雅返回
    else:
        r = _pearson_r_raw(x, y)

    stats = _r_to_stats(r, n, k, alpha)

    return {
        "r": round(r, 6) if math.isfinite(r) else None,
        "n": n,
        "k_controls": k,
        "alpha": alpha,
        **stats,
    }


# ---------------------------------------------------------------------------
# 半偏相关（part correlation）
# ---------------------------------------------------------------------------

def semipartial_correlation(
    x: list[float],
    y: list[float],
    controls: list[list[float]],
    which: str = "x",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """半偏相关（part correlation）。

    which="x"：仅对 x 去除控制变量影响，r(e_x, y)。
    which="y"：仅对 y 去除控制变量影响，r(x, e_y)。

    半偏相关² 表示该变量在控制其他变量后贡献的额外唯一方差。
    """
    if which not in ("x", "y"):
        raise ValueError(f"which 必须是 'x' 或 'y'，got {which!r}")

    n = len(x)
    if n != len(y):
        raise ValueError(f"x 长度 {n} 与 y 长度 {len(y)} 不一致")

    k = len(controls[0]) if controls else 0

    if controls:
        if len(controls) != n:
            raise ValueError(f"controls 行数 {len(controls)} 与 x 长度 {n} 不一致")
        if which == "x":
            e = _ols_residuals(x, controls)
            raw = y
        else:
            e = _ols_residuals(y, controls)
            raw = x
    else:
        e = x if which == "x" else y
        raw = y if which == "x" else x

    r = _pearson_r_raw(e, raw)
    stats = _r_to_stats(r, n, k, alpha)

    return {
        "r_semi": round(r, 6) if math.isfinite(r) else None,
        "which": which,
        "n": n,
        "k_controls": k,
        "alpha": alpha,
        **stats,
    }


# ---------------------------------------------------------------------------
# 偏相关矩阵
# ---------------------------------------------------------------------------

def partial_correlation_matrix(
    variables: list[list[float]],
    var_names: list[str],
    controls: list[list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """偏相关矩阵 — 对所有变量对，控制相同的协变量集。

    参数
    ----
    variables : p 个变量的数据，每个为 n 元数值列表
    var_names : 变量名列表（长度 = p）
    controls  : 协变量数据（同 partial_correlation 的格式）
    alpha     : 显著性水平

    返回
    ----
    {matrix, var_names, n, k_controls, df, alpha}
    其中 matrix[i][j] 含 {r, t, p, ci_lower, ci_upper, significant}；对角线 r=1。
    """
    p = len(variables)
    if p != len(var_names):
        raise ValueError("变量数与变量名列表长度不一致")
    if p < 2:
        raise ValueError("偏相关矩阵需要至少 2 个变量")

    n = len(variables[0])
    k = len(controls[0]) if controls else 0

    if controls:
        if len(controls) != n:
            raise ValueError(f"controls 行数 {len(controls)} 与变量长度 {n} 不一致")
        residuals = [_ols_residuals(v, controls) for v in variables]
    else:
        residuals = [list(v) for v in variables]

    df = n - 2 - k

    # 先填上三角
    upper: dict[tuple[int, int], dict[str, Any]] = {}
    for i in range(p):
        for j in range(i + 1, p):
            r = _pearson_r_raw(residuals[i], residuals[j])
            stats = _r_to_stats(r, n, k, alpha)
            p_val = stats.get("p")
            sig = (p_val < alpha) if (p_val is not None and math.isfinite(p_val)) else None
            upper[(i, j)] = {
                "r": round(r, 6) if math.isfinite(r) else None,
                "significant": sig,
                **stats,
            }

    diag = {
        "r": 1.0, "t": None, "p": None, "df": df,
        "ci_lower": 1.0, "ci_upper": 1.0, "significant": None,
    }

    matrix = []
    for i in range(p):
        row = []
        for j in range(p):
            if i == j:
                row.append(dict(diag))
            elif i < j:
                row.append(upper[(i, j)])
            else:
                row.append(upper[(j, i)])
        matrix.append(row)

    return {
        "matrix": matrix,
        "var_names": var_names,
        "n": n,
        "k_controls": k,
        "df": df,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _p_str(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return "= " + f"{p:.3f}".lstrip("0")


def format_apa_partial_corr(
    result: dict[str, Any],
    x_name: str = "x",
    y_name: str = "y",
    control_names: list[str] | None = None,
) -> str:
    """APA-7 偏相关/半偏相关汇总 Markdown 段落。"""
    n = result["n"]
    k = result["k_controls"]
    r = result.get("r") if "r" in result else result.get("r_semi")
    df = result["df"]
    t = result.get("t")
    p = result.get("p")
    ci_lo = result.get("ci_lower")
    ci_hi = result.get("ci_upper")
    alpha = result.get("alpha", 0.05)
    is_semi = "r_semi" in result
    which = result.get("which", "x") if is_semi else None

    ctrl_str = "、".join(control_names or [f"协变量{i+1}" for i in range(k)]) if k else "（无控制变量）"
    corr_type = ("半偏相关" + f"（对 {which} 去除影响）") if is_semi else "偏相关"

    lines = [f"## {corr_type}分析", ""]
    lines.append(f"- **变量 x**：{x_name}")
    lines.append(f"- **变量 y**：{y_name}")
    lines.append(f"- **控制变量**：{ctrl_str}")
    lines.append(f"- ***N*** = {n}，*df* = {df}（*n* − 2 − *k* = {n} − 2 − {k}）")
    lines.append("")

    r_str = f"{r:.3f}" if r is not None else "NaN"
    t_str = f"{t:.3f}" if t is not None and math.isfinite(t) else "—"
    p_str_val = _p_str(p)
    ci_str = (
        f"[{ci_lo:.3f}, {ci_hi:.3f}]"
        if ci_lo is not None and ci_hi is not None else "—"
    )

    lines.append(
        f"在控制 {ctrl_str} 后，{x_name} 与 {y_name} 之间的{corr_type}系数 "
        f"*r* = {r_str}，*t*({df}) = {t_str}，*p* {p_str_val}，"
        f"95% CI {ci_str}。"
    )

    if p is not None and math.isfinite(p):
        if p < 0.001:
            sig_line = f"该{corr_type}在 α = {alpha} 水平上**极显著**（*p* < .001）。"
        elif p < alpha:
            sig_line = f"该{corr_type}在 α = {alpha} 水平上**显著**（*p* {p_str_val}）。"
        else:
            sig_line = f"该{corr_type}在 α = {alpha} 水平上**不显著**（*p* {p_str_val}）。"
        lines.append(sig_line)

    # 汇总表
    lines += ["", "### 汇总表", ""]
    lines.append("| 分析 | 控制变量 | *r* | *t*(*df*) | *p* | 95% CI |")
    lines.append("|------|----------|-----|-----------|-----|--------|")
    t_cell = f"{t_str} ({df})" if t is not None and math.isfinite(t) else f"— ({df})"
    lines.append(
        f"| {corr_type} | {ctrl_str} | {r_str} | {t_cell} | {p_str_val} | {ci_str} |"
    )

    lines += [
        "", "### 参考文献", "",
        "Cohen, J., Cohen, P., West, S. G., & Aiken, L. S. (2003). "
        "*Applied multiple regression/correlation analysis for the behavioral sciences* "
        "(3rd ed.). Lawrence Erlbaum.",
        "",
        "Olkin, I., & Finn, J. D. (1995). Correlations redux. "
        "*Psychological Bulletin*, *118*(1), 155–164. "
        "https://doi.org/10.1037/0033-2909.118.1.155",
    ]
    return "\n".join(lines)


def format_apa_partial_matrix(result: dict[str, Any]) -> str:
    """APA-7 偏相关矩阵 Markdown 三线表（上三角；***=.001, **=.01, *=.05）。"""
    var_names = result["var_names"]
    matrix = result["matrix"]
    n = result["n"]
    k = result["k_controls"]
    p = len(var_names)

    lines = [f"## 偏相关矩阵（控制 {k} 个变量，*N* = {n}）", ""]
    header = "| 变量 | " + " | ".join(var_names) + " |"
    sep = "|------|" + "|------" * p + "|"
    lines += [header, sep]

    for i in range(p):
        cells = []
        for j in range(p):
            if i == j:
                cells.append("—")
            elif i > j:
                cells.append("")
            else:
                cell = matrix[i][j]
                r = cell.get("r")
                p_val = cell.get("p")
                if r is None:
                    cells.append("NA")
                else:
                    stars = ""
                    if p_val is not None and math.isfinite(p_val):
                        if p_val < 0.001:
                            stars = "***"
                        elif p_val < 0.01:
                            stars = "**"
                        elif p_val < 0.05:
                            stars = "*"
                    cells.append(f"{r:.3f}{stars}")
        lines.append("| " + var_names[i] + " | " + " | ".join(cells) + " |")

    lines += ["", "*注*：\\*\\*\\* *p* < .001，\\*\\* *p* < .01，\\* *p* < .05。"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON sidecar 工具
# ---------------------------------------------------------------------------

def _clean_json(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    return obj


def write_partial_corr_report(
    result: dict[str, Any],
    formatted: str,
    out_dir: str | pathlib.Path,
    stem: str = "partial_corr_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回 {md, json} 路径。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"{stem}.md"
    json_path = out / f"{stem}.json"
    md_path.write_text(formatted, encoding="utf-8")
    clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    json_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path)}


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_csv_cols(
    csv_path: str,
    col_names: list[str],
) -> tuple[dict[str, list[float]], int]:
    """读取 CSV 指定列，过滤缺失行，返回 {列名: 数值列表} 和排除行数。"""
    path = pathlib.Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到数据文件: {csv_path}")

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV 文件为空或无数据行")

    header = set(rows[0].keys())
    missing = [c for c in col_names if c not in header]
    if missing:
        raise ValueError(f"CSV 中找不到列: {missing}")

    data: dict[str, list[float]] = {c: [] for c in col_names}
    n_excluded = 0
    for row in rows:
        try:
            vals = {c: float(row[c]) for c in col_names}
            for c, v in vals.items():
                data[c].append(v)
        except (ValueError, KeyError):
            n_excluded += 1

    return data, n_excluded


def analyze_partial_corr(
    csv_path: str,
    x_col: str,
    y_col: str,
    control_cols: list[str],
    alpha: float = 0.05,
    semi: bool = False,
    which: str = "x",
    matrix_cols: list[str] | None = None,
    out_dir: str = "notes",
    return_json: bool = False,
) -> dict[str, Any]:
    """CSV 主入口：读取数据 → 计算偏相关 → 写 sidecar。

    可选同时计算偏相关矩阵（matrix_cols）。
    """
    need_cols = list(dict.fromkeys([x_col, y_col] + control_cols + (matrix_cols or [])))
    data, n_excluded = _read_csv_cols(csv_path, need_cols)

    n = len(data[x_col])
    x = data[x_col]
    y = data[y_col]
    ctrl = [[data[c][i] for c in control_cols] for i in range(n)] if control_cols else []

    if semi:
        result = semipartial_correlation(x, y, ctrl, which=which, alpha=alpha)
    else:
        result = partial_correlation(x, y, ctrl, alpha=alpha)

    result["n_excluded"] = n_excluded
    result["x_col"] = x_col
    result["y_col"] = y_col
    result["control_cols"] = control_cols

    formatted = format_apa_partial_corr(result, x_name=x_col, y_name=y_col,
                                        control_names=control_cols or None)

    if matrix_cols and len(matrix_cols) >= 2:
        mat_data = [data[c] for c in matrix_cols]
        mat_result = partial_correlation_matrix(mat_data, matrix_cols, ctrl, alpha=alpha)
        result["matrix_result"] = mat_result
        mat_formatted = format_apa_partial_matrix(mat_result)
        formatted = formatted + "\n\n" + mat_formatted

    paths = write_partial_corr_report(result, formatted, out_dir)
    result["_formatted"] = formatted
    result["_paths"] = paths

    if return_json:
        return _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def partial_corr_cli(argv: list[str]) -> int:
    import argparse
    from psyclaw import ui

    ap = argparse.ArgumentParser(
        prog="psyclaw partial-corr",
        description="偏相关分析 / 半偏相关 / 偏相关矩阵（APA-7，stdlib only）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--x", required=True, dest="x_col", help="变量 x 列名")
    ap.add_argument("--y", required=True, dest="y_col", help="变量 y 列名")
    ap.add_argument("--controls", default="",
                    help="控制变量列名，逗号分隔（可为空）")
    ap.add_argument("--semi", action="store_true",
                    help="计算半偏相关（part correlation）")
    ap.add_argument("--which", default="x", choices=["x", "y"],
                    help="半偏相关中对哪个变量去除控制变量影响（默认 x）")
    ap.add_argument("--matrix",
                    help="同时输出偏相关矩阵的变量列名（逗号分隔，≥2 列）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--out", default="notes",
                    help="报告输出目录（默认 notes/）")

    args = ap.parse_args(argv)
    control_cols = [c.strip() for c in args.controls.split(",") if c.strip()]
    matrix_cols = (
        [c.strip() for c in args.matrix.split(",") if c.strip()]
        if args.matrix else None
    )

    try:
        result = analyze_partial_corr(
            args.csv, args.x_col, args.y_col, control_cols,
            alpha=args.alpha, semi=args.semi, which=args.which,
            matrix_cols=matrix_cols, out_dir=args.out,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(ui.err(str(exc)))
        return 1

    if args.json:
        clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return 0

    r = result.get("r") if "r" in result else result.get("r_semi")
    n = result["n"]
    df = result["df"]
    p_val = result.get("p")
    ci_lo = result.get("ci_lower")
    ci_hi = result.get("ci_upper")
    k = result["k_controls"]
    ctrl_str = ", ".join(control_cols) if control_cols else "无"
    corr_type = "半偏相关" if args.semi else "偏相关"

    print(ui.title(f"{corr_type}分析"))
    print(ui.rule())
    print(f"  变量 x      : {args.x_col}")
    print(f"  变量 y      : {args.y_col}")
    print(f"  控制变量    : {ctrl_str}")
    print(f"  有效 N      : {n}  |  排除: {result.get('n_excluded', 0)}")
    print(f"  df          : {df}  (n−2−k = {n}−2−{k})")
    print()
    if r is not None:
        print(f"  {corr_type} r  : {r:.4f}")
    if p_val is not None:
        pdisp = "< .001" if p_val < 0.001 else f"= {p_val:.3f}"
        print(f"  p 值          : {pdisp}")
    if ci_lo is not None:
        print(f"  95% CI        : [{ci_lo:.4f}, {ci_hi:.4f}]")

    paths = result.get("_paths", {})
    if paths.get("md"):
        print(ui.dim(f"\n  报告已写入: {paths['md']}"))
    return 0
