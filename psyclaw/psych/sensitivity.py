"""P3-3: 敏感性分析框架 — Multiverse 分析 + 规格曲线（stdlib only）。

命令: psyclaw sensitivity <plan.md|forks.yaml> [--data CSV] [--dv col] [--group col]

四步流程：
  1. 解析决策分叉点（从 plan.md 的 ```yaml sensitivity_forks 块，或独立 YAML 文件）
  2. 生成多元宇宙（所有分叉点的笛卡尔积）
  3. 若提供数据 CSV → 对每个规格运行统计分析
  4. 汇报规格曲线（按效应量排序）+ 稳健性指标 + APA-7 段落

理论依据：
  Steegen, S., Tuerlinckx, F., Gelman, A., & Vanpaemel, W. (2016).
  Increasing transparency through a multiverse analysis. Perspectives on
  Psychological Science, 11(5), 702–712.

  Simonsohn, U., Simmons, J. P., & Nelson, L. D. (2020).
  Specification curve analysis. Nature Human Behaviour, 4, 1208–1214.

决策分叉点 YAML 格式（嵌入 Markdown 或独立 .yaml 文件）:

  forks:
    - name: outlier_exclusion
      label: "离群值剔除"
      type: outlier
      choices:
        - label: none
          description: "不剔除离群值"
        - label: "2SD"
          description: "剔除 > 2 SD"
        - label: "3SD"
          description: "剔除 > 3 SD"
    - name: test_type
      label: "统计检验"
      type: test_type
      choices:
        - label: welch
          description: "Welch 独立样本 t"
        - label: mann_whitney
          description: "Mann-Whitney U（非参数）"
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from pathlib import Path

from psyclaw.psych.stats_core import welch_ttest, student_ttest, mann_whitney, norm_ppf

# ---------------------------------------------------------------------------
# 决策分叉点 YAML 极简解析（避免引入 pyyaml）
# ---------------------------------------------------------------------------

def _parse_forks_yaml(text: str) -> list[dict]:
    """解析 sensitivity_forks YAML 结构（state-machine，专用于本格式）。"""
    forks: list[dict] = []
    cur_fork: dict | None = None
    cur_choice: dict | None = None
    in_forks = False
    in_choices = False

    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue

        if s == "forks:":
            in_forks = True
            continue
        if not in_forks:
            continue

        # ── 新分叉条目 ──
        if s.startswith("- name:"):
            if cur_fork is not None:
                if cur_choice is not None:
                    cur_fork["choices"].append(cur_choice)
                    cur_choice = None
                forks.append(cur_fork)
            name = s[len("- name:"):].strip().strip("\"'")
            cur_fork = {"name": name, "label": name, "type": "generic", "choices": []}
            in_choices = False

        elif cur_fork is not None and not in_choices:
            # ── 分叉属性 ──
            if s.startswith("label:"):
                cur_fork["label"] = s[len("label:"):].strip().strip("\"'")
            elif s.startswith("type:"):
                cur_fork["type"] = s[len("type:"):].strip().strip("\"'")
            elif s == "choices:":
                in_choices = True

        elif cur_fork is not None and in_choices:
            # ── 选项条目 ──
            if s.startswith("- label:"):
                if cur_choice is not None:
                    cur_fork["choices"].append(cur_choice)
                cur_choice = {
                    "label": s[len("- label:"):].strip().strip("\"'"),
                    "description": "",
                }
            elif cur_choice is not None and not s.startswith("-"):
                if ":" in s:
                    k, _, v = s.partition(":")
                    k, v = k.strip(), v.strip().strip("\"'")
                    if k not in ("name", "type", "choices"):
                        cur_choice[k] = v

    if cur_fork is not None:
        if cur_choice is not None:
            cur_fork["choices"].append(cur_choice)
        forks.append(cur_fork)

    return forks


def _extract_forks_from_markdown(text: str) -> str | None:
    """提取 Markdown 中 ```yaml sensitivity_forks ... ``` 块内容（不含围栏）。"""
    in_block = False
    block_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not in_block:
            if stripped.startswith(("```", "~~~")):
                info = stripped.lstrip("`~").strip().lower()
                if "sensitivity_forks" in info:
                    in_block = True
        else:
            if stripped.startswith(("```", "~~~")):
                break
            block_lines.append(line)
    return "\n".join(block_lines) if block_lines else None


def parse_forks(path: str) -> list[dict]:
    """从文件（.md / .yaml / .json）解析 sensitivity_forks 决策分叉点列表。

    Markdown 文件：在 ```yaml sensitivity_forks ... ``` 块内查找。
    YAML 文件：直接解析 forks: 顶级键。
    JSON 文件：读取 "forks" 字段。

    FileNotFoundError 若文件不存在。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    text = p.read_text(encoding="utf-8")

    suffix = p.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(text).get("forks", [])
        except json.JSONDecodeError:
            return []
    if suffix in (".yaml", ".yml"):
        return _parse_forks_yaml(text)

    # Markdown — 提取代码块
    yaml_text = _extract_forks_from_markdown(text)
    if yaml_text:
        return _parse_forks_yaml(yaml_text)

    # 退化：当作 YAML 全文解析
    return _parse_forks_yaml(text)


# ---------------------------------------------------------------------------
# 多元宇宙生成（笛卡尔积）
# ---------------------------------------------------------------------------

def generate_multiverse(forks: list[dict]) -> list[dict]:
    """生成所有决策组合（笛卡尔积）。

    Returns: list of spec dicts::

        {
          "id": "spec_001",
          "choices": {fork_name: {fork, fork_label, label, description, ...}},
        }
    """
    if not forks:
        return []

    choice_sequences = [
        [{"fork": f["name"], "fork_label": f.get("label", f["name"]), **c}
         for c in f.get("choices", []) if c]
        for f in forks
    ]
    # 跳过空选项列表的分叉（保护 itertools.product）
    choice_sequences = [cs for cs in choice_sequences if cs]
    if not choice_sequences:
        return []

    specs: list[dict] = []
    for i, combo in enumerate(itertools.product(*choice_sequences)):
        specs.append({
            "id": f"spec_{i + 1:03d}",
            "choices": {c["fork"]: c for c in combo},
        })
    return specs


# ---------------------------------------------------------------------------
# 数据辅助
# ---------------------------------------------------------------------------

def _to_float(val: object) -> float | None:
    if val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _load_csv(path: str) -> tuple[list[str], list[dict]]:
    p = Path(path)
    rows: list[dict] = []
    headers: list[str] = []
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        for row in reader:
            cleaned: dict = {}
            for k, v in row.items():
                sv = (v or "").strip()
                cleaned[k] = None if sv in ("", "NA", "NaN", "N/A", "nan") else sv
            rows.append(cleaned)
    return headers, rows


def _apply_outlier_filter(
    pairs: list[tuple[float, str]],
    threshold_sd: float | None,
) -> list[tuple[float, str]]:
    """在各分组内按 SD 阈值剔除离群值。

    pairs: [(dv_value, group_label), ...]
    threshold_sd: None → 不过滤；2.0 → ±2SD；3.0 → ±3SD
    """
    if threshold_sd is None or not pairs:
        return list(pairs)

    # 按组计算均值和 SD
    group_data: dict[str, list[float]] = {}
    for v, g in pairs:
        group_data.setdefault(g, []).append(v)

    group_stats: dict[str, tuple[float, float]] = {}
    for g, vals in group_data.items():
        m = sum(vals) / len(vals)
        sd = math.sqrt(sum((x - m) ** 2 for x in vals) / max(len(vals) - 1, 1))
        group_stats[g] = (m, sd)

    return [
        (v, g) for v, g in pairs
        if (group_stats[g][1] == 0 or abs(v - group_stats[g][0]) <= threshold_sd * group_stats[g][1])
    ]


def _r_to_d(r: float) -> float:
    """秩双列相关 r → Cohen's d（Cohen, 1988 近似，d = 2r/√(1−r²)）。"""
    r_clamped = max(-0.9999, min(0.9999, r))
    return 2 * r_clamped / math.sqrt(1 - r_clamped ** 2)


# ---------------------------------------------------------------------------
# 分叉检测辅助
# ---------------------------------------------------------------------------

_OUTLIER_FORK_KEYS = frozenset({"outlier", "outlier_exclusion", "outliers",
                                 "outlier_removal", "outlier_filter"})
_TEST_FORK_KEYS = frozenset({"test_type", "test", "stat_test", "statistical_test",
                              "analysis_method", "test_method"})


def _detect_outlier_threshold(choices: dict) -> float | None:
    """从规格选择中推断离群值 SD 阈值，找不到返回 None（不过滤）。"""
    for fork_name, choice in choices.items():
        fork_id = (choice.get("fork", "") or fork_name).lower().replace("-", "_")
        if any(k in fork_id for k in _OUTLIER_FORK_KEYS):
            lbl = choice.get("label", "").lower().replace(" ", "").replace("_", "")
            if "2sd" in lbl or lbl == "2":
                return 2.0
            if "2.5sd" in lbl:
                return 2.5
            if "3sd" in lbl or lbl == "3":
                return 3.0
            # "none" / "no" → return None (falls through)
    return None


def _detect_test_label(choices: dict) -> str:
    """从规格选择中推断统计检验类型，默认 welch。"""
    for fork_name, choice in choices.items():
        fork_id = (choice.get("fork", "") or fork_name).lower().replace("-", "_")
        if any(k in fork_id for k in _TEST_FORK_KEYS):
            return choice.get("label", "welch").lower()
    return "welch"


# ---------------------------------------------------------------------------
# 单规格统计检验
# ---------------------------------------------------------------------------

def _run_spec(g1: list[float], g2: list[float], test_label: str) -> dict:
    """对 g1/g2 运行指定检验，返回 {d, p, test, n1, n2, ci_lo, ci_hi}。

    所有效应量统一转换为 Cohen's d 以便规格曲线比较。
    Mann-Whitney r → d 用 Cohen (1988) 近似。
    CI 用 d 的汇合 SE 近似（统一公式，便于跨检验比较）。
    """
    n1, n2 = len(g1), len(g2)
    if n1 < 2 or n2 < 2:
        return {"d": float("nan"), "p": float("nan"), "test": test_label,
                "n1": n1, "n2": n2,
                "ci_lo": float("nan"), "ci_hi": float("nan"),
                "error": "样本量不足（各组至少需 2 个观测值）"}

    lbl = test_label.lower()
    zc = norm_ppf(0.975)

    if "mann" in lbl or "whitney" in lbl or "nonparam" in lbl or "rank" in lbl:
        res = mann_whitney(g1, g2)
        r = res.get("r", 0.0)
        d = _r_to_d(r)
        p = res.get("p", float("nan"))
        test_name = "Mann-Whitney U"
    elif "student" in lbl or "equal_var" in lbl:
        res = student_ttest(g1, g2)
        if "error" in res:
            return {"d": float("nan"), "p": float("nan"), "test": "Student t",
                    "n1": n1, "n2": n2,
                    "ci_lo": float("nan"), "ci_hi": float("nan"),
                    "error": res["error"]}
        d, p, test_name = res["d"], res["p"], "Student t"
    else:
        # 默认 Welch
        res = welch_ttest(g1, g2)
        if "error" in res:
            return {"d": float("nan"), "p": float("nan"), "test": "Welch t",
                    "n1": n1, "n2": n2,
                    "ci_lo": float("nan"), "ci_hi": float("nan"),
                    "error": res["error"]}
        d, p, test_name = res["d"], res["p"], "Welch t"

    # Cohen's d 的 95% CI（汇合 SE，适用于所有检验；Mann-Whitney 为近似）
    if math.isnan(d) or n1 + n2 <= 2:
        ci_lo, ci_hi = float("nan"), float("nan")
    else:
        se_d = math.sqrt((n1 + n2) / (n1 * n2) + d ** 2 / max(2 * (n1 + n2 - 2), 1))
        ci_lo = round(d - zc * se_d, 4)
        ci_hi = round(d + zc * se_d, 4)

    return {
        "d": round(d, 4),
        "p": round(p, 4),
        "test": test_name,
        "n1": n1,
        "n2": n2,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
    }


# ---------------------------------------------------------------------------
# 规格应用（单规格 → 数据 → 结果）
# ---------------------------------------------------------------------------

def apply_spec_to_data(
    rows: list[dict],
    dv_col: str,
    group_col: str,
    spec: dict,
) -> dict:
    """将一个规格应用于数据，运行检验，返回结果 dict。"""
    choices = spec.get("choices", {})

    # 提取原始有效对
    pairs_raw: list[tuple[float, str]] = []
    for row in rows:
        dv = _to_float(row.get(dv_col))
        grp = row.get(group_col)
        if dv is not None and grp is not None:
            pairs_raw.append((dv, str(grp)))

    if not pairs_raw:
        return {
            "d": float("nan"), "p": float("nan"), "n1": 0, "n2": 0,
            "ci_lo": float("nan"), "ci_hi": float("nan"),
            "error": f"无有效数据（DV={dv_col}, group={group_col}）",
            "spec_id": spec["id"], "n_total": 0, "n_removed": 0,
            "choices_desc": "",
        }

    # 离群值剔除
    threshold = _detect_outlier_threshold(choices)
    pairs = _apply_outlier_filter(pairs_raw, threshold)
    n_removed = len(pairs_raw) - len(pairs)

    # 分组
    group_vals: dict[str, list[float]] = {}
    for v, g in pairs:
        group_vals.setdefault(g, []).append(v)

    group_labels = sorted(group_vals.keys())
    if len(group_labels) < 2:
        return {
            "d": float("nan"), "p": float("nan"),
            "n1": len(pairs), "n2": 0,
            "ci_lo": float("nan"), "ci_hi": float("nan"),
            "error": f"少于 2 个分组（找到: {group_labels}）",
            "spec_id": spec["id"], "n_total": len(pairs), "n_removed": n_removed,
            "choices_desc": "",
        }

    g1 = group_vals[group_labels[0]]
    g2 = group_vals[group_labels[1]]

    # 统计检验
    test_label = _detect_test_label(choices)
    result = _run_spec(g1, g2, test_label)

    # 规格描述
    choices_desc = " / ".join(
        f"{c.get('fork_label', fork)}: {c.get('label', '?')}"
        for fork, c in choices.items()
    )
    result.update({
        "spec_id": spec["id"],
        "n_total": len(pairs),
        "n_removed": n_removed,
        "choices_desc": choices_desc,
    })
    return result


def run_multiverse(
    rows: list[dict],
    dv_col: str,
    group_col: str,
    specs: list[dict],
) -> list[dict]:
    """对所有规格运行统计分析，返回结果列表。"""
    return [apply_spec_to_data(rows, dv_col, group_col, spec) for spec in specs]


# ---------------------------------------------------------------------------
# 规格曲线统计（稳健性指标）
# ---------------------------------------------------------------------------

def compute_robustness(results: list[dict], alpha: float = 0.05) -> dict:
    """计算多元宇宙稳健性指标。

    Returns:
        k_specs, k_valid, k_sig, k_pos, k_robust,
        pct_sig, pct_robust,
        median_d, d_range, median_p, alpha
    """
    valid = [
        r for r in results
        if not r.get("error") and not math.isnan(r.get("d", float("nan")))
    ]
    k_valid = len(valid)

    if k_valid == 0:
        return {
            "k_specs": len(results), "k_valid": 0, "k_sig": 0, "k_pos": 0, "k_robust": 0,
            "pct_sig": 0.0, "pct_robust": 0.0,
            "median_d": float("nan"), "d_range": (float("nan"), float("nan")),
            "median_p": float("nan"), "alpha": alpha,
        }

    def _median(xs: list) -> float:
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    ds = sorted(r["d"] for r in valid)
    ps = sorted(r["p"] for r in valid)
    med_d = _median(ds)
    sign = 1 if med_d >= 0 else -1

    k_sig = sum(1 for r in valid if r.get("p", 1.0) < alpha)
    k_pos = sum(1 for r in valid if (r["d"] * sign) >= 0)
    k_robust = sum(1 for r in valid if r.get("p", 1.0) < alpha and (r["d"] * sign) >= 0)

    return {
        "k_specs": len(results),
        "k_valid": k_valid,
        "k_sig": k_sig,
        "k_pos": k_pos,
        "k_robust": k_robust,
        "pct_sig": round(k_sig / k_valid * 100, 1),
        "pct_robust": round(k_robust / k_valid * 100, 1),
        "median_d": round(med_d, 3),
        "d_range": (round(min(ds), 3), round(max(ds), 3)),
        "median_p": round(_median(ps), 4),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# ASCII 规格曲线表
# ---------------------------------------------------------------------------

def format_ascii_spec_curve(results: list[dict], alpha: float = 0.05) -> str:
    """生成 ASCII 规格曲线（按效应量升序排列的表格）。

    ● = p < alpha（显著）  ○ = p ≥ alpha（不显著）
    """
    valid = [
        r for r in results
        if not r.get("error") and not math.isnan(r.get("d", float("nan")))
    ]
    if not valid:
        return "(无有效规格，无法绘制规格曲线)"

    sorted_results = sorted(valid, key=lambda r: r["d"])
    k = len(sorted_results)

    hdr = f"规格曲线 (k={k}, 按效应量升序排列)  α={alpha}"
    sep = "─" * 70
    col_hdr = f"  {'排名':>3}  {'d':>7}  {'95% CI':^17}  {'p':>6}  {'sig':^3}  规格描述"

    lines = [hdr, sep, col_hdr, sep]
    for rank, r in enumerate(sorted_results, 1):
        d = r["d"]
        p = r.get("p", float("nan"))
        ci_lo = r.get("ci_lo", float("nan"))
        ci_hi = r.get("ci_hi", float("nan"))
        sig = "●" if not math.isnan(p) and p < alpha else "○"
        ci_str = (f"[{ci_lo:+.3f}, {ci_hi:+.3f}]"
                  if not math.isnan(ci_lo) else "      —      ")
        p_str = f"{p:.4f}" if not math.isnan(p) else "  —   "
        desc = r.get("choices_desc", r.get("spec_id", "?"))[:35]
        lines.append(f"  {rank:>3}.  {d:+.3f}  {ci_str}  {p_str}  {sig:^3}  {desc}")

    lines += [sep, f"  ● p < {alpha}（显著）  ○ p ≥ {alpha}（不显著）"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# APA-7 段落
# ---------------------------------------------------------------------------

def format_apa_sensitivity(
    forks: list[dict],
    robustness: dict,
    dv_label: str = "因变量",
    group_label: str = "分组",
) -> str:
    """生成 APA-7 敏感性分析方法段落。"""
    k_specs = robustness.get("k_specs", 0)
    k_valid = robustness.get("k_valid", 0)
    pct_sig = robustness.get("pct_sig", 0.0)
    pct_robust = robustness.get("pct_robust", 0.0)
    k_sig = robustness.get("k_sig", 0)
    k_robust = robustness.get("k_robust", 0)
    med_d = robustness.get("median_d", float("nan"))
    d_lo, d_hi = robustness.get("d_range", (float("nan"), float("nan")))
    alpha = robustness.get("alpha", 0.05)

    fork_desc_parts = [
        f"{f.get('label', f['name'])}（{len(f.get('choices', []))} 个选项）"
        for f in forks
    ]
    fork_desc = "、".join(fork_desc_parts) if fork_desc_parts else "（无分叉点）"

    med_str = f"{med_d:+.3f}" if not math.isnan(med_d) else "N/A"
    range_str = (f"[{d_lo:+.3f}, {d_hi:+.3f}]"
                 if not math.isnan(d_lo) else "N/A")

    lines: list[str] = [
        "## 敏感性分析（Multiverse 分析）",
        "",
        "为评估分析决策对研究结论的稳健性，本研究采用多元宇宙分析"
        f"（multiverse analysis; Steegen et al., 2016），系统考察"
        f"以下决策分叉点：{fork_desc}。"
        f"上述分叉点共产生 {k_specs} 个合理分析规格。",
    ]

    if k_valid > 0:
        lines += [
            "",
            f"规格曲线分析（specification curve analysis; Simonsohn et al., 2020）"
            f"显示，{dv_label}与{group_label}之间的标准化效应量（Cohen's *d*）"
            f"中位数为 *d* = {med_str}，范围 {range_str}（*k* = {k_valid}）。"
            f"在所有有效规格中，{pct_sig:.1f}% 的规格（*k* = {k_sig}/{k_valid}）"
            f"在 *α* = {alpha} 水平达到统计显著；方向一致且显著的比例为"
            f" {pct_robust:.1f}%（*k* = {k_robust}/{k_valid}），",
        ]

        if pct_robust >= 80:
            lines.append("表明研究结论对合理的分析决策选择具有**较高稳健性**。")
        elif pct_robust >= 50:
            lines.append("表明研究结论具有**中等稳健性**，建议在解读时谨慎对待。")
        else:
            lines.append(
                "表明研究结论**对分析决策较为敏感**，应向读者明确报告主要分析规格"
                "的选择理由，并将规格曲线作为补充材料公开。"
            )

        lines += [
            "",
            "**参考文献**",
            "",
            "Steegen, S., Tuerlinckx, F., Gelman, A., & Vanpaemel, W. (2016). "
            "Increasing transparency through a multiverse analysis. "
            "*Perspectives on Psychological Science*, *11*(5), 702–712. "
            "https://doi.org/10.1177/1745691616658637",
            "",
            "Simonsohn, U., Simmons, J. P., & Nelson, L. D. (2020). "
            "Specification curve analysis. "
            "*Nature Human Behaviour*, *4*, 1208–1214. "
            "https://doi.org/10.1038/s41562-020-0912-z",
        ]
    else:
        lines += [
            "",
            "规格曲线将在数据收集完成后生成。所有 "
            f"{k_specs} 个规格将被全部报告（见补充材料）。",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def analyze_sensitivity(
    plan_path: str,
    data_path: str | None = None,
    dv_col: str | None = None,
    group_col: str | None = None,
    out_dir: str | None = None,
    alpha: float = 0.05,
) -> dict:
    """主入口：解析分叉点 → 生成多元宇宙 → 分析（若有数据）→ 汇报。

    Returns 结构化结果 dict（含 forks, multiverse, results, robustness, apa_text）。
    """
    # 1. 解析分叉点
    forks = parse_forks(plan_path)
    if not forks:
        return {
            "error": (
                "未在文件中找到 sensitivity_forks 块。"
                "请在 Markdown 文件中添加 ```yaml sensitivity_forks ... ``` 块，"
                "或提供独立 YAML/JSON 文件（含顶级 forks: 键）。"
            ),
            "forks": [], "k_forks": 0, "k_specs": 0,
            "multiverse": [], "results": [], "robustness": {},
            "ascii_spec_curve": "", "apa_text": "",
        }

    # 2. 生成多元宇宙
    specs = generate_multiverse(forks)
    result: dict = {
        "forks": forks,
        "k_forks": len(forks),
        "k_specs": len(specs),
        "multiverse": specs,
        "results": [],
        "robustness": {},
        "ascii_spec_curve": "",
        "apa_text": "",
    }

    # 3. 若有数据，运行统计分析
    if data_path:
        if not dv_col or not group_col:
            result["error"] = "提供 --data 时需同时指定 --dv 和 --group"
            return result
        headers, rows = _load_csv(data_path)
        if dv_col not in headers:
            result["error"] = f"DV 列 '{dv_col}' 不在数据中（可用列: {headers}）"
            return result
        if group_col not in headers:
            result["error"] = f"分组列 '{group_col}' 不在数据中（可用列: {headers}）"
            return result

        analysis_results = run_multiverse(rows, dv_col, group_col, specs)
        rob = compute_robustness(analysis_results, alpha=alpha)
        result["results"] = analysis_results
        result["robustness"] = rob
        result["ascii_spec_curve"] = format_ascii_spec_curve(analysis_results, alpha=alpha)
        result["apa_text"] = format_apa_sensitivity(
            forks, rob, dv_label=dv_col, group_label=group_col
        )
    else:
        result["apa_text"] = format_apa_sensitivity(
            forks,
            {"k_specs": len(specs), "k_valid": 0, "alpha": alpha},
            dv_label="因变量",
            group_label="分组",
        )

    # 4. 写 sidecar
    if out_dir:
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)

        # Markdown 报告
        md_parts = ["# 敏感性分析报告（Multiverse Analysis）", ""]
        md_parts.append(f"**分叉点数**: {len(forks)}  |  **规格总数**: {len(specs)}")
        if result.get("robustness"):
            rob = result["robustness"]
            md_parts.append(
                f"**稳健性**: {rob.get('pct_robust', 0):.1f}% "
                f"({rob.get('k_robust', 0)}/{rob.get('k_valid', 0)}) 规格一致且显著"
            )
            md_parts.append(f"**效应量中位数**: *d* = {rob.get('median_d', float('nan')):+.3f}")
            md_parts.append(f"**效应量范围**: {rob.get('d_range', ('?', '?'))}")
        md_parts.append("")
        if result.get("ascii_spec_curve"):
            md_parts.append("```")
            md_parts.append(result["ascii_spec_curve"])
            md_parts.append("```")
            md_parts.append("")
        md_parts.append(result.get("apa_text", ""))

        (od / "sensitivity_report.md").write_text("\n".join(md_parts), encoding="utf-8")

        # JSON sidecar（去掉长文本字段）
        export = {k: v for k, v in result.items() if k not in ("ascii_spec_curve", "apa_text")}
        (od / "sensitivity_report.json").write_text(
            json.dumps(export, ensure_ascii=False, indent=2, default=float),
            encoding="utf-8",
        )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def sensitivity_cli(argv: list[str] | None = None) -> int:
    """CLI 入口: psyclaw sensitivity <plan> [--data CSV] [options]"""
    from psyclaw import ui

    parser = argparse.ArgumentParser(
        prog="psyclaw sensitivity",
        description="敏感性分析（Multiverse / 规格曲线，stdlib only）",
    )
    parser.add_argument(
        "plan",
        help="分叉点文件：plan.md（含 ```yaml sensitivity_forks 块）/ .yaml / .json",
    )
    parser.add_argument("--data", default=None, help="CSV 数据文件（提供后自动运行所有规格）")
    parser.add_argument("--dv", default=None, help="因变量列名（--data 时必填）")
    parser.add_argument("--group", default=None, help="分组列名（--data 时必填）")
    parser.add_argument("--alpha", type=float, default=0.05, help="显著性阈值（默认 .05）")
    parser.add_argument("--out", default=None, help="sidecar 输出目录（默认不写文件）")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="输出机器可读 JSON")

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        result = analyze_sensitivity(
            plan_path=args.plan,
            data_path=args.data,
            dv_col=args.dv,
            group_col=args.group,
            out_dir=args.out,
            alpha=args.alpha,
        )
    except FileNotFoundError as e:
        print(ui.err(str(e)))
        return 1

    if result.get("error"):
        print(ui.err(result["error"]))
        return 1

    # 文本输出
    print(ui.title("PsyClaw — 敏感性分析 / 多元宇宙分析"))
    print(ui.rule())
    print(f"  计划文件   : {args.plan}")
    print(f"  决策分叉点 : {result['k_forks']}")
    print(f"  规格总数   : {result['k_specs']}")
    print()

    print(ui.accent("决策分叉点"))
    for fork in result["forks"]:
        choices = fork.get("choices", [])
        print(f"  • {fork.get('label', fork['name'])} ({len(choices)} 个选项)")
        for c in choices:
            desc = f"  ({c['description']})" if c.get("description") else ""
            print(f"      - {c['label']}{desc}")
    print()

    rob = result.get("robustness", {})
    if rob:
        print(ui.accent("规格曲线统计"))
        print(f"  有效规格数     : {rob['k_valid']} / {rob['k_specs']}")
        med = rob['median_d']
        print(f"  效应量中位数   : d = {med:+.3f}" if not math.isnan(med) else "  效应量中位数   : N/A")
        lo, hi = rob['d_range']
        if not math.isnan(lo):
            print(f"  效应量范围     : [{lo:+.3f}, {hi:+.3f}]")
        print(f"  显著规格 (p < {rob['alpha']}) : {rob['k_sig']}/{rob['k_valid']} "
              f"({rob['pct_sig']:.1f}%)")
        print(f"  稳健性（一致且显著）: {rob['pct_robust']:.1f}%")
        print()

    if result.get("ascii_spec_curve"):
        print(result["ascii_spec_curve"])
        print()

    if result.get("apa_text"):
        print(ui.accent("APA-7 段落"))
        print(result["apa_text"])
        print()

    if args.out:
        print(ui.ok(
            f"  ✓ 已写出: {args.out}/sensitivity_report.md  +  sensitivity_report.json"
        ))

    if args.as_json:
        export = {k: v for k, v in result.items() if k != "ascii_spec_curve"}
        print(json.dumps(export, ensure_ascii=False, indent=2, default=float))

    return 0
