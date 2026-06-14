"""非参数检验套件 — Mann-Whitney U / Wilcoxon signed-rank / Kruskal-Wallis H / Spearman ρ。

心理学研究中数据偏态、等级/有序数据、小样本场景下的参数检验替代方案。

提供：
  - mann_whitney_u(x, y)         → U1/U2/Z/p/r 效应量
  - wilcoxon_signed_rank(x, y)   → W/Z/p/r（配对差值秩和）
  - kruskal_wallis(groups)       → H/df/p/eta2_h
  - spearman_rho(x, y)           → ρ/t/p
  - format_apa_nonpar(result)    → APA-7 段落
  - write_nonpar_report(result)  → MD + JSON sidecar
  - analyze_nonpar(csv, ...)     → CSV 主入口
  - CLI: psyclaw nonpar <data.csv> --test mwu|wilcoxon|kruskal|spearman ...
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any


# ---------------------------------------------------------------------------
# 共用：正态近似 / 分布工具
# ---------------------------------------------------------------------------

def _norm_sf(z: float) -> float:
    """正态分布 P(Z > |z|) × 2（双尾），使用误差函数近似。"""
    return math.erfc(abs(z) / math.sqrt(2))


def _chi2_sf(h: float, df: float) -> float:
    """χ² 生存函数（Poisson 级数近似）。"""
    if h <= 0 or df <= 0:
        return 1.0
    # 使用不完全伽马函数 P(a, x)：
    # chi2_sf(h, df) = 1 - P(df/2, h/2) = Q(df/2, h/2)
    a = df / 2.0
    x = h / 2.0
    return 1.0 - _regularized_gamma_lower(a, x)


def _regularized_gamma_lower(a: float, x: float) -> float:
    """正则化下不完全伽马函数 P(a, x) = γ(a,x)/Γ(a)。"""
    if x < 0:
        return 0.0
    if x == 0:
        return 0.0
    if x < a + 1:
        # 级数展开
        ap = a
        s = 1.0 / a
        delta = s
        for _ in range(300):
            ap += 1
            delta *= x / ap
            s += delta
            if abs(delta) < 1e-14 * abs(s):
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    else:
        # 连分数展开（Lentz 法）
        fpmin = 1e-300
        b = x + 1.0 - a
        c = 1.0 / fpmin
        d = 1.0 / b
        h_cf = d
        for i in range(1, 301):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            c = b + an / c
            if abs(d) < fpmin: d = fpmin
            if abs(c) < fpmin: c = fpmin
            d = 1.0 / d
            delta = d * c
            h_cf *= delta
            if abs(delta - 1.0) < 1e-14:
                break
        return 1.0 - math.exp(-x + a * math.log(x) - math.lgamma(a)) * h_cf


def _t_sf(t: float, df: float) -> float:
    """t 分布双尾 p 值（不完全贝塔函数）。"""
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _betai(a: float, b: float, x: float) -> float:
    if x < 0 or x > 1:
        return float("nan")
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):
        return 1.0 - _betai(b, a, 1.0 - x)
    fpmin = 1e-300
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1)
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin: d = fpmin
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        h *= d * c
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1.0 + num * d
        c = 1.0 + num / c
        if abs(d) < fpmin: d = fpmin
        if abs(c) < fpmin: c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return front * h


def _rank_data(data: list[float]) -> list[float]:
    """为列表赋秩（平均秩处理同值）。"""
    n = len(data)
    indexed = sorted(range(n), key=lambda i: data[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and data[indexed[j + 1]] == data[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed 平均秩
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


# ---------------------------------------------------------------------------
# Mann-Whitney U 检验（两独立样本非参数替代）
# ---------------------------------------------------------------------------

def mann_whitney_u(
    x: list[float],
    y: list[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Mann-Whitney U 检验（Wilcoxon 秩和检验）。

    x, y: 两独立样本数值列表（至少各 3 个观测）
    返回 U1/U2/Z/p/r_effect（效应量 r = Z/√N）
    """
    n1, n2 = len(x), len(y)
    if n1 < 3 or n2 < 3:
        raise ValueError(f"每组需要至少 3 个观测（x={n1}, y={n2}）")

    # 合并秩
    combined = x + y
    group_labels = [1] * n1 + [2] * n2
    ranks = _rank_data(combined)

    R1 = sum(r for r, g in zip(ranks, group_labels) if g == 1)
    U1 = n1 * n2 + n1 * (n1 + 1) / 2 - R1
    U2 = n1 * n2 - U1

    # 正态近似（大样本或有平均秩时使用）
    mean_U = n1 * n2 / 2
    sigma_U = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)

    Z = (U1 - mean_U) / sigma_U if sigma_U > 0 else 0.0
    p = _norm_sf(Z)  # 双尾

    N = n1 + n2
    r_effect = abs(Z) / math.sqrt(N)

    return {
        "test": "Mann-Whitney U",
        "U1": round(U1, 4),
        "U2": round(U2, 4),
        "n1": n1,
        "n2": n2,
        "Z": round(Z, 4),
        "p": round(p, 6),
        "r_effect": round(r_effect, 4),
        "alpha": alpha,
        "significant": p < alpha,
    }


# ---------------------------------------------------------------------------
# Wilcoxon signed-rank 检验（配对差值秩和）
# ---------------------------------------------------------------------------

def wilcoxon_signed_rank(
    x: list[float],
    y: list[float] | None = None,
    mu0: float = 0.0,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Wilcoxon signed-rank 检验（配对样本或单样本）。

    x: 第一组观测（配对时 y 为第二组；y=None 时检验 x - mu0）
    返回 W/Z/p/r
    """
    if y is not None:
        if len(x) != len(y):
            raise ValueError(f"配对样本长度不一致（x={len(x)}, y={len(y)}）")
        diffs = [a - b - mu0 for a, b in zip(x, y)]
    else:
        diffs = [v - mu0 for v in x]

    # 去除零值
    diffs = [d for d in diffs if d != 0.0]
    n = len(diffs)
    if n < 5:
        raise ValueError(f"非零差值数量不足（n={n}），需要至少 5 个")

    abs_diffs = [abs(d) for d in diffs]
    ranks = _rank_data(abs_diffs)

    # W+ = 正差值秩和
    W_plus = sum(r for r, d in zip(ranks, diffs) if d > 0)
    W_minus = sum(r for r, d in zip(ranks, diffs) if d < 0)

    # 正态近似
    mean_W = n * (n + 1) / 4
    sigma_W = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    W = min(W_plus, W_minus)
    Z = (W - mean_W) / sigma_W if sigma_W > 0 else 0.0
    p = _norm_sf(Z)

    N_total = len(x) if y is not None else len(x)
    r_effect = abs(Z) / math.sqrt(n)

    return {
        "test": "Wilcoxon signed-rank",
        "W_plus": round(W_plus, 4),
        "W_minus": round(W_minus, 4),
        "W": round(W, 4),
        "n_pairs": n,
        "Z": round(Z, 4),
        "p": round(p, 6),
        "r_effect": round(r_effect, 4),
        "alpha": alpha,
        "significant": p < alpha,
    }


# ---------------------------------------------------------------------------
# Kruskal-Wallis H 检验（多组非参数替代单因素 ANOVA）
# ---------------------------------------------------------------------------

def kruskal_wallis(
    groups: dict[str, list[float]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Kruskal-Wallis H 检验（单因素 ANOVA 的非参数替代）。

    groups: {组名: [观测值, ...]}（至少 2 组，各组 ≥ 3 观测）
    返回 H/df/p/eta2_h（效应量）
    """
    k = len(groups)
    if k < 2:
        raise ValueError(f"至少需要 2 组（当前 {k} 组）")
    group_names = list(groups.keys())
    group_data = [groups[name] for name in group_names]
    ns = [len(g) for g in group_data]
    if any(n < 3 for n in ns):
        raise ValueError("每组至少需要 3 个观测值")

    N = sum(ns)
    # 合并所有值并计算秩
    combined = []
    for i, g in enumerate(group_data):
        for v in g:
            combined.append((v, i))
    sorted_vals = sorted(combined, key=lambda t: t[0])

    # 平均秩（处理同值）
    n_all = len(sorted_vals)
    ranks_all = [0.0] * n_all
    i = 0
    while i < n_all:
        j = i
        while j < n_all - 1 and sorted_vals[j + 1][0] == sorted_vals[j][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for idx in range(i, j + 1):
            ranks_all[idx] = avg
        i = j + 1

    # 各组秩和
    group_rank_sums = [0.0] * k
    for idx, (_, gi) in enumerate(sorted_vals):
        group_rank_sums[gi] += ranks_all[idx]

    # H 统计量
    H = (12 / (N * (N + 1))) * sum(
        group_rank_sums[i] ** 2 / ns[i] for i in range(k)
    ) - 3 * (N + 1)

    df = k - 1
    p = _chi2_sf(H, df)

    # eta² = (H - k + 1) / (N - k)（效应量）
    eta2_h = max((H - k + 1) / (N - k), 0.0) if N > k else 0.0

    group_stats = [
        {
            "name": group_names[i],
            "n": ns[i],
            "median": round(sorted(group_data[i])[ns[i] // 2], 4),
            "mean_rank": round(group_rank_sums[i] / ns[i], 4),
        }
        for i in range(k)
    ]

    return {
        "test": "Kruskal-Wallis H",
        "H": round(H, 4),
        "df": df,
        "p": round(p, 6),
        "eta2_h": round(eta2_h, 4),
        "N": N,
        "k": k,
        "alpha": alpha,
        "significant": p < alpha,
        "group_stats": group_stats,
    }


# ---------------------------------------------------------------------------
# Spearman ρ（非参数单调相关）
# ---------------------------------------------------------------------------

def spearman_rho(
    x: list[float],
    y: list[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Spearman 秩相关系数 ρ。

    x, y: 两组等长配对数值
    返回 rho/t/p（双尾）
    """
    n = len(x)
    if n != len(y):
        raise ValueError(f"x 与 y 长度不一致（{n} vs {len(y)}）")
    if n < 4:
        raise ValueError(f"需要至少 4 对观测（当前 n={n}）")

    rx = _rank_data(x)
    ry = _rank_data(y)

    # Pearson r on ranks
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den = math.sqrt(
        sum((v - mean_rx) ** 2 for v in rx) * sum((v - mean_ry) ** 2 for v in ry)
    )
    rho = num / den if den > 0 else 0.0

    # t 近似：t = ρ √(n-2) / √(1 - ρ²)
    if abs(rho) >= 1.0:
        t = float("inf") if rho > 0 else float("-inf")
        p = 0.0
    else:
        t = rho * math.sqrt(n - 2) / math.sqrt(1 - rho ** 2)
        p = _t_sf(abs(t), n - 2)

    return {
        "test": "Spearman rho",
        "rho": round(rho, 4),
        "t": round(t, 4) if math.isfinite(t) else None,
        "df": n - 2,
        "p": round(p, 6) if math.isfinite(p) else None,
        "n": n,
        "alpha": alpha,
        "significant": p < alpha if math.isfinite(p) else True,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None or (isinstance(p, float) and not math.isfinite(p)):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def _interpret_r(r: float) -> str:
    ar = abs(r)
    if ar >= 0.50:
        return "大效应"
    if ar >= 0.30:
        return "中效应"
    if ar >= 0.10:
        return "小效应"
    return "微效应"


def format_apa_nonpar(result: dict[str, Any]) -> str:
    """生成 APA-7 格式非参数检验段落。"""
    test = result["test"]
    p = result.get("p")
    sig = result.get("significant", p is not None and p < result.get("alpha", 0.05))
    p_str = _fmt_p(p)
    sig_str = "达到统计显著性" if sig else "未达到统计显著性"

    if test == "Mann-Whitney U":
        U = result.get("U1")
        Z = result.get("Z")
        r = result.get("r_effect", 0.0)
        return (
            f"Mann-Whitney U 检验结果显示，*U* = {U:.0f}，*Z* = {Z:.2f}，"
            f"*p* {p_str}，*r* = {r:.3f}（{_interpret_r(r)}），{sig_str}。"
        )
    elif test == "Wilcoxon signed-rank":
        W = result.get("W")
        Z = result.get("Z")
        r = result.get("r_effect", 0.0)
        n = result.get("n_pairs")
        return (
            f"Wilcoxon 符号秩检验结果显示，*W* = {W:.0f}，*Z* = {Z:.2f}，"
            f"*p* {p_str}，*r* = {r:.3f}（{_interpret_r(r)}），*n* = {n}，{sig_str}。"
        )
    elif test == "Kruskal-Wallis H":
        H = result.get("H")
        df = result.get("df")
        eta2 = result.get("eta2_h", 0.0)
        N = result.get("N")
        return (
            f"Kruskal-Wallis 检验结果显示，*H*({df}) = {H:.2f}，"
            f"*p* {p_str}，*η*²_H = {eta2:.3f}（N = {N}），{sig_str}。"
        )
    elif test == "Spearman rho":
        rho = result.get("rho")
        t = result.get("t")
        df = result.get("df")
        n = result.get("n")
        t_str = f"{t:.2f}" if t is not None else "—"
        return (
            f"Spearman 秩相关结果显示，*r*_s = {rho:.3f}，"
            f"*t*({df}) = {t_str}，*p* {p_str}，*N* = {n}，{sig_str}。"
        )
    return f"{test}：*p* {p_str}，{sig_str}。"


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_nonpar_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    filename: str = "nonpar_report",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_name = result.get("test", "NonParametric")
    lines = [
        f"# 非参数检验报告：{test_name}",
        "",
        format_apa_nonpar(result),
    ]

    # 附组别统计（Kruskal-Wallis）
    if "group_stats" in result:
        lines += ["", "## 各组描述统计", "",
                  "| 组别 | *n* | 中位数 | 平均秩 |",
                  "|------|-----|--------|--------|"]
        for g in result["group_stats"]:
            lines.append(f"| {g['name']} | {g['n']} | {g['median']} | {g['mean_rank']} |")

    md_path = out / f"{filename}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / f"{filename}.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col(rows: list[dict], col: str) -> list[float]:
    """从 CSV 行列表读取一列数值（跳过缺失/非数值）。"""
    vals = []
    for row in rows:
        raw = row.get(col, "").strip()
        if not raw:
            continue
        try:
            v = float(raw)
            if math.isfinite(v):
                vals.append(v)
        except ValueError:
            continue
    return vals


def analyze_nonpar(
    csv_path: str,
    test: str,
    dv: str,
    group_col: str | None = None,
    x_col: str | None = None,
    y_col: str | None = None,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行非参数检验。

    test: 'mwu' | 'wilcoxon' | 'kruskal' | 'spearman'
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    test = test.lower()

    if test == "mwu":
        if group_col is None:
            raise ValueError("Mann-Whitney U 检验需要 --group 参数")
        groups_raw: dict[str, list[float]] = {}
        for row in rows:
            grp = row.get(group_col, "").strip()
            raw = row.get(dv, "").strip()
            if not grp or not raw:
                continue
            try:
                v = float(raw)
                if math.isfinite(v):
                    groups_raw.setdefault(grp, []).append(v)
            except ValueError:
                continue
        gnames = list(groups_raw.keys())
        if len(gnames) != 2:
            raise ValueError(
                f"Mann-Whitney U 需要恰好 2 组（发现 {len(gnames)}：{gnames}）"
            )
        result = mann_whitney_u(groups_raw[gnames[0]], groups_raw[gnames[1]], alpha=alpha)
        result["group1"] = gnames[0]
        result["group2"] = gnames[1]

    elif test == "wilcoxon":
        if y_col is None:
            raise ValueError("Wilcoxon 检验需要 --y 参数（第二组列名）")
        x_vals = _read_col(rows, dv)
        y_vals = _read_col(rows, y_col)
        n = min(len(x_vals), len(y_vals))
        result = wilcoxon_signed_rank(x_vals[:n], y_vals[:n], alpha=alpha)

    elif test == "kruskal":
        if group_col is None:
            raise ValueError("Kruskal-Wallis 检验需要 --group 参数")
        grp_map: dict[str, list[float]] = {}
        for row in rows:
            grp = row.get(group_col, "").strip()
            raw = row.get(dv, "").strip()
            if not grp or not raw:
                continue
            try:
                v = float(raw)
                if math.isfinite(v):
                    grp_map.setdefault(grp, []).append(v)
            except ValueError:
                continue
        result = kruskal_wallis(grp_map, alpha=alpha)

    elif test == "spearman":
        if y_col is None and x_col is None:
            raise ValueError("Spearman ρ 需要 --y 参数（第二变量列名）")
        col_x = x_col or dv
        col_y = y_col or dv
        x_vals = _read_col(rows, col_x)
        y_vals = _read_col(rows, col_y)
        n = min(len(x_vals), len(y_vals))
        result = spearman_rho(x_vals[:n], y_vals[:n], alpha=alpha)

    else:
        raise ValueError(
            f"未知检验类型 '{test}'，可选：mwu | wilcoxon | kruskal | spearman"
        )

    result["input_file"] = csv_path

    if write_files:
        fname = f"nonpar_{test}_report"
        md_path, json_path = write_nonpar_report(result, out_dir=out_dir, filename=fname)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def nonpar_cli(args: list[str]) -> int:
    """psyclaw nonpar <data.csv> --test mwu|wilcoxon|kruskal|spearman [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw nonpar",
        description="非参数检验：Mann-Whitney U / Wilcoxon / Kruskal-Wallis / Spearman ρ",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument(
        "--test",
        required=True,
        choices=["mwu", "wilcoxon", "kruskal", "spearman"],
        help="检验类型：mwu（Mann-Whitney U）| wilcoxon | kruskal | spearman",
    )
    parser.add_argument("--dv", required=True, help="因变量列名（或第一变量列名）")
    parser.add_argument("--group", dest="group_col", default=None, help="分组列名（mwu/kruskal 必需）")
    parser.add_argument("--y", dest="y_col", default=None, help="第二变量列名（wilcoxon/spearman 必需）")
    parser.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_nonpar(
            csv_path=opts.csv_file,
            test=opts.test,
            dv=opts.dv,
            group_col=opts.group_col,
            y_col=opts.y_col,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_nonpar(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
