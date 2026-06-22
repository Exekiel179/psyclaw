"""元分析核心 — DerSimonian-Laird 随机效应模型（stdlib only，可选 scipy 提升精度）。

输入 CSV 格式（任选其一）:
  study, d, se                       — 效应量 + 标准误（最推荐）
  study, d, ci_lower, ci_upper       — 效应量 + 95% CI（SE = (ci_upper-ci_lower)/3.92）
  study, d, n1, n2                   — Cohen's d + 样本量（SE 由 Hedges 公式推算）
  study, r, n                        — 相关系数 + 总样本量（r→Fisher z，SE=1/√(n-3)）

输出结构（meta_result dict）:
  k, effect_type, studies:           原始条目列表
  fixed: {theta, se, ci, z, p}       固定效应
  random: {theta, se, ci, z, p}      DerSimonian-Laird 随机效应
  heterogeneity: {Q, df, p_Q, I2, tau2}
  egger: {b0, se_b0, t, df, p, sign} (仅 k≥10)
  apa_text                            APA-7 段落
  forest_text                         ASCII 森林图
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

from scipy import special, stats


# ---------------------------------------------------------------------------
# 统计工具（stdlib only）
# ---------------------------------------------------------------------------

def _norm_cdf(z: float) -> float:
    """标准正态分布 CDF —— scipy.special.ndtr。"""
    return float(special.ndtr(z))


def _norm_ppf_two_sided_95() -> float:
    return 1.959963985  # exact z for alpha/2=0.025


def _chi2_p_wilson_hilferty(Q: float, df: int) -> float:
    """chi2(df) 右尾 p —— scipy.stats.chi2.sf（精确，替代 Wilson-Hilferty 近似）。"""
    if Q <= 0 or df <= 0:
        return 1.0
    return float(stats.chi2.sf(Q, df))


def _ols_simple(xs: list[float], ys: list[float]) -> tuple[float, float, float, float]:
    """OLS 简单线性回归 y = b0 + b1*x，返回 (b0, b1, se_b0, se_b1)。"""
    n = len(xs)
    if n < 3:
        return 0.0, 0.0, float("inf"), float("inf")
    mx = sum(xs) / n
    my = sum(ys) / n
    Sxx = sum((x - mx) ** 2 for x in xs)
    Sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if abs(Sxx) < 1e-15:
        return my, 0.0, float("inf"), float("inf")
    b1 = Sxy / Sxx
    b0 = my - b1 * mx
    # 残差方差
    ss_res = sum((y - (b0 + b1 * x)) ** 2 for x, y in zip(xs, ys))
    s2 = ss_res / (n - 2)
    se_b1 = math.sqrt(s2 / Sxx)
    se_b0 = math.sqrt(s2 * (1 / n + mx ** 2 / Sxx))
    return b0, b1, se_b0, se_b1


def _t_p_approx(t: float, df: int) -> float:
    """双侧 t 检验 p 值 —— scipy.stats.t.sf（精确）。"""
    if df <= 0:
        return 1.0
    return 2.0 * float(stats.t.sf(abs(t), df))


def _se_from_ci(d: float, ci_lower: float, ci_upper: float) -> float:
    return (ci_upper - ci_lower) / (2 * _norm_ppf_two_sided_95())


def _se_from_n1n2(d: float, n1: int, n2: int) -> float:
    """Cohen's d SE（Hedges 1981 近似）。"""
    if n1 < 2 or n2 < 2:
        return float("inf")
    return math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / (2 * (n1 + n2)))


def _fisher_z(r: float) -> float:
    r = max(-0.9999, min(0.9999, r))
    return 0.5 * math.log((1 + r) / (1 - r))


def _fisher_z_to_r(z: float) -> float:
    return (math.exp(2 * z) - 1) / (math.exp(2 * z) + 1)


# ---------------------------------------------------------------------------
# CSV 读取 & 效应量解析
# ---------------------------------------------------------------------------

def _parse_csv(text: str) -> tuple[str, list[dict]]:
    """解析 CSV，返回 (effect_type, studies_list)。

    studies_list 每项 = {"label": str, "d": float, "se": float}
    effect_type ∈ {"d", "r", "g", "OR", "RR"}
    """
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]

    # 检测效应量列
    eff_col = None
    eff_type = "d"
    for col, typ in [("d", "d"), ("g", "g"), ("r", "r"), ("or", "OR"), ("rr", "RR")]:
        if col in headers:
            eff_col, eff_type = col, typ
            break
    if eff_col is None:
        raise ValueError("CSV 必须含效应量列: d / g / r / OR / RR")

    # 检测标签列
    label_col = next((c for c in ["study", "label", "author", "name"] if c in headers), None)

    studies = []
    for i, row in enumerate(reader):
        row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
        label = row_lower.get(label_col, f"Study {i+1}") if label_col else f"Study {i+1}"
        eff = float(row_lower[eff_col])

        # SE 推导（优先级: se → ci → n1n2 → n）
        se_val = row_lower.get("se", "")
        ci_l = row_lower.get("ci_lower", row_lower.get("lower", ""))
        ci_u = row_lower.get("ci_upper", row_lower.get("upper", ""))
        n1s = row_lower.get("n1", "")
        n2s = row_lower.get("n2", "")
        ns = row_lower.get("n", "")

        if se_val:
            se = float(se_val)
        elif ci_l and ci_u:
            se = _se_from_ci(eff, float(ci_l), float(ci_u))
        elif n1s and n2s:
            se = _se_from_n1n2(eff, int(float(n1s)), int(float(n2s)))
        elif ns and eff_col == "r":
            n = int(float(ns))
            eff = _fisher_z(eff)       # r → Fisher z
            eff_type = "r_z"
            se = 1 / math.sqrt(max(1, n - 3))
        else:
            raise ValueError(f"第 {i+1} 行: 无法推算 SE（需提供 se / ci_lower+ci_upper / n1+n2 / n）")

        if se <= 0 or math.isnan(se) or math.isinf(se):
            raise ValueError(f"第 {i+1} 行: SE={se} 无效")

        studies.append({"label": label, "d": eff, "se": se})

    if not studies:
        raise ValueError("CSV 没有有效数据行")

    return eff_type, studies


# ---------------------------------------------------------------------------
# 核心元分析
# ---------------------------------------------------------------------------

def compute_meta(studies: list[dict], effect_type: str = "d") -> dict:
    """在 studies = [{"label", "d", "se"}, ...] 上跑元分析。

    返回完整 meta_result 字典。
    """
    k = len(studies)
    if k < 2:
        raise ValueError("元分析至少需要 2 个研究")

    ds = [s["d"] for s in studies]
    ses = [s["se"] for s in studies]
    ws = [1 / se ** 2 for se in ses]  # 固定效应权重

    Sw = sum(ws)
    Swd = sum(w * d for w, d in zip(ws, ds))

    # --- 固定效应 ---
    theta_fe = Swd / Sw
    se_fe = 1 / math.sqrt(Sw)
    z95 = _norm_ppf_two_sided_95()
    ci_fe = (theta_fe - z95 * se_fe, theta_fe + z95 * se_fe)
    z_fe = theta_fe / se_fe
    p_fe = 2 * (1 - _norm_cdf(abs(z_fe)))

    # --- Cochran's Q ---
    Q = sum(w * (d - theta_fe) ** 2 for w, d in zip(ws, ds))
    df_Q = k - 1
    p_Q = _chi2_p_wilson_hilferty(Q, df_Q)

    # --- τ² (DerSimonian-Laird) ---
    Sw2 = sum(w ** 2 for w in ws)
    C = Sw - Sw2 / Sw
    tau2 = max(0.0, (Q - df_Q) / C) if C > 1e-15 else 0.0

    # --- I² ---
    I2 = max(0.0, (Q - df_Q) / Q * 100) if Q > 0 else 0.0

    # --- 随机效应 (DL) ---
    ws_re = [1 / (se ** 2 + tau2) for se in ses]
    Sw_re = sum(ws_re)
    theta_re = sum(w * d for w, d in zip(ws_re, ds)) / Sw_re
    se_re = 1 / math.sqrt(Sw_re)
    ci_re = (theta_re - z95 * se_re, theta_re + z95 * se_re)
    z_re = theta_re / se_re
    p_re = 2 * (1 - _norm_cdf(abs(z_re)))

    # --- Egger's test (k ≥ 10) ---
    egger: dict = {}
    if k >= 10:
        zs_egger = [d / se for d, se in zip(ds, ses)]
        prec_egger = [1 / se for se in ses]
        b0, b1, se_b0, _ = _ols_simple(prec_egger, zs_egger)
        df_eg = k - 2
        t_eg = b0 / se_b0 if se_b0 > 0 else float("inf")
        p_eg = _t_p_approx(t_eg, df_eg)
        egger = {
            "b0": round(b0, 4),
            "se_b0": round(se_b0, 4),
            "t": round(t_eg, 3),
            "df": df_eg,
            "p": round(p_eg, 4),
            "significant": p_eg < 0.05,
        }

    # --- 每研究权重 (%) ---
    total_w_re = sum(ws_re)
    for s, w_re in zip(studies, ws_re):
        s["weight_pct"] = round(w_re / total_w_re * 100, 1)

    return {
        "k": k,
        "effect_type": effect_type,
        "studies": studies,
        "fixed": {
            "theta": round(theta_fe, 4),
            "se": round(se_fe, 4),
            "ci": (round(ci_fe[0], 4), round(ci_fe[1], 4)),
            "z": round(z_fe, 3),
            "p": round(p_fe, 4),
        },
        "random": {
            "theta": round(theta_re, 4),
            "se": round(se_re, 4),
            "ci": (round(ci_re[0], 4), round(ci_re[1], 4)),
            "z": round(z_re, 3),
            "p": round(p_re, 4),
        },
        "heterogeneity": {
            "Q": round(Q, 3),
            "df": df_Q,
            "p_Q": round(p_Q, 4),
            "I2": round(I2, 1),
            "tau2": round(tau2, 4),
            "tau": round(math.sqrt(tau2), 4),
        },
        "egger": egger,
        # --- 门禁字段 ---
        "meta_heterogeneity_reported": True,
        "meta_effect_ci_reported": True,
    }


# ---------------------------------------------------------------------------
# 格式输出
# ---------------------------------------------------------------------------

def _i2_interp(i2: float) -> str:
    if i2 < 25:
        return "低"
    if i2 < 75:
        return "中等"
    return "高"


def format_apa(result: dict) -> str:
    """生成 APA-7 风格元分析结果段落。"""
    r = result["random"]
    h = result["heterogeneity"]
    k = result["k"]
    et = result["effect_type"]
    sym = "z" if et in ("r", "r_z") else "d"

    egger_note = ""
    eg = result.get("egger", {})
    if eg:
        bias_word = "显著" if eg["significant"] else "不显著"
        p_eg_str = "< .001" if eg["p"] < 0.001 else f"= {eg['p']:.3f}"
        egger_note = (
            f" Egger's 检验显示出版偏倚{bias_word}，*b*₀ = {eg['b0']:.2f}，"
            f"*SE* = {eg['se_b0']:.2f}，*t*({eg['df']}) = {eg['t']:.2f}，"
            f"*p* {p_eg_str}。"
        )

    p_fmt = lambda p: "< .001" if p < 0.001 else f"= {p:.3f}"
    ci = r["ci"]
    theta = r["theta"]
    se = r["se"]

    lines = [
        f"本元分析纳入 {k} 项研究，采用 DerSimonian-Laird 随机效应模型。"
        f"汇总效应量为 *{sym}* = {theta:.2f}（95% CI [{ci[0]:.2f}, {ci[1]:.2f}]），"
        f"*SE* = {se:.2f}，*z* = {r['z']:.2f}，*p* {p_fmt(r['p'])}。",
        f"异质性检验结果：*Q*({h['df']}) = {h['Q']:.2f}，*p* {p_fmt(h['p_Q'])}，"
        f"*I*² = {h['I2']:.1f}%（{_i2_interp(h['I2'])}异质性），τ² = {h['tau2']:.4f}，τ = {h['tau']:.4f}。",
    ]
    if egger_note:
        lines.append(egger_note)
    return " ".join(lines)


def forest_plot_text(result: dict, width: int = 60) -> str:
    """ASCII 森林图（仅用于终端输出）。"""
    studies = result["studies"]
    r = result["random"]
    h = result["heterogeneity"]

    all_vals = ([s["d"] for s in studies]
                + [r["ci"][0], r["ci"][1]])
    lo = min(all_vals)
    hi = max(all_vals)
    span = hi - lo or 1.0
    pad = span * 0.1
    lo -= pad
    hi += pad

    def to_col(v: float) -> int:
        return int((v - lo) / (hi - lo) * (width - 1))

    def draw_line(d: float, ci_l: float, ci_u: float, diamond: bool = False) -> str:
        line = [" "] * width
        lc = max(0, to_col(ci_l))
        rc = min(width - 1, to_col(ci_u))
        for i in range(lc, rc + 1):
            line[i] = "─"
        mc = max(0, min(width - 1, to_col(d)))
        line[mc] = "◆" if diamond else "■"
        # 零线
        zero_c = to_col(0.0)
        if 0 <= zero_c < width and line[zero_c] == " ":
            line[zero_c] = "│"
        return "".join(line)

    label_w = max(len(s["label"]) for s in studies) + 2
    label_w = max(label_w, 10)

    sep = "─" * (label_w + width + 32)
    header = f"{'研究':<{label_w}} {'效应量区间':<{width}} {'效应量 [95% CI]':>20}  W%"
    rows = [header, sep]

    for s in studies:
        ci_l = s["d"] - _norm_ppf_two_sided_95() * s["se"]
        ci_u = s["d"] + _norm_ppf_two_sided_95() * s["se"]
        bar = draw_line(s["d"], ci_l, ci_u)
        label = s["label"][:label_w].ljust(label_w)
        eff_str = f"{s['d']:+.3f} [{ci_l:+.3f}, {ci_u:+.3f}]"
        rows.append(f"{label} {bar} {eff_str:>20}  {s.get('weight_pct', 0):4.1f}%")

    rows.append(sep)
    r_ci = r["ci"]
    bar_re = draw_line(r["theta"], r_ci[0], r_ci[1], diamond=True)
    eff_str_re = f"{r['theta']:+.3f} [{r_ci[0]:+.3f}, {r_ci[1]:+.3f}]"
    rows.append(f"{'RE 模型':<{label_w}} {bar_re} {eff_str_re:>20}  100.0%")
    rows.append(sep)
    rows.append(f"异质性: Q({h['df']})={h['Q']:.2f}, p={h['p_Q']:.3f}, I²={h['I2']:.1f}%, τ²={h['tau2']:.4f}")
    return "\n".join(rows)


def write_sidecar(result: dict, output_dir: Path) -> Path:
    """写 notes/meta_result.json（门禁检查用）。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "meta_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# 命令入口
# ---------------------------------------------------------------------------

def meta_cli(argv: list[str] | None = None) -> int:
    """psyclaw meta <data.csv> [--json] [--out dir] [--forest] 入口。"""
    import argparse
    p = argparse.ArgumentParser(prog="psyclaw meta", description="元分析（DerSimonian-Laird）")
    p.add_argument("csv", help="效应量 CSV 文件（必须含 study, d/g/r, se/ci/n 列）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--out", default="notes", help="sidecar 输出目录（默认 notes/）")
    p.add_argument("--forest", action="store_true", default=True, help="输出 ASCII 森林图（默认开）")
    p.add_argument("--no-forest", action="store_false", dest="forest", help="不输出森林图")
    args = p.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"错误: 文件不存在 — {csv_path}")
        return 1
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
        eff_type, studies = _parse_csv(text)
        result = compute_meta(studies, eff_type)
    except (ValueError, KeyError) as exc:
        print(f"错误: {exc}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(format_apa(result))
    print()
    if args.forest:
        print(forest_plot_text(result))
        print()

    out_dir = Path(args.out)
    sidecar = write_sidecar(result, out_dir)
    print(f"sidecar → {sidecar}")
    return 0
