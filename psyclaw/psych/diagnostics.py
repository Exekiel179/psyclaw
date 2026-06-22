"""可运行的前提假设诊断 — 纯 stdlib。

实现:
- 描述统计 + 偏度/峰度及其 z 检验(正态性的矩检验)
- Brown-Forsythe Levene 检验(方差齐性,中位数中心化,稳健)
- 经典单因素 ANOVA F 与 Welch F(各自 p 值)
- F 分布生存函数:自实现正则化不完全 Beta(连分式,Numerical Recipes 法)

这是 ARS-Stat 决策树(psyclaw assume)的可执行部分,对应门禁 STAT.assumptions。
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from scipy import special, stats


# ---------------------------------------------------------------------------
# 分布 p 值（scipy；betai 被测试 import）
# ---------------------------------------------------------------------------

def betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta I_x(a,b) —— scipy.special.betainc。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return float(special.betainc(a, b, x))


def f_sf(f_stat: float, df1: float, df2: float) -> float:
    """F 分布生存函数 P(F > f) —— scipy.stats.f.sf。"""
    if f_stat <= 0:
        return 1.0
    return float(stats.f.sf(f_stat, df1, df2))


def z_sf2(z: float) -> float:
    """标准正态双尾 p —— 2·scipy.stats.norm.sf(|z|)。"""
    return 2.0 * float(stats.norm.sf(abs(z)))


# ---------------------------------------------------------------------------
# 矩:偏度/峰度及 z 检验
# ---------------------------------------------------------------------------

def describe(xs: list) -> dict:
    n = len(xs)
    mean = sum(xs) / n
    dev = [x - mean for x in xs]
    m2 = sum(d * d for d in dev) / n
    m3 = sum(d ** 3 for d in dev) / n
    m4 = sum(d ** 4 for d in dev) / n
    sd = math.sqrt(m2 * n / (n - 1)) if n > 1 else 0.0
    out = {"n": n, "mean": mean, "sd": sd,
           "min": min(xs), "max": max(xs), "median": _median(xs)}
    if n > 3 and m2 > 0:
        g1 = m3 / m2 ** 1.5
        G1 = g1 * math.sqrt(n * (n - 1)) / (n - 2)               # 样本偏度
        g2 = m4 / (m2 * m2) - 3.0
        G2 = ((n + 1) * g2 + 6.0) * (n - 1) / ((n - 2) * (n - 3))  # 样本超额峰度
        se_skew = math.sqrt(6.0 * n * (n - 1) / ((n - 2) * (n + 1) * (n + 3)))
        se_kurt = 2.0 * se_skew * math.sqrt((n * n - 1) / ((n - 3) * (n + 5)))
        out.update({
            "skew": G1, "skew_z": G1 / se_skew, "skew_p": z_sf2(G1 / se_skew),
            "kurt": G2, "kurt_z": G2 / se_kurt, "kurt_p": z_sf2(G2 / se_kurt),
        })
    return out


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


# ---------------------------------------------------------------------------
# 组间检验:经典 F / Welch F / Brown-Forsythe Levene
# ---------------------------------------------------------------------------

def oneway_f(groups: list) -> dict:
    """经典单因素 ANOVA。groups: 各组数值列表的列表。"""
    k = len(groups)
    ns = [len(g) for g in groups]
    N = sum(ns)
    means = [sum(g) / len(g) for g in groups]
    grand = sum(sum(g) for g in groups) / N
    ss_b = sum(n * (m - grand) ** 2 for n, m in zip(ns, means))
    ss_w = sum(sum((x - m) ** 2 for x in g) for g, m in zip(groups, means))
    df1, df2 = k - 1, N - k
    if df2 <= 0 or ss_w == 0:
        return {"F": float("nan"), "df1": df1, "df2": df2, "p": float("nan"), "eta2": float("nan")}
    F = (ss_b / df1) / (ss_w / df2)
    return {"F": F, "df1": df1, "df2": df2, "p": f_sf(F, df1, df2),
            "eta2": ss_b / (ss_b + ss_w)}


def welch_f(groups: list) -> dict:
    """Welch ANOVA(不假设方差齐)。两组时 = Welch t 的 F 形式。"""
    k = len(groups)
    ns = [len(g) for g in groups]
    means = [sum(g) / len(g) for g in groups]
    vars_ = [sum((x - m) ** 2 for x in g) / (n - 1)
             for g, m, n in zip(groups, means, ns)]
    if any(v == 0 for v in vars_):
        return {"F": float("nan"), "df1": k - 1, "df2": float("nan"), "p": float("nan")}
    w = [n / v for n, v in zip(ns, vars_)]
    sw = sum(w)
    grand_w = sum(wi * m for wi, m in zip(w, means)) / sw
    num = sum(wi * (m - grand_w) ** 2 for wi, m in zip(w, means)) / (k - 1)
    lam = sum((1 - wi / sw) ** 2 / (n - 1) for wi, n in zip(w, ns))
    den = 1.0 + 2.0 * (k - 2) / (k * k - 1.0) * lam
    F = num / den
    df2 = (k * k - 1.0) / (3.0 * lam) if lam > 0 else float("inf")
    return {"F": F, "df1": k - 1, "df2": df2, "p": f_sf(F, k - 1, df2)}


def levene_bf(groups: list) -> dict:
    """Brown-Forsythe Levene:对 |x - 组中位数| 跑 ANOVA。"""
    z = [[abs(x - _median(g)) for x in g] for g in groups]
    r = oneway_f(z)
    return {"W": r["F"], "df1": r["df1"], "df2": r["df2"], "p": r["p"]}


# ---------------------------------------------------------------------------
# CLI:psyclaw check data.csv --dv col [--group col]
# ---------------------------------------------------------------------------

def _read_columns(path: Path, dv: str, group: str | None):
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if dv not in (reader.fieldnames or []):
            raise KeyError(f"找不到列 {dv}。可用列:{', '.join(reader.fieldnames or [])[:200]}")
        data: dict = {}
        for row in reader:
            try:
                val = float((row.get(dv) or "").strip())
            except ValueError:
                continue
            key = (row.get(group) or "?").strip() if group else "_all"
            data.setdefault(key, []).append(val)
    return data


def _fmt_p(p: float) -> str:
    if p != p:
        return "NA"
    return "< .001" if p < 0.001 else f"= {p:.3f}".replace("0.", ".")


def check_cli(path: str, dv: str, group: str | None = None) -> int:
    fp = Path(path)
    if not fp.exists():
        print(f"文件不存在:{path}")
        return 1
    try:
        data = _read_columns(fp, dv, group)
    except KeyError as e:
        print(e)
        return 1

    print(f"前提假设诊断 — {path}  (dv={dv}" + (f", group={group})" if group else ")"))
    print("-" * 60)

    # 1) 各组描述 + 正态性矩检验
    for name, xs in sorted(data.items()):
        d = describe(xs)
        print(f"\n  组 [{name}]  n={d['n']}  M={d['mean']:.3f}  SD={d['sd']:.3f}  "
              f"Mdn={d['median']:.3f}  range=[{d['min']:.2f}, {d['max']:.2f}]")
        if "skew" in d:
            sk_flag = " ⚠" if abs(d["skew"]) > 2 else ""
            ku_flag = " ⚠" if abs(d["kurt"]) > 7 else ""
            print(f"    偏度={d['skew']:.3f} (z={d['skew_z']:.2f}, p {_fmt_p(d['skew_p'])}){sk_flag}"
                  f"   峰度={d['kurt']:.3f} (z={d['kurt_z']:.2f}, p {_fmt_p(d['kurt_p'])}){ku_flag}")
            if d["n"] >= 100:
                print("    注:大样本下矩检验极易显著,看绝对值经验线(|偏|<2,|峰|<7)更实际")

    groups = [xs for _, xs in sorted(data.items()) if len(xs) >= 3]
    if group and len(groups) >= 2:
        # 2) 方差齐性
        lv = levene_bf(groups)
        print(f"\n  方差齐性 Brown-Forsythe: W({lv['df1']}, {lv['df2']}) = {lv['W']:.3f}, p {_fmt_p(lv['p'])}")
        hom = lv["p"] == lv["p"] and lv["p"] > .05
        print(f"    → {'未拒绝齐性' if hom else '方差不齐(或无法判定)'}")

        # 3) 经典 F vs Welch F
        cf = oneway_f(groups)
        wf = welch_f(groups)
        print(f"\n  经典 ANOVA : F({cf['df1']}, {cf['df2']}) = {cf['F']:.3f}, "
              f"p {_fmt_p(cf['p'])}, η² = {cf['eta2']:.3f}")
        print(f"  Welch ANOVA: F({wf['df1']}, {wf['df2']:.1f}) = {wf['F']:.3f}, p {_fmt_p(wf['p'])}")
        print("\n  ▶ 建议:无论齐性结果如何,默认报告 Welch(现代规范);"
              "两者结论不一致时必从 Welch。")
        print("  ▶ 效应量 η² 已给出;论文中请加 95% CI(M2 ARS-Stat 将自动补)。")
        print("  ▶ 完整假设清单:psyclaw assume " + ("t-ind" if len(groups) == 2 else "anova-oneway"))
    elif group:
        print("\n  分组后不足 2 个有效组(每组需 ≥3 个数值),仅输出描述统计。")
    else:
        print("\n  未指定 --group,仅输出整体描述与正态性诊断。")
    return 0


def check_cli_args(argv: list) -> int:
    """解析 `psyclaw check` 风格参数。"""
    if not argv:
        print("用法:psyclaw check <data.csv> --dv <列名> [--group <列名>]")
        return 1
    path = argv[0]
    dv = group = None
    if "--dv" in argv:
        dv = argv[argv.index("--dv") + 1]
    if "--group" in argv:
        group = argv[argv.index("--group") + 1]
    if not dv:
        print("必须指定 --dv <因变量列名>")
        return 1
    return check_cli(path, dv, group)
