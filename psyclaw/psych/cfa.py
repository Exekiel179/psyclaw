"""验证性因子分析 (CFA) — 受限 ULS 估计，stdlib only。

提供：
  - compute_cfa(data_cols, model_spec, ...)    → 因子载荷/拟合指数/残差
  - format_apa_cfa(result)                     → APA-7 Markdown 表格+段落
  - write_cfa_report(result, out_dir)          → MD + JSON sidecar
  - analyze_cfa(csv_path, ...)                 → CSV 主入口
  - cfa_cli(argv)                              → CLI 处理器

CLI:
  psyclaw cfa <data.csv> --model "F1:x1,x2,x3;F2:x4,x5,x6"
              [--oblique] [--max-iter N] [--json] [--out dir]

理论依据：
  Browne, M. W., & Cudeck, R. (1993). Alternative ways of assessing
    model fit. Sociological Methods & Research, 21(2), 230–258.
  Hu, L., & Bentler, P. M. (1999). Cutoff criteria for fit indexes in
    covariance structure analysis. Structural Equation Modeling, 6(1), 1–55.
  McDonald, R. P., & Ho, M. H. R. (2002). Principles and practice in
    reporting structural equation analyses. Psychological Methods, 7(1), 64–76.
  Kline, R. B. (2015). Principles and practice of structural equation
    modeling (4th ed.). Guilford Press.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any


# ─── 矩阵工具（stdlib only）──────────────────────────────────────────────────

def _mm(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """矩阵乘法 A(m×n) @ B(n×p) → m×p。"""
    m, n, p = len(A), len(A[0]), len(B[0])
    return [
        [sum(A[i][k] * B[k][j] for k in range(n)) for j in range(p)]
        for i in range(m)
    ]


def _T(A: list[list[float]]) -> list[list[float]]:
    """矩阵转置。"""
    return [[A[i][j] for i in range(len(A))] for j in range(len(A[0]))]


def _add(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[A[i][j] + B[i][j] for j in range(len(A[0]))] for i in range(len(A))]


def _sub(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    return [[A[i][j] - B[i][j] for j in range(len(A[0]))] for i in range(len(A))]


def _scale(A: list[list[float]], s: float) -> list[list[float]]:
    return [[A[i][j] * s for j in range(len(A[0]))] for i in range(len(A))]


def _diag(v: list[float]) -> list[list[float]]:
    n = len(v)
    return [[v[i] if i == j else 0.0 for j in range(n)] for i in range(n)]


# ─── 相关矩阵（完整案例 Pearson r）──────────────────────────────────────────

def _corr_matrix(
    cols: list[list[float]],
) -> tuple[list[list[float]], int]:
    """计算 Pearson 相关矩阵（完整案例过滤）。返回 (R, N_valid)。"""
    k = len(cols)
    n_orig = len(cols[0])
    valid = [i for i in range(n_orig) if all(math.isfinite(c[i]) for c in cols)]
    n = len(valid)
    if n < 3:
        raise ValueError(f"完整案例不足（{n} < 3），无法计算相关矩阵")

    vals = [[cols[j][i] for i in valid] for j in range(k)]
    means = [sum(v) / n for v in vals]
    sds = []
    for j in range(k):
        var = sum((vals[j][i] - means[j]) ** 2 for i in range(n)) / (n - 1)
        sds.append(math.sqrt(max(var, 0.0)))

    R: list[list[float]] = [[0.0] * k for _ in range(k)]
    for a in range(k):
        R[a][a] = 1.0
        for b in range(a + 1, k):
            if sds[a] < 1e-15 or sds[b] < 1e-15:
                R[a][b] = R[b][a] = 0.0
            else:
                cov = sum(
                    (vals[a][i] - means[a]) * (vals[b][i] - means[b]) for i in range(n)
                ) / (n - 1)
                r = max(-1.0, min(1.0, cov / (sds[a] * sds[b])))
                R[a][b] = R[b][a] = r
    return R, n


# ─── 模型规格解析 ─────────────────────────────────────────────────────────────

def _parse_model(
    model_spec: str | dict[str, list[str]],
    col_names: list[str],
) -> tuple[list[str], list[str], list[list[bool]], list[list[bool]]]:
    """解析 CFA 模型规格。

    model_spec:
      str  → "F1:x1,x2,x3; F2:x4,x5,x6"
      dict → {"F1": ["x1","x2","x3"], "F2": ["x4","x5","x6"]}

    返回:
      factors      — 因子名列表 [k]
      item_order   — 条目名列表 [p]（各因子条目去重合并，保留顺序）
      free_mask    — p×k bool，True=自由参数（含标记）
      marker_mask  — p×k bool，True=标记变量（固定为 1.0，每因子首条目）
    """
    if isinstance(model_spec, str):
        model_dict: dict[str, list[str]] = {}
        for part in model_spec.split(";"):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValueError(
                    f"无效模型规格片段: '{part}'，格式应为 'FactorName:item1,item2,...'"
                )
            fname, items_str = part.split(":", 1)
            items = [x.strip() for x in items_str.split(",") if x.strip()]
            model_dict[fname.strip()] = items
    else:
        model_dict = dict(model_spec)

    if not model_dict:
        raise ValueError("模型规格不能为空")

    factors = list(model_dict.keys())
    k = len(factors)

    # 条目顺序：按首次出现保留
    seen: dict[str, int] = {}
    for f_items in model_dict.values():
        for item in f_items:
            if item not in seen:
                seen[item] = len(seen)
    item_order = list(seen.keys())
    p = len(item_order)

    # 校验所有条目在数据列中存在
    for item in item_order:
        if item not in col_names:
            raise ValueError(f"模型中的变量 '{item}' 不在数据列中: {col_names}")

    # 构建掩码
    free_mask = [[False] * k for _ in range(p)]
    marker_mask = [[False] * k for _ in range(p)]

    for fi, (fname, f_items) in enumerate(model_dict.items()):
        for ii, item in enumerate(f_items):
            pi = item_order.index(item)
            free_mask[pi][fi] = True
            if ii == 0:
                marker_mask[pi][fi] = True  # 标记变量，固定为 1.0

    # 检查识别性：每个因子至少 2 个自由（非标记）条目
    for fi, fname in enumerate(factors):
        free_count = sum(
            1 for i in range(p)
            if free_mask[i][fi] and not marker_mask[i][fi]
        )
        if free_count < 1:
            raise ValueError(
                f"因子 '{fname}' 至少需要 2 个条目（含标记变量）以保证识别性，"
                f"当前只有 {free_count + 1} 个"
            )

    return factors, item_order, free_mask, marker_mask


# ─── CFA 核心（ULS + Adam 优化器）────────────────────────────────────────────

def _sigma(
    lam: list[list[float]],
    phi: list[list[float]],
    psi: list[float],
) -> list[list[float]]:
    """模型隐含相关矩阵 Σ = Λ Φ Λᵀ + Ψ。"""
    p = len(lam)
    k = len(lam[0])
    # Λ Φ: p×k
    LPhi = [[sum(lam[i][f] * phi[f][g] for f in range(k)) for g in range(k)] for i in range(p)]
    # (Λ Φ) Λᵀ: p×p
    Sigma = [[sum(LPhi[i][f] * lam[j][f] for f in range(k)) for j in range(p)] for i in range(p)]
    # + Ψ（对角）
    for i in range(p):
        Sigma[i][i] += psi[i]
    return Sigma


def _f_uls(S: list[list[float]], Sig: list[list[float]]) -> float:
    """ULS 拟合函数 F = 0.5 * Σ_ij (S_ij − Σ_ij)²。"""
    p = len(S)
    total = 0.0
    for i in range(p):
        for j in range(p):
            d = S[i][j] - Sig[i][j]
            total += d * d
    return 0.5 * total


def _residual(S: list[list[float]], Sig: list[list[float]]) -> list[list[float]]:
    return [[S[i][j] - Sig[i][j] for j in range(len(S[0]))] for i in range(len(S))]


def _grad_lam(
    R: list[list[float]],
    lam: list[list[float]],
    phi: list[list[float]],
    free_mask: list[list[bool]],
    marker_mask: list[list[bool]],
) -> list[list[float]]:
    """∂F/∂Λ = −2 R Λ Φ（仅对自由非标记参数有效）。"""
    p, k = len(lam), len(lam[0])
    # R Λ: p×k
    RL = [[sum(R[i][j] * lam[j][f] for j in range(p)) for f in range(k)] for i in range(p)]
    # (R Λ) Φ: p×k
    RLP = [[sum(RL[i][f] * phi[f][g] for f in range(k)) for g in range(k)] for i in range(p)]
    grad = [[0.0] * k for _ in range(p)]
    for i in range(p):
        for j in range(k):
            if free_mask[i][j] and not marker_mask[i][j]:
                grad[i][j] = -2.0 * RLP[i][j]
    return grad


def _grad_psi(R: list[list[float]]) -> list[float]:
    """∂F/∂Ψ_ii = −R_ii。"""
    return [-R[i][i] for i in range(len(R))]


def _grad_phi_offdiag(
    R: list[list[float]],
    lam: list[list[float]],
    k: int,
) -> list[list[float]]:
    """∂F/∂Φ_ab（off-diagonal）= −(ΛᵀRΛ)_ab。"""
    p = len(lam)
    LtRL = [
        [sum(lam[q][a] * R[q][r] * lam[r][b] for q in range(p) for r in range(p))
         for b in range(k)]
        for a in range(k)
    ]
    grad = [[0.0] * k for _ in range(k)]
    for a in range(k):
        for b in range(a + 1, k):
            g = -LtRL[a][b]
            grad[a][b] = g
            grad[b][a] = g
    return grad


def compute_cfa(
    data_cols: dict[str, list[float]],
    model_spec: str | dict[str, list[str]],
    *,
    oblique: bool = False,
    max_iter: int = 4000,
    lr: float = 0.008,
    tol: float = 1e-11,
) -> dict[str, Any]:
    """CFA 主入口：ULS 估计 + Adam 优化器。

    Args:
        data_cols:   {列名: [数值列表]}，长度必须相同
        model_spec:  "F1:x1,x2,x3;F2:x4,x5" 或 dict
        oblique:     是否允许因子间相关（斜交，默认正交）
        max_iter:    最大迭代次数（默认 4000）
        lr:          Adam 学习率（默认 0.008）
        tol:         收敛容忍度 |ΔF| < tol（默认 1e-11）

    Returns:
        结果字典（因子载荷、拟合指数、残差、诊断信息等）
    """
    col_names = list(data_cols.keys())
    factors, item_order, free_mask, marker_mask = _parse_model(model_spec, col_names)

    p = len(item_order)
    k = len(factors)

    # 按 item_order 排列的数据列
    cols_ordered = [data_cols[it] for it in item_order]
    S, N = _corr_matrix(cols_ordered)

    # ── 初始化参数 ─────────────────────────────────────────────────────────────
    # Λ: 标记载荷=1.0，其余自由=0.6，非指定=0.0
    lam = [[0.0] * k for _ in range(p)]
    for i in range(p):
        for j in range(k):
            if marker_mask[i][j]:
                lam[i][j] = 1.0
            elif free_mask[i][j]:
                lam[i][j] = 0.6

    # Φ: 初始单位阵（正交）
    phi = [[1.0 if a == b else 0.0 for b in range(k)] for a in range(k)]

    # Ψ: 初始独特方差 0.5
    psi = [0.5] * p

    # ── 参数索引 ───────────────────────────────────────────────────────────────
    lam_free_idx = [
        (i, j) for i in range(p) for j in range(k)
        if free_mask[i][j] and not marker_mask[i][j]
    ]
    phi_idx = [(a, b) for a in range(k) for b in range(a + 1, k)] if oblique else []
    n_lam = len(lam_free_idx)
    n_phi = len(phi_idx)
    n_params = n_lam + p + n_phi  # 自由载荷 + 独特方差 + 因子相关（若斜交）

    # Adam 状态
    m_adam = [0.0] * n_params
    v_adam = [0.0] * n_params
    beta1, beta2, eps_a = 0.9, 0.999, 1e-8

    def pack() -> list[float]:
        ps = [lam[i][j] for i, j in lam_free_idx]
        ps += list(psi)
        ps += [phi[a][b] for a, b in phi_idx]
        return ps

    def unpack(ps: list[float]) -> None:
        nonlocal lam, psi, phi
        idx = 0
        for i, j in lam_free_idx:
            lam[i][j] = ps[idx]; idx += 1
        for i in range(p):
            psi[i] = max(1e-6, ps[idx]); idx += 1
        for a, b in phi_idx:
            v = max(-0.95, min(0.95, ps[idx])); idx += 1
            phi[a][b] = phi[b][a] = v

    # ── 优化循环 ───────────────────────────────────────────────────────────────
    f_prev = float("inf")
    n_iter = 0
    warnings: list[str] = []

    for t in range(1, max_iter + 1):
        n_iter = t
        Sig = _sigma(lam, phi, psi)
        R = _residual(S, Sig)
        f = _f_uls(S, Sig)

        if abs(f_prev - f) < tol and t > 50:
            break
        f_prev = f

        # 梯度
        g_lam = _grad_lam(R, lam, phi, free_mask, marker_mask)
        g_psi = _grad_psi(R)
        grads = [g_lam[i][j] for i, j in lam_free_idx] + g_psi
        if oblique:
            g_phi = _grad_phi_offdiag(R, lam, k)
            grads += [g_phi[a][b] for a, b in phi_idx]

        # Adam 更新
        ps = pack()
        for idx in range(n_params):
            m_adam[idx] = beta1 * m_adam[idx] + (1 - beta1) * grads[idx]
            v_adam[idx] = beta2 * v_adam[idx] + (1 - beta2) * grads[idx] ** 2
            m_hat = m_adam[idx] / (1 - beta1 ** t)
            v_hat = v_adam[idx] / (1 - beta2 ** t)
            ps[idx] -= lr * m_hat / (math.sqrt(v_hat) + eps_a)
        unpack(ps)

    converged = n_iter < max_iter
    if not converged:
        warnings.append(f"ULS 在 {max_iter} 次迭代后未完全收敛，结果可能不稳定")

    # ── 最终计算 ───────────────────────────────────────────────────────────────
    Sig = _sigma(lam, phi, psi)
    R_fin = _residual(S, Sig)
    f_fin = _f_uls(S, Sig)

    # 共同度 h²
    communalities: list[float] = []
    for i in range(p):
        h2 = sum(
            lam[i][a] * phi[a][b] * lam[i][b]
            for a in range(k) for b in range(k)
        )
        communalities.append(max(0.0, min(1.0, h2)))

    # ── 拟合指数 ───────────────────────────────────────────────────────────────
    # 自由度：df = 已知协方差数 − 自由参数数
    n_free_params = n_lam + p + n_phi
    n_known = p * (p + 1) // 2  # 独立相关/方差数（下三角含对角）
    df = max(0, n_known - n_free_params)

    # 零模型（独立模型）：Σ_null = I（所有相关=0）
    I_mat = [[1.0 if i == j else 0.0 for j in range(p)] for i in range(p)]
    f_null = _f_uls(S, I_mat)
    df_null = p * (p - 1) // 2

    # SRMR
    n_off = p * (p - 1) // 2
    srmr = math.sqrt(
        sum(R_fin[i][j] ** 2 for i in range(p) for j in range(i + 1, p)) / max(1, n_off)
    )

    # 近似 χ²（ULS 标度）
    T_target = (N - 1) * f_fin
    T_null = (N - 1) * f_null

    # CFI = 1 − max(T−df, 0) / max(T_null−df_null, 0)
    den_cfi = max(T_null - df_null, 0.0)
    cfi = 1.0 - max(T_target - df, 0.0) / den_cfi if den_cfi > 0 else 1.0
    cfi = max(0.0, min(1.0, cfi))

    # TLI (Tucker-Lewis Index)
    if df > 0 and df_null > 0 and T_null > 0:
        tli_num = T_null / df_null - T_target / df
        tli_den = T_null / df_null - 1.0
        tli = tli_num / tli_den if abs(tli_den) > 1e-15 else 1.0
        tli = max(0.0, min(1.1, tli))
    else:
        tli = 1.0

    # RMSEA（Browne & Cudeck, 1993）
    if df > 0:
        rmsea = math.sqrt(max(0.0, (T_target - df) / (df * (N - 1))))
        if rmsea > 0:
            se_rmsea = math.sqrt(rmsea ** 2 / max(1, 2 * df * (N - 1)))
            rmsea_lo = max(0.0, rmsea - 1.645 * se_rmsea)
            rmsea_hi = rmsea + 1.645 * se_rmsea
        else:
            rmsea_lo = rmsea_hi = 0.0
    else:
        rmsea = rmsea_lo = rmsea_hi = 0.0

    # 拟合诊断告警
    fit_warns: list[str] = []
    if cfi < 0.90:
        fit_warns.append(
            f"CFI = {cfi:.3f} < .90，拟合较差（Hu & Bentler, 1999 建议 CFI ≥ .95）"
        )
    elif cfi < 0.95:
        fit_warns.append(f"CFI = {cfi:.3f} 处于临界（建议 ≥ .95）")
    if rmsea > 0.10:
        fit_warns.append(
            f"RMSEA = {rmsea:.3f} > .10，拟合不佳（建议 ≤ .08，理想 ≤ .06）"
        )
    elif rmsea > 0.08:
        fit_warns.append(f"RMSEA = {rmsea:.3f} 处于临界（建议 ≤ .08）")
    if srmr > 0.10:
        fit_warns.append(f"SRMR = {srmr:.3f} > .10，标准化残差偏大（建议 ≤ .08）")
    if df == 0:
        fit_warns.append(
            "模型恰好识别（df = 0），拟合指数不可解读；建议增加过度识别约束"
        )

    # Heywood case 检测（共同度 ≥ 1）
    heywood = [item_order[i] for i, h in enumerate(communalities) if h >= 0.99]
    if heywood:
        fit_warns.append(
            f"检测到 Heywood 案例（共同度 ≥ .99）：{', '.join(heywood)}；"
            "模型可能过度参数化或数据不足"
        )
    warnings.extend(fit_warns)

    return {
        "n": N,
        "p": p,
        "k": k,
        "factors": factors,
        "items": item_order,
        "loadings": [[lam[i][j] for j in range(k)] for i in range(p)],
        "communalities": communalities,
        "unique_variances": list(psi),
        "factor_correlations": [[phi[a][b] for b in range(k)] for a in range(k)],
        "oblique": oblique,
        "S": S,
        "Sigma": Sig,
        "residuals": R_fin,
        "fit": {
            "srmr": srmr,
            "cfi": cfi,
            "tli": tli,
            "rmsea": rmsea,
            "rmsea_ci_lower": rmsea_lo,
            "rmsea_ci_upper": rmsea_hi,
            "chi2_approx": T_target,
            "df": df,
            "n_free_params": n_free_params,
            "f_uls_min": f_fin,
        },
        "convergence": converged,
        "n_iter": n_iter,
        "warnings": warnings,
    }


# ─── APA-7 格式化 ────────────────────────────────────────────────────────────

def format_apa_cfa(result: dict[str, Any]) -> str:
    """生成 APA-7 Markdown CFA 报告。"""
    factors = result["factors"]
    items = result["items"]
    loadings = result["loadings"]
    communalities = result["communalities"]
    phi = result["factor_correlations"]
    fit = result["fit"]
    oblique = result["oblique"]
    N = result["n"]
    p = result["p"]
    k = result["k"]

    cfi = fit["cfi"]
    tli = fit["tli"]
    rmsea = fit["rmsea"]
    srmr = fit["srmr"]
    df = fit["df"]
    chi2 = fit["chi2_approx"]

    def chk(val: float, good: float, ok: float, higher_is_better: bool = True) -> str:
        if higher_is_better:
            return "✓" if val >= good else ("△" if val >= ok else "✗")
        else:
            return "✓" if val <= good else ("△" if val <= ok else "✗")

    lines: list[str] = []
    lines.append("## 验证性因子分析（CFA，ULS 估计）结果\n")

    # 拟合指数表
    lines.append("### 模型拟合指数\n")
    lines.append("| 指数 | 值 | 参考阈值 | 判断 |")
    lines.append("|------|----|----------|------|")
    lines.append(f"| χ²(df = {df}) | {chi2:.3f} | — | — |")
    lines.append(
        f"| CFI | {cfi:.3f} | ≥ .950 | {chk(cfi, 0.95, 0.90)} |"
    )
    lines.append(
        f"| TLI | {tli:.3f} | ≥ .950 | {chk(tli, 0.95, 0.90)} |"
    )
    lines.append(
        f"| RMSEA | {rmsea:.3f} "
        f"[{fit['rmsea_ci_lower']:.3f}, {fit['rmsea_ci_upper']:.3f}] "
        f"| ≤ .060 | {chk(rmsea, 0.06, 0.08, higher_is_better=False)} |"
    )
    lines.append(
        f"| SRMR | {srmr:.3f} | ≤ .080 | {chk(srmr, 0.08, 0.10, higher_is_better=False)} |"
    )
    lines.append(f"\n> *N* = {N}，自由参数数 = {fit['n_free_params']}，ULS 拟合函数值 = {fit['f_uls_min']:.6f}\n")

    # 因子载荷矩阵
    lines.append("### 因子载荷矩阵\n")
    header = "| 条目 | " + " | ".join(factors) + " | 共同度 *h*² |"
    sep = "|------|" + "------|" * k + "------------|"
    lines.append(header)
    lines.append(sep)
    for pi in range(p):
        row = f"| {items[pi]} |"
        for fi in range(k):
            v = loadings[pi][fi]
            if abs(v) < 0.001:
                row += " — |"
            elif abs(v) >= 0.50:
                row += f" **{v:.3f}** |"
            else:
                row += f" {v:.3f} |"
        row += f" {communalities[pi]:.3f} |"
        lines.append(row)
    lines.append("")
    lines.append("> 注：**粗体** = |λ| ≥ .50；— = 未指定载荷（固定为 0）\n")

    # 因子相关矩阵（斜交）
    if oblique and k > 1:
        lines.append("### 因子间相关矩阵（斜交）\n")
        h2 = "| 因子 | " + " | ".join(factors) + " |"
        sep2 = "|------|" + "------|" * k
        lines.append(h2)
        lines.append(sep2)
        for a in range(k):
            row = f"| {factors[a]} |"
            for b in range(k):
                if a == b:
                    row += " 1.000 |"
                else:
                    row += f" {phi[a][b]:.3f} |"
            lines.append(row)
        lines.append("")

    # APA 结果段落
    lines.append("### 结果摘要（APA-7 格式）\n")
    good = cfi >= 0.95 and rmsea <= 0.08 and srmr <= 0.08
    marginal = cfi >= 0.90 and rmsea <= 0.10
    fit_label = "良好" if good else ("尚可" if marginal else "较差")
    oblique_note = "，因子间采用斜交旋转" if oblique else ""

    para = (
        f"对 {k} 因子结构进行验证性因子分析（CFA，ULS 估计{oblique_note}），"
        f"共纳入 *N* = {N} 例完整案例、{p} 个测量条目。"
        f"模型拟合{fit_label}：CFI = {cfi:.3f}，TLI = {tli:.3f}，"
        f"RMSEA = {rmsea:.3f} [90% CI: {fit['rmsea_ci_lower']:.3f}, "
        f"{fit['rmsea_ci_upper']:.3f}]，SRMR = {srmr:.3f}"
        f"（参考阈值：CFI/TLI ≥ .95，RMSEA ≤ .06，SRMR ≤ .08；"
        f"Hu & Bentler, 1999）。"
    )
    lines.append(para)
    lines.append("")

    # 各因子描述
    for fi, fname in enumerate(factors):
        hi_items = [items[pi] for pi in range(p) if abs(loadings[pi][fi]) >= 0.50]
        if hi_items:
            lines.append(
                f"因子 {fname} 在以下条目上呈现较高负荷（λ ≥ .50）："
                + "、".join(hi_items) + "。"
            )
    lines.append("")

    if oblique and k > 1:
        phi_vals = [phi[a][b] for a in range(k) for b in range(a + 1, k)]
        max_phi = max(abs(v) for v in phi_vals) if phi_vals else 0.0
        direction = "较强" if max_phi > 0.30 else "较弱"
        lines.append(
            f"因子间相关范围为 {min(phi_vals):.3f} 至 {max(phi_vals):.3f}，"
            f"最大相关 |r| = {max_phi:.3f}（{direction}），"
            f"{'建议报告因子间相关矩阵。' if max_phi > 0.30 else '正交结构亦可接受。'}"
        )
        lines.append("")

    # 注意事项
    if result["warnings"]:
        lines.append("### ⚠ 注意事项\n")
        for w in result["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    lines.append(
        "**参考文献**：Hu, L., & Bentler, P. M. (1999). Cutoff criteria for fit indexes "
        "in covariance structure analysis. *Structural Equation Modeling*, *6*(1), 1–55. "
        "Browne, M. W., & Cudeck, R. (1993). Alternative ways of assessing model fit. "
        "*Sociological Methods & Research*, *21*(2), 230–258. "
        "Kline, R. B. (2015). *Principles and practice of structural equation modeling* "
        "(4th ed.). Guilford Press."
    )

    return "\n".join(lines)


# ─── sidecar 输出 ─────────────────────────────────────────────────────────────

def write_cfa_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 MD + JSON sidecar，返回 (md_path, json_path)。"""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "cfa_report.md"
    json_path = out_dir / "cfa_report.json"

    md_path.write_text(format_apa_cfa(result), encoding="utf-8")

    def _safe(v: Any) -> Any:
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return v

    def _deep_safe(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _deep_safe(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_deep_safe(x) for x in obj]
        return _safe(obj)

    json_path.write_text(
        json.dumps(_deep_safe(result), ensure_ascii=False, indent=2, default=float),
        encoding="utf-8",
    )
    return md_path, json_path


# ─── CSV 主入口 ───────────────────────────────────────────────────────────────

def analyze_cfa(
    csv_path: str | pathlib.Path,
    model_spec: str | dict[str, list[str]],
    *,
    oblique: bool = False,
    max_iter: int = 4000,
    out_dir: str | pathlib.Path | None = None,
    return_json: bool = False,
) -> dict[str, Any]:
    """从 CSV 文件运行 CFA。

    Args:
        csv_path:   CSV 数据路径
        model_spec: 模型规格（字符串或 dict）
        oblique:    是否斜交
        max_iter:   最大迭代次数
        out_dir:    sidecar 输出目录（None 则不写文件）
        return_json:是否在返回值里附上格式化字符串

    Returns:
        结果字典
    """
    csv_path = pathlib.Path(csv_path)
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError(f"CSV 文件为空：{csv_path}")

    headers = list(rows[0].keys())

    def _float(v: str) -> float:
        try:
            return float(v)
        except (ValueError, TypeError):
            return float("nan")

    data_cols: dict[str, list[float]] = {
        h: [_float(r[h]) for r in rows] for h in headers
    }

    result = compute_cfa(
        data_cols, model_spec, oblique=oblique, max_iter=max_iter
    )

    if out_dir is not None:
        write_cfa_report(result, out_dir)

    if return_json:
        result["_formatted"] = format_apa_cfa(result)

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

def cfa_cli(argv: list[str] | None = None) -> int:
    """CLI 入口：psyclaw cfa <data.csv> --model "F1:x1,x2;F2:x3,x4" ..."""
    ap = argparse.ArgumentParser(
        prog="psyclaw cfa",
        description="验证性因子分析（CFA，ULS 估计，stdlib only）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument(
        "--model", "-m", required=True,
        help='模型规格："F1:x1,x2,x3;F2:x4,x5,x6"'
    )
    ap.add_argument("--oblique", action="store_true",
                    help="允许因子间相关（斜交旋转，默认正交）")
    ap.add_argument("--max-iter", type=int, default=4000, dest="max_iter",
                    help="最大迭代次数（默认 4000）")
    ap.add_argument("--out", default="notes",
                    help="sidecar 输出目录（默认 notes/）")
    ap.add_argument("--json", action="store_true",
                    help="输出机器可读 JSON")

    args = ap.parse_args(argv)

    result = analyze_cfa(
        args.csv,
        args.model,
        oblique=args.oblique,
        max_iter=args.max_iter,
        out_dir=args.out,
        return_json=args.json,
    )

    if args.json:
        def _safe(v: Any) -> Any:
            if isinstance(v, float) and not math.isfinite(v):
                return None
            return v

        def _deep_safe(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _deep_safe(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_deep_safe(x) for x in obj]
            return _safe(obj)

        print(json.dumps(_deep_safe(result), ensure_ascii=False, indent=2, default=float))
    else:
        print(format_apa_cfa(result))
        md, js = pathlib.Path(args.out) / "cfa_report.md", pathlib.Path(args.out) / "cfa_report.json"
        print(f"\n报告已写入：{md}，{js}")

    return 0
