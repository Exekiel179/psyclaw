"""OLS 回归分析 — APA-7 系数表（stdlib only）。

提供：
  - 纯 stdlib OLS（Gauss-Jordan 求逆 + 正规方程）
  - B（非标准化系数）、β（标准化系数）、SE、t、p
  - R²、调整 R²、F 检验
  - APA-7 Markdown 三线系数表 + 文字摘要段落
  - CSV 主入口 + MD/JSON sidecar + CLI

CLI:
  psyclaw regress <data.csv> --dv <col> --iv col1,col2,...
          [--std] [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
import statsmodels.api as sm
from scipy import stats


# ---------------------------------------------------------------------------
# 矩阵工具（numpy；测试直接 import 这些 helper）
# ---------------------------------------------------------------------------

def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
    return np.asarray(A, dtype=float).T.tolist()


def _mat_mult(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """矩阵乘法 A(m×n) × B(n×p) → C(m×p)。"""
    return (np.asarray(A, dtype=float) @ np.asarray(B, dtype=float)).tolist()


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    """矩阵 × 向量。"""
    return (np.asarray(A, dtype=float) @ np.asarray(v, dtype=float)).tolist()


def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    """n×n 矩阵逆（numpy），奇异返回 None。"""
    try:
        return np.linalg.inv(np.asarray(M, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        return None


# ---------------------------------------------------------------------------
# 分布 p 值（scipy；测试直接 import _t_sf2/_f_sf）
# ---------------------------------------------------------------------------

def _t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p。"""
    if df <= 0:
        return float("nan")
    return 2.0 * float(stats.t.sf(abs(t), df))


def _f_sf(f_stat: float, df1: float, df2: float) -> float:
    """F 分布上尾 p 值。"""
    if f_stat <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    return float(stats.f.sf(f_stat, df1, df2))


# ---------------------------------------------------------------------------
# OLS 核心
# ---------------------------------------------------------------------------

def compute_ols(
    y: list[float],
    X: list[list[float]],
    iv_names: list[str],
    dv_name: str = "y",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """OLS 回归（含截距），X 为设计矩阵（不含常数列，函数内部添加）。

    返回
    ----
    {
      n, k (预测变量数), df_model, df_resid,
      coefficients: [{name, B, SE, t, p, ci_lower, ci_upper, beta}],
      R2, R2_adj, F, F_p, SSE, SSR, SST, MSE, RMSE,
      dv_name, iv_names
    }
    """
    n = len(y)
    k = len(X[0]) if X else 0  # 预测变量数（不含截距）

    if n < k + 2:
        raise ValueError(f"有效数据行数 ({n}) 不足以拟合 {k} 个预测变量 + 截距")

    # 设计矩阵：截距列 + IV 列；先用 numpy 检测奇异（保留 ValueError 契约）
    Xd = [[1.0] + list(X[i]) for i in range(n)]
    XtX = _mat_mult(_mat_transpose(Xd), Xd)
    if _mat_invert(XtX) is None:
        raise ValueError("设计矩阵奇异（预测变量完全多重共线），无法求逆")

    # statsmodels OLS 拟合
    model = sm.OLS(np.asarray(y, dtype=float), np.asarray(Xd, dtype=float)).fit()
    betas = [float(v) for v in model.params]
    ses = [float(v) for v in model.bse]
    tvals = [float(v) for v in model.tvalues]
    pvals = [float(v) for v in model.pvalues]
    ci = np.asarray(model.conf_int(alpha), dtype=float)  # (k+1, 2)

    df_model = k
    df_resid = n - k - 1
    SSE = float(model.ssr)
    SST = float(model.centered_tss)
    SSR = float(model.ess)
    MSE = float(model.mse_resid) if df_resid > 0 else float("nan")
    R2 = float(model.rsquared)
    R2_adj = float(model.rsquared_adj) if df_resid > 0 else float("nan")
    F = float(model.fvalue) if model.fvalue is not None else float("nan")
    F_p = float(model.f_pvalue) if model.f_pvalue is not None else float("nan")

    # 标准化系数 β（基于标准化 X 和 y）
    def _sd(xs: list[float]) -> float:
        m = sum(xs) / len(xs)
        return math.sqrt(sum((v - m) ** 2 for v in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0

    sd_y = _sd(y) if n > 1 else 1.0
    sd_ivs = [_sd([X[i][j] for i in range(n)]) for j in range(k)]

    def _coef(idx: int, name: str, beta: float | None) -> dict[str, Any]:
        lo, hi = float(ci[idx][0]), float(ci[idx][1])
        p_val = pvals[idx]
        return {
            "name": name,
            "B": round(betas[idx], 4),
            "SE": round(ses[idx], 4),
            "t": round(tvals[idx], 4),
            "p": round(p_val, 4) if math.isfinite(p_val) else None,
            "ci_lower": round(lo, 4) if math.isfinite(lo) else None,
            "ci_upper": round(hi, 4) if math.isfinite(hi) else None,
            "beta": round(beta, 4) if beta is not None else None,
        }

    coefficients = [_coef(0, "截距 (Intercept)", None)]
    for j, name in enumerate(iv_names):
        beta = (betas[j + 1] * sd_ivs[j] / sd_y) if sd_y > 0 and sd_ivs[j] > 0 else None
        coefficients.append(_coef(j + 1, name, beta))

    return {
        "n": n,
        "k": k,
        "df_model": df_model,
        "df_resid": df_resid,
        "coefficients": coefficients,
        "R2": round(R2, 4),
        "R2_adj": round(R2_adj, 4) if math.isfinite(R2_adj) else None,
        "F": round(F, 4) if math.isfinite(F) else None,
        "F_p": round(F_p, 4) if math.isfinite(F_p) else None,
        "SSE": round(SSE, 4),
        "SSR": round(SSR, 4),
        "SST": round(SST, 4),
        "MSE": round(MSE, 4) if math.isfinite(MSE) else None,
        "RMSE": round(math.sqrt(MSE), 4) if math.isfinite(MSE) else None,
        "dv_name": dv_name,
        "iv_names": list(iv_names),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    """APA-7 p 值格式。"""
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")  # .123 not 0.123


def _fmt_b(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.2f}"


def format_apa_regression_table(
    result: dict[str, Any],
    title: str | None = None,
) -> str:
    """生成 APA-7 Markdown 回归系数三线表。"""
    dv = result.get("dv_name", "y")
    if title is None:
        title = f"OLS 回归分析：预测 {dv}"
    lines = [
        f"*{title}*",
        "",
        "| 变量 | *B* | *SE* | *β* | *t* | *p* | 95% CI |",
        "|------|-----|------|-----|-----|-----|--------|",
    ]
    for c in result["coefficients"]:
        ci = (f"[{c['ci_lower']:.2f}, {c['ci_upper']:.2f}]"
              if c["ci_lower"] is not None else "—")
        beta_str = _fmt_b(c["beta"]) if c["beta"] is not None else "—"
        lines.append(
            f"| {c['name']} | {_fmt_b(c['B'])} | {_fmt_b(c['SE'])} | "
            f"{beta_str} | {_fmt_b(c['t'])} | {_fmt_p(c['p'])} | {ci} |"
        )
    # 模型拟合摘要行
    r2_adj_str = f"{result['R2_adj']:.3f}" if result.get("R2_adj") is not None else "—"
    f_str = f"{result['F']:.2f}" if result.get("F") is not None else "—"
    lines += [
        "",
        (f"*注：N* = {result['n']}。"
         f"*R*² = {result['R2']:.3f}，"
         f"调整 *R*² = {r2_adj_str}，"
         f"*F*({result['df_model']}, {result['df_resid']}) = {f_str}，"
         f"*p* {_fmt_p(result.get('F_p'))}。"),
    ]
    return "\n".join(lines)


def format_apa_paragraph(result: dict[str, Any]) -> str:
    """生成 APA-7 格式回归结果文字段落。"""
    dv = result.get("dv_name", "y")
    n = result["n"]
    R2 = result["R2"]
    R2_adj = result.get("R2_adj")
    F = result.get("F")
    F_p = result.get("F_p")
    df1, df2 = result["df_model"], result["df_resid"]

    f_str = f"*F*({df1}, {df2}) = {F:.2f}" if F is not None else ""
    p_str = f"*p* {_fmt_p(F_p)}" if F_p is not None else ""
    r2_str = f"*R*² = {R2:.3f}"
    adj_str = f"（调整 *R*² = {R2_adj:.3f}）" if R2_adj is not None else ""

    # 显著预测变量
    sig = [c for c in result["coefficients"]
           if c["name"] != "截距 (Intercept)" and c["p"] is not None and c["p"] < 0.05]
    sig_strs = []
    for c in sig:
        beta = f"*β* = {c['beta']:.2f}，" if c["beta"] is not None else ""
        sig_strs.append(f"{c['name']}（*B* = {c['B']:.2f}，{beta}*t*({df2}) = {c['t']:.2f}，*p* {_fmt_p(c['p'])}）")

    para = (
        f"以 {', '.join(result['iv_names'])} 为预测变量对 {dv} 进行 OLS 回归分析（N = {n}）。"
        f"模型整体显著，{f_str}，{p_str}，{r2_str}{adj_str}，解释方差比例为 {R2 * 100:.1f}%。"
    )
    if sig_strs:
        para += f"显著预测变量包括：{'；'.join(sig_strs)}。"
    else:
        para += "无预测变量达显著水平（p < .05）。"
    return para


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_regression_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 regression_report.md + regression_report.json。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "# OLS 回归分析报告",
        "",
        format_apa_regression_table(result),
        "",
        "## APA-7 文字摘要",
        "",
        format_apa_paragraph(result),
        "",
        "## 模型诊断",
        "",
        f"- **SST** = {result['SST']}  |  **SSR** = {result['SSR']}  |  **SSE** = {result['SSE']}",
        f"- **MSE** = {result.get('MSE', '—')}  |  **RMSE** = {result.get('RMSE', '—')}",
        f"- **自由度**：模型 df = {result['df_model']}，残差 df = {result['df_resid']}",
    ]

    md_path = out / "regression_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / "regression_report.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col(rows: list[dict[str, str]], col: str) -> list[float | None]:
    """读取一列数值，非数值或 NaN/inf 返回 None。"""
    result = []
    for row in rows:
        raw = row.get(col, "").strip()
        if not raw:
            result.append(None)
            continue
        try:
            v = float(raw)
            result.append(None if not math.isfinite(v) else v)
        except ValueError:
            result.append(None)
    return result


def analyze_regression(
    csv_path: str,
    dv: str,
    ivs: list[str],
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行 OLS 回归，返回完整结果字典。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    # 读取各列，仅保留所有变量均有效的行
    all_cols = [dv] + list(ivs)
    raw: dict[str, list[float | None]] = {c: _read_col(rows, c) for c in all_cols}

    # 完整案例过滤
    valid_idx = [i for i in range(len(rows))
                 if all(raw[c][i] is not None for c in all_cols)]
    n_total = len(rows)
    n_valid = len(valid_idx)
    n_excluded = n_total - n_valid

    if n_valid < len(ivs) + 2:
        raise ValueError(
            f"有效数据行数 ({n_valid}) 不足以拟合 {len(ivs)} 个预测变量 + 截距"
        )

    y = [raw[dv][i] for i in valid_idx]
    X = [[raw[iv][i] for iv in ivs] for i in valid_idx]

    ols_result = compute_ols(y, X, iv_names=ivs, dv_name=dv, alpha=alpha)
    ols_result["n_total"] = n_total
    ols_result["n_excluded"] = n_excluded
    ols_result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_regression_report(ols_result, out_dir=out_dir)
        ols_result["report_md"] = str(md_path)
        ols_result["report_json"] = str(json_path)

    return ols_result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def regression_cli(args: list[str]) -> int:
    """psyclaw regress <data.csv> --dv <col> --iv col1,col2,..."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw regress",
        description="OLS 多元回归分析，输出 APA-7 系数表（B/β/SE/t/p/95%CI）",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--iv", required=True,
                        help="预测变量（逗号分隔，如 --iv age,edu,score）")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05，影响 CI 和 * 标注）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    iv_list = [s.strip() for s in opts.iv.split(",") if s.strip()]

    try:
        result = analyze_regression(
            csv_path=opts.csv_file,
            dv=opts.dv,
            ivs=iv_list,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_regression_table(result))
    print()
    print(format_apa_paragraph(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
