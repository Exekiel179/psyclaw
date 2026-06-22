"""ROC 曲线 / AUC 诊断准确性分析（Diagnostic Accuracy）— APA-7 格式（stdlib only）。

用于量表筛查截断值（cutoff）验证：给定连续预测分（如 PHQ-9 总分）与二元金标准
结局（0/1，如临床诊断），评估其区分能力并推荐最优截断点。

提供：
  - roc_auc: AUC（一致性/Wilcox-Mann-Whitney 法，精确含 .5 平局）
            + Hanley & McNeil (1982) 渐近 SE → Wald z/p + 95% CI
  - roc_curve: 全阈值 ROC 点（敏感度 / 特异度 / FPR）
  - optimal_cutoff: Youden's J 最大化的最优截断点 + 该点诊断指标
                    （敏感度 / 特异度 / 准确率 / PPV / NPV / LR+ / LR−）
  - interpret_auc: AUC 言语解读（Hosmer, Lemeshow & Sturdivant 2013）
  - APA-7 Markdown 三线表 + 文字段落
  - CSV 主入口 + MD/JSON sidecar + CLI

理论依据：
  Hanley, J. A., & McNeil, B. J. (1982). The meaning and use of the area under a
    receiver operating characteristic (ROC) curve. Radiology, 143(1), 29–36.
    https://doi.org/10.1148/radiology.143.1.7063747
  Youden, W. J. (1950). Index for rating diagnostic tests. Cancer, 3(1), 32–35.
    https://doi.org/10.1002/1097-0142(1950)3:1<32::AID-CNCR2820030106>3.0.CO;2-3
  Hosmer, D. W., Lemeshow, S., & Sturdivant, R. X. (2013). Applied logistic
    regression (3rd ed.). Wiley.
  DeLong, E. R., DeLong, D. M., & Clarke-Pearson, D. L. (1988). Comparing the areas
    under two or more correlated ROC curves. Biometrics, 44(3), 837–845.

CLI:
  psyclaw roc <data.csv> --score col --outcome col
          [--direction higher|lower] [--positive 1] [--alpha .05] [--json] [--out dir]
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

from scipy import special


# ---------------------------------------------------------------------------
# 分布工具（stdlib only）
# ---------------------------------------------------------------------------

def _norm_cdf(z: float) -> float:
    """标准正态分布 CDF —— scipy.special.ndtr。"""
    return float(special.ndtr(z))


def _norm_sf2(z: float) -> float:
    """标准正态双尾 p 值（经 _norm_cdf → scipy）。"""
    return 2.0 * (1.0 - _norm_cdf(abs(z)))


def _norm_ppf(p: float) -> float:
    """标准正态分布分位数 —— scipy.special.ndtri。"""
    if not 0 < p < 1:
        return float("nan")
    return float(special.ndtri(p))


# ---------------------------------------------------------------------------
# 核心 AUC（一致性 / Wilcoxon-Mann-Whitney 法）
# ---------------------------------------------------------------------------

def _split_groups(
    scores: list[float],
    outcomes: list[int],
    direction: str,
) -> tuple[list[float], list[float]]:
    """按结局拆分阳性/阴性组分数；direction='lower' 时取负使「高分=阳性」统一。"""
    if direction not in ("higher", "lower"):
        raise ValueError(f"direction 必须是 'higher' 或 'lower'，got {direction!r}")
    sign = 1.0 if direction == "higher" else -1.0
    pos = [sign * s for s, o in zip(scores, outcomes) if o == 1]
    neg = [sign * s for s, o in zip(scores, outcomes) if o == 0]
    return pos, neg


def _auc_concordance(pos: list[float], neg: list[float]) -> float:
    """AUC = P(score_pos > score_neg) + .5·P(=)，对所有阳/阴配对计数（平局记 .5）。

    等价于梯形法 ROC 曲线下面积，也等价于 Wilcoxon-Mann-Whitney 统计量。
    采用排序法 O((n+m) log(n+m)) 而非 O(n·m) 暴力配对。
    """
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # 合并排序，赋平均秩（处理平局）；AUC = (R_pos - n_pos(n_pos+1)/2) / (n_pos·n_neg)
    combined = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg], key=lambda t: t[0])
    n = len(combined)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    r_pos = sum(ranks[k] for k in range(n) if combined[k][1] == 1)
    u_pos = r_pos - n_pos * (n_pos + 1) / 2.0
    return u_pos / (n_pos * n_neg)


def _hanley_mcneil_se(auc: float, n_pos: int, n_neg: int) -> float:
    """Hanley & McNeil (1982) AUC 渐近标准误。"""
    if n_pos < 1 or n_neg < 1 or not math.isfinite(auc):
        return float("nan")
    q1 = auc / (2.0 - auc)
    q2 = 2.0 * auc * auc / (1.0 + auc)
    var = (
        auc * (1.0 - auc)
        + (n_pos - 1) * (q1 - auc * auc)
        + (n_neg - 1) * (q2 - auc * auc)
    ) / (n_pos * n_neg)
    if var < 0:
        var = 0.0
    return math.sqrt(var)


def roc_auc(
    scores: list[float],
    outcomes: list[int],
    direction: str = "higher",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """AUC + Hanley-McNeil SE + Wald 检验（H0: AUC=0.5）+ 95% CI。

    参数
    ----
    scores    : 连续预测分（如量表总分）
    outcomes  : 二元结局，1=阳性（病例）/ 0=阴性（对照）
    direction : 'higher'（高分→阳性，默认）| 'lower'（低分→阳性）
    alpha     : 显著性水平（双尾 CI）

    返回
    ----
    {auc, se, z, p, ci_lower, ci_upper, n, n_pos, n_neg, direction, alpha}
    """
    n = len(scores)
    if n != len(outcomes):
        raise ValueError(f"scores 长度 {n} 与 outcomes 长度 {len(outcomes)} 不一致")
    pos, neg = _split_groups(scores, outcomes, direction)
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("阳性组与阴性组都必须至少有 1 个观测")

    auc = _auc_concordance(pos, neg)
    se = _hanley_mcneil_se(auc, n_pos, n_neg)

    if math.isfinite(se) and se > 0:
        z = (auc - 0.5) / se
        p_val = _norm_sf2(z)
        z_crit = _norm_ppf(1.0 - alpha / 2.0)
        ci_lower = max(0.0, auc - z_crit * se)
        ci_upper = min(1.0, auc + z_crit * se)
    else:
        # 完美区分（AUC=1）或退化：SE→0
        z = float("inf") if auc > 0.5 else (float("-inf") if auc < 0.5 else 0.0)
        p_val = 0.0 if auc != 0.5 else 1.0
        ci_lower = ci_upper = auc

    return {
        "auc": round(auc, 6) if math.isfinite(auc) else None,
        "se": round(se, 6) if math.isfinite(se) else None,
        "z": round(z, 6) if math.isfinite(z) else None,
        "p": round(p_val, 6) if math.isfinite(p_val) else None,
        "ci_lower": round(ci_lower, 6),
        "ci_upper": round(ci_upper, 6),
        "n": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "direction": direction,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# ROC 曲线点
# ---------------------------------------------------------------------------

def _confusion_at(
    scores: list[float],
    outcomes: list[int],
    threshold: float,
    direction: str,
) -> tuple[int, int, int, int]:
    """在阈值处的混淆矩阵 (TP, FP, TN, FN)。

    direction='higher': 预测阳性当 score >= threshold；'lower': score <= threshold。
    """
    tp = fp = tn = fn = 0
    for s, o in zip(scores, outcomes):
        pred = (s >= threshold) if direction == "higher" else (s <= threshold)
        if pred and o == 1:
            tp += 1
        elif pred and o == 0:
            fp += 1
        elif (not pred) and o == 0:
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def _metrics_from_confusion(tp: int, fp: int, tn: int, fn: int) -> dict[str, float]:
    """由混淆矩阵导出诊断指标。"""
    sens = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    spec = tn / (tn + fp) if (tn + fp) > 0 else float("nan")
    ppv = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    npv = tn / (tn + fn) if (tn + fn) > 0 else float("nan")
    total = tp + fp + tn + fn
    acc = (tp + tn) / total if total > 0 else float("nan")
    youden = (sens + spec - 1.0) if (math.isfinite(sens) and math.isfinite(spec)) else float("nan")
    # 似然比
    lr_pos = (sens / (1.0 - spec)) if (math.isfinite(sens) and math.isfinite(spec) and spec < 1.0) else float("inf")
    lr_neg = ((1.0 - sens) / spec) if (math.isfinite(sens) and math.isfinite(spec) and spec > 0.0) else float("inf")
    return {
        "sensitivity": sens,
        "specificity": spec,
        "ppv": ppv,
        "npv": npv,
        "accuracy": acc,
        "youden_j": youden,
        "lr_pos": lr_pos,
        "lr_neg": lr_neg,
    }


def roc_curve(
    scores: list[float],
    outcomes: list[int],
    direction: str = "higher",
) -> dict[str, Any]:
    """全阈值 ROC 曲线点。

    返回
    ----
    {points: [{threshold, sensitivity, specificity, fpr, youden_j}, ...],
     n_pos, n_neg, direction}
    曲线含端点 (FPR=0, TPR=0) 与 (FPR=1, TPR=1)，按 FPR 升序。
    """
    n = len(scores)
    if n != len(outcomes):
        raise ValueError(f"scores 长度 {n} 与 outcomes 长度 {len(outcomes)} 不一致")
    n_pos = sum(1 for o in outcomes if o == 1)
    n_neg = sum(1 for o in outcomes if o == 0)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("阳性组与阴性组都必须至少有 1 个观测")

    uniq = sorted(set(scores))
    # 候选阈值：每个唯一分数 + 一个超过端点的阈值（产生 (0,0) 点）
    if direction == "higher":
        # 阈值从高到低 → FPR 升序；附加 max+1 使无人预测阳性
        thresholds = [uniq[-1] + 1.0] + list(reversed(uniq))
    else:
        thresholds = [uniq[0] - 1.0] + list(uniq)

    points = []
    for t in thresholds:
        tp, fp, tn, fn = _confusion_at(scores, outcomes, t, direction)
        m = _metrics_from_confusion(tp, fp, tn, fn)
        sens = m["sensitivity"]
        spec = m["specificity"]
        fpr = 1.0 - spec if math.isfinite(spec) else float("nan")
        points.append({
            "threshold": t,
            "sensitivity": round(sens, 6) if math.isfinite(sens) else None,
            "specificity": round(spec, 6) if math.isfinite(spec) else None,
            "fpr": round(fpr, 6) if math.isfinite(fpr) else None,
            "youden_j": round(m["youden_j"], 6) if math.isfinite(m["youden_j"]) else None,
        })

    return {
        "points": points,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "direction": direction,
    }


# ---------------------------------------------------------------------------
# 最优截断点（Youden's J）
# ---------------------------------------------------------------------------

def optimal_cutoff(
    scores: list[float],
    outcomes: list[int],
    direction: str = "higher",
) -> dict[str, Any]:
    """Youden's J = 敏感度 + 特异度 − 1 最大化的最优截断点。

    仅在实际观测到的唯一分数上搜索（不含曲线端点伪阈值）。
    返回该截断点处全部诊断指标。
    """
    n = len(scores)
    if n != len(outcomes):
        raise ValueError(f"scores 长度 {n} 与 outcomes 长度 {len(outcomes)} 不一致")
    n_pos = sum(1 for o in outcomes if o == 1)
    n_neg = sum(1 for o in outcomes if o == 0)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("阳性组与阴性组都必须至少有 1 个观测")

    uniq = sorted(set(scores))
    best: dict[str, Any] | None = None
    for t in uniq:
        tp, fp, tn, fn = _confusion_at(scores, outcomes, t, direction)
        m = _metrics_from_confusion(tp, fp, tn, fn)
        j = m["youden_j"]
        if not math.isfinite(j):
            continue
        if best is None or j > best["_j"]:
            best = {
                "_j": j,
                "cutoff": t,
                "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                **m,
            }

    if best is None:
        raise ValueError("无法确定最优截断点（指标均不可计算）")

    def _r(v: float) -> float | None:
        return round(v, 6) if (isinstance(v, float) and math.isfinite(v)) else (
            None if isinstance(v, float) else v
        )

    return {
        "cutoff": best["cutoff"],
        "direction": direction,
        "tp": best["tp"], "fp": best["fp"], "tn": best["tn"], "fn": best["fn"],
        "sensitivity": _r(best["sensitivity"]),
        "specificity": _r(best["specificity"]),
        "ppv": _r(best["ppv"]),
        "npv": _r(best["npv"]),
        "accuracy": _r(best["accuracy"]),
        "youden_j": _r(best["youden_j"]),
        "lr_pos": _r(best["lr_pos"]),
        "lr_neg": _r(best["lr_neg"]),
    }


# ---------------------------------------------------------------------------
# 解读
# ---------------------------------------------------------------------------

def interpret_auc(auc: float) -> str:
    """AUC 言语解读（Hosmer, Lemeshow & Sturdivant 2013）。"""
    if auc is None or not math.isfinite(auc):
        return "无法计算"
    a = max(auc, 1.0 - auc)  # 对称：AUC<.5 视为反向同等区分力
    if a < 0.5 + 1e-9:
        return "无区分力（≈随机）"
    if a < 0.7:
        return "区分力差（poor）"
    if a < 0.8:
        return "区分力可接受（acceptable）"
    if a < 0.9:
        return "区分力优良（excellent）"
    return "区分力卓越（outstanding）"


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _p_str(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return "= " + f"{p:.3f}".lstrip("0")


def _fmt(v: float | None, nd: int = 3) -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return "—"
    if math.isinf(v):
        return "∞"
    return f"{v:.{nd}f}"


def format_apa_roc(
    auc_result: dict[str, Any],
    cutoff_result: dict[str, Any] | None = None,
    score_name: str = "score",
    outcome_name: str = "outcome",
) -> str:
    """APA-7 ROC/AUC Markdown 报告（汇总表 + 文字段落 + 参考文献）。"""
    auc = auc_result.get("auc")
    se = auc_result.get("se")
    p = auc_result.get("p")
    ci_lo = auc_result.get("ci_lower")
    ci_hi = auc_result.get("ci_upper")
    n = auc_result.get("n")
    n_pos = auc_result.get("n_pos")
    n_neg = auc_result.get("n_neg")
    alpha = auc_result.get("alpha", 0.05)
    direction = auc_result.get("direction", "higher")
    dir_str = "高分→阳性" if direction == "higher" else "低分→阳性"

    lines = ["## ROC 曲线 / AUC 诊断准确性分析", ""]
    lines.append(f"- **预测变量**：{score_name}（{dir_str}）")
    lines.append(f"- **结局变量**：{outcome_name}（1 = 阳性 / 0 = 阴性）")
    lines.append(f"- ***N*** = {n}（阳性 = {n_pos}，阴性 = {n_neg}）")
    lines.append("")

    ci_str = f"[{_fmt(ci_lo)}, {_fmt(ci_hi)}]" if ci_lo is not None else "—"
    interp = interpret_auc(auc) if auc is not None else "无法计算"
    lines.append(
        f"{score_name} 区分 {outcome_name} 的曲线下面积 "
        f"*AUC* = {_fmt(auc)}，*SE* = {_fmt(se)}，95% CI {ci_str}，"
        f"*p* {_p_str(p)}（H₀：AUC = .50）。区分力评级：{interp}。"
    )

    if p is not None and math.isfinite(p):
        if p < alpha:
            lines.append(
                f"AUC 在 α = {alpha} 水平上**显著**高于 .50，"
                f"表明该指标具有优于随机的诊断区分能力。"
            )
        else:
            lines.append(
                f"AUC 在 α = {alpha} 水平上**不显著**异于 .50，"
                f"尚无证据表明该指标具有诊断区分能力。"
            )

    # AUC 汇总表
    lines += ["", "### AUC 汇总表", ""]
    lines.append("| 指标 | *AUC* | *SE* | 95% CI | *z* | *p* |")
    lines.append("|------|-------|------|--------|-----|-----|")
    lines.append(
        f"| {score_name} | {_fmt(auc)} | {_fmt(se)} | {ci_str} | "
        f"{_fmt(auc_result.get('z'), 2)} | {_p_str(p)} |"
    )

    # 最优截断点
    if cutoff_result is not None:
        cut = cutoff_result.get("cutoff")
        lines += ["", "### 最优截断点（Youden's *J*）", ""]
        lines.append(
            f"以 Youden's *J* 最大化为准则，最优截断值为 **{score_name} {'≥' if direction == 'higher' else '≤'} {cut}**，"
            f"此时敏感度 = {_fmt(cutoff_result.get('sensitivity'))}，"
            f"特异度 = {_fmt(cutoff_result.get('specificity'))}，"
            f"*J* = {_fmt(cutoff_result.get('youden_j'))}。"
        )
        lines += ["", "| 指标 | 值 |", "|------|-----|"]
        rows = [
            ("截断值", str(cut)),
            ("敏感度 (Sensitivity)", _fmt(cutoff_result.get("sensitivity"))),
            ("特异度 (Specificity)", _fmt(cutoff_result.get("specificity"))),
            ("阳性预测值 (PPV)", _fmt(cutoff_result.get("ppv"))),
            ("阴性预测值 (NPV)", _fmt(cutoff_result.get("npv"))),
            ("准确率 (Accuracy)", _fmt(cutoff_result.get("accuracy"))),
            ("Youden's *J*", _fmt(cutoff_result.get("youden_j"))),
            ("阳性似然比 (LR+)", _fmt(cutoff_result.get("lr_pos"), 2)),
            ("阴性似然比 (LR−)", _fmt(cutoff_result.get("lr_neg"), 2)),
        ]
        for label, val in rows:
            lines.append(f"| {label} | {val} |")
        lines.append("")
        lines.append(
            "*注*：PPV / NPV 依赖样本患病率，外推至患病率不同的人群时须谨慎。"
        )

    lines += [
        "", "### 参考文献", "",
        "Hanley, J. A., & McNeil, B. J. (1982). The meaning and use of the area under "
        "a receiver operating characteristic (ROC) curve. *Radiology, 143*(1), 29–36. "
        "https://doi.org/10.1148/radiology.143.1.7063747",
        "",
        "Youden, W. J. (1950). Index for rating diagnostic tests. *Cancer, 3*(1), 32–35.",
        "",
        "Hosmer, D. W., Lemeshow, S., & Sturdivant, R. X. (2013). *Applied logistic "
        "regression* (3rd ed.). Wiley.",
    ]
    return "\n".join(lines)


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


def write_roc_report(
    result: dict[str, Any],
    formatted: str,
    out_dir: str | pathlib.Path,
    stem: str = "roc_report",
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

def _read_csv_cols(csv_path: str, col_names: list[str]) -> tuple[dict[str, list[str]], int]:
    """读取 CSV 指定列原始字符串，过滤任一列缺失的行，返回 {列名: 原始值列表} 与排除行数。"""
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
    data: dict[str, list[str]] = {c: [] for c in col_names}
    n_excluded = 0
    for row in rows:
        vals = {c: (row.get(c) or "").strip() for c in col_names}
        if any(v == "" for v in vals.values()):
            n_excluded += 1
            continue
        for c, v in vals.items():
            data[c].append(v)
    return data, n_excluded


def analyze_roc(
    csv_path: str,
    score_col: str,
    outcome_col: str,
    direction: str = "higher",
    positive_label: str = "1",
    alpha: float = 0.05,
    out_dir: str = "notes",
    return_json: bool = False,
) -> dict[str, Any]:
    """CSV 主入口：读取数据 → AUC + 最优截断点 → 写 sidecar。

    outcome 列按 positive_label 二值化（等于该标签→1，否则→0）。
    """
    data, n_excluded = _read_csv_cols(csv_path, [score_col, outcome_col])

    scores: list[float] = []
    outcomes: list[int] = []
    n_bad = 0
    for s_raw, o_raw in zip(data[score_col], data[outcome_col]):
        try:
            s = float(s_raw)
        except ValueError:
            n_bad += 1
            continue
        scores.append(s)
        outcomes.append(1 if o_raw == positive_label else 0)
    n_excluded += n_bad

    auc_result = roc_auc(scores, outcomes, direction=direction, alpha=alpha)
    cutoff_result = optimal_cutoff(scores, outcomes, direction=direction)
    curve = roc_curve(scores, outcomes, direction=direction)

    result: dict[str, Any] = dict(auc_result)
    result["cutoff"] = cutoff_result
    result["curve"] = curve
    result["interpretation"] = interpret_auc(auc_result.get("auc"))
    result["n_excluded"] = n_excluded
    result["score_col"] = score_col
    result["outcome_col"] = outcome_col
    result["positive_label"] = positive_label

    formatted = format_apa_roc(auc_result, cutoff_result,
                               score_name=score_col, outcome_name=outcome_col)
    paths = write_roc_report(result, formatted, out_dir)
    result["_formatted"] = formatted
    result["_paths"] = paths

    if return_json:
        return _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def roc_cli(argv: list[str]) -> int:
    import argparse
    from psyclaw import ui

    ap = argparse.ArgumentParser(
        prog="psyclaw roc",
        description="ROC 曲线 / AUC 诊断准确性分析（截断值验证，APA-7，stdlib only）",
    )
    ap.add_argument("csv", help="输入数据 CSV 路径")
    ap.add_argument("--score", required=True, dest="score_col", help="连续预测分列名")
    ap.add_argument("--outcome", required=True, dest="outcome_col",
                    help="二元结局列名（金标准诊断）")
    ap.add_argument("--direction", default="higher", choices=["higher", "lower"],
                    help="高分→阳性(higher，默认) | 低分→阳性(lower)")
    ap.add_argument("--positive", default="1", dest="positive_label",
                    help="结局列中代表「阳性」的值（默认 '1'）")
    ap.add_argument("--alpha", type=float, default=0.05, help="显著性水平（默认 .05）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")

    args = ap.parse_args(argv)

    try:
        result = analyze_roc(
            args.csv, args.score_col, args.outcome_col,
            direction=args.direction, positive_label=args.positive_label,
            alpha=args.alpha, out_dir=args.out,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(ui.err(str(exc)))
        return 1

    if args.json:
        clean = _clean_json({k: v for k, v in result.items() if not k.startswith("_")})
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return 0

    auc = result.get("auc")
    cut = result.get("cutoff", {})
    print(ui.title("ROC / AUC 诊断准确性分析"))
    print(ui.rule())
    print(f"  预测分      : {args.score_col}（{args.direction}）")
    print(f"  结局        : {args.outcome_col}（阳性 = {args.positive_label}）")
    print(f"  有效 N      : {result.get('n')}  (阳性 {result.get('n_pos')} / 阴性 {result.get('n_neg')})"
          f"  |  排除: {result.get('n_excluded', 0)}")
    print()
    if auc is not None:
        ci_lo = result.get("ci_lower")
        ci_hi = result.get("ci_upper")
        p_val = result.get("p")
        pdisp = "< .001" if (p_val is not None and p_val < 0.001) else (
            f"= {p_val:.3f}" if p_val is not None else "—")
        print(f"  AUC         : {auc:.4f}  95% CI [{ci_lo:.4f}, {ci_hi:.4f}]  p {pdisp}")
        print(f"  区分力      : {result.get('interpretation')}")
    if cut:
        op = "≥" if args.direction == "higher" else "≤"
        print()
        print(f"  最优截断    : {args.score_col} {op} {cut.get('cutoff')}")
        print(f"    敏感度    : {_fmt(cut.get('sensitivity'))}")
        print(f"    特异度    : {_fmt(cut.get('specificity'))}")
        print(f"    Youden J  : {_fmt(cut.get('youden_j'))}")

    paths = result.get("_paths", {})
    if paths.get("md"):
        print(ui.dim(f"\n  报告已写入: {paths['md']}"))
    return 0
