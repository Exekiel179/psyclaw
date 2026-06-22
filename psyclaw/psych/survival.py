"""生存分析（时间到事件）— Kaplan-Meier 估计 + Log-rank 检验，stdlib only。

填补统计套件空白：此前回归族、方差分析族、非参数、分类、信度、ROC 一应俱全，
唯独缺**时间到事件（time-to-event / survival）分析**。临床与纵向心理学极常见此类结局：
治疗后到复发的时间、研究中到脱落（attrition）的时间、到首次发作/达标的时间。这类数据
含**删失（censoring）**——被试在观察结束时仍未发生事件，或中途失访——普通 t 检验/
回归无法正确处理删失，会丢弃或曲解信息。

提供：
  - kaplan_meier(times, events)        → 乘积极限生存曲线 S(t) + Greenwood SE + log-log CI + 中位生存
  - logrank_test(groups)               → Mantel-Haenszel Log-rank 检验比较 2+ 组生存曲线
  - format_apa_survival(result)        → APA-7 段落
  - write_survival_report(result)      → MD + JSON sidecar
  - analyze_survival(csv_path, ...)    → CSV 主入口
  - CLI: psyclaw survival <data.csv> --time <col> --event <col> [--group <col>]

理论依据：Kaplan & Meier (1958)；Mantel (1966)；Peto & Peto (1972)；
Greenwood (1926, 方差)；Collett (2015) Modelling Survival Data in Medical Research (3rd ed.)。

数值要点：
  - 删失（event=0）的被试在其时间点之前一直计入风险集，但不贡献事件。
  - Log-rank 方差的同分校正因子 d_i(n_i−d_i)/(n_i−1)，在 n_i=1（最后仅剩 1 人）时取 0。
  - log-log 变换 CI 保证生存概率界落在 [0, 1]（朴素 Greenwood CI 可能出界）。
  - 中位生存 = 使 S(t) ≤ 0.5 的最小事件时间；若 S 始终 > 0.5（重删失）则「未达到」(None)。
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
# 分布工具（与 chisquare.py / roc.py 同款，stdlib only）
# ---------------------------------------------------------------------------

def _chi2_sf(x: float, df: float) -> float:
    """χ² 分布生存函数 P(X > x) —— scipy.stats.chi2.sf。"""
    if x <= 0 or df <= 0:
        return 1.0 if x <= 0 else 0.0
    return float(stats.chi2.sf(x, df))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


def _matrix_inverse(mat: list[list[float]]) -> list[list[float]]:
    """方阵求逆（numpy）；奇异抛 ValueError（Log-rank k>2 协方差阵用）。"""
    try:
        return np.linalg.inv(np.asarray(mat, dtype=float)).tolist()
    except np.linalg.LinAlgError:
        raise ValueError("Log-rank 协方差矩阵奇异，无法求逆")


# ---------------------------------------------------------------------------
# 输入清洗
# ---------------------------------------------------------------------------

def _clean_survival(
    times: list[float], events: list[float]
) -> tuple[list[float], list[int]]:
    """校验并归一化生存数据：times≥0、events∈{0,1}、等长、n≥1。"""
    if len(times) != len(events):
        raise ValueError("times 与 events 长度必须相等")
    if not times:
        raise ValueError("生存分析至少需要 1 个观测")
    t_out: list[float] = []
    e_out: list[int] = []
    for t, e in zip(times, events):
        ft = float(t)
        if ft < 0 or not math.isfinite(ft):
            raise ValueError(f"生存时间必须为非负有限数（得到 {t}）")
        fe = float(e)
        if fe == 0.0:
            ev = 0
        elif fe == 1.0:
            ev = 1
        else:
            raise ValueError(f"事件指示必须为 0(删失)/1(事件)（得到 {e}）")
        t_out.append(ft)
        e_out.append(ev)
    return t_out, e_out


# ---------------------------------------------------------------------------
# Kaplan-Meier 乘积极限估计
# ---------------------------------------------------------------------------

def kaplan_meier(
    times: list[float],
    events: list[float],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Kaplan-Meier 乘积极限生存曲线估计。

    times: 各被试观测时间（事件时间或删失时间）；events: 0=删失，1=事件发生。
    在每个不同的**事件**时间 t_i：风险集 n_i = 时间 ≥ t_i 的被试数，d_i = 该时刻事件数；
    S(t) = Π_{t_i ≤ t} (1 − d_i / n_i)。删失观测在其时间前一直计入风险集但不掉 S。

    Greenwood (1926) 方差：Var[S(t)] = S(t)² · Σ_{t_i≤t} d_i / (n_i(n_i−d_i))；
    95% CI 用 complementary log-log 变换（保证界 ∈ [0,1]）：
        S(t)^exp(±z·SE_c)，SE_c = sqrt(Σ d_i/(n_i(n_i−d_i))) / |ln S(t)|。
    中位生存 = 使 S(t) ≤ 0.5 的最小事件时间；S 始终 > 0.5 则未达到（None）。
    """
    t, e = _clean_survival(times, events)
    n_total = len(t)
    z = _norm_ppf(1.0 - alpha / 2.0)

    # 各不同事件时间（升序），仅当该时刻确有事件发生
    event_times = sorted({ti for ti, ei in zip(t, e) if ei == 1})

    survival = 1.0
    cum_var_sum = 0.0   # Σ d_i / (n_i (n_i − d_i))，Greenwood 累积项
    timeline: list[dict[str, Any]] = []
    median_survival: float | None = None

    for ti in event_times:
        n_risk = sum(1 for x in t if x >= ti)
        d = sum(1 for x, ev in zip(t, e) if x == ti and ev == 1)
        n_cens = sum(1 for x, ev in zip(t, e) if x == ti and ev == 0)
        survival *= (n_risk - d) / n_risk
        if n_risk - d > 0:
            cum_var_sum += d / (n_risk * (n_risk - d))
        se = survival * math.sqrt(cum_var_sum)

        if 0.0 < survival < 1.0 and cum_var_sum > 0:
            se_c = math.sqrt(cum_var_sum) / abs(math.log(survival))
            ci_lower = survival ** math.exp(z * se_c)
            ci_upper = survival ** math.exp(-z * se_c)
        elif survival >= 1.0:
            ci_lower = ci_upper = 1.0
        else:  # survival == 0
            ci_lower = ci_upper = 0.0

        timeline.append({
            "time": ti,
            "n_risk": n_risk,
            "n_event": d,
            "n_censored": n_cens,
            "survival": round(survival, 6),
            "se": round(se, 6),
            "ci_lower": round(ci_lower, 6),
            "ci_upper": round(ci_upper, 6),
        })

        if median_survival is None and survival <= 0.5:
            median_survival = ti

    n_events = sum(e)
    return {
        "test": "Kaplan-Meier",
        "n": n_total,
        "n_events": n_events,
        "n_censored": n_total - n_events,
        "median_survival": median_survival,
        "alpha": alpha,
        "timeline": timeline,
    }


# ---------------------------------------------------------------------------
# Log-rank 检验（Mantel-Haenszel）
# ---------------------------------------------------------------------------

def logrank_test(
    groups: dict[str, tuple[list[float], list[float]]],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Log-rank（Mantel-Haenszel）检验比较 2+ 组生存曲线。

    groups: {组名: (times, events)}，至少 2 组。H0：各组生存函数相同。
    在所有组合并的每个不同事件时间 t_i：n_i = 总风险数、d_i = 总事件数，
    组 j 风险 n_ij、事件 d_ij；期望 e_ij = d_i · n_ij / n_i。
    观测合计 O_j = Σ d_ij、期望合计 E_j = Σ e_ij。

    (k−1) 维约化二次型 χ² = (O−E)' V⁻¹ (O−E)，df = k−1；
    协方差 V_jj = Σ c_i (n_ij/n_i)(1−n_ij/n_i)，V_jl = −Σ c_i (n_ij n_il)/n_i²（j≠l），
    同分校正 c_i = d_i (n_i − d_i)/(n_i − 1)（n_i=1 时取 0）。k=2 时退化为标量 (O₁−E₁)²/V。
    """
    if len(groups) < 2:
        raise ValueError("Log-rank 检验至少需要 2 组")
    names = list(groups.keys())
    k = len(names)
    cleaned: dict[str, tuple[list[float], list[int]]] = {}
    for name in names:
        ts, es = groups[name]
        cleaned[name] = _clean_survival(ts, es)

    # 所有组合并的不同事件时间
    all_event_times = sorted({
        ti
        for name in names
        for ti, ei in zip(*cleaned[name]) if ei == 1
    })

    O = [0.0] * k
    E = [0.0] * k
    V = [[0.0] * k for _ in range(k)]

    for ti in all_event_times:
        n_risk = [sum(1 for x in cleaned[names[j]][0] if x >= ti) for j in range(k)]
        d_grp = [sum(1 for x, ev in zip(*cleaned[names[j]]) if x == ti and ev == 1)
                 for j in range(k)]
        n_i = sum(n_risk)
        d_i = sum(d_grp)
        if n_i <= 0 or d_i <= 0:
            continue
        for j in range(k):
            O[j] += d_grp[j]
            E[j] += d_i * n_risk[j] / n_i
        # 同分校正因子（n_i=1 时分母为 0 → 取 0）
        c_i = d_i * (n_i - d_i) / (n_i - 1) if n_i > 1 else 0.0
        if c_i == 0.0:
            continue
        for j in range(k):
            pj = n_risk[j] / n_i
            V[j][j] += c_i * pj * (1.0 - pj)
            for l in range(j + 1, k):
                cov = -c_i * (n_risk[j] * n_risk[l]) / (n_i * n_i)
                V[j][l] += cov
                V[l][j] += cov

    # 约化（去掉最后一组）二次型
    diff = [O[j] - E[j] for j in range(k)]
    if k == 2:
        var = V[0][0]
        chi2 = (diff[0] ** 2) / var if var > 0 else 0.0
    else:
        Vr = [[V[j][l] for l in range(k - 1)] for j in range(k - 1)]
        dr = diff[:k - 1]
        try:
            Vinv = _matrix_inverse(Vr)
            chi2 = sum(
                dr[a] * Vinv[a][b] * dr[b]
                for a in range(k - 1) for b in range(k - 1)
            )
        except ValueError:
            chi2 = 0.0
    chi2 = max(chi2, 0.0)
    df = k - 1
    p = _chi2_sf(chi2, df)

    group_summaries: list[dict[str, Any]] = []
    for j, name in enumerate(names):
        km = kaplan_meier(*groups[name], alpha=alpha)
        group_summaries.append({
            "name": name,
            "n": km["n"],
            "n_events": km["n_events"],
            "n_censored": km["n_censored"],
            "observed": round(O[j], 4),
            "expected": round(E[j], 4),
            "median_survival": km["median_survival"],
            "timeline": km["timeline"],
        })

    return {
        "test": "Log-rank",
        "chi2": round(chi2, 4),
        "df": df,
        "p": round(p, 6),
        "k": k,
        "alpha": alpha,
        "significant": p < alpha,
        "groups": group_summaries,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None:
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


def _fmt_median(m: float | None) -> str:
    return "未达到" if m is None else f"{m:g}"


def format_apa_survival(result: dict[str, Any]) -> str:
    """生成 APA-7 生存分析段落。"""
    test = result["test"]
    lines: list[str] = []

    if test == "Kaplan-Meier":
        n = result["n"]
        ne = result["n_events"]
        nc = result["n_censored"]
        med = _fmt_median(result.get("median_survival"))
        lines.append(
            f"Kaplan-Meier 乘积极限估计（*N* = {n}，事件 {ne} 例，删失 {nc} 例）显示，"
            f"中位生存时间为 {med}。"
        )
        tl = result.get("timeline", [])
        if tl:
            last = tl[-1]
            lines.append(
                f"末次事件时间点 *t* = {last['time']:g} 处的估计生存概率为 "
                f"{last['survival']:.3f}（95% CI [{last['ci_lower']:.3f}, "
                f"{last['ci_upper']:.3f}]）。"
            )

    elif test == "Log-rank":
        chi2 = result.get("chi2", 0.0)
        df = result.get("df")
        p = result.get("p")
        p_str = _fmt_p(p)
        sig = "存在统计显著差异" if result.get("significant") else "无统计显著差异"
        lines.append(
            f"Log-rank 检验显示，{result.get('k')} 组生存曲线之间 {sig}，"
            f"*χ*²({df}) = {chi2:.2f}，*p* {p_str}。"
        )
        meds = "、".join(
            f"{g['name']} = {_fmt_median(g['median_survival'])}"
            for g in result.get("groups", [])
        )
        if meds:
            lines.append(f"各组中位生存时间：{meds}。")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def _json_safe(obj: Any) -> Any:
    """递归把 NaN/inf 转 None，保证 JSON 合法。"""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def _km_table(timeline: list[dict[str, Any]]) -> list[str]:
    lines = ["| *t* | 风险数 | 事件 | 删失 | *S(t)* | SE | 95% CI |",
             "|-----|--------|------|------|--------|-----|--------|"]
    for row in timeline:
        lines.append(
            f"| {row['time']:g} | {row['n_risk']} | {row['n_event']} | "
            f"{row['n_censored']} | {row['survival']:.3f} | {row['se']:.3f} | "
            f"[{row['ci_lower']:.3f}, {row['ci_upper']:.3f}] |"
        )
    return lines


def write_survival_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    filename: str = "survival_report",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_labels = {"Kaplan-Meier": "Kaplan-Meier 生存曲线",
                   "Log-rank": "Log-rank 组间比较"}
    label = test_labels.get(result.get("test", ""), "生存分析")
    lines = [f"# 生存分析报告：{label}", "", format_apa_survival(result)]

    if result.get("test") == "Kaplan-Meier":
        lines += ["", "## 生存函数表", ""]
        lines += _km_table(result.get("timeline", []))

    elif result.get("test") == "Log-rank":
        lines += ["", "## 各组观测/期望事件数", "",
                  "| 组 | *n* | 事件 | 删失 | 观测 *O* | 期望 *E* | 中位生存 |",
                  "|----|-----|------|------|----------|----------|----------|"]
        for g in result.get("groups", []):
            lines.append(
                f"| {g['name']} | {g['n']} | {g['n_events']} | {g['n_censored']} | "
                f"{g['observed']} | {g['expected']} | "
                f"{_fmt_median(g['median_survival'])} |"
            )
        for g in result.get("groups", []):
            lines += ["", f"### {g['name']} 组生存函数表", ""]
            lines += _km_table(g.get("timeline", []))

    md_path = out / f"{filename}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    json_path = out / f"{filename}.json"
    json_path.write_text(
        json.dumps(_json_safe(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def analyze_survival(
    csv_path: str,
    time_col: str,
    event_col: str,
    group_col: str | None = None,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行生存分析。

    每行一名被试：time_col = 观测时间（数值），event_col = 0(删失)/1(事件)。
    指定 group_col 时按组计算 KM 曲线并做 Log-rank 比较；否则单组 KM。
    完整案例筛选：time/event（及 group）缺失或非法的行排除并计数。
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    n_excluded = 0

    if group_col:
        grouped: dict[str, tuple[list[float], list[float]]] = {}
        store: dict[str, tuple[list[float], list[float]]] = {}
        for row in rows:
            traw = (row.get(time_col) or "").strip()
            eraw = (row.get(event_col) or "").strip()
            graw = (row.get(group_col) or "").strip()
            if not graw:
                n_excluded += 1
                continue
            try:
                tv = float(traw)
                ev = float(eraw)
            except ValueError:
                n_excluded += 1
                continue
            if tv < 0 or ev not in (0.0, 1.0):
                n_excluded += 1
                continue
            store.setdefault(graw, ([], []))
            store[graw][0].append(tv)
            store[graw][1].append(ev)
        if len(store) < 2:
            raise ValueError(
                f"Log-rank 检验需要至少 2 个有效分组（当前 {len(store)}）"
            )
        grouped = store
        result = logrank_test(grouped, alpha=alpha)
        result["group_col"] = group_col
        result["n_excluded"] = n_excluded

    else:
        times: list[float] = []
        events: list[float] = []
        for row in rows:
            traw = (row.get(time_col) or "").strip()
            eraw = (row.get(event_col) or "").strip()
            try:
                tv = float(traw)
                ev = float(eraw)
            except ValueError:
                n_excluded += 1
                continue
            if tv < 0 or ev not in (0.0, 1.0):
                n_excluded += 1
                continue
            times.append(tv)
            events.append(ev)
        if not times:
            raise ValueError("无有效观测（检查 time/event 列名与取值）")
        result = kaplan_meier(times, events, alpha=alpha)
        result["n_excluded"] = n_excluded

    result["input_file"] = csv_path
    result["time_col"] = time_col
    result["event_col"] = event_col

    if write_files:
        fname = "survival_logrank_report" if group_col else "survival_km_report"
        md_path, json_path = write_survival_report(result, out_dir=out_dir, filename=fname)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def survival_cli(args: list[str]) -> int:
    """psyclaw survival <data.csv> --time <col> --event <col> [--group <col>]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw survival",
        description="生存分析：Kaplan-Meier 曲线 + Log-rank 检验",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--time", dest="time_col", required=True,
                        help="生存时间列名（数值）")
    parser.add_argument("--event", dest="event_col", required=True,
                        help="事件指示列名（0=删失，1=事件发生）")
    parser.add_argument("--group", dest="group_col", default=None,
                        help="分组列名（指定后做 Log-rank 组间比较）")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_survival(
            csv_path=opts.csv_file,
            time_col=opts.time_col,
            event_col=opts.event_col,
            group_col=opts.group_col,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
        return 0

    print()
    print(format_apa_survival(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
