"""两层随机截距混合线性模型（HLM/MLM）— EM 算法，ICC/AIC/BIC，APA-7，stdlib only。

模型: y_ij = X_ij * β + u_j + ε_ij
      u_j ~ N(0, τ²),  ε_ij ~ N(0, σ²)

其中 j = 1…J 为 level-2 单元（cluster），i = 1…nⱼ 为 level-1 观测。

提供:
  - fit_random_intercept(y, X, groups, ...)  → 结果字典
  - compute_icc_mlm(tau2, sigma2)            → ICC + 解释
  - format_apa_mlm(result, alpha)            → APA-7 Markdown 表格 + 段落
  - write_mlm_report(result, out_dir, alpha) → MD + JSON sidecar
  - analyze_mlm(csv_path, dv, cluster, ivs) → CSV 主入口
  - mlm_cli(argv)                            → CLI 入口

CLI:
  psyclaw mlm <data.csv> --dv <col> --cluster <col>
              [--iv col1,col2,...] [--alpha .05]
              [--max-iter 200] [--json] [--out dir]

理论依据:
  Laird & Ware (1982). Random-effects models for longitudinal data.
    Biometrics, 38(4), 963–974.
  Bryk & Raudenbush (1992). Hierarchical Linear Models. Sage.
  Raudenbush & Bryk (2002). Hierarchical Linear Models (2nd ed.). Sage.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any

import numpy as np
from scipy import stats


# ─────────────────────────────────────────────────────────────────────────────
# 矩阵工具 (Gauss-Jordan, stdlib only)
# ─────────────────────────────────────────────────────────────────────────────

def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    try:
        return np.linalg.inv(np.asarray(M, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        return None


def _mat_vec(A: list[list[float]], v: list[float]) -> list[float]:
    return (np.asarray(A, dtype=float) @ np.asarray(v, dtype=float)).tolist()


# ─────────────────────────────────────────────────────────────────────────────
# 分布工具（scipy）
# ─────────────────────────────────────────────────────────────────────────────

def _t_sf2(t: float, df: float) -> float:
    """双尾 t 检验 p 值 —— scipy.stats.t.sf。"""
    if not math.isfinite(t) or not math.isfinite(df) or df <= 0:
        return float("nan")
    return 2.0 * float(stats.t.sf(abs(t), df))


def _t_quantile(p: float, df: float) -> float:
    """t 分布临界值（双尾 p 对应的 |t|）—— scipy.stats.t.ppf。"""
    if df <= 0 or not (0 < p < 1):
        return float("nan")
    return float(stats.t.ppf(1.0 - p / 2.0, df))


def _chi2_sf(x: float, df: float) -> float:
    if x <= 0:
        return 1.0
    if not math.isfinite(x) or df <= 0:
        return float("nan")
    return float(stats.chi2.sf(x, df))


# ─────────────────────────────────────────────────────────────────────────────
# 核心估计: EM 算法 (ML) for random intercept model
# ─────────────────────────────────────────────────────────────────────────────

def fit_random_intercept(
    y: list[float],
    X: list[list[float]],
    groups: list,
    pred_names: list[str] | None = None,
    max_iter: int = 100,
    tol: float = 1e-8,
) -> dict[str, Any]:
    """两层随机截距模型的 ML 估计 (EM 算法)。

    参数:
      y          : 因变量观测值列表 (N,)
      X          : 固定效应设计矩阵，不含截距，可为空列表 [] (N×q)
      groups     : 每个观测所属的 cluster 标签列表 (N,)
      pred_names : 预测变量名称列表 (q,)；若为 None 则自动编号
      max_iter   : EM 最大迭代次数
      tol        : 收敛判据（参数变化绝对值）

    返回 dict，包含:
      beta, se, t, p, ci_lower, ci_upper — 固定效应
      sigma2, tau2, icc                   — 方差分量
      ll, aic, bic                        — 模型拟合
      u_hat, blup_se                      — 随机效应 BLUPs
      converged, n_iter                   — 诊断信息
    """
    N = len(y)
    if N < 3:
        raise ValueError(f"样本量过小（N={N}），至少需要 3 个观测")

    # --- 处理 cluster 标签 ---
    unique_groups = sorted(set(groups), key=str)
    J = len(unique_groups)
    if J < 2:
        raise ValueError(f"至少需要 2 个 cluster（实得 {J}），单组数据无法估计 τ²")
    if J == N:
        raise ValueError("每个 cluster 仅有 1 个观测，无法估计 σ²（组内无重复）")

    grp_map = {g: j for j, g in enumerate(unique_groups)}
    gj = [grp_map[g] for g in groups]

    members: list[list[int]] = [[] for _ in range(J)]
    for i, j in enumerate(gj):
        members[j].append(i)
    n_j = [len(m) for m in members]

    # --- 设计矩阵（含截距）---
    q = len(X[0]) if X and X[0] else 0
    Xint = [[1.0] + (list(X[i]) if X else []) for i in range(N)]
    p = q + 1  # 参数个数（含截距）

    if pred_names is None:
        pred_names = [f"X{k+1}" for k in range(q)]
    term_names = ["Intercept"] + list(pred_names)

    def _gls_beta(sigma2: float, tau2: float):
        """GLS 固定效应估计，返回 (beta, cov_matrix) or None。"""
        XtVX = [[0.0] * p for _ in range(p)]
        XtVy = [0.0] * p
        for j in range(J):
            nj = n_j[j]
            a_j = 1.0 / sigma2
            b_j = tau2 / (sigma2 * (sigma2 + nj * tau2))
            idx = members[j]
            col_sums = [sum(Xint[idx[k]][col] for k in range(nj)) for col in range(p)]
            y_sum_j = sum(y[idx[k]] for k in range(nj))
            for a in range(p):
                for b in range(p):
                    XtVX[a][b] += (
                        a_j * sum(Xint[idx[k]][a] * Xint[idx[k]][b] for k in range(nj))
                        - b_j * col_sums[a] * col_sums[b]
                    )
                XtVy[a] += (
                    a_j * sum(Xint[idx[k]][a] * y[idx[k]] for k in range(nj))
                    - b_j * col_sums[a] * y_sum_j
                )
        inv = _mat_invert(XtVX)
        if inv is None:
            return None, None
        return _mat_vec(inv, XtVy), inv

    # --- 初始 OLS（忽略聚类）---
    XtX = [[sum(Xint[i][a] * Xint[i][b] for i in range(N)) for b in range(p)] for a in range(p)]
    Xty = [sum(Xint[i][a] * y[i] for i in range(N)) for a in range(p)]
    inv0 = _mat_invert(XtX)
    if inv0 is None:
        raise ValueError("设计矩阵奇异，请检查预测变量是否存在多重共线性")
    beta = _mat_vec(inv0, Xty)
    cov_beta = inv0

    resid = [y[i] - sum(Xint[i][k] * beta[k] for k in range(p)) for i in range(N)]
    sigma2 = sum(r * r for r in resid) / max(1, N - p)

    # 初始 τ² 用组间-组内 MS 法（调和平均数修正）
    grand = sum(y) / N
    ss_b = sum(n_j[j] * (sum(y[members[j][k]] for k in range(n_j[j])) / n_j[j] - grand) ** 2 for j in range(J))
    ms_b = ss_b / (J - 1) if J > 1 else 0.0
    n_harm = (N - sum(nj ** 2 for nj in n_j) / N) / (J - 1) if J > 1 else N
    tau2 = max(1e-8, (ms_b - sigma2) / n_harm)

    # --- EM 迭代 ---
    converged = False
    n_iter = 0
    for iteration in range(max_iter):
        n_iter = iteration + 1
        old_sigma2, old_tau2 = sigma2, tau2
        old_beta = beta[:]

        # E-step: 后验均值 û_j 和后验方差 Var(u_j|y)
        resid = [y[i] - sum(Xint[i][k] * beta[k] for k in range(p)) for i in range(N)]
        u_hat = []
        var_u = []
        for j in range(J):
            nj = n_j[j]
            mean_resid_j = sum(resid[members[j][k]] for k in range(nj)) / nj
            lam_j = tau2 / (tau2 + sigma2 / nj)
            u_hat.append(lam_j * mean_resid_j)
            var_u.append(tau2 * (1.0 - lam_j))

        # M-step: 更新方差分量
        ss_resid = 0.0
        for j in range(J):
            for i in members[j]:
                r = y[i] - sum(Xint[i][k] * beta[k] for k in range(p)) - u_hat[j]
                ss_resid += r * r
        sigma2 = max(1e-14, ss_resid / N)
        tau2 = max(1e-14, sum(u_hat[j] ** 2 + var_u[j] for j in range(J)) / J)

        # GLS 更新 beta
        new_beta, new_cov = _gls_beta(sigma2, tau2)
        if new_beta is not None:
            beta = new_beta
            cov_beta = new_cov

        # 收敛检查
        dbeta = max(abs(beta[k] - old_beta[k]) for k in range(p))
        if abs(sigma2 - old_sigma2) < tol and abs(tau2 - old_tau2) < tol and dbeta < tol:
            converged = True
            break

    # --- 最终 BLUPs ---
    resid = [y[i] - sum(Xint[i][k] * beta[k] for k in range(p)) for i in range(N)]
    u_hat = []
    blup_se = []
    for j in range(J):
        nj = n_j[j]
        mean_resid_j = sum(resid[members[j][k]] for k in range(nj)) / nj
        lam_j = tau2 / (tau2 + sigma2 / nj)
        u_hat.append(lam_j * mean_resid_j)
        blup_se.append(math.sqrt(max(0.0, tau2 * (1.0 - lam_j))))

    # --- 固定效应推断 ---
    df_resid = max(1, N - J)  # Raudenbush & Bryk 推荐近似
    se_beta = [math.sqrt(max(0.0, cov_beta[k][k])) for k in range(p)]
    t_vals = [
        beta[k] / se_beta[k] if se_beta[k] > 1e-14 else float("nan")
        for k in range(p)
    ]
    p_vals = [
        _t_sf2(t, df_resid) if math.isfinite(t) else float("nan")
        for t in t_vals
    ]
    t_crit = _t_quantile(0.05, df_resid)  # 双尾 α=.05 临界值
    ci_lower = [beta[k] - t_crit * se_beta[k] for k in range(p)]
    ci_upper = [beta[k] + t_crit * se_beta[k] for k in range(p)]

    # --- 对数似然 / AIC / BIC ---
    ll = _log_likelihood_ri(y, Xint, members, n_j, beta, sigma2, tau2)
    k_params = p + 2  # p 固定效应 + σ² + τ²
    aic = -2.0 * ll + 2.0 * k_params
    bic = -2.0 * ll + k_params * math.log(N)

    icc = tau2 / (tau2 + sigma2) if (tau2 + sigma2) > 0 else 0.0

    return {
        "N": N, "J": J, "n_j": n_j, "unique_groups": [str(g) for g in unique_groups],
        "term_names": term_names, "pred_names": pred_names,
        "beta": beta, "se": se_beta, "t": t_vals, "p": p_vals,
        "ci_lower": ci_lower, "ci_upper": ci_upper,
        "df_resid": df_resid,
        "sigma2": sigma2, "tau2": tau2, "icc": icc,
        "ll": ll, "aic": aic, "bic": bic,
        "u_hat": u_hat, "blup_se": blup_se,
        "converged": converged, "n_iter": n_iter,
    }


def _log_likelihood_ri(
    y: list[float],
    Xint: list[list[float]],
    members: list[list[int]],
    n_j: list[int],
    beta: list[float],
    sigma2: float,
    tau2: float,
) -> float:
    """随机截距模型的边际对数似然（ML）。"""
    N = len(y)
    p = len(beta)
    ll = -0.5 * N * math.log(2.0 * math.pi)
    for j, idx in enumerate(members):
        nj = n_j[j]
        resid_j = [y[idx[k]] - sum(Xint[idx[k]][col] * beta[col] for col in range(p)) for k in range(nj)]
        sum_r = sum(resid_j)
        ss_j = sum(r * r for r in resid_j)
        # log|V_j| = (nj-1)*log(σ²) + log(σ² + nj*τ²)
        ll -= 0.5 * ((nj - 1) * math.log(sigma2) + math.log(sigma2 + nj * tau2))
        # (y_j - Xβ)' V_j^{-1} (y_j - Xβ)
        quad = ss_j / sigma2 - tau2 / (sigma2 * (sigma2 + nj * tau2)) * sum_r ** 2
        ll -= 0.5 * quad
    return ll


# ─────────────────────────────────────────────────────────────────────────────
# ICC 计算与解释
# ─────────────────────────────────────────────────────────────────────────────

def compute_icc_mlm(tau2: float, sigma2: float) -> dict[str, Any]:
    total = tau2 + sigma2
    icc = tau2 / total if total > 1e-14 else 0.0
    if icc < 0.05:
        interp = "可忽略（< .05）；MLM 修正收益小"
    elif icc < 0.10:
        interp = "小（.05–.10）；建议使用 MLM 控制聚类效应"
    elif icc < 0.25:
        interp = "中等（.10–.25）；应使用 MLM"
    else:
        interp = "大（≥ .25）；数据严重嵌套，MLM 不可省略"
    return {"icc": icc, "tau2": tau2, "sigma2": sigma2, "interpretation": interp}


# ─────────────────────────────────────────────────────────────────────────────
# APA-7 格式化
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(x: float, dec: int = 2) -> str:
    if not math.isfinite(x):
        return str(x)
    return f"{x:.{dec}f}"


def _fmt_p(p: float) -> str:
    if not math.isfinite(p):
        return "N/A"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}"


def format_apa_mlm(result: dict[str, Any], alpha: float = 0.05) -> str:
    """生成 APA-7 MLM 结果文本：固定效应表 + 方差分量表 + 段落摘要。"""
    ci_pct = int((1.0 - alpha) * 100)
    names = result["term_names"]
    beta = result["beta"]
    se = result["se"]
    t_vals = result["t"]
    p_vals = result["p"]
    ci_lo = result["ci_lower"]
    ci_hi = result["ci_upper"]
    sigma2 = result["sigma2"]
    tau2 = result["tau2"]
    icc = result["icc"]
    J = result["J"]
    N = result["N"]
    n_j = result["n_j"]
    df = result["df_resid"]

    # ── 固定效应表 ──
    col_w = max(len(n) for n in names)
    header = (
        f"| {'固定效应':<{col_w}} | {'*B*':>8} | {'SE':>6} | "
        f"{'*t*':>8} | {'*p*':>8} | {f'{ci_pct}% CI':>14} |"
    )
    sep = f"| {'-'*col_w} | {'-'*8} | {'-'*6} | {'-'*8} | {'-'*8} | {'-'*14} |"
    rows_fe = [header, sep]
    for k, name in enumerate(names):
        ci_str = f"[{_fmt(ci_lo[k])}, {_fmt(ci_hi[k])}]"
        rows_fe.append(
            f"| {name:<{col_w}} | {_fmt(beta[k]):>8} | {_fmt(se[k]):>6} | "
            f"{_fmt(t_vals[k]):>8} | {_fmt_p(p_vals[k]):>8} | {ci_str:>14} |"
        )
    rows_fe.append(sep)
    rows_fe.append(f"*注*: *t* 自由度 = {df}（N − J 近似，Raudenbush & Bryk, 2002）。")

    # ── 方差分量表 ──
    icc_info = compute_icc_mlm(tau2, sigma2)
    n_min, n_max = min(n_j), max(n_j)
    n_mean = N / J
    vc_rows = [
        "| 方差分量 | 估计值 | 说明 |",
        "| --- | --- | --- |",
        f"| τ²（截距方差） | {_fmt(tau2, 4)} | Level-2 随机截距方差（ML 估计，偏低） |",
        f"| σ²（残差方差） | {_fmt(sigma2, 4)} | Level-1 残差方差 |",
        f"| ICC | {_fmt(icc, 4)} | {icc_info['interpretation']} |",
        f"| *J*（clusters） | {J} | |",
        f"| *N*（观测） | {N} | |",
        f"| 每组 *n*（范围） | {n_min}–{n_max}（均值 {_fmt(n_mean, 1)}） | |",
    ]

    # ── 模型拟合 ──
    fit_rows = [
        "| 拟合指标 | 值 |",
        "| --- | --- |",
        f"| −2LL | {_fmt(-2 * result['ll'], 3)} |",
        f"| AIC | {_fmt(result['aic'], 3)} |",
        f"| BIC | {_fmt(result['bic'], 3)} |",
        f"| EM 迭代次数 | {result['n_iter']} |",
        f"| 收敛 | {'是' if result['converged'] else '否（达最大迭代次数）'} |",
    ]

    # ── 文字段落 ──
    sig_preds = [
        (names[k], beta[k], t_vals[k], p_vals[k])
        for k in range(1, len(names))
        if math.isfinite(p_vals[k]) and p_vals[k] < alpha
    ]
    b0 = beta[0]
    para_parts = [
        f"我们对 {J} 个 cluster（*N* = {N}）的数据拟合了两层随机截距模型。"
        f"ICC = {_fmt(icc, 3)}（{icc_info['interpretation']}），"
        f"表明 {_fmt(icc * 100, 1)}% 的总方差归属于 cluster 层。",
        f"固定效应截距 *B* = {_fmt(b0, 2)}，*t*({df}) {_fmt(t_vals[0], 2)}，"
        f"*p* {_fmt_p(p_vals[0])}。",
    ]
    if sig_preds:
        parts = []
        for name, b, t, pv in sig_preds:
            parts.append(f"{name}（*B* = {_fmt(b, 2)}，*t*({df}) = {_fmt(t, 2)}，*p* {_fmt_p(pv)}）")
        para_parts.append("显著固定效应预测变量：" + "；".join(parts) + "。")
    else:
        para_parts.append("无显著固定效应预测变量（*p* < .05）。")
    para_parts.append(
        f"方差分量：τ² = {_fmt(tau2, 4)}（cluster-level 截距方差），"
        f"σ² = {_fmt(sigma2, 4)}（个体 level 残差方差）。"
        f"AIC = {_fmt(result['aic'], 2)}，BIC = {_fmt(result['bic'], 2)}。"
    )

    sections = [
        "## 固定效应（Fixed Effects）",
        "\n".join(rows_fe),
        "",
        "## 方差分量（Random Effects）",
        "\n".join(vc_rows),
        "",
        "## 模型拟合",
        "\n".join(fit_rows),
        "",
        "## 结果摘要",
        " ".join(para_parts),
    ]
    return "\n".join(sections)


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar 输出
# ─────────────────────────────────────────────────────────────────────────────

def write_mlm_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    alpha: float = 0.05,
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / "mlm_report.md"
    json_path = out / "mlm_report.json"

    md_text = f"# MLM 随机截距模型报告\n\n{format_apa_mlm(result, alpha)}\n"
    md_path.write_text(md_text, encoding="utf-8")

    # JSON 序列化（移除大型列表以免过大）
    serial = {k: v for k, v in result.items() if k not in ("u_hat", "blup_se")}
    json_path.write_text(json.dumps(serial, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


# ─────────────────────────────────────────────────────────────────────────────
# CSV 主入口
# ─────────────────────────────────────────────────────────────────────────────

def analyze_mlm(
    csv_path: str | pathlib.Path,
    dv: str,
    cluster: str,
    ivs: list[str] | None = None,
    alpha: float = 0.05,
    max_iter: int = 200,
    out_dir: str | pathlib.Path | None = None,
    json_output: bool = False,
) -> dict[str, Any]:
    """从 CSV 读取数据，拟合随机截距模型，返回结果字典并可选写 sidecar。"""
    ivs = ivs or []

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        raise ValueError(f"CSV 文件为空：{csv_path}")

    required = [dv, cluster] + ivs
    missing = [c for c in required if c not in rows[0]]
    if missing:
        raise ValueError(f"CSV 缺少列：{missing}")

    y, groups, X = [], [], []
    n_excluded = 0
    for row in rows:
        try:
            y_val = float(row[dv])
            if not math.isfinite(y_val):
                n_excluded += 1
                continue
            x_vals = [float(row[iv]) for iv in ivs]
            if any(not math.isfinite(v) for v in x_vals):
                n_excluded += 1
                continue
            grp_raw = str(row[cluster]).strip()
            if not grp_raw:
                n_excluded += 1
                continue
            y.append(y_val)
            groups.append(grp_raw)
            X.append(x_vals)
        except (ValueError, TypeError):
            n_excluded += 1

    if not y:
        raise ValueError("过滤后无有效观测，请检查数据")

    result = fit_random_intercept(
        y=y, X=X, groups=groups, pred_names=ivs or None,
        max_iter=max_iter,
    )
    result["n_excluded"] = n_excluded
    result["dv"] = dv
    result["cluster_var"] = cluster
    result["ivs"] = ivs

    if out_dir is not None:
        md_p, json_p = write_mlm_report(result, out_dir, alpha)
        result["_md_path"] = str(md_p)
        result["_json_path"] = str(json_p)

    if json_output:
        serial = {k: v for k, v in result.items() if k not in ("u_hat", "blup_se")}
        print(json.dumps(serial, ensure_ascii=False, indent=2))
    else:
        print(format_apa_mlm(result, alpha))
        if n_excluded:
            print(f"\n[注意] 排除了 {n_excluded} 个含缺失/无效值的观测。")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────

def mlm_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="psyclaw mlm",
        description="两层随机截距混合线性模型（HLM/MLM），EM 算法，stdlib only。",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--dv", required=True, help="因变量列名")
    ap.add_argument("--cluster", required=True, help="Level-2 聚类变量列名（如 school_id、therapist_id）")
    ap.add_argument("--iv", default=None, dest="iv",
                    help="固定效应预测变量列名，逗号分隔（可选；不填则仅拟合零模型）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--max-iter", type=int, default=200, dest="max_iter",
                    help="EM 最大迭代次数（默认 200）")
    ap.add_argument("--out", default=None, help="sidecar 输出目录（写 mlm_report.{md,json}）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")

    args = ap.parse_args(argv)
    ivs = [v.strip() for v in args.iv.split(",")] if args.iv else []

    try:
        analyze_mlm(
            csv_path=args.csv,
            dv=args.dv,
            cluster=args.cluster,
            ivs=ivs,
            alpha=args.alpha,
            max_iter=args.max_iter,
            out_dir=args.out,
            json_output=args.json,
        )
    except Exception as exc:
        print(f"错误: {exc}")
        return 1
    return 0
