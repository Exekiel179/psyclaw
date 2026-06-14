"""效应量转换器 — Cohen's d / r / eta² / f / phi / OR（stdlib only）。

心理学报告中需要在不同效应量指标间转换（例如元分析整合、功效分析计划），
并对照 Cohen (1988) 约定提供 small / medium / large 言语标签。

转换公式：
  d ↔ r   Cohen (1988): r = d/√(d²+4), d = 2r/√(1-r²)
  d ↔ f   f = d/2 (两组等样本), d = 2f
  d → eta²  η² = d²/(d²+4)，适用于两组等 n
  f → eta²  η² = f²/(1+f²)
  F → eta²  η² = F*df1 / (F*df1 + df2)（偏 η² 对单因素全量 η² 等价）
  t → d    独立双样本 d = t*√(1/n1+1/n2)；单样本/配对 d = t/√n
  chi² → phi  phi = √(chi²/N)；Cramér's V = phi/√(min(r,c)-1)
  OR → d   Borenstein et al. (2009): d = ln(OR)*√3/π

CLI: psyclaw effect-size --from d --to r --value 0.5
     psyclaw effect-size --compute d --m1 M1 --sd1 SD1 --n1 N1 [--m2 M2 --sd2 SD2 --n2 N2]
"""

from __future__ import annotations

import json
import math
from typing import Any


# ---------------------------------------------------------------------------
# 核心转换函数
# ---------------------------------------------------------------------------

def d_to_r(d: float) -> float:
    """Cohen's d → Pearson r（Cohen 1988，等样本双组假设）。"""
    return d / math.sqrt(d ** 2 + 4.0)


def r_to_d(r: float) -> float:
    """Pearson r → Cohen's d（Cohen 1988）。"""
    if abs(r) >= 1.0:
        return math.copysign(float("inf"), r)
    return 2.0 * r / math.sqrt(1.0 - r ** 2)


def d_to_f(d: float) -> float:
    """Cohen's d → Cohen's f（两组等 n: f = d/2）。"""
    return d / 2.0


def f_to_d(f: float) -> float:
    """Cohen's f → Cohen's d（两组等 n: d = 2f）。"""
    return 2.0 * f


def d_to_eta2(d: float) -> float:
    """Cohen's d → eta²（两组等 n：η² = d²/(d²+4)）。"""
    return d ** 2 / (d ** 2 + 4.0)


def eta2_to_d(eta2: float) -> float:
    """eta² → Cohen's d（两组等 n）。"""
    if eta2 <= 0 or eta2 >= 1:
        return float("nan")
    return math.sqrt(4.0 * eta2 / (1.0 - eta2))


def f_to_eta2(f: float) -> float:
    """Cohen's f → eta²：η² = f²/(1+f²)。"""
    return f ** 2 / (1.0 + f ** 2)


def eta2_to_f(eta2: float) -> float:
    """eta² → Cohen's f。"""
    if eta2 <= 0 or eta2 >= 1:
        return float("nan")
    return math.sqrt(eta2 / (1.0 - eta2))


def F_to_eta2(F_stat: float, df1: float, df2: float) -> float:
    """F 统计量 → eta²（偏 η²，单因素时即全量 η²）。"""
    if F_stat <= 0 or df1 <= 0 or df2 <= 0:
        return float("nan")
    return F_stat * df1 / (F_stat * df1 + df2)


def t_to_d_two_sample(t: float, n1: int, n2: int) -> float:
    """独立双样本 t → Cohen's d（Hedges' correction 未应用）。"""
    if n1 <= 0 or n2 <= 0:
        return float("nan")
    return t * math.sqrt(1.0 / n1 + 1.0 / n2)


def t_to_d_one_sample(t: float, n: int) -> float:
    """单样本/配对样本 t → Cohen's d。"""
    if n <= 0:
        return float("nan")
    return t / math.sqrt(n)


def chi2_to_phi(chi2: float, n: int) -> float:
    """卡方统计量 → phi 系数（2×2 列联表）。"""
    if n <= 0 or chi2 < 0:
        return float("nan")
    return math.sqrt(chi2 / n)


def chi2_to_cramers_v(chi2: float, n: int, k: int) -> float:
    """卡方 → Cramér's V（r×c 表，k = min(rows, cols)）。"""
    if n <= 0 or chi2 < 0 or k < 2:
        return float("nan")
    return math.sqrt(chi2 / (n * (k - 1)))


def or_to_d(odds_ratio: float) -> float:
    """Odds Ratio → Cohen's d（Borenstein et al. 2009）。"""
    if odds_ratio <= 0:
        return float("nan")
    return math.log(odds_ratio) * math.sqrt(3.0) / math.pi


def d_to_or(d: float) -> float:
    """Cohen's d → Odds Ratio（Borenstein et al. 2009 逆变换）。"""
    return math.exp(d * math.pi / math.sqrt(3.0))


# ---------------------------------------------------------------------------
# 从摘要统计计算 d（Hedges & Olkin 1985）
# ---------------------------------------------------------------------------

def cohens_d_two_group(
    m1: float, sd1: float, n1: int,
    m2: float, sd2: float, n2: int,
    pooled: bool = True,
) -> dict[str, Any]:
    """从两组摘要统计计算 Cohen's d（及 Hedges' g 偏差校正）。

    pooled=True：合并 SD（经典 Cohen's d）。
    pooled=False：仅用控制组 SD（Glass's Δ）。
    """
    if n1 < 2 or n2 < 2:
        raise ValueError(f"每组需要至少 2 人（n1={n1}, n2={n2}）")
    if sd1 < 0 or sd2 < 0:
        raise ValueError("SD 不能为负数")

    if pooled:
        sd_p = math.sqrt(((n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2) / (n1 + n2 - 2))
    else:
        sd_p = sd2  # Glass's Δ 用对照组 SD

    if sd_p == 0:
        raise ValueError("合并 SD 为 0，无法计算效应量")

    d = (m1 - m2) / sd_p

    # Hedges' g 偏差校正因子 J（近似：1 - 3/(4*(n1+n2-2)-1)）
    df = n1 + n2 - 2
    j = 1.0 - 3.0 / (4.0 * df - 1) if df > 1 else 1.0
    g = d * j

    # SE for d（近似公式）
    se_d = math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2 - 2)))
    ci_lo = d - 1.96 * se_d
    ci_hi = d + 1.96 * se_d

    return {
        "d": round(d, 4),
        "hedges_g": round(g, 4),
        "se": round(se_d, 4),
        "ci_lower_95": round(ci_lo, 4),
        "ci_upper_95": round(ci_hi, 4),
        "pooled_sd": round(sd_p, 4),
        "n1": n1, "n2": n2,
        "m1": m1, "m2": m2,
        "sd1": sd1, "sd2": sd2,
        "interpretation": interpret_d(abs(d)),
        "r": round(d_to_r(d), 4),
        "eta2": round(d_to_eta2(d), 4),
    }


def cohens_d_one_sample(
    m: float, sd: float, n: int, mu0: float = 0.0,
) -> dict[str, Any]:
    """从单样本/配对摘要统计计算 Cohen's d = (M-μ₀)/SD。"""
    if n < 2:
        raise ValueError(f"至少需要 2 个观测（n={n}）")
    if sd <= 0:
        raise ValueError("SD 必须 > 0")
    d = (m - mu0) / sd
    se_d = math.sqrt(1.0 / n + d ** 2 / (2 * (n - 1)))
    ci_lo = d - 1.96 * se_d
    ci_hi = d + 1.96 * se_d
    return {
        "d": round(d, 4),
        "se": round(se_d, 4),
        "ci_lower_95": round(ci_lo, 4),
        "ci_upper_95": round(ci_hi, 4),
        "n": n,
        "m": m, "sd": sd, "mu0": mu0,
        "interpretation": interpret_d(abs(d)),
        "r": round(d_to_r(d), 4),
        "eta2": round(d_to_eta2(d), 4),
    }


# ---------------------------------------------------------------------------
# 言语标签（Cohen 1988 约定）
# ---------------------------------------------------------------------------

def interpret_d(d: float) -> str:
    """Cohen (1988) d 约定：small ≥ .20, medium ≥ .50, large ≥ .80。"""
    ad = abs(d)
    if ad >= 0.80:
        return "大效应 (large, d ≥ 0.80)"
    if ad >= 0.50:
        return "中效应 (medium, d ≥ 0.50)"
    if ad >= 0.20:
        return "小效应 (small, d ≥ 0.20)"
    return "可忽略效应 (negligible, d < 0.20)"


def interpret_r(r: float) -> str:
    """Cohen (1988) r 约定：small ≥ .10, medium ≥ .30, large ≥ .50。"""
    ar = abs(r)
    if ar >= 0.50:
        return "大效应 (large, r ≥ 0.50)"
    if ar >= 0.30:
        return "中效应 (medium, r ≥ 0.30)"
    if ar >= 0.10:
        return "小效应 (small, r ≥ 0.10)"
    return "可忽略效应 (negligible, r < 0.10)"


def interpret_eta2(eta2: float) -> str:
    """Cohen (1988) eta² 约定：small ≥ .01, medium ≥ .06, large ≥ .14。"""
    if eta2 >= 0.14:
        return "大效应 (large, η² ≥ 0.14)"
    if eta2 >= 0.06:
        return "中效应 (medium, η² ≥ 0.06)"
    if eta2 >= 0.01:
        return "小效应 (small, η² ≥ 0.01)"
    return "可忽略效应 (negligible, η² < 0.01)"


def interpret_f(f: float) -> str:
    """Cohen (1988) f 约定：small ≥ .10, medium ≥ .25, large ≥ .40。"""
    if f >= 0.40:
        return "大效应 (large, f ≥ 0.40)"
    if f >= 0.25:
        return "中效应 (medium, f ≥ 0.25)"
    if f >= 0.10:
        return "小效应 (small, f ≥ 0.10)"
    return "可忽略效应 (negligible, f < 0.10)"


# ---------------------------------------------------------------------------
# 通用转换入口
# ---------------------------------------------------------------------------

_SUPPORTED_TYPES = ("d", "r", "f", "eta2", "phi", "or", "g")

_CONVERSIONS: dict[tuple[str, str], Any] = {
    ("d", "r"):    d_to_r,
    ("d", "f"):    d_to_f,
    ("d", "eta2"): d_to_eta2,
    ("d", "or"):   d_to_or,
    ("r", "d"):    r_to_d,
    ("r", "eta2"): lambda r: d_to_eta2(r_to_d(r)),
    ("r", "f"):    lambda r: d_to_f(r_to_d(r)),
    ("f", "d"):    f_to_d,
    ("f", "eta2"): f_to_eta2,
    ("f", "r"):    lambda f: d_to_r(f_to_d(f)),
    ("eta2", "d"): eta2_to_d,
    ("eta2", "f"): eta2_to_f,
    ("eta2", "r"): lambda e: d_to_r(eta2_to_d(e)),
    ("or", "d"):   or_to_d,
    ("or", "r"):   lambda o: d_to_r(or_to_d(o)),
}


def convert(value: float, from_type: str, to_type: str) -> float:
    """通用效应量转换：from_type ∈ {d,r,f,eta2,or}，to_type ∈ {d,r,f,eta2,or}。"""
    from_type = from_type.lower().replace("²", "2").replace("η", "eta")
    to_type = to_type.lower().replace("²", "2").replace("η", "eta")
    if from_type == to_type:
        return value
    key = (from_type, to_type)
    if key not in _CONVERSIONS:
        raise ValueError(
            f"不支持的转换 '{from_type}' → '{to_type}'。"
            f"支持的类型：{', '.join(sorted(set(k for pair in _CONVERSIONS for k in pair)))}"
        )
    return _CONVERSIONS[key](value)


def format_apa_effect_size(
    d: float | None = None,
    r: float | None = None,
    eta2: float | None = None,
    f: float | None = None,
    phi: float | None = None,
    note: str = "",
) -> str:
    """生成 APA-7 效应量报告文字（含言语标签）。"""
    parts = []
    if d is not None and math.isfinite(d):
        parts.append(f"*d* = {d:.2f}（{interpret_d(d)}）")
    if r is not None and math.isfinite(r):
        parts.append(f"*r* = {r:.2f}（{interpret_r(r)}）")
    if eta2 is not None and math.isfinite(eta2):
        parts.append(f"*η*² = {eta2:.3f}（{interpret_eta2(eta2)}）")
    if f is not None and math.isfinite(f):
        parts.append(f"*f* = {f:.2f}（{interpret_f(f)}）")
    if phi is not None and math.isfinite(phi):
        parts.append(f"*φ* = {phi:.2f}")
    if not parts:
        return "效应量未指定。"
    text = "效应量：" + "，".join(parts) + "。"
    if note:
        text += f"（{note}）"
    return text


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def effect_size_cli(args: list[str]) -> int:
    """psyclaw effect-size [--from d --to r --value 0.5]
                          [--compute d --m1 M1 --sd1 SD1 --n1 N1 ...]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw effect-size",
        description=(
            "效应量转换器（d↔r↔f↔η²↔OR；从摘要统计计算 d）"
            "。Cohen (1988) 言语标签。"
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")

    # convert 子命令
    pconv = sub.add_parser("convert", help="效应量类型间转换（如 d→r）")
    pconv.add_argument("--from", dest="from_type", required=True,
                       choices=["d", "r", "f", "eta2", "or"],
                       help="源效应量类型")
    pconv.add_argument("--to", dest="to_type", required=True,
                       choices=["d", "r", "f", "eta2", "or"],
                       help="目标效应量类型")
    pconv.add_argument("--value", type=float, required=True, help="源效应量值")
    pconv.add_argument("--json", action="store_true")

    # compute 子命令
    pcomp = sub.add_parser("compute", help="从摘要统计计算 Cohen's d")
    pcomp.add_argument("--m1", type=float, required=True, help="组1 均值")
    pcomp.add_argument("--sd1", type=float, required=True, help="组1 SD")
    pcomp.add_argument("--n1", type=int, required=True, help="组1 样本量")
    pcomp.add_argument("--m2", type=float, default=None, help="组2 均值（双样本模式）")
    pcomp.add_argument("--sd2", type=float, default=None, help="组2 SD")
    pcomp.add_argument("--n2", type=int, default=None, help="组2 样本量")
    pcomp.add_argument("--mu0", type=float, default=0.0, help="单样本参考均值（默认 0）")
    pcomp.add_argument("--json", action="store_true")

    # interpret 子命令
    pint = sub.add_parser("interpret", help="言语标签")
    pint.add_argument("--type", dest="es_type", required=True,
                      choices=["d", "r", "eta2", "f"],
                      help="效应量类型")
    pint.add_argument("--value", type=float, required=True)
    pint.add_argument("--json", action="store_true")

    opts = parser.parse_args(args)

    if opts.subcmd == "convert":
        try:
            result_val = convert(opts.value, opts.from_type, opts.to_type)
        except ValueError as exc:
            print(f"错误：{exc}")
            return 1
        interp_fn = {"d": interpret_d, "r": interpret_r,
                     "eta2": interpret_eta2, "f": interpret_f}.get(opts.to_type)
        interp = interp_fn(result_val) if interp_fn else ""
        out = {
            "from_type": opts.from_type, "from_value": opts.value,
            "to_type": opts.to_type, "to_value": round(result_val, 6),
            "interpretation": interp,
        }
        if opts.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"{opts.from_type} = {opts.value}  →  {opts.to_type} = {result_val:.4f}  （{interp}）")
        return 0

    elif opts.subcmd == "compute":
        try:
            if opts.m2 is not None:
                result = cohens_d_two_group(
                    opts.m1, opts.sd1, opts.n1,
                    opts.m2, opts.sd2 or opts.sd1, opts.n2 or opts.n1,
                )
            else:
                result = cohens_d_one_sample(opts.m1, opts.sd1, opts.n1, mu0=opts.mu0)
        except ValueError as exc:
            print(f"错误：{exc}")
            return 1
        if opts.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"\nCohen's d = {result['d']}  （{result['interpretation']}）")
            if "hedges_g" in result:
                print(f"Hedges' g = {result['hedges_g']}")
            print(f"95% CI    = [{result['ci_lower_95']}, {result['ci_upper_95']}]")
            print(f"r         = {result['r']},  η² = {result['eta2']}")
        return 0

    elif opts.subcmd == "interpret":
        fn = {"d": interpret_d, "r": interpret_r,
              "eta2": interpret_eta2, "f": interpret_f}[opts.es_type]
        label = fn(opts.value)
        if opts.json:
            print(json.dumps({"type": opts.es_type, "value": opts.value,
                              "interpretation": label}, ensure_ascii=False))
        else:
            print(f"{opts.es_type} = {opts.value}：{label}")
        return 0

    else:
        parser.print_help()
        return 1
