"""相关系数差异检验（Comparing Correlation Coefficients）— APA-7（stdlib only）。

回答「两个相关系数是否显著不同」——此前 PsyClaw 只能各自检验 r ≠ 0，
无法比较 r₁ 与 r₂。覆盖三类规范情形（与 R 的 cocor 包同构）：

  - compare_independent_corrs:    两独立样本（Fisher z 检验 + Zou 2007 差异 CI）
  - compare_dependent_overlapping: 同一样本、共享一个变量（r_jk vs r_jh，
                                   Williams 1959 t 检验，df = n − 3）
  - compare_dependent_nonoverlapping: 同一样本、四个不同变量（r_jk vs r_hm，
                                   Steiger 1980 / Dunn & Clark 1969 Z 检验）

各情形均给出 Zou (2007) MOVER 法的差异置信区间（相关性优于单纯比较两个 CI 是否重叠）。

理论依据：
  Fisher, R. A. (1921). On the "probable error" of a coefficient of correlation
    deduced from a small sample. Metron, 1, 3–32.
  Williams, E. J. (1959). The comparison of regression variables.
    Journal of the Royal Statistical Society: Series B, 21(2), 396–399.
  Dunn, O. J., & Clark, V. A. (1969). Correlation coefficients measured on the
    same individuals. Journal of the American Statistical Association, 64, 366–377.
  Steiger, J. H. (1980). Tests for comparing elements of a correlation matrix.
    Psychological Bulletin, 87(2), 245–251.
    https://doi.org/10.1037/0033-2909.87.2.245
  Zou, G. Y. (2007). Toward using confidence intervals to compare correlations.
    Psychological Methods, 12(4), 399–413. https://doi.org/10.1037/1082-989X.12.4.399

CLI:
  psyclaw compare-corr --kind independent --r1 .7 --n1 103 --r2 .5 --n2 103
  psyclaw compare-corr --kind overlapping <data.csv> --x col --y col --z col
  psyclaw compare-corr --kind nonoverlapping <data.csv> --vars a,b,c,d
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

from scipy import special, stats


# ---------------------------------------------------------------------------
# 分布工具（正态 / t，stdlib only）
# ---------------------------------------------------------------------------

def _norm_cdf(z: float) -> float:
    """标准正态分布 CDF Φ(z) —— scipy.special.ndtr。"""
    return float(special.ndtr(z))


def _norm_sf2(z: float) -> float:
    """标准正态双尾 p 值 —— 2·scipy.stats.norm.sf(|z|)。"""
    return 2.0 * float(stats.norm.sf(abs(z)))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a,b) —— scipy.special.betainc。"""
    if x < 0 or x > 1:
        return float("nan")
    return float(special.betainc(a, b, x))


def _t_sf2(t: float, df: float) -> float:
    """t 分布双尾 p 值 —— scipy.stats.t.sf。"""
    if df <= 0:
        return float("nan")
    return 2.0 * float(stats.t.sf(abs(t), df))


# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------

def _check_r(r: float, name: str) -> None:
    if not math.isfinite(r) or not (-1.0 <= r <= 1.0):
        raise ValueError(f"{name} 必须在 [−1, 1] 内，got {r!r}")


def _fisher_z_ci(r: float, n: int, alpha: float) -> tuple[float, float]:
    """单个相关系数的 Fisher z 置信区间 (l, u)。

    z = atanh(r)，SE = 1/√(n−3)，反变换回 r 尺度。
    """
    if n <= 3 or abs(r) >= 1.0:
        return (float("nan"), float("nan"))
    z = math.atanh(r)
    se = 1.0 / math.sqrt(n - 3)
    zc = _norm_ppf(1.0 - alpha / 2.0)
    return (math.tanh(z - zc * se), math.tanh(z + zc * se))


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Pearson r。"""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in xs))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in ys))
    if sx < 1e-14 or sy < 1e-14:
        return float("nan")
    return num / (sx * sy)


def _round(v: float, nd: int = 6) -> float | None:
    return round(v, nd) if (v is not None and math.isfinite(v)) else None


# ---------------------------------------------------------------------------
# 情形 1：两独立样本相关系数差异（Fisher z）
# ---------------------------------------------------------------------------

def compare_independent_corrs(
    r1: float, n1: int, r2: float, n2: int, alpha: float = 0.05,
) -> dict[str, Any]:
    """比较来自两个独立样本的相关系数（Fisher z 检验）。

    H0: ρ₁ = ρ₂。差异置信区间用 Zou (2007) MOVER 法。

    返回 {kind, r1, n1, r2, n2, diff, z, p, ci_lower, ci_upper, alpha, significant}
    """
    _check_r(r1, "r1")
    _check_r(r2, "r2")
    if n1 <= 3 or n2 <= 3:
        raise ValueError("每个样本量须 > 3（Fisher z 需 n − 3 自由度）")
    if abs(r1) >= 1.0 or abs(r2) >= 1.0:
        raise ValueError("Fisher z 检验要求 |r| < 1")

    z1, z2 = math.atanh(r1), math.atanh(r2)
    se = math.sqrt(1.0 / (n1 - 3) + 1.0 / (n2 - 3))
    z = (z1 - z2) / se
    p = _norm_sf2(z)

    # Zou (2007) 独立样本差异 CI（MOVER）
    l1, u1 = _fisher_z_ci(r1, n1, alpha)
    l2, u2 = _fisher_z_ci(r2, n2, alpha)
    diff = r1 - r2
    ci_lower = diff - math.sqrt((r1 - l1) ** 2 + (u2 - r2) ** 2)
    ci_upper = diff + math.sqrt((u1 - r1) ** 2 + (r2 - l2) ** 2)

    return {
        "kind": "independent",
        "r1": _round(r1), "n1": n1, "r2": _round(r2), "n2": n2,
        "diff": _round(diff),
        "z": _round(z), "p": _round(p),
        "ci_lower": _round(ci_lower), "ci_upper": _round(ci_upper),
        "alpha": alpha,
        "significant": bool(p < alpha) if math.isfinite(p) else None,
    }


# ---------------------------------------------------------------------------
# 情形 2：同一样本、共享一个变量（重叠，Williams's t）
# ---------------------------------------------------------------------------

def compare_dependent_overlapping(
    r_jk: float, r_jh: float, r_kh: float, n: int, alpha: float = 0.05,
) -> dict[str, Any]:
    """比较同一样本中两个共享变量的相关（r_jk vs r_jh，j 为共享变量）。

    使用 Williams (1959) T2 检验（Hittner et al. 2003 推荐），df = n − 3。
    第三个相关 r_kh 是被比较的两个变量之间的相关。
    差异 CI 用 Zou (2007) 重叠法，估计量相关 c 由 Olkin (1967) 公式。

    返回 {kind, r_jk, r_jh, r_kh, n, diff, t, df, p, ci_lower, ci_upper,
          alpha, significant}
    """
    for r, nm in ((r_jk, "r_jk"), (r_jh, "r_jh"), (r_kh, "r_kh")):
        _check_r(r, nm)
    if n <= 3:
        raise ValueError("样本量须 > 3")

    df = n - 3
    det = 1.0 - r_jk**2 - r_jh**2 - r_kh**2 + 2.0 * r_jk * r_jh * r_kh
    rbar = (r_jk + r_jh) / 2.0
    denom = 2.0 * ((n - 1.0) / (n - 3.0)) * det + rbar**2 * (1.0 - r_kh) ** 3
    if denom <= 0:
        raise ValueError("Williams 检验分母非正（相关矩阵近奇异），无法计算")

    t = (r_jk - r_jh) * math.sqrt((n - 1.0) * (1.0 + r_kh) / denom)
    p = _t_sf2(t, df)

    # Zou (2007) 重叠差异 CI；c = r_jk 与 r_jh 估计量的渐近相关（Olkin 1967）
    diff = r_jk - r_jh
    cd1 = (1.0 - r_jk**2) * (1.0 - r_jh**2)
    if abs(cd1) < 1e-14:
        ci_lower = ci_upper = float("nan")
    else:
        c = ((r_kh - 0.5 * r_jk * r_jh) * (1.0 - r_jk**2 - r_jh**2 - r_kh**2)
             + r_kh**3) / cd1
        c = max(-1.0, min(1.0, c))
        l1, u1 = _fisher_z_ci(r_jk, n, alpha)
        l2, u2 = _fisher_z_ci(r_jh, n, alpha)
        ci_lower = diff - math.sqrt(
            max(0.0, (r_jk - l1) ** 2 + (u2 - r_jh) ** 2
                - 2.0 * c * (r_jk - l1) * (u2 - r_jh))
        )
        ci_upper = diff + math.sqrt(
            max(0.0, (u1 - r_jk) ** 2 + (r_jh - l2) ** 2
                - 2.0 * c * (u1 - r_jk) * (r_jh - l2))
        )

    return {
        "kind": "overlapping",
        "r_jk": _round(r_jk), "r_jh": _round(r_jh), "r_kh": _round(r_kh),
        "n": n, "diff": _round(diff),
        "t": _round(t), "df": df, "p": _round(p),
        "ci_lower": _round(ci_lower), "ci_upper": _round(ci_upper),
        "alpha": alpha,
        "significant": bool(p < alpha) if math.isfinite(p) else None,
    }


# ---------------------------------------------------------------------------
# 情形 3：同一样本、四个不同变量（非重叠，Steiger's Z）
# ---------------------------------------------------------------------------

def compare_dependent_nonoverlapping(
    r_jk: float, r_hm: float,
    r_jh: float, r_jm: float, r_kh: float, r_km: float,
    n: int, alpha: float = 0.05,
) -> dict[str, Any]:
    """比较同一样本中两个无共享变量的相关（r_jk vs r_hm，四个变量 j,k,h,m）。

    使用 Steiger (1980) / Dunn & Clark (1969) 的 Z 检验（Fisher z 变换 + 估计量协方差）。
    需要全部六个两两相关。差异 CI 用 Zou (2007) 非重叠法。

    返回 {kind, r_jk, r_hm, n, diff, z, p, ci_lower, ci_upper, alpha, significant}
    """
    for r, nm in ((r_jk, "r_jk"), (r_hm, "r_hm"), (r_jh, "r_jh"),
                  (r_jm, "r_jm"), (r_kh, "r_kh"), (r_km, "r_km")):
        _check_r(r, nm)
    if n <= 3:
        raise ValueError("样本量须 > 3")
    if abs(r_jk) >= 1.0 or abs(r_hm) >= 1.0:
        raise ValueError("Steiger 检验要求被比较相关 |r| < 1")

    # 估计量协方差（Steiger 1980 / Dunn & Clark 1969）
    cov = (0.5 * r_jk * r_hm * (r_jh**2 + r_jm**2 + r_kh**2 + r_km**2)
           + r_jh * r_km + r_jm * r_kh
           - (r_jk * r_jh * r_km + r_jk * r_jm * r_kh
              + r_hm * r_jh * r_kh + r_hm * r_jm * r_km))
    cd = (1.0 - r_jk**2) * (1.0 - r_hm**2)
    c = cov / cd if abs(cd) > 1e-14 else 0.0
    c = max(-1.0, min(1.0, c))

    z_jk, z_hm = math.atanh(r_jk), math.atanh(r_hm)
    z = (z_jk - z_hm) * math.sqrt(n - 3) / math.sqrt(max(1e-14, 2.0 - 2.0 * c))
    p = _norm_sf2(z)

    # Zou (2007) 非重叠差异 CI
    diff = r_jk - r_hm
    l1, u1 = _fisher_z_ci(r_jk, n, alpha)
    l2, u2 = _fisher_z_ci(r_hm, n, alpha)
    ci_lower = diff - math.sqrt(
        max(0.0, (r_jk - l1) ** 2 + (u2 - r_hm) ** 2
            - 2.0 * c * (r_jk - l1) * (u2 - r_hm))
    )
    ci_upper = diff + math.sqrt(
        max(0.0, (u1 - r_jk) ** 2 + (r_hm - l2) ** 2
            - 2.0 * c * (u1 - r_jk) * (r_hm - l2))
    )

    return {
        "kind": "nonoverlapping",
        "r_jk": _round(r_jk), "r_hm": _round(r_hm),
        "r_jh": _round(r_jh), "r_jm": _round(r_jm),
        "r_kh": _round(r_kh), "r_km": _round(r_km),
        "n": n, "diff": _round(diff),
        "z": _round(z), "p": _round(p),
        "ci_lower": _round(ci_lower), "ci_upper": _round(ci_upper),
        "alpha": alpha,
        "significant": bool(p < alpha) if math.isfinite(p) else None,
    }


# ---------------------------------------------------------------------------
# 解读
# ---------------------------------------------------------------------------

def interpret_compare(result: dict[str, Any]) -> str:
    """对差异检验结果给出方向 + 显著性的简短中文叙述。"""
    p = result.get("p")
    alpha = result.get("alpha", 0.05)
    diff = result.get("diff")
    if p is None or not math.isfinite(p):
        return "无法判定（检验统计量不可计算）。"
    if p < alpha:
        if diff is not None and diff > 0:
            dirn = "前一个相关显著更强"
        elif diff is not None and diff < 0:
            dirn = "后一个相关显著更强"
        else:
            dirn = "两相关显著不同"
        return f"两相关系数在 α = {alpha} 水平上**存在显著差异**（{dirn}）。"
    return (f"两相关系数在 α = {alpha} 水平上**无显著差异**——"
            f"不能据此断言两者不同。")


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _p_str(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return "= " + f"{p:.3f}".lstrip("0")


def _f3(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    s = f"{v:.3f}"
    # APA：移除前导零（保留负号），但 |v|≥1 时保留整数位
    if s.startswith("0."):
        return s[1:]
    if s.startswith("-0."):
        return "-" + s[2:]
    return s


_REFS = [
    "Fisher, R. A. (1921). On the \"probable error\" of a coefficient of "
    "correlation deduced from a small sample. *Metron*, *1*, 3–32.",
    "Williams, E. J. (1959). The comparison of regression variables. "
    "*Journal of the Royal Statistical Society: Series B*, *21*(2), 396–399.",
    "Steiger, J. H. (1980). Tests for comparing elements of a correlation "
    "matrix. *Psychological Bulletin*, *87*(2), 245–251. "
    "https://doi.org/10.1037/0033-2909.87.2.245",
    "Zou, G. Y. (2007). Toward using confidence intervals to compare "
    "correlations. *Psychological Methods*, *12*(4), 399–413. "
    "https://doi.org/10.1037/1082-989X.12.4.399",
]


def format_apa_compare_corr(
    result: dict[str, Any],
    labels: dict[str, str] | None = None,
) -> str:
    """APA-7 相关系数差异检验 Markdown 段落。

    labels 可提供变量名，如 {"j":"焦虑","k":"成绩",...}；缺省用占位名。
    """
    labels = labels or {}
    kind = result["kind"]
    p = result.get("p")
    diff = result.get("diff")
    ci_lo = result.get("ci_lower")
    ci_hi = result.get("ci_upper")
    alpha = result.get("alpha", 0.05)
    ci_str = f"[{_f3(ci_lo)}, {_f3(ci_hi)}]" if ci_lo is not None and ci_hi is not None else "—"

    lines: list[str] = ["## 相关系数差异检验", ""]

    if kind == "independent":
        r1, r2 = result["r1"], result["r2"]
        n1, n2 = result["n1"], result["n2"]
        z = result.get("z")
        g1 = labels.get("g1", "样本 1")
        g2 = labels.get("g2", "样本 2")
        lines += [
            f"- **方法**：两独立样本 Fisher *z* 检验",
            f"- **{g1}**：*r* = {_f3(r1)}，*n* = {n1}",
            f"- **{g2}**：*r* = {_f3(r2)}，*n* = {n2}",
            "",
            f"比较两独立样本的相关系数，{g1}（*r* = {_f3(r1)}）与 {g2}"
            f"（*r* = {_f3(r2)}）之间的差异为 Δ*r* = {_f3(diff)}，"
            f"Fisher *z* = {_f3(z)}，*p* {_p_str(p)}，95% CI {ci_str}。",
        ]
        stat_row = f"| 独立样本 Fisher *z* | {_f3(z)} | — | {_p_str(p)} |"
    elif kind == "overlapping":
        r_jk, r_jh, r_kh = result["r_jk"], result["r_jh"], result["r_kh"]
        n, dfree, t = result["n"], result["df"], result.get("t")
        j = labels.get("j", "j")
        k = labels.get("k", "k")
        h = labels.get("h", "h")
        lines += [
            f"- **方法**：相依（重叠）相关 Williams *t* 检验",
            f"- **共享变量**：{j}",
            f"- *r*({j},{k}) = {_f3(r_jk)}，*r*({j},{h}) = {_f3(r_jh)}，"
            f"*r*({k},{h}) = {_f3(r_kh)}，*N* = {n}",
            "",
            f"在同一样本（*N* = {n}）中比较两个共享变量 {j} 的相关，"
            f"*r*({j},{k}) = {_f3(r_jk)} 与 *r*({j},{h}) = {_f3(r_jh)} 的差异为 "
            f"Δ*r* = {_f3(diff)}，Williams *t*({dfree}) = {_f3(t)}，"
            f"*p* {_p_str(p)}，95% CI {ci_str}。",
        ]
        stat_row = f"| 重叠 Williams *t* | {_f3(t)} | {dfree} | {_p_str(p)} |"
    else:  # nonoverlapping
        r_jk, r_hm = result["r_jk"], result["r_hm"]
        n, z = result["n"], result.get("z")
        lines += [
            f"- **方法**：相依（非重叠）相关 Steiger *Z* 检验",
            f"- *r*₁ = {_f3(r_jk)}，*r*₂ = {_f3(r_hm)}，*N* = {n}",
            "",
            f"在同一样本（*N* = {n}）中比较两个无共享变量的相关，"
            f"*r*₁ = {_f3(r_jk)} 与 *r*₂ = {_f3(r_hm)} 的差异为 "
            f"Δ*r* = {_f3(diff)}，Steiger *Z* = {_f3(z)}，"
            f"*p* {_p_str(p)}，95% CI {ci_str}。",
        ]
        stat_row = f"| 非重叠 Steiger *Z* | {_f3(z)} | — | {_p_str(p)} |"

    lines.append(interpret_compare(result))

    lines += ["", "### 汇总表", "",
              "| 检验 | 统计量 | *df* | *p* |",
              "|------|--------|------|-----|",
              stat_row,
              f"| 差异 Δ*r* | {_f3(diff)} | — | 95% CI {ci_str} |"]

    lines += ["", "### 参考文献", ""]
    lines += [r + "\n" for r in _REFS]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# JSON sidecar
# ---------------------------------------------------------------------------

def _clean_json(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_json(v) for v in obj]
    return obj


def write_compare_corr_report(
    result: dict[str, Any],
    formatted: str,
    out_dir: str | pathlib.Path,
    stem: str = "compare_corr_report",
) -> dict[str, str]:
    """写 MD + JSON sidecar，返回 {md, json} 路径。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md_path = out / f"{stem}.md"
    json_path = out / f"{stem}.json"
    md_path.write_text(formatted, encoding="utf-8")
    clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    json_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path)}


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_csv_cols(csv_path: str, col_names: list[str]) -> tuple[dict[str, list[float]], int]:
    """读取 CSV 指定列，整行无缺失才纳入，返回 {列名: 列表} 和排除行数。"""
    path = pathlib.Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"找不到数据文件: {csv_path}")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("CSV 文件为空或无数据行")
    header = set(rows[0].keys())
    missing = [c for c in col_names if c not in header]
    if missing:
        raise ValueError(f"CSV 中找不到列: {missing}")
    data: dict[str, list[float]] = {c: [] for c in col_names}
    n_excluded = 0
    for row in rows:
        try:
            vals = {c: float(row[c]) for c in col_names}
        except (ValueError, KeyError, TypeError):
            n_excluded += 1
            continue
        for c, v in vals.items():
            data[c].append(v)
    return data, n_excluded


def analyze_compare_corr(
    kind: str,
    csv_path: str | None = None,
    *,
    # 独立样本（CSV 模式）
    x_col: str | None = None,
    y_col: str | None = None,
    group_col: str | None = None,
    # 重叠 / 非重叠（CSV 模式）
    z_col: str | None = None,
    var_cols: list[str] | None = None,
    # 手填相关（无 CSV 模式）
    r1: float | None = None, n1: int | None = None,
    r2: float | None = None, n2: int | None = None,
    alpha: float = 0.05,
    out_dir: str = "notes",
    return_json: bool = False,
) -> dict[str, Any]:
    """主入口：CSV 计算相关或直接接收相关值 → 差异检验 → 写 sidecar。

    - independent: CSV 需 x_col,y_col,group_col（两水平分组各算 r(x,y)）；
                   或手填 r1,n1,r2,n2。
    - overlapping: CSV 需 x_col,y_col,z_col（j=x 共享，r_xy vs r_xz，第三 r_yz）。
    - nonoverlapping: CSV 需 var_cols=[a,b,c,d]（比较 r_ab vs r_cd，余为交叉相关）。
    """
    labels: dict[str, str] = {}

    if kind == "independent":
        if csv_path:
            if not (x_col and y_col and group_col):
                raise ValueError("independent CSV 模式需 --x --y --group")
            data, n_excluded = _read_csv_cols(csv_path, [x_col, y_col, group_col])
            groups: dict[float, list[int]] = {}
            for i, g in enumerate(data[group_col]):
                groups.setdefault(g, []).append(i)
            gkeys = sorted(groups)
            if len(gkeys) != 2:
                raise ValueError(f"--group 须恰为 2 个水平，实得 {len(gkeys)} 个")
            (gA, gB) = gkeys
            xA = [data[x_col][i] for i in groups[gA]]
            yA = [data[y_col][i] for i in groups[gA]]
            xB = [data[x_col][i] for i in groups[gB]]
            yB = [data[y_col][i] for i in groups[gB]]
            r1v, n1v = _pearson_r(xA, yA), len(xA)
            r2v, n2v = _pearson_r(xB, yB), len(xB)
            labels = {"g1": f"{group_col}={gA:g}", "g2": f"{group_col}={gB:g}"}
            result = compare_independent_corrs(r1v, n1v, r2v, n2v, alpha=alpha)
            result["n_excluded"] = n_excluded
        else:
            if None in (r1, n1, r2, n2):
                raise ValueError("independent 手填模式需 --r1 --n1 --r2 --n2")
            result = compare_independent_corrs(r1, int(n1), r2, int(n2), alpha=alpha)

    elif kind == "overlapping":
        if csv_path:
            if not (x_col and y_col and z_col):
                raise ValueError("overlapping CSV 模式需 --x --y --z")
            data, n_excluded = _read_csv_cols(csv_path, [x_col, y_col, z_col])
            n = len(data[x_col])
            r_jk = _pearson_r(data[x_col], data[y_col])
            r_jh = _pearson_r(data[x_col], data[z_col])
            r_kh = _pearson_r(data[y_col], data[z_col])
            labels = {"j": x_col, "k": y_col, "h": z_col}
            result = compare_dependent_overlapping(r_jk, r_jh, r_kh, n, alpha=alpha)
            result["n_excluded"] = n_excluded
        else:
            if None in (r1, r2, n1) or n2 is None:
                # 复用 r1=r_jk, r2=r_jh, n1=r_kh(放宽), n2=n —— 见 CLI 显式参数
                raise ValueError("overlapping 手填模式请用 CLI 的 --r-jk --r-jh --r-kh --n")
            result = compare_dependent_overlapping(r1, r2, n1, int(n2), alpha=alpha)

    elif kind == "nonoverlapping":
        if csv_path:
            if not var_cols or len(var_cols) != 4:
                raise ValueError("nonoverlapping CSV 模式需 --vars a,b,c,d（恰 4 列）")
            a, b, c, d = var_cols
            data, n_excluded = _read_csv_cols(csv_path, var_cols)
            n = len(data[a])
            r_jk = _pearson_r(data[a], data[b])
            r_hm = _pearson_r(data[c], data[d])
            r_jh = _pearson_r(data[a], data[c])
            r_jm = _pearson_r(data[a], data[d])
            r_kh = _pearson_r(data[b], data[c])
            r_km = _pearson_r(data[b], data[d])
            result = compare_dependent_nonoverlapping(
                r_jk, r_hm, r_jh, r_jm, r_kh, r_km, n, alpha=alpha)
            result["n_excluded"] = n_excluded
            result["var_cols"] = var_cols
        else:
            raise ValueError("nonoverlapping 手填模式请用 CLI 的六个 --r-* 与 --n")
    else:
        raise ValueError(f"未知 kind: {kind!r}（须为 independent/overlapping/nonoverlapping）")

    formatted = format_apa_compare_corr(result, labels=labels)
    paths = write_compare_corr_report(result, formatted, out_dir)
    result["_formatted"] = formatted
    result["_paths"] = paths

    if return_json:
        return _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def compare_corr_cli(argv: list[str]) -> int:
    import argparse
    from psyclaw import ui

    ap = argparse.ArgumentParser(
        prog="psyclaw compare-corr",
        description="相关系数差异检验（Fisher z / Williams t / Steiger Z，APA-7，stdlib only）",
    )
    ap.add_argument("csv", nargs="?", help="输入数据 CSV 路径（省略则用手填相关值）")
    ap.add_argument("--kind", required=True,
                    choices=["independent", "overlapping", "nonoverlapping"],
                    help="independent(两独立样本) | overlapping(共享一变量) | nonoverlapping(四个变量)")
    # CSV 列
    ap.add_argument("--x", dest="x_col", help="independent/overlapping：变量 x（重叠时为共享变量 j）")
    ap.add_argument("--y", dest="y_col", help="independent/overlapping：变量 y")
    ap.add_argument("--z", dest="z_col", help="overlapping：变量 z")
    ap.add_argument("--group", dest="group_col", help="independent：分组列（恰 2 水平）")
    ap.add_argument("--vars", help="nonoverlapping：四列名 a,b,c,d（比较 r_ab vs r_cd）")
    # 手填相关
    ap.add_argument("--r1", type=float, help="手填：r₁ / r_jk")
    ap.add_argument("--n1", type=float, help="手填：n₁（independent）")
    ap.add_argument("--r2", type=float, help="手填：r₂ / r_jh")
    ap.add_argument("--n2", type=float, help="手填：n₂（independent）")
    ap.add_argument("--r-jk", dest="r_jk", type=float, help="dependent 手填：r_jk")
    ap.add_argument("--r-jh", dest="r_jh", type=float, help="overlapping 手填：r_jh")
    ap.add_argument("--r-kh", dest="r_kh", type=float, help="overlapping 手填：r_kh")
    ap.add_argument("--r-hm", dest="r_hm", type=float, help="nonoverlapping 手填：r_hm")
    ap.add_argument("--r-jm", dest="r_jm", type=float, help="nonoverlapping 手填：r_jm")
    ap.add_argument("--r-km", dest="r_km", type=float, help="nonoverlapping 手填：r_km")
    ap.add_argument("--n", type=float, help="dependent 手填：样本量 n")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")

    args = ap.parse_args(argv)

    try:
        if args.csv:
            var_cols = [c.strip() for c in args.vars.split(",")] if args.vars else None
            result = analyze_compare_corr(
                args.kind, csv_path=args.csv,
                x_col=args.x_col, y_col=args.y_col, z_col=args.z_col,
                group_col=args.group_col, var_cols=var_cols,
                alpha=args.alpha, out_dir=args.out,
            )
        else:
            # 手填模式：直接调用核心函数
            if args.kind == "independent":
                if None in (args.r1, args.n1, args.r2, args.n2):
                    raise ValueError("independent 手填需 --r1 --n1 --r2 --n2")
                result = compare_independent_corrs(
                    args.r1, int(args.n1), args.r2, int(args.n2), alpha=args.alpha)
            elif args.kind == "overlapping":
                rjk = args.r_jk if args.r_jk is not None else args.r1
                rjh = args.r_jh if args.r_jh is not None else args.r2
                if None in (rjk, rjh, args.r_kh, args.n):
                    raise ValueError("overlapping 手填需 --r-jk --r-jh --r-kh --n")
                result = compare_dependent_overlapping(
                    rjk, rjh, args.r_kh, int(args.n), alpha=args.alpha)
            else:
                rjk = args.r_jk if args.r_jk is not None else args.r1
                if None in (rjk, args.r_hm, args.r_jh, args.r_jm,
                            args.r_kh, args.r_km, args.n):
                    raise ValueError(
                        "nonoverlapping 手填需 --r-jk --r-hm --r-jh --r-jm --r-kh --r-km --n")
                result = compare_dependent_nonoverlapping(
                    rjk, args.r_hm, args.r_jh, args.r_jm, args.r_kh, args.r_km,
                    int(args.n), alpha=args.alpha)
            formatted = format_apa_compare_corr(result)
            paths = write_compare_corr_report(result, formatted, args.out)
            result["_formatted"] = formatted
            result["_paths"] = paths
    except (FileNotFoundError, ValueError) as exc:
        print(ui.err(str(exc)))
        return 1

    if args.json:
        clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return 0

    stat = result.get("z", result.get("t"))
    stat_name = "z" if "z" in result else "t"
    print(ui.title("相关系数差异检验"))
    print(ui.rule())
    print(f"  情形        : {result['kind']}")
    print(f"  差异 Δr     : {result.get('diff')}")
    if stat is not None:
        print(f"  统计量 {stat_name}    : {stat}")
    p_val = result.get("p")
    if p_val is not None:
        pdisp = "< .001" if (math.isfinite(p_val) and p_val < 0.001) else f"= {p_val:.3f}"
        print(f"  p 值        : {pdisp}")
    ci_lo, ci_hi = result.get("ci_lower"), result.get("ci_upper")
    if ci_lo is not None and ci_hi is not None:
        print(f"  95% CI(Δr)  : [{ci_lo}, {ci_hi}]")
    print()
    print("  " + interpret_compare(result))
    paths = result.get("_paths", {})
    if paths.get("md"):
        print(ui.dim(f"\n  报告已写入: {paths['md']}"))
    return 0
