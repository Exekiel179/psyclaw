"""配对/重复测量二分数据检验 — McNemar 检验 / Cochran's Q，stdlib only。

填补分类数据套件空白：普通卡方（`chisquare.py`）要求观测独立（每人只贡献一个单元格），
**重复测量/配对二分结局**（同一批被试在前后两时点、或两评分者对同一对象的 0/1 判定）违反
该假设，须用配对检验。`assumptions.json` 早已指明此场景应改用 McNemar，但此前无实现。

提供：
  - mcnemar_test(table, correction, exact)   → 配对 2×2，χ²/精确二项 p + 边际比例差 + OR
  - cochran_q(conditions, post_hoc)          → k≥3 重复测量二分（McNemar 的多条件推广）
  - format_apa_paircat(result)               → APA-7 段落
  - write_paircat_report(result)             → MD + JSON sidecar
  - analyze_paircat(csv_path, ...)           → CSV 主入口
  - CLI: psyclaw paired-cat <data.csv> --test mcnemar|cochran ...

理论依据：McNemar (1947)；Cochran (1950)；Edwards (1948, 连续性校正)；
Sheskin (2011) Handbook of Parametric and Nonparametric Statistical Procedures (5th ed.)。

数值要点：
  - Cochran's Q 在 k=2 时代数化简退化为未校正 McNemar χ² = (b−c)²/(b+c)（恒等式，已测）。
  - 全 0 / 全 1 行（无被试内变异）对 Q 的分母贡献为 R_i(k−R_i)=0，自动不计入，与理论一致。
  - 不一致对 b+c < 25 时默认改用精确二项检验（Sheskin 2011 建议）。
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

from scipy import stats


# ---------------------------------------------------------------------------
# 分布工具（scipy）
# ---------------------------------------------------------------------------

def _chi2_sf(x: float, df: float) -> float:
    """χ² 分布上尾 P(X > x)，df 自由度。"""
    if x <= 0 or df <= 0:
        return 1.0 if x <= 0 else 0.0
    return float(stats.chi2.sf(x, df))


def _binom_two_tailed_p(b: int, c: int) -> float:
    """McNemar 精确检验的双尾 p：不一致对在 H0 下 b ~ Binomial(b+c, 0.5)。

    双尾 p = 2 · P(X ≤ min(b, c))，封顶 1.0；无不一致对时 p = 1。
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(2.0 * tail, 1.0)


def _holm_adjust(pvals: list[float]) -> list[float]:
    """Holm (1979) 逐步降低 FWER 校正；返回与输入同序的校正 p 值（单调非降）。"""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    prev = 0.0
    for rank, idx in enumerate(order):
        val = min((m - rank) * pvals[idx], 1.0)
        val = max(val, prev)
        adj[idx] = val
        prev = val
    return adj


# ---------------------------------------------------------------------------
# McNemar 检验（配对二分 2×2）
# ---------------------------------------------------------------------------

def mcnemar_test(
    table: list[list[float]],
    correction: bool = True,
    exact: bool | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """McNemar 检验（同一批被试在两条件/两时点的配对二分结局）。

    table = [[a, b], [c, d]]，行=条件1（0,1），列=条件2（0,1）：
        a = 两条件均 0；b = 条件1=0 且条件2=1；c = 条件1=1 且条件2=0；d = 两条件均 1。
    仅不一致对 b、c 携带信息：检验边际比例 P(条件1=1) vs P(条件2=1) 是否相等。

    统计量：χ² = (b−c)² / (b+c)，df=1；连续性校正（Edwards 1948）χ² = (|b−c|−1)² / (b+c)。
    exact: None → 不一致对 b+c < 25 时自动用精确二项检验（Sheskin 2011）；True/False 强制。
    效应量：OR = b/c（不一致对比值）+ 边际比例差 = (b−c)/N。
    """
    if len(table) != 2 or any(len(r) != 2 for r in table):
        raise ValueError("McNemar 检验需要 2×2 配对列联表 [[a,b],[c,d]]")
    a, b, c, d = (int(table[0][0]), int(table[0][1]),
                  int(table[1][0]), int(table[1][1]))
    if min(a, b, c, d) < 0:
        raise ValueError("列联表单元格频数不能为负")
    N = a + b + c + d
    if N <= 0:
        raise ValueError("列联表总频数必须 > 0")

    n_disc = b + c
    if n_disc > 0:
        chi2 = (b - c) ** 2 / n_disc
        chi2_cc = (abs(b - c) - 1) ** 2 / n_disc
        p_chi2 = _chi2_sf(chi2, 1)
        p_chi2_cc = _chi2_sf(chi2_cc, 1)
    else:
        chi2 = chi2_cc = 0.0
        p_chi2 = p_chi2_cc = 1.0

    p_exact = _binom_two_tailed_p(b, c)

    use_exact = exact if exact is not None else (n_disc < 25)
    if use_exact:
        method = "exact_binomial"
        p = p_exact
        stat = None
    elif correction:
        method = "chi2_continuity"
        p = p_chi2_cc
        stat = chi2_cc
    else:
        method = "chi2"
        p = p_chi2
        stat = chi2

    if c == 0:
        OR: float = float("inf") if b > 0 else float("nan")
    else:
        OR = b / c

    prop1 = (c + d) / N   # P(条件1 = 1) = 行1合计
    prop2 = (b + d) / N   # P(条件2 = 1) = 列1合计
    prop_diff = (b - c) / N

    return {
        "test": "McNemar",
        "a": a, "b": b, "c": c, "d": d,
        "N": N,
        "n_discordant": n_disc,
        "chi2": round(chi2, 4),
        "chi2_corrected": round(chi2_cc, 4),
        "statistic": round(stat, 4) if stat is not None else None,
        "df": 1,
        "method": method,
        "p": round(p, 6),
        "p_exact": round(p_exact, 6),
        "p_chi2": round(p_chi2, 6),
        "p_chi2_corrected": round(p_chi2_cc, 6),
        "OR": round(OR, 4) if math.isfinite(OR) else str(OR),
        "prop1": round(prop1, 4),
        "prop2": round(prop2, 4),
        "prop_diff": round(prop_diff, 4),
        "alpha": alpha,
        "significant": p < alpha,
        "correction": correction,
    }


# ---------------------------------------------------------------------------
# Cochran's Q（k≥3 重复测量二分）
# ---------------------------------------------------------------------------

def _coerce_binary(value: Any, where: str) -> int:
    """把单值强制为 0/1，否则报错。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where} 含非数值 '{value}'；Cochran's Q 要求二分(0/1)数据")
    if v == 0.0:
        return 0
    if v == 1.0:
        return 1
    raise ValueError(f"{where} 含非二分值 {value}；Cochran's Q 仅接受 0 / 1")


def cochran_q(
    conditions: dict[str, list[float]],
    alpha: float = 0.05,
    post_hoc: bool = False,
) -> dict[str, Any]:
    """Cochran's Q 检验（重复测量单因素 ANOVA 二分结局的非参数推广）。

    conditions: {条件名: [被试1, 被试2, ...]}，各列须等长（同一批被试在所有条件下均有
    0/1 评分），至少 3 个条件（2 个条件请用 McNemar）、至少 2 名被试。

    统计量：Q = (k−1)[k·Σ C_j² − N²] / [k·N − Σ R_i²]，df = k−1，
    其中 C_j = 各条件成功数（列和）、R_i = 各被试成功数（行和）、N = 总成功数。
    全 0 / 全 1 行对分母贡献 R_i(k−R_i)=0，自动不计入（与理论一致）。
    k=2 时代数化简退化为未校正 McNemar χ²。

    返回 Q/df/p + 各条件成功比例；post_hoc=True 时附成对 McNemar（Holm 校正）。
    """
    k = len(conditions)
    if k < 3:
        raise ValueError(
            f"Cochran's Q 至少需要 3 个相关条件（当前 {k}）；2 个条件请用 McNemar"
        )
    names = list(conditions.keys())
    cols = [conditions[name] for name in names]
    n = len(cols[0])
    if any(len(col) != n for col in cols):
        raise ValueError("各条件的观测数必须相等（同一批被试须在所有条件下均有评分）")
    if n < 2:
        raise ValueError(f"Cochran's Q 至少需要 2 名被试（当前 n={n}）")

    # n×k 二分矩阵（逐被试一行）
    data = [
        [_coerce_binary(cols[j][i], f"条件 '{names[j]}'") for j in range(k)]
        for i in range(n)
    ]

    C = [sum(data[i][j] for i in range(n)) for j in range(k)]   # 列和（各条件成功数）
    R = [sum(data[i][j] for j in range(k)) for i in range(n)]   # 行和（各被试成功数）
    N = sum(C)
    sum_C2 = sum(cj * cj for cj in C)
    sum_R2 = sum(ri * ri for ri in R)

    denom = k * N - sum_R2
    if denom <= 0:
        # 所有被试行恒定（全 0 或全 k）→ 无被试内变异，退化
        Q = 0.0
        p = 1.0
    else:
        Q = (k - 1) * (k * sum_C2 - N * N) / denom
        p = _chi2_sf(Q, k - 1)

    df = k - 1
    condition_stats = [
        {
            "name": names[j],
            "n": n,
            "n_success": C[j],
            "proportion": round(C[j] / n, 4) if n > 0 else 0.0,
        }
        for j in range(k)
    ]

    result: dict[str, Any] = {
        "test": "Cochran Q",
        "Q": round(Q, 4),
        "df": df,
        "p": round(p, 6),
        "n": n,
        "k": k,
        "N_success": N,
        "alpha": alpha,
        "significant": p < alpha,
        "condition_stats": condition_stats,
    }

    if post_hoc:
        result["post_hoc"] = _cochran_post_hoc(names, data, alpha)

    return result


def _cochran_post_hoc(
    names: list[str],
    data: list[list[int]],
    alpha: float,
) -> list[dict[str, Any]]:
    """Cochran's Q 显著后的成对 McNemar 事后比较（Holm 校正）。"""
    n = len(data)
    k = len(names)
    pairs: list[dict[str, Any]] = []
    raw: list[float] = []
    for x in range(k):
        for y in range(x + 1, k):
            a = b = c = d = 0
            for i in range(n):
                vx, vy = data[i][x], data[i][y]
                if vx == 0 and vy == 0:
                    a += 1
                elif vx == 0 and vy == 1:
                    b += 1
                elif vx == 1 and vy == 0:
                    c += 1
                else:
                    d += 1
            res = mcnemar_test([[a, b], [c, d]], alpha=alpha)
            raw.append(res["p"])
            pairs.append({
                "cond1": names[x],
                "cond2": names[y],
                "b": b,
                "c": c,
                "method": res["method"],
                "p_raw": round(res["p"], 6),
            })
    adj = _holm_adjust(raw)
    for pr, ap in zip(pairs, adj):
        pr["p_holm"] = round(ap, 6)
        pr["significant"] = ap < alpha
    return pairs


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None:
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".lstrip("0")


_METHOD_LABELS = {
    "exact_binomial": "精确二项检验",
    "chi2_continuity": "连续性校正 χ²",
    "chi2": "χ²",
}


def format_apa_paircat(result: dict[str, Any]) -> str:
    """生成 APA-7 配对/重复测量二分检验段落。"""
    test = result["test"]
    p = result.get("p")
    p_str = _fmt_p(p)
    sig_str = "达到统计显著性" if result.get("significant") else "未达到统计显著性"

    lines: list[str] = []
    if test == "McNemar":
        N = result["N"]
        b, c = result["b"], result["c"]
        method = result.get("method", "chi2")
        OR = result.get("OR")
        OR_str = f"{OR:.3f}" if isinstance(OR, (int, float)) else str(OR)
        prop1, prop2 = result.get("prop1"), result.get("prop2")
        if method == "exact_binomial":
            lines.append(
                f"McNemar 精确检验（二项）结果显示，不一致对 *b* = {b}、*c* = {c}，"
                f"*p* {p_str}（双尾，*N* = {N}），{sig_str}。"
            )
        else:
            stat = result.get("statistic", 0.0)
            label = _METHOD_LABELS.get(method, "χ²")
            lines.append(
                f"McNemar 检验（{label}）结果显示，*χ*²(1, *N* = {N}) = {stat:.2f}，"
                f"*p* {p_str}，{sig_str}。"
            )
        lines.append(
            f"两条件阳性比例分别为 {prop1:.3f} 与 {prop2:.3f}"
            f"（差异 = {result.get('prop_diff'):+.3f}），不一致对比值 OR = {OR_str}。"
        )

    elif test == "Cochran Q":
        Q = result.get("Q", 0.0)
        df = result.get("df")
        n = result.get("n")
        k = result.get("k")
        lines.append(
            f"Cochran's *Q* 检验结果显示，{k} 个相关条件间，"
            f"*Q*({df}, *N* = {n}) = {Q:.2f}，*p* {p_str}，{sig_str}。"
        )
        cs = result.get("condition_stats", [])
        if cs:
            props = "、".join(f"{c['name']} = {c['proportion']:.3f}" for c in cs)
            lines.append(f"各条件阳性比例：{props}。")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_paircat_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
    filename: str = "paircat_report",
) -> tuple[pathlib.Path, pathlib.Path]:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    test_labels = {"McNemar": "McNemar 检验", "Cochran Q": "Cochran's Q 检验"}
    label = test_labels.get(result.get("test", ""), "配对二分检验")
    lines = [f"# 配对/重复测量二分检验报告：{label}", "", format_apa_paircat(result)]

    if result.get("test") == "McNemar":
        lines += ["", "## 配对 2×2 列联表", "",
                  "| 条件1 \\ 条件2 | 0 | 1 |",
                  "|---|---|---|",
                  f"| 0 | {result['a']} | {result['b']} |",
                  f"| 1 | {result['c']} | {result['d']} |"]

    if "condition_stats" in result:
        lines += ["", "## 各条件描述统计", "",
                  "| 条件 | *n* | 阳性数 | 阳性比例 |",
                  "|------|-----|--------|----------|"]
        for c in result["condition_stats"]:
            lines.append(
                f"| {c['name']} | {c['n']} | {c['n_success']} | {c['proportion']} |"
            )

    if result.get("post_hoc"):
        lines += ["", "## 事后两两比较（成对 McNemar，Holm 校正）", "",
                  "| 比较 | *b* | *c* | 方法 | *p*(原始) | *p*(Holm) | 显著 |",
                  "|------|-----|-----|------|-----------|-----------|------|"]
        for ph in result["post_hoc"]:
            sig = "✓" if ph.get("significant") else ""
            method = _METHOD_LABELS.get(ph.get("method", ""), ph.get("method", ""))
            lines.append(
                f"| {ph['cond1']} vs {ph['cond2']} | {ph['b']} | {ph['c']} | "
                f"{method} | {_fmt_p(ph['p_raw'])} | {_fmt_p(ph['p_holm'])} | {sig} |"
            )

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

def analyze_paircat(
    csv_path: str,
    test: str,
    cond1_col: str | None = None,
    cond2_col: str | None = None,
    conditions: str | list[str] | None = None,
    correction: bool = True,
    exact: bool | None = None,
    post_hoc: bool = False,
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行配对/重复测量二分检验。

    test: 'mcnemar'（两二分列）| 'cochran'（≥3 二分列）。
    宽表格式：每行一名被试，各条件为单独 0/1 列。完整案例筛选（任一条件列缺失/非二分则排除）。
    """
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    test = test.lower()

    if test == "mcnemar":
        if not cond1_col or not cond2_col:
            raise ValueError("McNemar 检验需要 --cond1 与 --cond2 参数（两个二分列名）")
        a = b = c = d = 0
        n_excluded = 0
        for row in rows:
            r1 = (row.get(cond1_col) or "").strip()
            r2 = (row.get(cond2_col) or "").strip()
            try:
                v1 = _coerce_binary(r1, "条件1")
                v2 = _coerce_binary(r2, "条件2")
            except ValueError:
                n_excluded += 1
                continue
            if v1 == 0 and v2 == 0:
                a += 1
            elif v1 == 0 and v2 == 1:
                b += 1
            elif v1 == 1 and v2 == 0:
                c += 1
            else:
                d += 1
        result = mcnemar_test([[a, b], [c, d]], correction=correction,
                              exact=exact, alpha=alpha)
        result["cond1"] = cond1_col
        result["cond2"] = cond2_col
        result["n_excluded"] = n_excluded

    elif test == "cochran":
        if not conditions:
            raise ValueError(
                "Cochran's Q 需要 --conditions 参数（≥3 个二分列名，逗号分隔）"
            )
        if isinstance(conditions, str):
            cond_cols = [c.strip() for c in conditions.split(",") if c.strip()]
        else:
            cond_cols = [str(c).strip() for c in conditions if str(c).strip()]
        if len(cond_cols) < 3:
            raise ValueError(
                f"Cochran's Q 至少需要 3 个条件列（当前 {len(cond_cols)}）；"
                f"2 个条件请用 mcnemar"
            )
        cond_data: dict[str, list[float]] = {c: [] for c in cond_cols}
        n_excluded = 0
        for row in rows:
            vals: dict[str, int] = {}
            ok = True
            for c in cond_cols:
                raw = (row.get(c) or "").strip()
                try:
                    vals[c] = _coerce_binary(raw, f"条件 '{c}'")
                except ValueError:
                    ok = False
                    break
            if ok:
                for c in cond_cols:
                    cond_data[c].append(vals[c])
            else:
                n_excluded += 1
        result = cochran_q(cond_data, alpha=alpha, post_hoc=post_hoc)
        result["conditions"] = cond_cols
        result["n_excluded"] = n_excluded

    else:
        raise ValueError(f"未知检验类型 '{test}'，可选：mcnemar | cochran")

    result["input_file"] = csv_path

    if write_files:
        fname = f"paircat_{test}_report"
        md_path, json_path = write_paircat_report(result, out_dir=out_dir, filename=fname)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def paircat_cli(args: list[str]) -> int:
    """psyclaw paired-cat <data.csv> --test mcnemar|cochran [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw paired-cat",
        description="配对/重复测量二分检验：McNemar / Cochran's Q",
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument(
        "--test",
        required=True,
        choices=["mcnemar", "cochran"],
        help="检验类型：mcnemar（配对两条件）| cochran（≥3 重复测量条件）",
    )
    parser.add_argument("--cond1", dest="cond1_col", default=None,
                        help="第一个二分列名（mcnemar 必需）")
    parser.add_argument("--cond2", dest="cond2_col", default=None,
                        help="第二个二分列名（mcnemar 必需）")
    parser.add_argument("--conditions", default=None,
                        help="重复测量条件列名，逗号分隔（cochran 必需，≥3 列）")
    parser.add_argument("--no-correction", dest="correction", action="store_false",
                        help="mcnemar 关闭连续性校正（默认开启）")
    parser.add_argument("--exact", dest="exact", action="store_true", default=None,
                        help="mcnemar 强制使用精确二项检验")
    parser.add_argument("--post-hoc", dest="post_hoc", action="store_true",
                        help="cochran 显著后做成对 McNemar 事后比较（Holm 校正）")
    parser.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    try:
        result = analyze_paircat(
            csv_path=opts.csv_file,
            test=opts.test,
            cond1_col=opts.cond1_col,
            cond2_col=opts.cond2_col,
            conditions=opts.conditions,
            correction=opts.correction,
            exact=opts.exact,
            post_hoc=opts.post_hoc,
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
    print(format_apa_paircat(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
