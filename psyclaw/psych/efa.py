"""探索性因子分析 (EFA) — 主轴因子法 (PAF) + Varimax 旋转，stdlib only。

提供：
  - compute_efa(data, n_factors, ...)     → 因子载荷/共同度/特征值/解释方差
  - format_apa_efa(result)                → APA-7 Markdown 因子载荷表 + 段落
  - write_efa_report(result, out_dir)     → MD + JSON sidecar
  - analyze_efa(csv_path, cols, ...)      → CSV 主入口
  - efa_cli(argv)                         → CLI 处理器

CLI:
  psyclaw efa <data.csv> --cols c1,c2,...  [--n-factors N]
              [--rotation varimax|none] [--method paf|pca]
              [--min-loading 0.3] [--json] [--out dir]

理论依据：
  Harman, H. H. (1976). Modern Factor Analysis (3rd ed.). University of Chicago Press.
  Kaiser, H. F. (1958). The varimax criterion for analytic rotation in factor analysis.
    Psychometrika, 23(3), 187–200.
  Cattell, R. B. (1966). The scree test for the number of factors.
    Multivariate Behavioral Research, 1(2), 245–276.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Any

import numpy as np


# ─── 矩阵工具（Gauss-Jordan 求逆，stdlib only）────────────────────────────────

def _mat_invert(M: list[list[float]]) -> list[list[float]] | None:
    """矩阵逆（numpy）；奇异返回 None。"""
    try:
        return np.linalg.inv(np.asarray(M, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        return None


# ─── 对称矩阵特征值分解（numpy）──────────────────────────────────────────────

def _jacobi_eig(
    A: list[list[float]], max_sweeps: int = 60
) -> tuple[list[float], list[list[float]]]:
    """对称矩阵特征值/特征向量 —— numpy.linalg.eigh，按特征值降序返回。

    返回 (eigenvalues 降序, eigenvectors[row][col])。
    符号约定：每个特征向量绝对值最大的分量取正，保证可复现。
    """
    vals, vecs = np.linalg.eigh(np.asarray(A, dtype=float))
    order = np.argsort(vals)[::-1]
    vals = vals[order]
    vecs = vecs[:, order]
    for col in range(vecs.shape[1]):
        v = vecs[:, col]
        k = int(np.argmax(np.abs(v)))
        if v[k] < 0:
            vecs[:, col] = -v
    return (
        [float(x) for x in vals],
        [[float(vecs[r][c]) for c in range(vecs.shape[1])] for r in range(vecs.shape[0])],
    )


# ─── Pearson 相关矩阵 ─────────────────────────────────────────────────────────

def _corr_matrix(data: list[list[float]]) -> list[list[float]]:
    """由变量列表计算 Pearson 相关矩阵。data[i] = 第 i 个变量的所有观测值列表。"""
    p = len(data)
    n = len(data[0])
    means = [sum(col) / n for col in data]
    stds = []
    for col, m in zip(data, means):
        var = sum((v - m) ** 2 for v in col) / (n - 1)
        stds.append(math.sqrt(var) if var > 1e-15 else 0.0)

    R = [[1.0 if i == j else 0.0 for j in range(p)] for i in range(p)]
    for i in range(p):
        for j in range(i + 1, p):
            if stds[i] < 1e-15 or stds[j] < 1e-15:
                r = 0.0
            else:
                cov = sum(
                    (data[i][k] - means[i]) * (data[j][k] - means[j])
                    for k in range(n)
                ) / (n - 1)
                r = max(-1.0, min(1.0, cov / (stds[i] * stds[j])))
            R[i][j] = R[j][i] = r
    return R


# ─── 平方多重相关（SMC）作为 PAF 初始公因子方差 ────────────────────────────────

def _smc(R: list[list[float]]) -> list[float]:
    """SMC_i = 1 − 1/R⁻¹_{ii}（从相关矩阵逆对角线导出）。

    若 R 奇异，则降级为各变量与其他变量的最大绝对相关平方。
    """
    p = len(R)
    R_inv = _mat_invert(R)
    if R_inv is not None:
        return [
            max(0.0, min(1.0 - 1.0 / R_inv[i][i], 0.999)) if R_inv[i][i] > 1e-10 else 0.0
            for i in range(p)
        ]
    return [max(R[i][j] ** 2 for j in range(p) if j != i) for i in range(p)]


# ─── 因子提取：主轴因子法（PAF）──────────────────────────────────────────────

def _extract_paf(
    R: list[list[float]],
    n_factors: int,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> tuple[list[list[float]], list[float], list[float]]:
    """主轴因子法（PAF）：迭代更新公因子方差，提取 n_factors 个因子。

    返回 (L, h2, evals_extracted)：
      L     — p×k 未旋转载荷矩阵
      h2    — 最终公因子方差（每变量）
      evals — 提取因子对应特征值
    """
    p = len(R)
    h2 = _smc(R)
    L: list[list[float]] = []
    evals: list[float] = []

    for _iteration in range(max_iter):
        # 以估计共同度替换对角线
        R_mod = [row[:] for row in R]
        for i in range(p):
            R_mod[i][i] = h2[i]

        eigvals, eigvecs = _jacobi_eig(R_mod)

        # 取正特征值中最多 n_factors 个
        k = min(n_factors, sum(1 for v in eigvals if v > 1e-10))
        k = max(k, 1)

        L_new = [
            [eigvecs[i][f] * math.sqrt(max(eigvals[f], 0.0)) for f in range(k)]
            for i in range(p)
        ]
        h2_new = [
            max(0.0, min(sum(L_new[i][f] ** 2 for f in range(k)), 0.999))
            for i in range(p)
        ]

        delta = max(abs(h2_new[i] - h2[i]) for i in range(p))
        h2 = h2_new
        L = L_new
        evals = eigvals[:k]
        if delta < tol:
            break

    return L, h2, evals


def _extract_pca(
    R: list[list[float]],
    n_factors: int,
) -> tuple[list[list[float]], list[float], list[float]]:
    """PCA 因子提取（对完整相关矩阵特征分解；无公因子方差迭代）。"""
    p = len(R)
    eigvals, eigvecs = _jacobi_eig(R)
    k = min(n_factors, p)
    L = [
        [eigvecs[i][f] * math.sqrt(max(eigvals[f], 0.0)) for f in range(k)]
        for i in range(p)
    ]
    h2 = [sum(L[i][f] ** 2 for f in range(k)) for i in range(p)]
    return L, h2, eigvals[:k]


# ─── Varimax 正交旋转（Kaiser 1958，非规范化）────────────────────────────────

def _varimax(
    L: list[list[float]],
    max_iter: int = 1000,
    tol: float = 1e-10,
) -> tuple[list[list[float]], list[list[float]]]:
    """Kaiser (1958) Varimax 正交旋转。

    准则：最大化各因子内载荷平方的方差，使载荷结构简洁。
    返回 (L_rot, T)，其中 L_rot ≈ L @ T（旋转矩阵 T 为正交矩阵）。
    """
    p = len(L)
    k = len(L[0]) if L else 0
    if k <= 1:
        T = [[1.0]] if k == 1 else []
        return [row[:] for row in L], T

    Lw = [row[:] for row in L]
    # 旋转矩阵（累积每次对旋转）
    T = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]

    old_crit = -math.inf
    for _outer in range(max_iter):
        for f1 in range(k - 1):
            for f2 in range(f1 + 1, k):
                x = [Lw[i][f1] for i in range(p)]
                y = [Lw[i][f2] for i in range(p)]

                u = [xi * xi - yi * yi for xi, yi in zip(x, y)]
                v = [2.0 * xi * yi for xi, yi in zip(x, y)]

                A = sum(u)
                B = sum(v)
                C = sum(ui * ui - vi * vi for ui, vi in zip(u, v))
                D = sum(2.0 * ui * vi for ui, vi in zip(u, v))

                num = D - 2.0 * A * B / p
                denom = C - (A * A - B * B) / p
                theta = 0.25 * math.atan2(num, denom)
                c = math.cos(theta)
                s = math.sin(theta)

                for i in range(p):
                    nf1 = c * Lw[i][f1] + s * Lw[i][f2]
                    nf2 = -s * Lw[i][f1] + c * Lw[i][f2]
                    Lw[i][f1] = nf1
                    Lw[i][f2] = nf2

                for i in range(k):
                    nf1 = c * T[i][f1] + s * T[i][f2]
                    nf2 = -s * T[i][f1] + c * T[i][f2]
                    T[i][f1] = nf1
                    T[i][f2] = nf2

        # Varimax 准则（非规范化）：最大化各因子内载荷⁴均值与载荷²均值之差
        crit = sum(
            p * sum(Lw[i][f] ** 4 for i in range(p))
            - sum(Lw[i][f] ** 2 for i in range(p)) ** 2
            for f in range(k)
        )
        if abs(crit - old_crit) < tol:
            break
        old_crit = crit

    return Lw, T


# ─── ASCII 碎石图 ─────────────────────────────────────────────────────────────

def _ascii_scree(eigenvalues: list[float], n_extract: int, max_show: int = 12) -> str:
    """生成 ASCII 碎石图（最多显示 max_show 个特征值）。"""
    ev = eigenvalues[:max_show]
    if not ev:
        return ""
    max_ev = max(max(ev), 1.0)
    height = 7

    lines = ["碎石图（特征值）"]
    for row in range(height, 0, -1):
        thresh = max_ev * row / height
        line = f"{thresh:5.2f} │"
        for f_idx, val in enumerate(ev):
            sep = "│" if f_idx == n_extract else " "
            sym = "■" if val >= thresh else " "
            line += f" {sym}  {sep}"
        lines.append(line)
    lines.append("      └" + "─────" * len(ev))
    axis = "       "
    for f_idx in range(len(ev)):
        axis += f"{f_idx + 1:<5}"
    lines.append(axis)
    lines.append(f"       （竖线 = 提取截止；共提取 {n_extract} 个因子）")
    return "\n".join(lines)


# ─── 主计算入口 ───────────────────────────────────────────────────────────────

def compute_efa(
    data: list[list[float]],
    n_factors: int = 0,
    rotation: str = "varimax",
    method: str = "paf",
    cols: list[str] | None = None,
    max_iter: int = 1000,
    tol: float = 1e-6,
) -> dict[str, Any]:
    """全流程 EFA（探索性因子分析）。

    Args:
        data      : data[i] = 第 i 个变量的 n 个观测值列表（变量优先）
        n_factors : 提取因子数（0 = Kaiser 准则自动确定，特征值 ≥ 1.0）
        rotation  : 'varimax'（默认）| 'none'
        method    : 'paf'（主轴因子法，默认）| 'pca'
        cols      : 变量名列表（长度须等于 len(data)）
        max_iter  : PAF/Varimax 最大迭代次数
        tol       : 收敛容忍度

    Returns:
        包含 loadings、communalities、eigenvalues、pct_var 等的字典。
    """
    p = len(data)
    n = len(data[0]) if data else 0
    if cols is None:
        cols = [f"V{i + 1}" for i in range(p)]

    if p < 2:
        raise ValueError("EFA 要求至少 2 个变量")
    if n < 2:
        raise ValueError("EFA 要求至少 2 个有效观测值")

    warnings: list[str] = []
    if n < p + 1:
        warnings.append(f"样本量 ({n}) 偏小（建议 ≥ {p + 1}）；结果可能不稳定")

    # 1. 相关矩阵
    R = _corr_matrix(data)

    # 2. 完整特征值（碎石图 + Kaiser 准则）
    evals_full, _ = _jacobi_eig(R)

    # 3. 确定提取因子数
    if n_factors <= 0:
        n_factors = max(1, sum(1 for v in evals_full if v >= 1.0))
        warnings.append(
            f"Kaiser 准则自动确定提取 {n_factors} 个因子（特征值 ≥ 1.0）"
        )
    n_factors = max(1, min(n_factors, p - 1))

    # 4. 因子提取
    if method == "pca":
        L_unrot, h2_init, evals_extracted = _extract_pca(R, n_factors)
    else:
        L_unrot, h2_init, evals_extracted = _extract_paf(
            R, n_factors, max_iter=max_iter, tol=tol
        )

    k = len(L_unrot[0]) if L_unrot else 0

    # 5. 旋转
    T_rot: list[list[float]] | None = None
    if rotation == "varimax" and k > 1:
        L_rot, T_rot = _varimax(L_unrot, max_iter=max_iter, tol=1e-10)
        rot_label = "varimax"
    else:
        L_rot = [row[:] for row in L_unrot]
        rot_label = "none"

    # 6. 旋转后公因子方差
    h2_final = [sum(L_rot[i][f] ** 2 for f in range(k)) for i in range(p)]

    # 7. 各因子载荷平方和（SSL）与方差解释
    ssl = [sum(L_rot[i][f] ** 2 for i in range(p)) for f in range(k)]
    pct_var = [v / p * 100.0 for v in ssl]
    cum_pct: list[float] = []
    running = 0.0
    for v in pct_var:
        running += v
        cum_pct.append(running)

    # 8. 碎石图
    scree = _ascii_scree(evals_full, n_factors)

    return {
        "n_vars": p,
        "n_obs": n,
        "n_factors": k,
        "method": method,
        "rotation": rot_label,
        "cols": list(cols),
        "eigenvalues": evals_full,
        "eigenvalues_extracted": evals_extracted[:k],
        "ssl": ssl,
        "pct_var": pct_var,
        "cum_pct_var": cum_pct,
        "loadings": L_rot,
        "loadings_unrotated": L_unrot,
        "communalities": h2_final,
        "uniqueness": [max(0.0, 1.0 - h) for h in h2_final],
        "rotation_matrix": T_rot,
        "corr_matrix": R,
        "scree_ascii": scree,
        "warnings": warnings,
    }


# ─── APA-7 输出 ───────────────────────────────────────────────────────────────

def _fmt2(v: float) -> str:
    """两位小数，去前导零（APA-7 惯例）。"""
    if not math.isfinite(v):
        return "—"
    s = f"{v:.2f}"
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


def format_apa_efa(
    result: dict[str, Any],
    min_loading: float = 0.30,
) -> str:
    """APA-7 Markdown 因子载荷三线表 + 结果段落。

    Args:
        result      : compute_efa 返回值
        min_loading : 绝对值低于此阈值的载荷以空格代替（默认 .30）
    """
    k = result["n_factors"]
    cols = result["cols"]
    L = result["loadings"]
    h2 = result["communalities"]
    ssl = result["ssl"]
    pct = result["pct_var"]
    cum = result["cum_pct_var"]

    method_cn = {"paf": "主轴因子法", "pca": "主成分法"}.get(result["method"], result["method"])
    rot_cn = {
        "varimax": "正交 Varimax 旋转",
        "none": "未旋转",
    }.get(result["rotation"], result["rotation"])

    # 三线表
    factor_hdrs = " | ".join(f"*F{f + 1}*" for f in range(k))
    header = f"| 变量 | {factor_hdrs} | *h*² |"
    sep = "|------|" + "------|" * k + "------|"

    rows = [
        f"*因子载荷矩阵（{method_cn}，{rot_cn}，N = {result['n_obs']}）*",
        "",
        header,
        sep,
    ]

    for i, col in enumerate(cols):
        load_strs = []
        for f in range(k):
            v = L[i][f]
            if abs(v) >= min_loading:
                s = f"**{_fmt2(v)}**" if abs(v) >= 0.50 else _fmt2(v)
            else:
                s = "    "
            load_strs.append(s)
        rows.append(f"| {col} | {' | '.join(load_strs)} | {h2[i]:.2f} |")

    ssl_strs = [f"{v:.2f}" for v in ssl]
    pct_strs = [f"{v:.1f}%" for v in pct]
    cum_strs = [f"{v:.1f}%" for v in cum]
    rows += [
        f"| *SSL* | {' | '.join(ssl_strs)} | |",
        f"| *方差解释* | {' | '.join(pct_strs)} | |",
        f"| *累积方差* | {' | '.join(cum_strs)} | |",
        "",
        f"*注：|载荷| ≥ {min_loading:.2f} 显示数值，≥ .50 加粗；"
        "h² = 公因子方差；SSL = 载荷平方和。*",
        "",
    ]

    # 结果段落
    total_pct = cum[-1] if cum else 0.0
    para = (
        f"以{method_cn}（{rot_cn}）对 {len(cols)} 个变量进行探索性因子分析（N = {result['n_obs']}）。"
        f"依据 Kaiser 准则（特征值 ≥ 1.0），提取 {k} 个因子，"
        f"累积解释方差 {total_pct:.1f}%。"
    )
    for f in range(k):
        top_idx = sorted(range(len(cols)), key=lambda i: -abs(L[i][f]))
        top_vars = [cols[i] for i in top_idx if abs(L[i][f]) >= min_loading][:3]
        if top_vars:
            para += (
                f"因子 {f + 1} 解释方差 {pct[f]:.1f}%，"
                f"主载荷变量：{'/'.join(top_vars)}。"
            )

    rows.append(para)
    return "\n".join(rows)


# ─── MD + JSON sidecar ───────────────────────────────────────────────────────

def write_efa_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    min_loading: float = 0.30,
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 efa_report.md + efa_report.json 到 out_dir。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    md_path = out / "efa_report.md"
    json_path = out / "efa_report.json"

    apa_text = format_apa_efa(result, min_loading=min_loading)
    md_lines = [
        "# EFA 报告\n",
        apa_text,
        "\n## 碎石图\n",
        f"```\n{result['scree_ascii']}\n```\n",
    ]
    if result.get("warnings"):
        md_lines.append("\n## 警告\n")
        md_lines.extend(f"- {w}\n" for w in result["warnings"])

    md_path.write_text("".join(md_lines), encoding="utf-8")

    # JSON：保留所有数值型字段（omit 大矩阵以外的均保留）
    safe: dict[str, Any] = {}
    for key, val in result.items():
        if key == "scree_ascii":
            continue
        safe[key] = val
    json_path.write_text(
        json.dumps(safe, ensure_ascii=False, indent=2, default=float),
        encoding="utf-8",
    )

    return md_path, json_path


# ─── CSV 主入口 ───────────────────────────────────────────────────────────────

def analyze_efa(
    csv_path: str,
    cols: list[str],
    n_factors: int = 0,
    rotation: str = "varimax",
    method: str = "paf",
    out_dir: str | None = None,
    as_json: bool = False,
    min_loading: float = 0.30,
) -> dict[str, Any]:
    """从 CSV 读取数据并执行 EFA。

    缺失值（空格或非数值）的行会被逐行排除，并计入 n_excluded。
    """
    path = pathlib.Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到 CSV 文件：{csv_path}")

    with open(path, encoding="utf-8-sig", newline="") as fh:
        all_rows = list(csv.DictReader(fh))

    if not all_rows:
        raise ValueError("CSV 文件无数据行")

    # 若未指定列，自动选数值列
    if not cols:
        first = all_rows[0]
        cols = [c for c in first if _is_numeric(first[c])]
        if not cols:
            raise ValueError("CSV 中找不到数值列；请用 --cols 指定")

    raw: list[list[float]] = [[] for _ in cols]
    n_excluded = 0
    for row in all_rows:
        try:
            vals = [float(row[c]) for c in cols]
        except (ValueError, KeyError):
            n_excluded += 1
            continue
        for i, v in enumerate(vals):
            raw[i].append(v)

    if not raw[0]:
        raise ValueError("过滤缺失值后无有效数据行")

    result = compute_efa(
        raw, n_factors=n_factors, rotation=rotation,
        method=method, cols=cols,
    )
    result["n_excluded"] = n_excluded

    if out_dir:
        write_efa_report(result, out_dir=out_dir, min_loading=min_loading)

    if as_json:
        safe = {k: v for k, v in result.items() if k != "scree_ascii"}
        print(json.dumps(safe, ensure_ascii=False, indent=2, default=float))
    else:
        print(format_apa_efa(result, min_loading=min_loading))
        print()
        print(result["scree_ascii"])
        if result.get("warnings"):
            print("\n警告：")
            for w in result["warnings"]:
                print(f"  · {w}")

    return result


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# ─── CLI 处理器 ──────────────────────────────────────────────────────────────

def efa_cli(argv: list[str]) -> int:
    """psyclaw efa 命令处理器。"""
    ap = argparse.ArgumentParser(
        prog="psyclaw efa",
        description="探索性因子分析（PAF + Varimax，stdlib only）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument(
        "--cols", default=None,
        help="参与分析的列名，逗号分隔（默认自动选所有数值列）",
    )
    ap.add_argument(
        "--n-factors", type=int, default=0, dest="n_factors",
        help="提取因子数（默认 0 = Kaiser 准则自动确定，特征值 ≥ 1.0）",
    )
    ap.add_argument(
        "--rotation", choices=["varimax", "none"], default="varimax",
        help="旋转方法（默认 varimax）",
    )
    ap.add_argument(
        "--method", choices=["paf", "pca"], default="paf",
        help="提取方法：paf（主轴因子法，默认）| pca（主成分法）",
    )
    ap.add_argument(
        "--min-loading", type=float, default=0.30, dest="min_loading",
        help="载荷显示阈值（|载荷| < 阈值显示空白，默认 .30）",
    )
    ap.add_argument(
        "--out", default=None,
        help="sidecar 输出目录（写 efa_report.md + efa_report.json）",
    )
    ap.add_argument(
        "--json", action="store_true", dest="as_json",
        help="输出机器可读 JSON",
    )
    args = ap.parse_args(argv)

    cols = [c.strip() for c in args.cols.split(",")] if args.cols else []

    try:
        analyze_efa(
            csv_path=args.csv,
            cols=cols,
            n_factors=args.n_factors,
            rotation=args.rotation,
            method=args.method,
            out_dir=args.out,
            as_json=args.as_json,
            min_loading=args.min_loading,
        )
        return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1
