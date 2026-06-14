"""等价检验 — TOST (Two One-Sided Tests) 两单侧检验框架（stdlib only）。

支持:
  - 双样本独立等价检验（Welch t）
  - 单样本等价检验（与已知参考值比）
  - 配对样本等价检验

理论依据:
  Schuirmann, D. J. (1987). A comparison of the two one-sided tests procedure and the
    power approach for assessing the equivalence of average bioavailability.
    Journal of Pharmacokinetics and Biopharmaceutics, 15(6), 657–680.
  Lakens, D. (2017). Equivalence tests: A practical primer for t tests, correlations,
    and meta-analyses. Social Psychological and Personality Science, 8(4), 355–362.
  Lakens, D., Scheel, A. M., & Isager, P. M. (2018). Equivalence testing for
    psychological research: A tutorial. Advances in Methods and Practices in
    Psychological Science, 1(2), 259–269.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from psyclaw.psych.stats_core import norm_ppf, t_ppf, t_sf2


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _one_tail_right(t: float, df: float) -> float:
    """P(T_{df} > t)，单尾右侧概率。
    利用 t_sf2(t, df) = P(|T| > |t|) = 2*P(T > t) 对 t≥0 的对称性。
    """
    if t >= 0:
        return t_sf2(t, df) / 2.0
    else:
        return 1.0 - t_sf2(-t, df) / 2.0


def _variance(values: list[float]) -> float:
    """样本方差（n-1 分母）。"""
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return sum((x - m) ** 2 for x in values) / (n - 1)


def _welch_df(var1: float, n1: int, var2: float, n2: int) -> float:
    """Welch-Satterthwaite 近似自由度。"""
    a = var1 / n1
    b = var2 / n2
    num = (a + b) ** 2
    den = a**2 / (n1 - 1) + b**2 / (n2 - 1)
    return num / den if den > 0 else float("nan")


def _pooled_sd(values1: list[float], values2: list[float]) -> float:
    """汇合 SD（等方差假设，用于 Cohen's d 计算）。"""
    n1, n2 = len(values1), len(values2)
    mean1 = sum(values1) / n1
    mean2 = sum(values2) / n2
    ss1 = sum((x - mean1) ** 2 for x in values1)
    ss2 = sum((x - mean2) ** 2 for x in values2)
    return math.sqrt((ss1 + ss2) / (n1 + n2 - 2)) if n1 + n2 > 2 else 0.0


def _fmt_p(p: float) -> str:
    if p < 0.001:
        return "< .001"
    s = f"{p:.3f}"
    return f"= {s.lstrip('0') or '0'}"


def _fmt2(v: float) -> str:
    return f"{v:.2f}"


# ---------------------------------------------------------------------------
# 核心检验
# ---------------------------------------------------------------------------

def tost_two_sample(
    y1: list[float],
    y2: list[float],
    lower_bound: float,
    upper_bound: float,
    alpha: float = 0.05,
) -> dict:
    """双样本独立 TOST 等价检验（Welch t）。

    等价区间 [lower_bound, upper_bound] 单位与原始均值差相同。
    Lakens (2017) 推荐：等价成立当且仅当 (1-2α) CI ⊆ [lower_bound, upper_bound]。

    返回 dict，含:
      test / n1 / n2 / mean1 / mean2 / mean_diff / se / df /
      t_lower / t_upper / p_lower / p_upper / p_tost /
      ci_lower / ci_upper / ci_level / cohen_d / pooled_sd /
      alpha / equivalent / equivalence_tested
    """
    if len(y1) < 3 or len(y2) < 3:
        return {"error": "每组需至少 3 个观测值"}
    if lower_bound >= upper_bound:
        return {"error": "等价区间无效：lower_bound 必须小于 upper_bound"}

    n1, n2 = len(y1), len(y2)
    mean1 = sum(y1) / n1
    mean2 = sum(y2) / n2
    var1 = _variance(y1)
    var2 = _variance(y2)
    mean_diff = mean1 - mean2

    se = math.sqrt(var1 / n1 + var2 / n2)
    if se == 0:
        return {"error": "零方差：无法计算 SE"}

    df = _welch_df(var1, n1, var2, n2)

    # H01: diff ≤ lower_bound  →  reject if T_lower 足够大（右尾）
    t_lower = (mean_diff - lower_bound) / se
    p_lower = _one_tail_right(t_lower, df)

    # H02: diff ≥ upper_bound  →  reject if T_upper 足够小（左尾）
    t_upper = (mean_diff - upper_bound) / se
    p_upper = 1.0 - _one_tail_right(t_upper, df)

    p_tost = max(p_lower, p_upper)
    equivalent = bool(p_tost < alpha)

    # (1-2α) CI：α=0.05 时为 90% CI（Lakens, 2017）
    ci_level = 1.0 - 2.0 * alpha
    t_crit = t_ppf(1.0 - alpha, df)
    ci_lower = mean_diff - t_crit * se
    ci_upper = mean_diff + t_crit * se

    pooled = _pooled_sd(y1, y2)
    cohen_d = mean_diff / pooled if pooled > 0 else float("nan")

    return {
        "test": "tost_two_sample",
        "n1": n1, "n2": n2,
        "mean1": mean1, "mean2": mean2,
        "sd1": math.sqrt(var1), "sd2": math.sqrt(var2),
        "mean_diff": mean_diff,
        "se": se,
        "df": df,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "t_lower": t_lower,
        "t_upper": t_upper,
        "p_lower": p_lower,
        "p_upper": p_upper,
        "p_tost": p_tost,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "ci_level": ci_level,
        "cohen_d": cohen_d,
        "pooled_sd": pooled,
        "alpha": alpha,
        "equivalent": equivalent,
        "equivalence_tested": True,
    }


def tost_one_sample(
    y: list[float],
    mu0: float,
    lower_bound: float,
    upper_bound: float,
    alpha: float = 0.05,
) -> dict:
    """单样本 TOST：检验样本均值 μ 是否等价于已知参考值 mu0。"""
    if len(y) < 3:
        return {"error": "需至少 3 个观测值"}
    if lower_bound >= upper_bound:
        return {"error": "等价区间无效：lower_bound 必须小于 upper_bound"}

    n = len(y)
    mean_y = sum(y) / n
    var_y = _variance(y)
    se = math.sqrt(var_y / n)
    if se == 0:
        return {"error": "零方差：无法计算 SE"}

    df = n - 1
    mean_diff = mean_y - mu0

    t_lower = (mean_diff - lower_bound) / se
    t_upper = (mean_diff - upper_bound) / se
    p_lower = _one_tail_right(t_lower, df)
    p_upper = 1.0 - _one_tail_right(t_upper, df)
    p_tost = max(p_lower, p_upper)
    equivalent = bool(p_tost < alpha)

    ci_level = 1.0 - 2.0 * alpha
    t_crit = t_ppf(1.0 - alpha, df)
    ci_lower = mean_diff - t_crit * se
    ci_upper = mean_diff + t_crit * se

    cohen_d = mean_diff / math.sqrt(var_y) if var_y > 0 else float("nan")

    return {
        "test": "tost_one_sample",
        "n": n,
        "mean_y": mean_y,
        "mu0": mu0,
        "mean_diff": mean_diff,
        "se": se,
        "df": df,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "t_lower": t_lower,
        "t_upper": t_upper,
        "p_lower": p_lower,
        "p_upper": p_upper,
        "p_tost": p_tost,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "ci_level": ci_level,
        "cohen_d": cohen_d,
        "alpha": alpha,
        "equivalent": equivalent,
        "equivalence_tested": True,
    }


def tost_paired(
    y1: list[float],
    y2: list[float],
    lower_bound: float,
    upper_bound: float,
    alpha: float = 0.05,
) -> dict:
    """配对样本 TOST（差值的单样本等价检验，参考值 mu0=0）。"""
    if len(y1) != len(y2):
        return {"error": f"y1 和 y2 长度不一致：{len(y1)} vs {len(y2)}"}
    diffs = [a - b for a, b in zip(y1, y2)]
    result = tost_one_sample(diffs, 0.0, lower_bound, upper_bound, alpha)
    if "error" in result:
        return result
    result["test"] = "tost_paired"
    result["n_pairs"] = len(diffs)
    return result


def compute_mdes(
    n1: int,
    n2: int | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """等价检验最小可探测效应量（MDES，Cohen's d 单位；大样本正态近似）。

    参考 Lakens (2017)：ncp = z_{1-alpha} + z_{power}，MDES = ncp × SE。
    含义：若等价区间 = ±MDES，则在给定 alpha/power 下，TOST 恰好有 power 的把握
    在 diff=0 时建立等价性。
    """
    if n2 is None:
        n2 = n1
    se = math.sqrt(1.0 / n1 + 1.0 / n2)
    z_alpha = norm_ppf(1.0 - alpha)    # ≈1.645 for alpha=.05
    z_power = norm_ppf(power)          # ≈0.842 for power=.80
    return abs((z_alpha + z_power) * se)


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------

def format_apa_equivalence(result: dict) -> str:
    """生成 APA-7 等价检验报告段落（Lakens, 2017 格式）。"""
    if "error" in result:
        return f"[等价检验错误: {result['error']}]"

    test = result.get("test", "tost_two_sample")
    lb, ub = result["lower_bound"], result["upper_bound"]
    diff = result["mean_diff"]
    ci_lo, ci_hi = result["ci_lower"], result["ci_upper"]
    ci_lvl = int(round(result["ci_level"] * 100))
    p_tost = result["p_tost"]
    equiv = result["equivalent"]
    d = result.get("cohen_d", float("nan"))
    alpha = result["alpha"]

    if test == "tost_two_sample":
        n1, n2 = result["n1"], result["n2"]
        df = result["df"]
        t_lo, t_up = result["t_lower"], result["t_upper"]
        sample_info = f"两独立样本（*n*₁ = {n1}，*n*₂ = {n2}）"
        diff_info = f"均值差 Δ*M* = {_fmt2(diff)}"
    elif test == "tost_one_sample":
        n = result["n"]
        mu0 = result["mu0"]
        df = result["df"]
        t_lo, t_up = result["t_lower"], result["t_upper"]
        sample_info = f"单样本（*n* = {n}，参考值 μ₀ = {_fmt2(mu0)}）"
        diff_info = f"偏差 Δ = {_fmt2(diff)}"
    else:  # paired
        n = result.get("n_pairs", result.get("n", "?"))
        df = result["df"]
        t_lo, t_up = result["t_lower"], result["t_upper"]
        sample_info = f"配对样本（*n*对 = {n}）"
        diff_info = f"配对差值均值 *M*_diff = {_fmt2(diff)}"

    stat_str = (
        f"*t*_lower({_fmt2(df)}) = {_fmt2(t_lo)}，*p* {_fmt_p(result['p_lower'])}；"
        f"*t*_upper({_fmt2(df)}) = {_fmt2(t_up)}，*p* {_fmt_p(result['p_upper'])}；"
        f"*p*_TOST {_fmt_p(p_tost)}。"
    )
    ci_str = f"{ci_lvl}% CI [{_fmt2(ci_lo)}, {_fmt2(ci_hi)}]"
    d_str = f"{d:.2f}" if not (isinstance(d, float) and math.isnan(d)) else "N/A"

    bound_str = f"[{_fmt2(lb)}, {_fmt2(ub)}]"
    if equiv:
        conclusion = (
            f"以 {bound_str} 为等价区间，{sample_info}的{diff_info}（{ci_str}）完全落入等价区间，"
            f"可在 α = {alpha} 水平上建立统计等价性（TOST：{stat_str}）"
            f"效应量 Cohen's *d* = {d_str}（Lakens, 2017；Schuirmann, 1987）。"
        )
    else:
        conclusion = (
            f"以 {bound_str} 为等价区间，{sample_info}的{diff_info}（{ci_str}）未完全落入等价区间，"
            f"未能在 α = {alpha} 水平上建立统计等价性（TOST：{stat_str}）"
            f"效应量 Cohen's *d* = {d_str}（Lakens, 2017；Schuirmann, 1987）。"
        )

    return conclusion


def write_equivalence_report(result: dict, out_dir: str | None = None) -> dict[str, Path]:
    """将等价检验结果写入 notes/ 目录（MD + JSON sidecar）。"""
    out = Path(out_dir) if out_dir else Path("notes")
    out.mkdir(parents=True, exist_ok=True)

    md_path = out / "equivalence_report.md"
    json_path = out / "equivalence_report.json"

    apa = format_apa_equivalence(result)
    equiv = result.get("equivalent", False)
    verdict = "等价成立" if equiv else "等价不成立（或证据不足）"

    lb = result.get("lower_bound", "?")
    ub = result.get("upper_bound", "?")
    p_tost = result.get("p_tost", float("nan"))
    ci_lo = result.get("ci_lower", float("nan"))
    ci_hi = result.get("ci_upper", float("nan"))
    ci_lvl = int(round(result.get("ci_level", 0.90) * 100))
    d = result.get("cohen_d", float("nan"))

    lines = [
        "# 等价检验报告（TOST — Two One-Sided Tests）",
        "",
        f"**结论**: {verdict}",
        "",
        "## APA-7 段落",
        "",
        apa,
        "",
        "## 关键参数",
        "",
        f"- 等价区间: [{lb:.3f}, {ub:.3f}]" if isinstance(lb, float) else f"- 等价区间: [{lb}, {ub}]",
        f"- α = {result.get('alpha', 0.05)}",
        f"- *p*_TOST = {p_tost:.4f}",
        f"- CI ({ci_lvl}%): [{ci_lo:.4f}, {ci_hi:.4f}]",
    ]
    if not (isinstance(d, float) and math.isnan(d)):
        lines.append(f"- Cohen's *d* = {d:.3f}")

    lines.extend([
        "",
        "## 引文",
        "",
        "Lakens, D. (2017). Equivalence tests: A practical primer for *t* tests, correlations, "
        "and meta-analyses. *Social Psychological and Personality Science*, *8*(4), 355–362. "
        "https://doi.org/10.1177/1948550617697177",
        "",
        "Lakens, D., Scheel, A. M., & Isager, P. M. (2018). Equivalence testing for "
        "psychological research: A tutorial. *Advances in Methods and Practices in Psychological "
        "Science*, *1*(2), 259–269. https://doi.org/10.1177/2515245918770963",
        "",
        "Schuirmann, D. J. (1987). A comparison of the two one-sided tests procedure and the "
        "power approach for assessing the equivalence of average bioavailability. "
        "*Journal of Pharmacokinetics and Biopharmaceutics*, *15*(6), 657–680. "
        "https://doi.org/10.1007/BF01059553",
    ])

    md_path.write_text("\n".join(lines), encoding="utf-8")

    def _safe(v):
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    safe_result = {k: _safe(v) for k, v in result.items()}
    safe_result["apa_text"] = apa
    json_path.write_text(
        json.dumps(safe_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"md": md_path, "json": json_path}


# ---------------------------------------------------------------------------
# CSV 加载
# ---------------------------------------------------------------------------

def _load_csv(path: str) -> tuple[list[str], list[dict]]:
    """读 CSV，缺失值统一为 None。"""
    p = Path(path)
    rows: list[dict] = []
    headers: list[str] = []
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                v = (v or "").strip()
                cleaned[k] = None if v in ("", "NA", "NaN", "N/A", "nan") else v
            rows.append(cleaned)
    return headers, rows


def _get_float(row: dict, col: str) -> float | None:
    v = row.get(col)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def analyze_equivalence(
    csv_path: str,
    dv: str,
    group: str | None = None,
    lower_bound: float = -0.5,
    upper_bound: float = 0.5,
    alpha: float = 0.05,
    mu0: float | None = None,
    paired: bool = False,
    out_dir: str | None = None,
    json_out: bool = False,
) -> dict:
    """从 CSV 数据运行 TOST 等价检验（CLI 主入口）。

    - group 指定分组列（双样本/配对），需恰好 2 个水平。
    - mu0 指定参考值（单样本，与 group 互斥）。
    - paired=True 时 group 两水平视为配对（每组等量观测）。
    - out_dir 非 None 时写 notes/equivalence_report.{md,json}。
    """
    headers, rows = _load_csv(csv_path)

    if dv not in headers:
        return {"error": f"列 {dv!r} 不在数据中。可用列: {headers}"}

    if mu0 is not None:
        values = [_get_float(r, dv) for r in rows if _get_float(r, dv) is not None]
        result = tost_one_sample(values, mu0, lower_bound, upper_bound, alpha)

    elif group is not None:
        if group not in headers:
            return {"error": f"分组列 {group!r} 不在数据中。可用列: {headers}"}
        # 按出现顺序收集水平
        levels: list[str] = []
        seen: set[str] = set()
        for r in rows:
            g = r.get(group)
            if g and g not in seen:
                seen.add(g)
                levels.append(g)
        if len(levels) != 2:
            return {
                "error": f"需要 {group!r} 列恰好有 2 个水平，实际: {levels[:10]}"
            }
        g1 = [v for r in rows if r.get(group) == levels[0]
              if (v := _get_float(r, dv)) is not None]
        g2 = [v for r in rows if r.get(group) == levels[1]
              if (v := _get_float(r, dv)) is not None]

        if paired:
            result = tost_paired(g1, g2, lower_bound, upper_bound, alpha)
        else:
            result = tost_two_sample(g1, g2, lower_bound, upper_bound, alpha)

    else:
        return {"error": "需提供 --group（双样本/配对）或 --one-sample <mu0>（单样本）"}

    if "error" in result:
        return result

    if out_dir is not None:
        write_equivalence_report(result, out_dir)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def equivalence_cli(argv: list[str] | None = None) -> int:
    import argparse

    from psyclaw import ui

    parser = argparse.ArgumentParser(
        prog="psyclaw tost",
        description=(
            "TOST 等价检验（Two One-Sided Tests；Lakens, 2017）\n"
            "  双样本: psyclaw tost data.csv --dv score --group cond "
            "--lower -0.5 --upper 0.5\n"
            "  单样本: psyclaw tost data.csv --dv score --one-sample 50 "
            "--lower -5 --upper 5"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv", help="CSV 数据文件")
    parser.add_argument("--dv", required=True, help="因变量列名")
    parser.add_argument("--group", default=None,
                        help="分组列名（双样本/配对；需恰好 2 个水平）")
    parser.add_argument("--lower", type=float, required=True,
                        help="等价区间下界（原始均值差单位，如 -0.5）")
    parser.add_argument("--upper", type=float, required=True,
                        help="等价区间上界（原始均值差单位，如 0.5）")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 0.05）")
    parser.add_argument("--one-sample", type=float, default=None, dest="mu0",
                        metavar="MU0", help="参考均值（单样本模式，与 --group 互斥）")
    parser.add_argument("--paired", action="store_true", help="配对样本模式")
    parser.add_argument("--out", default=None,
                        help="sidecar 输出目录（写 notes/equivalence_report.*）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv or [])

    result = analyze_equivalence(
        args.csv, args.dv,
        group=args.group,
        lower_bound=args.lower,
        upper_bound=args.upper,
        alpha=args.alpha,
        mu0=args.mu0,
        paired=args.paired,
        out_dir=args.out,
        json_out=args.json,
    )

    if "error" in result:
        print(ui.err(f"错误: {result['error']}"))
        return 1

    equiv = result["equivalent"]
    test_type = result.get("test", "tost_two_sample")

    print(ui.title("TOST 等价检验"))
    print(ui.rule())
    print(f"数据: {args.csv}  |  因变量: {args.dv}")

    if test_type == "tost_two_sample":
        print(
            f"检验类型: 双样本独立  |  "
            f"n₁={result['n1']}，n₂={result['n2']}"
        )
        print(
            f"M₁={result['mean1']:.3f} (SD={result['sd1']:.3f})，"
            f"M₂={result['mean2']:.3f} (SD={result['sd2']:.3f})"
        )
        print(
            f"均值差 ΔM = {result['mean_diff']:.4f}  |  "
            f"SE = {result['se']:.4f}  |  df = {result['df']:.1f}"
        )
    elif test_type == "tost_one_sample":
        print(
            f"检验类型: 单样本  |  n={result['n']}  |  "
            f"参考值 μ₀={result['mu0']:.3f}"
        )
        print(
            f"样本均值 M = {result['mean_y']:.4f}，"
            f"偏差 Δ = {result['mean_diff']:.4f}  |  "
            f"SE = {result['se']:.4f}  |  df = {result['df']}"
        )
    else:  # paired
        n_pairs = result.get("n_pairs", result.get("n", "?"))
        print(f"检验类型: 配对样本  |  n对 = {n_pairs}")
        print(
            f"配对差值均值 M_diff = {result['mean_diff']:.4f}  |  "
            f"SE = {result['se']:.4f}  |  df = {result['df']}"
        )

    print()
    print(f"等价区间: [{args.lower:.3f}, {args.upper:.3f}]  |  α = {args.alpha}")
    print(
        f"t_lower = {result['t_lower']:.4f},  p_lower {_fmt_p(result['p_lower'])}"
    )
    print(
        f"t_upper = {result['t_upper']:.4f},  p_upper {_fmt_p(result['p_upper'])}"
    )
    print(f"p_TOST  = {result['p_tost']:.4f}")

    ci_lvl = int(round(result["ci_level"] * 100))
    print(
        f"\n{ci_lvl}% CI: [{result['ci_lower']:.4f}, {result['ci_upper']:.4f}]"
    )
    d = result.get("cohen_d", float("nan"))
    if not (isinstance(d, float) and math.isnan(d)):
        print(f"Cohen's d = {d:.4f}")

    # MDES 提示
    if test_type in ("tost_two_sample",):
        mdes = compute_mdes(result["n1"], result["n2"], args.alpha)
    elif test_type in ("tost_paired", "tost_one_sample"):
        n = result.get("n_pairs", result.get("n", 30))
        mdes = compute_mdes(n, n, args.alpha) / math.sqrt(2) if test_type == "tost_paired" else compute_mdes(n, n, args.alpha)
    else:
        mdes = None

    if mdes is not None:
        print(ui.dim(f"\n当前样本量下等价检验 MDES（power=.80）: ±{mdes:.4f}（原始单位）"))

    verdict_str = ui.ok("等价成立 ✓") if equiv else ui.warn("等价不成立（或证据不足）✗")
    print(f"\n结论: {verdict_str}")

    if args.json:
        import json as _json
        def _safe(v):
            if isinstance(v, float) and math.isnan(v):
                return None
            return v
        safe = {k: _safe(v) for k, v in result.items()}
        safe["apa_text"] = format_apa_equivalence(result)
        print(_json.dumps(safe, ensure_ascii=False, indent=2))

    if args.out:
        files = write_equivalence_report(result, args.out)
        print(ui.ok(f"\n✓ sidecar 已写出: {files['md']}, {files['json']}"))

    return 0
