"""协方差分析 (ANCOVA) — APA-7 报告（stdlib only）。

单因素 ANCOVA：在统计控制协变量后比较各组调整均值。

提供：
  - ancova(y, groups, covariates, cov_names)      → 全量结果字典
  - format_apa_ancova(result, ph_result)           → APA-7 Markdown 段落+表格
  - write_ancova_report(result, ph_result, out_dir)→ MD + JSON sidecar
  - analyze_ancova(csv_path, ...)                  → CSV 主入口
  - ancova_cli(args)                               → CLI 入口

统计方法：
  - Type-III SS（偏 SS）通过两次 OLS 对比求得
  - GLM 哑变量编码（treatment coding，首组为参照）
  - 同质性回归斜率检验（group×covariate 交互项）
  - 估计边际均值 (EMM / LS Means)：在协变量总体均值处的预测值
  - 偏 partial η² / partial ω²（Olejnik & Algina, 2003）
  - 事后成对 t 检验（基于 GLM 对比向量，Holm 校正）

参考文献：
  Maxwell, S. E., Delaney, H. D., & Kelley, K. (2017). Designing experiments
    and analyzing data (3rd ed.). Routledge.
  Olejnik, S., & Algina, J. (2003). Generalized eta and omega squared statistics.
    Psychological Methods, 8(4), 434–447.
  Milliken, G. A., & Johnson, D. E. (2009). Analysis of messy data, volume 1.
    CRC Press.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# 矩阵工具（stdlib only，同 regression.py）
# ---------------------------------------------------------------------------

def _mat_transpose(A: list[list[float]]) -> list[list[float]]:
    return np.asarray(A, dtype=float).T.tolist()


def _mat_mult(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return (np.asarray(A, dtype=float) @ np.asarray(B, dtype=float)).tolist()


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return (np.asarray(A, dtype=float) @ np.asarray(v, dtype=float)).tolist()


def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    arr = np.asarray(M, dtype=float)
    try:
        return np.linalg.inv(arr).tolist()
    except np.linalg.LinAlgError:
        return None


# ---------------------------------------------------------------------------
# 统计分布（scipy 适配；不再手写分布函数）
# ---------------------------------------------------------------------------

def _t_sf2(t: float, df: float) -> float:
    """学生 t 双尾 p。"""
    if df <= 0:
        return float("nan")
    return 2.0 * float(stats.t.sf(abs(t), df))


def _f_sf(f: float, df1: float, df2: float) -> float:
    if f <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    return float(stats.f.sf(f, df1, df2))


def _t_ppf(p: float, df: float) -> float:
    """返回双尾 p = p 对应的 t（即 t.ppf(1 - p/2)）。"""
    if df <= 0:
        return float("nan")
    return float(stats.t.ppf(1 - p / 2.0, df))


# ---------------------------------------------------------------------------
# 内部 OLS 辅助
# ---------------------------------------------------------------------------

def _fit_ols(y: list[float], X: list[list[float]]) -> tuple[float, list[float], list[list[float]]]:
    """拟合 OLS，返回 (SSE, beta, XtX_inv)。奇异矩阵抛 ValueError。"""
    n, q = len(y), len(X[0])
    Xt = _mat_transpose(X)
    XtX = _mat_mult(Xt, X)
    XtX_inv = _mat_invert(XtX)
    if XtX_inv is None:
        raise ValueError("设计矩阵奇异（多重共线或完全重叠）")
    beta = _mat_vec(XtX_inv, _mat_vec(Xt, y))
    y_hat = [sum(beta[j] * X[i][j] for j in range(q)) for i in range(n)]
    SSE = sum((y[i] - y_hat[i]) ** 2 for i in range(n))
    return SSE, beta, XtX_inv


def _build_X(
    n: int,
    group_idxs: list[int],
    k: int,
    covariates: list[list[float]],
    p: int,
    include_group: bool = True,
    exclude_cov: int | None = None,
    include_interactions: bool = False,
) -> list[list[float]]:
    """构建 GLM 设计矩阵（treatment coding，首组为参照）。"""
    rows = []
    for i in range(n):
        row = [1.0]  # intercept
        if include_group:
            gi = group_idxs[i]
            for g in range(1, k):
                row.append(1.0 if gi == g else 0.0)
        for ci in range(p):
            if ci == exclude_cov:
                continue
            row.append(covariates[i][ci])
        if include_interactions and include_group:
            gi = group_idxs[i]
            for g in range(1, k):
                d = 1.0 if gi == g else 0.0
                for ci in range(p):
                    if ci == exclude_cov:
                        continue
                    row.append(d * covariates[i][ci])
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# 核心 ANCOVA
# ---------------------------------------------------------------------------

def ancova(
    y: list[float],
    groups: list[str],
    covariates: list[list[float]],
    cov_names: list[str],
    alpha: float = 0.05,
    include_post_hoc: bool = False,
) -> dict[str, Any]:
    """单因素 ANCOVA（Type-III SS，GLM哑变量编码）。

    参数
    ----
    y            : 因变量数值列表（长度 N）
    groups       : 分组标签列表（长度 N）
    covariates   : 协变量矩阵，shape [N][p]
    cov_names    : 协变量名称列表（长度 p）
    alpha        : 显著性水平
    include_post_hoc : 是否附加事后成对 t 检验（Holm 校正）

    返回
    ----
    {
      group_effect, covariate_effects, homogeneity,
      adjusted_means, coefficients, model, alpha,
      post_hoc (可选)
    }
    """
    n = len(y)
    p = len(cov_names)
    if len(covariates) != n or any(len(row) != p for row in covariates):
        raise ValueError("协变量矩阵维度与数据行数或 cov_names 不匹配")
    if p == 0:
        raise ValueError("至少需要一个协变量")

    group_levels = sorted(set(groups))
    k = len(group_levels)
    if k < 2:
        raise ValueError(f"至少需要 2 个分组水平（当前 {k}）")

    group_idx_map = {g: i for i, g in enumerate(group_levels)}
    group_idxs = [group_idx_map[g] for g in groups]

    group_n = [sum(1 for g in groups if g == lv) for lv in group_levels]
    grand_mean = sum(y) / n
    group_raw_means = []
    for li, lv in enumerate(group_levels):
        vals = [y[i] for i in range(n) if groups[i] == lv]
        group_raw_means.append(sum(vals) / len(vals))

    grand_cov_means = [sum(covariates[i][ci] for i in range(n)) / n for ci in range(p)]

    # 全模型：Type-III SS 基准
    X_full = _build_X(n, group_idxs, k, covariates, p, include_group=True)
    try:
        SSE_full, beta_full, XtX_inv_full = _fit_ols(y, X_full)
    except ValueError as exc:
        raise ValueError(f"全模型拟合失败：{exc}") from exc

    df_error = n - k - p
    if df_error <= 0:
        raise ValueError(
            f"自由度不足（N={n}, k={k}, p={p}，df_error={df_error}）；"
            "需要更多数据或减少协变量"
        )
    MS_error = SSE_full / df_error

    # Type-III SS for 组因子：全模型 vs 仅协变量模型
    X_cov_only = _build_X(n, group_idxs, k, covariates, p, include_group=False)
    SSE_cov_only, _, _ = _fit_ols(y, X_cov_only)
    SS_group = SSE_cov_only - SSE_full
    df_group = k - 1
    MS_group = SS_group / df_group if df_group > 0 else 0.0
    F_group = MS_group / MS_error if MS_error > 0 else float("nan")
    p_group = _f_sf(F_group, df_group, df_error) if math.isfinite(F_group) else float("nan")

    # partial η² / partial ω² for 组因子
    denom_eta = SS_group + SSE_full
    partial_eta2_group = SS_group / denom_eta if denom_eta > 0 else 0.0
    denom_omega = SS_group + SSE_full + MS_error
    partial_omega2_group = max(
        (SS_group - df_group * MS_error) / denom_omega, 0.0
    ) if denom_omega > 0 else 0.0

    group_effect: dict[str, Any] = {
        "SS": round(SS_group, 4),
        "df": df_group,
        "MS": round(MS_group, 4),
        "F": round(F_group, 4) if math.isfinite(F_group) else None,
        "p": round(p_group, 6) if math.isfinite(p_group) else None,
        "partial_eta2": round(partial_eta2_group, 4),
        "partial_omega2": round(partial_omega2_group, 4),
    }

    # Type-III SS for 各协变量
    covariate_effects: list[dict[str, Any]] = []
    for ci, cov_name in enumerate(cov_names):
        X_no_ci = _build_X(n, group_idxs, k, covariates, p,
                            include_group=True, exclude_cov=ci)
        try:
            SSE_no_ci, _, _ = _fit_ols(y, X_no_ci)
        except ValueError:
            covariate_effects.append({
                "name": cov_name, "SS": None, "df": 1, "MS": None,
                "F": None, "p": None, "partial_eta2": None,
            })
            continue
        SS_ci = SSE_no_ci - SSE_full
        MS_ci = SS_ci
        F_ci = MS_ci / MS_error if MS_error > 0 else float("nan")
        p_ci = _f_sf(F_ci, 1.0, df_error) if math.isfinite(F_ci) else float("nan")
        denom_ci = SS_ci + SSE_full
        peta2_ci = SS_ci / denom_ci if denom_ci > 0 else 0.0
        covariate_effects.append({
            "name": cov_name,
            "SS": round(SS_ci, 4),
            "df": 1,
            "MS": round(MS_ci, 4),
            "F": round(F_ci, 4) if math.isfinite(F_ci) else None,
            "p": round(p_ci, 6) if math.isfinite(p_ci) else None,
            "partial_eta2": round(peta2_ci, 4),
        })

    # 同质性回归斜率检验（group × covariate 交互）
    try:
        X_int = _build_X(n, group_idxs, k, covariates, p,
                          include_group=True, include_interactions=True)
        SSE_int, _, _ = _fit_ols(y, X_int)
        df_hom = (k - 1) * p
        df_error_int = n - k - p - df_hom
        if df_hom > 0 and df_error_int > 0 and SSE_int > 0:
            SS_hom = SSE_full - SSE_int
            MS_hom = SS_hom / df_hom
            MS_err_int = SSE_int / df_error_int
            F_hom = MS_hom / MS_err_int if MS_err_int > 0 else float("nan")
            p_hom = _f_sf(F_hom, df_hom, df_error_int) if math.isfinite(F_hom) else float("nan")
            hom_p = p_hom if math.isfinite(p_hom) else None
            homogeneity: dict[str, Any] = {
                "F": round(F_hom, 4) if math.isfinite(F_hom) else None,
                "df1": df_hom,
                "df2": df_error_int,
                "p": round(hom_p, 6) if hom_p is not None else None,
                "assumption_met": hom_p is None or hom_p >= alpha,
            }
        else:
            homogeneity = {"F": None, "df1": None, "df2": None,
                           "p": None, "assumption_met": True,
                           "note": "自由度不足，无法进行交互检验"}
    except ValueError:
        homogeneity = {"F": None, "df1": None, "df2": None,
                       "p": None, "assumption_met": True,
                       "note": "交互设计矩阵奇异"}

    # 估计边际均值（EMMs）及置信区间
    t_crit = _t_ppf(alpha, df_error)
    emm_rows: list[list[float]] = []
    adjusted_means: list[dict[str, Any]] = []
    for li, lv in enumerate(group_levels):
        row_emm = [1.0]
        for g in range(1, k):
            row_emm.append(1.0 if li == g else 0.0)
        for ci in range(p):
            row_emm.append(grand_cov_means[ci])
        emm_rows.append(row_emm)

        adj_m = sum(beta_full[j] * row_emm[j] for j in range(len(row_emm)))
        Xb = _mat_vec(XtX_inv_full, row_emm)
        var_adj = MS_error * sum(row_emm[j] * Xb[j] for j in range(len(row_emm)))
        se_adj = math.sqrt(max(var_adj, 0.0))
        adjusted_means.append({
            "group": lv,
            "n": group_n[li],
            "unadj_mean": round(group_raw_means[li], 4),
            "adj_mean": round(adj_m, 4),
            "SE": round(se_adj, 4),
            "ci_lower": round(adj_m - t_crit * se_adj, 4),
            "ci_upper": round(adj_m + t_crit * se_adj, 4),
        })

    # 系数表（GLM 参数：截距 + 组哑变量 + 协变量）
    coefficients: list[dict[str, Any]] = []
    n_params = 1 + (k - 1) + p
    for j in range(n_params):
        if j == 0:
            name = "截距 (Intercept)"
        elif 1 <= j <= k - 1:
            name = f"{group_levels[j]} vs {group_levels[0]}"
        else:
            name = cov_names[j - k]
        b = beta_full[j]
        var_b = MS_error * XtX_inv_full[j][j]
        se_b = math.sqrt(max(var_b, 0.0)) if var_b >= 0 else float("nan")
        t_val = b / se_b if se_b > 0 else float("nan")
        p_val = _t_sf2(abs(t_val), df_error) if math.isfinite(t_val) else float("nan")
        coefficients.append({
            "name": name,
            "B": round(b, 4),
            "SE": round(se_b, 4) if math.isfinite(se_b) else None,
            "t": round(t_val, 4) if math.isfinite(t_val) else None,
            "p": round(p_val, 4) if math.isfinite(p_val) else None,
            "ci_lower": round(b - t_crit * se_b, 4) if math.isfinite(se_b) else None,
            "ci_upper": round(b + t_crit * se_b, 4) if math.isfinite(se_b) else None,
        })

    SS_total = sum((yi - grand_mean) ** 2 for yi in y)

    result: dict[str, Any] = {
        "group_effect": group_effect,
        "covariate_effects": covariate_effects,
        "homogeneity": homogeneity,
        "adjusted_means": adjusted_means,
        "coefficients": coefficients,
        "model": {
            "N": n,
            "k": k,
            "p_covariates": p,
            "SS_total": round(SS_total, 4),
            "SS_group": round(SS_group, 4),
            "SS_error": round(SSE_full, 4),
            "MS_error": round(MS_error, 4),
            "df_error": df_error,
            "group_levels": group_levels,
            "cov_names": cov_names,
            "grand_cov_means": [round(m, 4) for m in grand_cov_means],
        },
        "alpha": alpha,
    }

    # 事后成对 t 检验（基于 GLM 对比向量）
    if include_post_hoc:
        pairs: list[dict[str, Any]] = []
        for i in range(k):
            for j in range(i + 1, k):
                contrast = [emm_rows[i][c] - emm_rows[j][c] for c in range(len(emm_rows[i]))]
                Xb = _mat_vec(XtX_inv_full, contrast)
                var_diff = MS_error * sum(contrast[c] * Xb[c] for c in range(len(contrast)))
                se_diff = math.sqrt(max(var_diff, 0.0))
                diff = adjusted_means[i]["adj_mean"] - adjusted_means[j]["adj_mean"]
                t_val = diff / se_diff if se_diff > 0 else float("nan")
                p_val = _t_sf2(abs(t_val), df_error) if math.isfinite(t_val) else float("nan")
                pairs.append({
                    "group1": group_levels[i],
                    "group2": group_levels[j],
                    "adj_mean1": adjusted_means[i]["adj_mean"],
                    "adj_mean2": adjusted_means[j]["adj_mean"],
                    "diff": round(diff, 4),
                    "t": round(t_val, 4) if math.isfinite(t_val) else None,
                    "df": df_error,
                    "p_orig": round(p_val, 6) if math.isfinite(p_val) else None,
                })

        from psyclaw.psych.multiple_testing import holm as _holm
        pvals = [pr["p_orig"] if pr["p_orig"] is not None else 1.0 for pr in pairs]
        labels = [f"{pr['group1']} vs {pr['group2']}" for pr in pairs]
        corr = _holm(pvals, alpha=alpha, labels=labels)
        for idx, pr in enumerate(pairs):
            pr["p_adj"] = corr["tests"][idx]["p_adj"]
            pr["reject_h0"] = corr["tests"][idx]["reject_h0"]

        result["post_hoc"] = {
            "comparisons": pairs,
            "method": "holm",
            "n_significant": sum(pr["reject_h0"] for pr in pairs),
            "alpha": alpha,
        }

    return result


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def format_apa_ancova(result: dict[str, Any]) -> str:
    """生成 APA-7 ANCOVA 汇总表 + 调整均值表 + 文字段落。"""
    ge = result["group_effect"]
    mod = result["model"]
    cov_effects = result["covariate_effects"]
    adj_means = result["adjusted_means"]
    hom = result.get("homogeneity", {})

    k = mod["k"]
    N = mod["N"]
    p_cov = mod["p_covariates"]
    df_err = mod["df_error"]
    alpha = result.get("alpha", 0.05)

    # 同质性提示
    hom_warn = ""
    if not hom.get("assumption_met", True):
        hom_warn = (
            f"\n\n**警告（回归斜率同质性假设违反）：** "
            f"组×协变量交互显著，"
            f"*F*({hom['df1']}, {hom['df2']}) = {hom['F']:.2f}，"
            f"*p* {_fmt_p(hom['p'])}。"
            "调整均值比较在此条件下解释需谨慎；考虑逐组分析或 Johnson-Neyman 方法。"
        )

    # ANOVA 汇总表
    lines = [
        "## ANCOVA 汇总表",
        "",
        "| 来源 | *SS* | *df* | *MS* | *F* | *p* | 偏 *η*² |",
        "|------|------|------|------|-----|-----|---------|",
    ]
    # 协变量行
    for ce in cov_effects:
        f_str = f"{ce['F']:.2f}" if ce["F"] is not None else "—"
        ss_str = f"{ce['SS']:.3f}" if ce["SS"] is not None else "—"
        ms_str = f"{ce['MS']:.3f}" if ce["MS"] is not None else "—"
        pet_str = f"{ce['partial_eta2']:.3f}" if ce["partial_eta2"] is not None else "—"
        lines.append(
            f"| {ce['name']} | {ss_str} | {ce['df']} | {ms_str} | "
            f"{f_str} | {_fmt_p(ce['p'])} | {pet_str} |"
        )
    # 组因子行
    F_str = f"{ge['F']:.2f}" if ge["F"] is not None else "—"
    lines.append(
        f"| 组别 | {ge['SS']:.3f} | {ge['df']} | {ge['MS']:.3f} | "
        f"{F_str} | {_fmt_p(ge['p'])} | {ge['partial_eta2']:.3f} |"
    )
    # 误差行
    lines.append(
        f"| 误差 | {mod['SS_error']:.3f} | {df_err} | {mod['MS_error']:.3f} | | | |"
    )
    lines += ["", f"*注：N* = {N}，协变量已在组均值处估计调整均值。"]

    # 调整均值表
    cov_mean_strs = [
        f"{mod['cov_names'][i]} = {mod['grand_cov_means'][i]:.2f}"
        for i in range(p_cov)
    ]
    lines += [
        "",
        f"## 调整均值（协变量固定于：{', '.join(cov_mean_strs)}）",
        "",
        "| 组别 | *n* | 原始 *M* | 调整 *M* | *SE* | 95% CI |",
        "|------|-----|----------|----------|------|--------|",
    ]
    for am in adj_means:
        ci = f"[{am['ci_lower']:.2f}, {am['ci_upper']:.2f}]"
        lines.append(
            f"| {am['group']} | {am['n']} | {am['unadj_mean']:.2f} | "
            f"{am['adj_mean']:.2f} | {am['SE']:.2f} | {ci} |"
        )

    # 同质性检验行
    if hom.get("F") is not None:
        lines += [
            "",
            "## 回归斜率同质性检验",
            "",
            f"Group × Covariate 交互：*F*({hom['df1']}, {hom['df2']}) = {hom['F']:.2f}，"
            f"*p* {_fmt_p(hom['p'])}。"
            f"{'同质性假设成立（p ≥ .05）。' if hom['assumption_met'] else '**违反同质性假设（p < .05）。**'}",
        ]

    # APA 文字段落
    ge_F = ge["F"] if ge["F"] is not None else float("nan")
    ge_p = _fmt_p(ge["p"])
    ge_pet = ge["partial_eta2"]
    ge_pom = ge["partial_omega2"]

    cov_sents = []
    for ce in cov_effects:
        cov_sents.append(
            f"{ce['name']}（*F*(1, {df_err}) = "
            f"{ce['F']:.2f}，*p* {_fmt_p(ce['p'])}，偏 *η*² = {ce['partial_eta2']:.3f}）"
            if ce["F"] is not None else f"{ce['name']}（无法估计）"
        )

    para = (
        f"\n## APA-7 结果段落\n\n"
        f"在控制{'/'.join(mod['cov_names'])}后，以{'/'.join(mod['group_levels'])}为自变量对因变量进行单因素 ANCOVA（N = {N}）。"
        f"协变量{'分别' if p_cov > 1 else ''}显著预测了因变量：{'；'.join(cov_sents)}。"
        f"组间差异{'显著' if ge['p'] is not None and ge['p'] < alpha else '未达显著水平'}，"
        f"*F*({ge['df']}, {df_err}) = {ge_F:.2f}，*p* {ge_p}，"
        f"偏 *η*² = {ge_pet:.3f}，偏 *ω*² = {ge_pom:.3f}。"
        f"{hom_warn}"
    )
    lines.append(para)
    return "\n".join(lines)


def format_apa_post_hoc(ph_result: dict[str, Any]) -> str:
    """格式化事后检验结果为 Markdown 表格。"""
    lines = [
        "## 事后成对比较（调整均值，Holm 校正 t）",
        "",
        "| 对比 | 调整 *M* 差 | *t* | *df* | 原始 *p* | 校正 *p* | 显著 |",
        "|------|------------|-----|------|---------|---------|------|",
    ]
    for c in ph_result["comparisons"]:
        t_str = f"{c['t']:.2f}" if c["t"] is not None else "—"
        sig = "✓" if c["reject_h0"] else ""
        lines.append(
            f"| {c['group1']} vs {c['group2']} | {c['diff']:.2f} | "
            f"{t_str} | {c['df']} | {_fmt_p(c['p_orig'])} | "
            f"{_fmt_p(c['p_adj'])} | {sig} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_ancova_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ph_result = result.get("post_hoc")
    lines = [
        "# ANCOVA（协方差分析）报告",
        "",
        format_apa_ancova(result),
    ]
    if ph_result:
        lines += ["", format_apa_post_hoc(ph_result)]

    md_path = out / "ancova_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / "ancova_report.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col_float(rows: list[dict[str, str]], col: str) -> list[float | None]:
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


def analyze_ancova(
    csv_path: str,
    dv: str,
    group_col: str,
    cov_cols: list[str],
    alpha: float = 0.05,
    include_post_hoc: bool = False,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行 ANCOVA。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    # 读取各列
    dv_vals = _read_col_float(rows, dv)
    grp_vals = [row.get(group_col, "").strip() for row in rows]
    cov_vals = [_read_col_float(rows, c) for c in cov_cols]

    # 完整案例过滤
    valid_idx = [
        i for i in range(len(rows))
        if dv_vals[i] is not None
        and grp_vals[i]
        and all(cov_vals[ci][i] is not None for ci in range(len(cov_cols)))
    ]
    n_excluded = len(rows) - len(valid_idx)

    if not valid_idx:
        raise ValueError("过滤后无有效数据行（检查 DV / 分组 / 协变量列是否存在缺失）")

    y = [dv_vals[i] for i in valid_idx]
    groups = [grp_vals[i] for i in valid_idx]
    covariates = [[cov_vals[ci][i] for ci in range(len(cov_cols))] for i in valid_idx]

    result = ancova(
        y=y,
        groups=groups,
        covariates=covariates,
        cov_names=cov_cols,
        alpha=alpha,
        include_post_hoc=include_post_hoc,
    )
    result["dv"] = dv
    result["group_col"] = group_col
    result["n_excluded"] = n_excluded
    result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_ancova_report(result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def ancova_cli(args: list[str]) -> int:
    """psyclaw ancova <data.csv> --dv <col> --group <col> --cov cov1[,cov2] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw ancova",
        description=(
            "单因素 ANCOVA（协方差分析）：控制协变量后比较各组调整均值；"
            "Type-III SS / 偏 η² / 偏 ω² / EMM / 同质性检验 / APA-7 报告"
        ),
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--group", required=True, help="分组列名（分类变量）")
    parser.add_argument("--cov", required=True,
                        help="协变量列名，逗号分隔（如 --cov age,pretest）")
    parser.add_argument("--post-hoc", action="store_true", dest="post_hoc",
                        help="附加 Holm 校正事后成对调整均值比较")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    cov_list = [c.strip() for c in opts.cov.split(",") if c.strip()]
    if not cov_list:
        print("错误：--cov 至少需要一个协变量列名")
        return 1

    try:
        result = analyze_ancova(
            csv_path=opts.csv_file,
            dv=opts.dv,
            group_col=opts.group,
            cov_cols=cov_list,
            alpha=opts.alpha,
            include_post_hoc=opts.post_hoc,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_ancova(result))
    if opts.post_hoc and "post_hoc" in result:
        print()
        print(format_apa_post_hoc(result["post_hoc"]))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
