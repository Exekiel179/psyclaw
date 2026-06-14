"""缺失数据报告 — Little's MCAR 检验、MAR 预测、插补策略推荐、APA-7 段落（stdlib only）。

入口: psyclaw missing <data.csv>

四步分析：
  1. 缺失模式矩阵       — 各缺失模式频次与缺失比例
  2. Little's MCAR 检验  — d² ~ χ² 检验数据是否 MCAR（完整案例估计协方差）
  3. MAR 预测（分组比较）— 每个含缺失变量 vs 预测变量组的 t 检验
  4. 插补策略推荐        — 据 MCAR/MAR 结果的规则型推荐 + APA-7 缺失报告段落

理论依据：
  Little (1988), Biometrics — MCAR 测试
  Rubin (1976), Biometrika — MCAR/MAR/MNAR 分类框架
  van Buuren & Groothuis-Oudshoorn (2011), JSS — mice 插补策略
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from psyclaw.psych.careless import _mat_inv
from psyclaw.psych.stats_core import chi2_sf, t_sf2


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _is_numeric(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _load_csv(path: str) -> tuple[list[str], list[dict]]:
    """读取 CSV，返回 (headers, rows_as_dicts)。缺失值统一为 None。"""
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


def _numeric_cols(headers: list[str], rows: list[dict]) -> list[str]:
    """返回全部（或主要）数值型列。"""
    result = []
    for h in headers:
        vals = [r[h] for r in rows if r.get(h) is not None]
        if vals and sum(1 for v in vals if _is_numeric(v)) / len(vals) >= 0.5:
            result.append(h)
    return result


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 步骤 1：缺失模式矩阵
# ---------------------------------------------------------------------------

def missing_pattern(rows: list[dict], headers: list[str]) -> dict:
    """计算缺失模式矩阵。

    Returns:
        {
          "n_rows": int,
          "n_cols": int,
          "headers": [...],
          "missing_pct_per_col": {col: pct},   # 各列缺失比例（0-1）
          "n_complete": int,                     # 完整行数
          "patterns": [
              {"pattern": [0,1,0,...], "count": int, "pct": float},
              ...
          ],
          "overall_missing_pct": float,          # 全局缺失比
        }
    """
    n = len(rows)
    k = len(headers)
    if n == 0 or k == 0:
        return {"n_rows": 0, "n_cols": k, "headers": headers,
                "missing_pct_per_col": {}, "n_complete": 0,
                "patterns": [], "overall_missing_pct": 0.0}

    # 各列缺失比例
    col_miss = {h: sum(1 for r in rows if r.get(h) is None) / n for h in headers}

    # 缺失模式（每行一个二进制元组：0=观测，1=缺失）
    pattern_counts: dict[tuple, int] = {}
    for r in rows:
        pat = tuple(0 if r.get(h) is not None else 1 for h in headers)
        pattern_counts[pat] = pattern_counts.get(pat, 0) + 1

    patterns = sorted(
        [{"pattern": list(p), "count": c, "pct": round(c / n, 4)}
         for p, c in pattern_counts.items()],
        key=lambda x: -x["count"],
    )
    n_complete = sum(c for p, c in pattern_counts.items() if sum(p) == 0)
    total_cells = n * k
    total_missing = sum(sum(p) * c for p, c in pattern_counts.items())

    return {
        "n_rows": n,
        "n_cols": k,
        "headers": headers,
        "missing_pct_per_col": {h: round(v, 4) for h, v in col_miss.items()},
        "n_complete": n_complete,
        "patterns": patterns,
        "overall_missing_pct": round(total_missing / total_cells, 4) if total_cells else 0.0,
    }


# ---------------------------------------------------------------------------
# 步骤 2：Little's MCAR 检验（stdlib，完整案例协方差估计）
# ---------------------------------------------------------------------------

def little_mcar_test(rows: list[dict], numeric_cols: list[str]) -> dict:
    """Little (1988) MCAR 检验（纯 stdlib，完整案例估计均值与协方差）。

    算法：
      1. 完整案例（无缺失行）估计均值 μ̂ 和协方差 Σ̂
      2. 按缺失模式分组，对每个非完整模式计算观测变量均值 ȳ_j
      3. d²_j = n_j * (ȳ_j - μ̂_j)ᵀ Σ̂_j⁻¹ (ȳ_j - μ̂_j)
      4. D² = Σ d²_j ~ χ²(df)
      5. df = Σ_{非完整模式 j} |O_j|（O_j = 模式 j 中被观测到的变量数）

    Returns:
        {
          "statistic": float,   # D²
          "df": int,
          "p_value": float,
          "verdict": "MCAR" | "not_MCAR" | "insufficient_data",
          "n_complete_cases": int,
          "note": str,          # 方法说明
        }
    """
    k = len(numeric_cols)
    if k < 2:
        return {"statistic": None, "df": None, "p_value": None,
                "verdict": "insufficient_data",
                "n_complete_cases": 0,
                "note": "需至少 2 个数值变量才能跑 MCAR 检验"}

    # 完整案例行
    def _row_vals(r: dict) -> list[float] | None:
        vals = [_to_float(r.get(c)) for c in numeric_cols]
        return vals if all(v is not None for v in vals) else None

    complete: list[list[float]] = [v for r in rows if (v := _row_vals(r)) is not None]
    nc = len(complete)
    if nc < k + 2:
        return {"statistic": None, "df": None, "p_value": None,
                "verdict": "insufficient_data",
                "n_complete_cases": nc,
                "note": f"完整案例数 {nc} < {k + 2}，无法估计协方差"}

    # 完整案例估计均值和协方差
    mu = [sum(row[j] for row in complete) / nc for j in range(k)]
    cov = [[0.0] * k for _ in range(k)]
    for row in complete:
        d = [row[j] - mu[j] for j in range(k)]
        for a in range(k):
            for b in range(k):
                cov[a][b] += d[a] * d[b]
    for a in range(k):
        for b in range(k):
            cov[a][b] /= max(nc - 1, 1)
    for i in range(k):
        cov[i][i] += 1e-10  # 正则化防奇异

    # 按缺失模式分组（只考虑非完整模式）
    pattern_rows: dict[tuple, list[list[float]]] = {}
    for r in rows:
        vals_opt = [_to_float(r.get(c)) for c in numeric_cols]
        obs_mask = tuple(0 if v is None else 1 for v in vals_opt)
        if sum(obs_mask) == k:
            continue  # 完整模式，不贡献
        if sum(obs_mask) == 0:
            continue  # 全缺失，无法计算均值
        key = obs_mask
        observed_vals = [vals_opt[j] for j in range(k) if obs_mask[j]]
        pattern_rows.setdefault(key, []).append(observed_vals)

    d2_total = 0.0
    df_total = 0

    for obs_mask, pvals in pattern_rows.items():
        obs_idx = [j for j in range(k) if obs_mask[j]]
        p_j = len(obs_idx)
        n_j = len(pvals)
        if n_j < 2:
            continue

        # 子均值
        mu_j = [mu[j] for j in obs_idx]
        y_j = [sum(row[i] for row in pvals) / n_j for i in range(p_j)]
        diff = [y_j[i] - mu_j[i] for i in range(p_j)]

        # 子协方差矩阵
        sub_cov = [[cov[obs_idx[a]][obs_idx[b]] for b in range(p_j)]
                   for a in range(p_j)]
        try:
            sub_inv = _mat_inv(sub_cov)
        except ValueError:
            continue  # 奇异，跳过这个模式

        # 二次型 n_j * dᵀ Σ⁻¹ d
        qf = sum(diff[a] * sub_inv[a][b] * diff[b]
                 for a in range(p_j) for b in range(p_j))
        d2_total += n_j * qf
        df_total += p_j

    if df_total == 0:
        return {"statistic": 0.0, "df": 0, "p_value": 1.0,
                "verdict": "MCAR",
                "n_complete_cases": nc,
                "note": "无含缺失数据的模式（所有缺失模式 n < 2）"}

    p_val = chi2_sf(d2_total, df_total)
    verdict = "MCAR" if p_val >= 0.05 else "not_MCAR"

    return {
        "statistic": round(d2_total, 4),
        "df": df_total,
        "p_value": round(p_val, 4),
        "verdict": verdict,
        "n_complete_cases": nc,
        "note": ("完整案例估计协方差（近似）；p ≥ .05 → 不能拒绝 MCAR"),
    }


# ---------------------------------------------------------------------------
# 步骤 3：MAR 预测（分组 t 检验）
# ---------------------------------------------------------------------------

def mar_test(rows: list[dict], target_col: str, predictor_cols: list[str]) -> dict:
    """检验 target_col 的缺失是否与 predictor_cols 的值相关（MAR 指征）。

    方法：对每个 predictor，做两样本 t 检验比较
      group_obs  = predictor 值（当 target 已观测时）
      group_miss = predictor 值（当 target 缺失时）
    显著（p < .05）→ 该 predictor 预测了 target 的缺失 → MAR 指征

    Returns:
        {
          "target": col_name,
          "n_missing": int,
          "n_observed": int,
          "predictors": [
              {"predictor": col, "t": float, "df": float, "p": float,
               "mean_obs": float, "mean_miss": float, "significant": bool},
              ...
          ],
          "any_significant": bool,
          "verdict": "MAR_likely" | "MCAR_consistent" | "insufficient_data",
        }
    """
    obs_group: list[float] = []
    miss_group: list[float] = []
    for r in rows:
        target_val = _to_float(r.get(target_col))
        is_missing = target_val is None

        for pc in predictor_cols:
            _ = pc  # done per predictor below

        if is_missing:
            miss_group.append(1)
        else:
            obs_group.append(1)

    n_miss = sum(1 for r in rows if r.get(target_col) is None)
    n_obs = len(rows) - n_miss

    if n_miss < 2 or n_obs < 2:
        return {
            "target": target_col,
            "n_missing": n_miss,
            "n_observed": n_obs,
            "predictors": [],
            "any_significant": False,
            "verdict": "insufficient_data",
        }

    predictor_results = []
    for pc in predictor_cols:
        if pc == target_col:
            continue
        g_obs = [_to_float(r[pc]) for r in rows
                 if r.get(target_col) is not None and _to_float(r.get(pc)) is not None]
        g_miss = [_to_float(r[pc]) for r in rows
                  if r.get(target_col) is None and _to_float(r.get(pc)) is not None]
        if len(g_obs) < 2 or len(g_miss) < 2:
            continue

        n1, n2 = len(g_obs), len(g_miss)
        m1 = sum(g_obs) / n1
        m2 = sum(g_miss) / n2
        var1 = sum((x - m1) ** 2 for x in g_obs) / max(n1 - 1, 1)
        var2 = sum((x - m2) ** 2 for x in g_miss) / max(n2 - 1, 1)

        pooled = var1 / n1 + var2 / n2
        if pooled < 1e-15:
            continue

        t_stat = (m1 - m2) / math.sqrt(pooled)
        # Welch df
        df_w = pooled ** 2 / (
            (var1 / n1) ** 2 / max(n1 - 1, 1) + (var2 / n2) ** 2 / max(n2 - 1, 1)
        ) if pooled > 0 else 1.0
        p_val = t_sf2(abs(t_stat), max(df_w, 1.0))

        predictor_results.append({
            "predictor": pc,
            "t": round(t_stat, 4),
            "df": round(df_w, 2),
            "p": round(p_val, 4),
            "mean_obs": round(m1, 4),
            "mean_miss": round(m2, 4),
            "significant": p_val < 0.05,
        })

    any_sig = any(pr["significant"] for pr in predictor_results)
    verdict = "MAR_likely" if any_sig else "MCAR_consistent"
    if not predictor_results:
        verdict = "insufficient_data"

    return {
        "target": target_col,
        "n_missing": n_miss,
        "n_observed": n_obs,
        "predictors": predictor_results,
        "any_significant": any_sig,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# 步骤 4：插补策略推荐
# ---------------------------------------------------------------------------

def recommend_imputation(
    overall_missing_pct: float,
    mcar_verdict: str | None,
    mar_summary: dict | None,
) -> dict:
    """基于缺失类型与比例给出推荐插补策略。

    Returns:
        {
          "primary": str,       # 首选策略
          "alternatives": [...],
          "warnings": [...],
          "rationale": str,
        }
    """
    pct = overall_missing_pct
    is_mcar = mcar_verdict == "MCAR"
    is_mar = (mar_summary or {}).get("any_significant", False)
    warnings = []
    alternatives = []

    if pct > 0.20:
        warnings.append(f"缺失比例较高（{pct:.1%}），插补结果不确定性大，建议咨询统计专家")
    if pct > 0.50:
        warnings.append("缺失比例超过 50%，任何插补策略结论都应谨慎")

    if pct < 0.05 and is_mcar:
        primary = "完整案例分析（listwise deletion）"
        rationale = (f"缺失比例 {pct:.1%} 较低且数据 MCAR，完整案例分析效率损失可接受；"
                     "仍推荐多重插补（MI）以最大化功效。")
        alternatives = ["均值/中位数单一插补", "多重插补（MI，mice）"]
    elif is_mar:
        primary = "多重插补（Multiple Imputation，MI）"
        rationale = ("MAR 检验显著：其他变量预测了缺失，单一删除/替换引入偏差。"
                     "推荐用 mice/Amelia/R-mice 做多重插补，合并结果（Rubin's rules）。")
        alternatives = ["完全信息最大似然（FIML，适用于 SEM/MLM）", "贝叶斯插补"]
        warnings.append("MAR 假设仍不可证伪；建议敏感性分析（compare CC vs MI 结果）")
    elif is_mcar:
        primary = "均值/中位数单一插补 或 多重插补（MI）"
        rationale = (f"数据 MCAR（p ≥ .05），单一插补可接受（缺失比例 {pct:.1%}）；"
                     "但多重插补提供更准确的标准误，仍为首选（van Buuren, 2018）。")
        alternatives = ["完整案例分析", "热卡插补（hot-deck）"]
    else:
        primary = "多重插补（MI）"
        rationale = ("MCAR 检验未运行或不确定；保守起见推荐多重插补，"
                     "并报告完整案例分析作为敏感性对照。")
        alternatives = ["完整案例分析（敏感性分析对照）"]

    return {
        "primary": primary,
        "alternatives": alternatives,
        "warnings": warnings,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# APA-7 缺失报告段落
# ---------------------------------------------------------------------------

def format_apa_missing(
    pattern_result: dict,
    mcar_result: dict,
    mar_results: list[dict] | None = None,
    imputation: dict | None = None,
) -> str:
    """生成 APA-7 格式的缺失数据报告段落。"""
    lines: list[str] = []

    n = pattern_result.get("n_rows", 0)
    k = pattern_result.get("n_cols", 0)
    overall_pct = pattern_result.get("overall_missing_pct", 0.0)
    n_complete = pattern_result.get("n_complete", 0)
    n_patterns = len(pattern_result.get("patterns", []))

    lines.append("## 缺失数据报告")
    lines.append("")
    lines.append(
        f"在 {n} 名参与者 × {k} 个变量的数据集中，"
        f"总体缺失比例为 {overall_pct:.1%}。"
        f"共有 {n_complete} 名参与者（{n_complete/n:.1%}）提供了完整数据，"
        f"数据呈现 {n_patterns} 种缺失模式。"
    )

    # 各列缺失比例（仅报告有缺失的列）
    col_miss = {c: v for c, v in pattern_result.get("missing_pct_per_col", {}).items() if v > 0}
    if col_miss:
        top = sorted(col_miss.items(), key=lambda x: -x[1])[:5]
        desc = "；".join(f"{c}（{v:.1%}）" for c, v in top)
        lines.append(f"缺失最多的变量为：{desc}。")

    # MCAR 检验
    chi2 = mcar_result.get("statistic")
    df = mcar_result.get("df")
    p = mcar_result.get("p_value")
    verdict = mcar_result.get("verdict", "insufficient_data")

    if chi2 is not None and df is not None and p is not None:
        p_str = f"*p* = {p:.3f}" if p >= 0.001 else "*p* < .001"
        lines.append(
            f"采用 Little（1988）MCAR 检验评估缺失机制，"
            f"结果为 *d*²({df}) = {chi2:.2f}，{p_str}。"
        )
        if verdict == "MCAR":
            lines.append("检验结果不拒绝完全随机缺失（MCAR）假设。")
        else:
            lines.append(
                "检验结果拒绝 MCAR 假设（*p* < .05），提示数据可能非随机缺失（MAR 或 MNAR）。"
            )
    else:
        lines.append(mcar_result.get("note", "MCAR 检验未能运行（完整案例不足）。"))

    # MAR 预测
    if mar_results:
        sig_pairs = [(r["target"], r) for r in mar_results if r.get("any_significant")]
        if sig_pairs:
            lines.append(
                "分组比较分析表明，部分变量的缺失与其他变量的取值显著相关，"
                "提示随机缺失（MAR）机制（"
                + "；".join(
                    f"{t}: {', '.join(p['predictor'] for p in r['predictors'] if p['significant'])}"
                    for t, r in sig_pairs[:3]
                )
                + "）。"
            )
        else:
            lines.append("分组比较分析未发现缺失与其他变量存在显著关联，与 MCAR 假设一致。")

    # 插补策略
    if imputation:
        lines.append(f"据此，本研究采用{imputation['primary']}处理缺失数据。")
        if imputation.get("warnings"):
            for w in imputation["warnings"]:
                lines.append(f"注意：{w}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主分析入口（CLI 用）
# ---------------------------------------------------------------------------

def analyze_missing(
    data_path: str,
    out_dir: str | None = None,
    json_out: bool = False,
) -> dict:
    """加载 CSV，运行四步缺失分析，写报告，返回完整结果 dict。"""
    headers, rows = _load_csv(data_path)
    num_cols = _numeric_cols(headers, rows)
    miss_cols = [c for c in headers
                 if any(r.get(c) is None for r in rows)]

    # 步骤 1
    pat = missing_pattern(rows, headers)

    # 步骤 2
    mcar = little_mcar_test(rows, num_cols)

    # 步骤 3
    mar_results = [
        mar_test(rows, col, [c for c in num_cols if c != col])
        for col in miss_cols if col in num_cols
    ]

    # 步骤 4
    imp = recommend_imputation(
        pat["overall_missing_pct"],
        mcar["verdict"],
        {"any_significant": any(r["any_significant"] for r in mar_results)} if mar_results else None,
    )

    # APA-7 段落
    apa = format_apa_missing(pat, mcar, mar_results, imp)

    result = {
        "data_path": data_path,
        "n_rows": pat["n_rows"],
        "n_cols": pat["n_cols"],
        "pattern": pat,
        "mcar": mcar,
        "mar": mar_results,
        "imputation": imp,
        "apa_paragraph": apa,
    }

    if out_dir:
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)
        (od / "missing_report.md").write_text(apa, encoding="utf-8")
        if json_out:
            (od / "missing_report.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


# ---------------------------------------------------------------------------
# CLI 薄入口
# ---------------------------------------------------------------------------

def missing_cli(argv: list[str]) -> int:
    """psyclaw missing <data.csv> [--json] [--out <dir>]"""
    import sys

    data_path = None
    json_out = False
    out_dir = None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            json_out = True
        elif a == "--out":
            i += 1
            if i < len(argv):
                out_dir = argv[i]
        elif not a.startswith("-"):
            data_path = a
        i += 1

    if not data_path:
        print("用法: psyclaw missing <data.csv> [--json] [--out <dir>]", file=sys.stderr)
        return 1

    if not Path(data_path).exists():
        print(f"错误: 找不到文件 {data_path}", file=sys.stderr)
        return 1

    try:
        result = analyze_missing(data_path, out_dir=out_dir, json_out=json_out)
    except Exception as exc:  # noqa: BLE001
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(result["apa_paragraph"])
    print()

    # 摘要
    pat = result["pattern"]
    mcar = result["mcar"]
    print(f"── 缺失概况 ──────────────────────────────")
    print(f"总体缺失比：{pat['overall_missing_pct']:.1%}")
    print(f"完整案例数：{pat['n_complete']}/{pat['n_rows']}")
    print(f"缺失模式数：{len(pat['patterns'])}")
    if mcar.get("statistic") is not None:
        print(f"MCAR 检验：d²({mcar['df']}) = {mcar['statistic']:.2f}，"
              f"p = {mcar['p_value']:.3f}  [{mcar['verdict']}]")
    print(f"推荐策略：{result['imputation']['primary']}")

    if out_dir:
        print(f"\n报告已写入: {out_dir}/missing_report.md")

    return 0
