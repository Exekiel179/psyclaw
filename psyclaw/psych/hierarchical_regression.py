"""层级 OLS 回归（Hierarchical Multiple Regression）— APA-7 分块摘要表（stdlib only）。

提供：
  - 分块 OLS（每块继承上一块全部预测变量 + 新增变量）
  - 每块 R²、调整 R²、ΔR²、F 整体显著、F 变化量（ΔF）、df 变化量、p(ΔF)
  - 最终块完整系数表（B / β / SE / t / p / 95% CI）
  - APA-7 Markdown 分块汇总表 + 文字摘要段落
  - CSV 主入口 + MD/JSON sidecar + CLI

CLI:
  psyclaw hreg <data.csv> --dv <col> --block1 c1,c2 [--block2 c3 --block3 c4,c5 ...]
          [--alpha .05] [--json] [--out dir]

理论依据：
  Cohen, J., Cohen, P., West, S. G., & Aiken, L. S. (2003).
  Applied multiple regression/correlation analysis for the behavioral sciences (3rd ed.).
  Erlbaum.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any

from psyclaw.psych.regression import (
    _mat_transpose, _mat_mult, _mat_vec, _mat_invert,
    _betai, _t_sf2, _f_sf, _t_ppf, compute_ols,
)


# ---------------------------------------------------------------------------
# 核心：分块层级回归
# ---------------------------------------------------------------------------

def hierarchical_regression(
    y: list[float],
    blocks: list[list[str]],          # blocks[i] = 该块新增变量列名
    X_cols: dict[str, list[float]],   # 变量名 → 数值列表（对齐 y）
    dv_name: str = "y",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """对 y 做层级 OLS 回归，blocks 为各块新增变量名列表。

    返回字典包含：
      - blocks_results: 每块 OLS 结果 + ΔR² + F_change + df_change + p_change
      - final_coefficients: 最终块完整系数表
      - n, dv_name, all_iv_names
    """
    n = len(y)
    if n < 3:
        raise ValueError(f"样本量 ({n}) 不足，至少需 3 行")

    if not blocks:
        raise ValueError("至少须提供一个块（block）")

    cumulative_ivs: list[str] = []
    block_results: list[dict[str, Any]] = []
    prev_R2 = 0.0
    prev_SSE = None

    for block_idx, new_vars in enumerate(blocks):
        if not new_vars:
            raise ValueError(f"块 {block_idx + 1} 的新增变量列表不能为空")

        # 检查无重复
        overlap = set(new_vars) & set(cumulative_ivs)
        if overlap:
            raise ValueError(f"变量重复：块 {block_idx + 1} 包含已在前块中声明的变量：{overlap}")

        cumulative_ivs = cumulative_ivs + list(new_vars)

        # 构建 X 矩阵
        X = [[X_cols[iv][i] for iv in cumulative_ivs] for i in range(n)]

        ols = compute_ols(y, X, iv_names=cumulative_ivs, dv_name=dv_name, alpha=alpha)

        R2 = ols["R2"]
        delta_R2 = round(R2 - prev_R2, 4)
        k2 = len(cumulative_ivs)        # 当前块预测变量总数
        k1 = k2 - len(new_vars)         # 上一块预测变量总数
        df_change = k2 - k1             # 新增 df（即新变量个数）
        df_resid = ols["df_resid"]      # n - k2 - 1

        if block_idx == 0:
            # 第一块：ΔF = F of model (vs. intercept only)
            F_change = ols["F"]
            df_change_used = k2
            p_change = ols["F_p"]
        else:
            # ΔF = (ΔR² / df_change) / ((1 - R²) / df_resid)
            denom = (1.0 - R2) / df_resid if df_resid > 0 and R2 < 1.0 else None
            if denom and denom > 0:
                F_change = round((delta_R2 / df_change) / denom, 4)
                df_change_used = df_change
                p_change = round(_f_sf(F_change, df_change, df_resid), 4)
            else:
                F_change = None
                df_change_used = df_change
                p_change = None

        block_summary = {
            "block": block_idx + 1,
            "new_vars": list(new_vars),
            "cumulative_vars": list(cumulative_ivs),
            "n": n,
            "k": len(cumulative_ivs),
            "R2": R2,
            "R2_adj": ols["R2_adj"],
            "delta_R2": delta_R2,
            "F": ols["F"],
            "df_model": ols["df_model"],
            "df_resid": df_resid,
            "F_p": ols["F_p"],
            "F_change": F_change,
            "df_change": df_change_used,
            "p_change": p_change if p_change is not None else None,
            "ols": ols,
        }
        block_results.append(block_summary)
        prev_R2 = R2

    final_ols = block_results[-1]["ols"]

    return {
        "n": n,
        "dv_name": dv_name,
        "all_iv_names": list(cumulative_ivs),
        "n_blocks": len(blocks),
        "blocks_results": block_results,
        "final_coefficients": final_ols["coefficients"],
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# APA-7 格式化
# ---------------------------------------------------------------------------

def _fmt_p(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return "—"
    if p < 0.001:
        return "< .001"
    return f"= {p:.3f}".replace("0.", ".")


def _fmt_v(v: float | None, dec: int = 3) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    fmt = f"{v:.{dec}f}"
    # 移除前导零（APA-7 规范：不写 0.50，写 .50）
    if fmt.startswith("0."):
        return fmt[1:]
    if fmt.startswith("-0."):
        return "-" + fmt[2:]
    return fmt


def format_apa_hierarchical_table(result: dict[str, Any]) -> str:
    """生成 APA-7 层级回归分块汇总 Markdown 三线表。"""
    dv = result["dv_name"]
    lines = [
        f"*层级回归分析：预测 {dv}*",
        "",
        "| 块 | 新增变量 | *R*² | Δ*R*² | 调整 *R*² |"
        " *F*(*df*₁, *df*₂) | *p* | Δ*F*(*df*₁) | *p*(Δ*F*) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for br in result["blocks_results"]:
        new_v = ", ".join(br["new_vars"])
        r2 = _fmt_v(br["R2"])
        dr2 = _fmt_v(br["delta_R2"])
        r2adj = _fmt_v(br["R2_adj"])
        f_str = (f"{br['F']:.2f}({br['df_model']}, {br['df_resid']})"
                 if br["F"] is not None else "—")
        fp = _fmt_p(br["F_p"])
        if br["block"] == 1:
            df_ch = br["df_change"]
            fc_str = f"{br['F_change']:.2f}({df_ch})" if br["F_change"] is not None else "—"
        else:
            fc_str = f"{br['F_change']:.2f}({br['df_change']})" if br["F_change"] is not None else "—"
        pc = _fmt_p(br["p_change"])
        lines.append(
            f"| 块{br['block']} | {new_v} | {r2} | {dr2} | {r2adj} | {f_str} | {fp} | {fc_str} | {pc} |"
        )

    lines += [
        "",
        f"*注：N* = {result['n']}。所有块使用相同完整案例数据集。"
        f"Δ*F* 检验各块新增预测元对 *R*² 的增量贡献。",
    ]
    return "\n".join(lines)


def format_apa_coefficients_table(result: dict[str, Any]) -> str:
    """最终块系数表（APA-7 三线表）。"""
    dv = result["dv_name"]
    final_block = result["blocks_results"][-1]
    ols = final_block["ols"]
    df2 = ols["df_resid"]

    lines = [
        f"*最终模型系数（块 {final_block['block']}，预测 {dv}）*",
        "",
        "| 变量 | *B* | *SE* | *β* | *t* | *p* | 95% CI |",
        "|------|-----|------|-----|-----|-----|--------|",
    ]
    for c in ols["coefficients"]:
        ci = (f"[{c['ci_lower']:.2f}, {c['ci_upper']:.2f}]"
              if c["ci_lower"] is not None else "—")
        beta_str = f"{c['beta']:.2f}" if c["beta"] is not None else "—"
        p_str = _fmt_p(c["p"])
        lines.append(
            f"| {c['name']} | {c['B']:.2f} | {c['SE']:.2f} | "
            f"{beta_str} | {c['t']:.2f} | *p* {p_str} | {ci} |"
        )
    lines += [
        "",
        f"*注：df* = {df2}。95% CI 为非标准化系数置信区间。",
    ]
    return "\n".join(lines)


def format_apa_hierarchical_paragraph(result: dict[str, Any]) -> str:
    """生成 APA-7 层级回归结果文字段落。"""
    dv = result["dv_name"]
    n = result["n"]
    n_blocks = result["n_blocks"]

    paras = [
        f"以层级多元回归分析检验预测 {dv} 的增量效度（*N* = {n}）。"
        f"分析共 {n_blocks} 个步骤。"
    ]

    for br in result["blocks_results"]:
        blk = br["block"]
        new_v = "、".join(br["new_vars"])
        r2 = br["R2"]
        dr2 = br["delta_R2"]
        r2adj = br["R2_adj"]
        F = br["F"]
        df1 = br["df_model"]
        df2 = br["df_resid"]
        Fp = br["F_p"]
        Fc = br["F_change"]
        dfc = br["df_change"]
        pc = br["p_change"]

        f_str = f"*F*({df1}, {df2}) = {F:.2f}" if F is not None else ""
        fp_str = f"*p* {_fmt_p(Fp)}"
        r2_str = f"*R*² = {r2:.3f}"
        adj_str = f"（调整 *R*² = {r2adj:.3f}）" if r2adj is not None else ""

        if blk == 1:
            sent = (
                f"步骤 {blk}，纳入 {new_v}，模型整体显著，"
                f"{f_str}，{fp_str}，{r2_str}{adj_str}，"
                f"解释变异 {r2 * 100:.1f}%。"
            )
        else:
            fc_str = f"Δ*F*({dfc}, {df2}) = {Fc:.2f}" if Fc is not None else ""
            pc_str = f"*p* {_fmt_p(pc)}"
            sig = "显著" if (pc is not None and pc < 0.05) else "未达显著"
            sent = (
                f"步骤 {blk}，纳入 {new_v}，{r2_str}{adj_str}，"
                f"Δ*R*² = {dr2:.3f}，{fc_str}，{pc_str}，增量 {sig}。"
            )
        paras.append(sent)

    # 最终块显著预测变量
    final_ols = result["blocks_results"][-1]["ols"]
    df2 = final_ols["df_resid"]
    sig = [c for c in final_ols["coefficients"]
           if c["name"] != "截距 (Intercept)" and c["p"] is not None and c["p"] < 0.05]
    if sig:
        sig_strs = []
        for c in sig:
            beta = f"*β* = {c['beta']:.2f}，" if c["beta"] is not None else ""
            sig_strs.append(
                f"{c['name']}（*B* = {c['B']:.2f}，{beta}*t*({df2}) = {c['t']:.2f}，"
                f"*p* {_fmt_p(c['p'])}）"
            )
        paras.append(f"最终模型中显著预测变量：{'；'.join(sig_strs)}。")
    else:
        paras.append("最终模型中无显著预测变量（p < .05）。")

    return "\n\n".join(paras)


# ---------------------------------------------------------------------------
# MD + JSON sidecar
# ---------------------------------------------------------------------------

def write_hierarchical_report(
    result: dict[str, Any],
    out_dir: str | pathlib.Path = "notes",
) -> tuple[pathlib.Path, pathlib.Path]:
    """写 hierarchical_regression_report.md + .json。"""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 层级回归分析报告",
        "",
        format_apa_hierarchical_table(result),
        "",
        "## 最终模型系数表",
        "",
        format_apa_coefficients_table(result),
        "",
        "## APA-7 文字摘要",
        "",
        format_apa_hierarchical_paragraph(result),
    ]

    md_path = out / "hierarchical_regression_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    # JSON 中不含 ols 子字典（冗余），仅保留摘要
    def _block_summary(br: dict) -> dict:
        return {k: v for k, v in br.items() if k != "ols"}

    json_result = {k: v for k, v in result.items() if k != "blocks_results"}
    json_result["blocks_results"] = [_block_summary(br) for br in result["blocks_results"]]

    json_path = out / "hierarchical_regression_report.json"
    json_path.write_text(
        json.dumps(json_result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return md_path, json_path


# ---------------------------------------------------------------------------
# CSV 主入口
# ---------------------------------------------------------------------------

def _read_col(rows: list[dict[str, str]], col: str) -> list[float | None]:
    result = []
    for row in rows:
        raw = row.get(col, "").strip()
        if not raw:
            result.append(None)
            continue
        try:
            v = float(raw)
            result.append(None if not math.isfinite(v) else v)
        except ValueError:
            result.append(None)
    return result


def analyze_hierarchical(
    csv_path: str,
    dv: str,
    blocks: list[list[str]],
    alpha: float = 0.05,
    out_dir: str | pathlib.Path = "notes",
    write_files: bool = True,
) -> dict[str, Any]:
    """从 CSV 执行层级 OLS 回归，返回完整结果字典。"""
    rows: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))

    if not rows:
        raise ValueError(f"CSV 文件无数据行：{csv_path}")

    all_ivs = [iv for block in blocks for iv in block]
    all_cols = [dv] + all_ivs

    # 去重检查
    seen: set[str] = set()
    for iv in all_ivs:
        if iv in seen:
            raise ValueError(f"变量 '{iv}' 在多个块中重复出现")
        seen.add(iv)

    raw: dict[str, list[float | None]] = {c: _read_col(rows, c) for c in all_cols}

    valid_idx = [i for i in range(len(rows))
                 if all(raw[c][i] is not None for c in all_cols)]
    n_total = len(rows)
    n_valid = len(valid_idx)
    n_excluded = n_total - n_valid

    if n_valid < len(all_ivs) + 2:
        raise ValueError(
            f"有效数据行数 ({n_valid}) 不足以拟合 {len(all_ivs)} 个预测变量 + 截距"
        )

    y = [raw[dv][i] for i in valid_idx]
    X_cols = {iv: [raw[iv][i] for i in valid_idx] for iv in all_ivs}

    result = hierarchical_regression(y, blocks, X_cols, dv_name=dv, alpha=alpha)
    result["n_total"] = n_total
    result["n_excluded"] = n_excluded
    result["input_file"] = csv_path

    if write_files:
        md_path, json_path = write_hierarchical_report(result, out_dir=out_dir)
        result["report_md"] = str(md_path)
        result["report_json"] = str(json_path)

    return result


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def hierarchical_cli(args: list[str]) -> int:
    """psyclaw hreg <data.csv> --dv <col> --block1 c1,c2 [--block2 c3 ...]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="psyclaw hreg",
        description=(
            "层级多元回归分析（APA-7）：分块逐步纳入预测变量，"
            "输出 ΔR²、F 变化量、最终块系数表"
        ),
    )
    parser.add_argument("csv_file", help="输入数据 CSV 路径")
    parser.add_argument("--dv", required=True, help="因变量列名")
    # 支持 --block1 … --block9（最多 9 块）
    for i in range(1, 10):
        parser.add_argument(
            f"--block{i}", default=None,
            help=f"第 {i} 块新增预测变量（逗号分隔），按数字顺序构成层级"
        )
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="显著性水平（默认 .05）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--out", default="notes", help="报告输出目录（默认 notes/）")
    opts = parser.parse_args(args)

    blocks: list[list[str]] = []
    for i in range(1, 10):
        raw = getattr(opts, f"block{i}", None)
        if raw:
            ivs = [s.strip() for s in raw.split(",") if s.strip()]
            if ivs:
                blocks.append(ivs)

    if not blocks:
        print("错误：至少须提供 --block1 <变量列表>")
        return 1

    try:
        result = analyze_hierarchical(
            csv_path=opts.csv_file,
            dv=opts.dv,
            blocks=blocks,
            alpha=opts.alpha,
            out_dir=opts.out,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"错误：{exc}")
        return 1

    if opts.json:
        def _block_summary(br: dict) -> dict:
            return {k: v for k, v in br.items() if k != "ols"}
        out = {k: v for k, v in result.items() if k not in ("blocks_results", "final_coefficients")}
        out["blocks_results"] = [_block_summary(br) for br in result["blocks_results"]]
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    print()
    print(format_apa_hierarchical_table(result))
    print()
    print(format_apa_coefficients_table(result))
    print()
    print(format_apa_hierarchical_paragraph(result))
    if "report_md" in result:
        print(f"\n报告已写入 {result['report_md']}")
    return 0
