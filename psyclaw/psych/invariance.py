"""M-3 测量不变性序列 — configural → metric → scalar 逐级检验。

判据 (Cheung & Rensvold 2002):
  ΔCFI ≤ −.010  AND  ΔRMSEA ≤ .015 → 该层不变性成立

若 scalar 不成立 → 阻断潜均值比较，建议部分不变性；
若 metric 不成立 → 阻断所有结构参数跨组比较。

R 可用时走 semTools::measurementInvariance()；
R 不可用时接受用户手动录入拟合指数(--cfi-*/--rmsea-*)，
或生成可执行的 R 脚本骨架供用户自跑。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# 判据常量 (Cheung & Rensvold 2002)
# ---------------------------------------------------------------------------

DELTA_CFI_THRESHOLD = -0.010   # 降幅超此则不变性失败 (负方向更严)
DELTA_RMSEA_THRESHOLD = 0.015  # 升幅超此则不变性失败


# ---------------------------------------------------------------------------
# R 后端整合
# ---------------------------------------------------------------------------

def _run_r_invariance(data_path: str, model: str, group: str) -> str:
    """生成并(若 R 可用)执行不变性 R 脚本,返回原始输出。"""
    from psyclaw.psych.r_backend import r_available, _run_r

    script = f'''library(lavaan); library(semTools)
d <- read.csv("{data_path}")
model <- '
{model}
'
# 逐级不变性: configural -> metric -> scalar
inv <- measurementInvariance(model = model, data = d, group = "{group}",
                              estimator = "MLR")

# 输出机器可读摘要 (psyclaw: 前缀行供 Python 解析)
s <- summary(inv)
fits <- do.call(rbind, lapply(inv, fitMeasures, fit.measures = c("cfi","rmsea")))
cat("\\npsyclaw:fits\\n")
print(fits)
cat("\\npsyclaw:models\\n")
print(names(inv))
cat("\\n判据: ΔCFI <= .010 且 ΔRMSEA <= .015 视为不变 (Cheung & Rensvold 2002)\\n")
'''
    exe = r_available()
    if not exe:
        return ""
    return _run_r(script)


# ---------------------------------------------------------------------------
# 解析 R 输出
# ---------------------------------------------------------------------------

def _parse_r_fits(r_output: str) -> dict[str, dict]:
    """从 R 输出提取各层拟合指数。返回 {model_name: {cfi, rmsea}}。"""
    fits: dict[str, dict] = {}
    in_fits = False
    for line in r_output.splitlines():
        if "psyclaw:fits" in line:
            in_fits = True
            continue
        if "psyclaw:models" in line:
            in_fits = False
            continue
        if not in_fits:
            continue
        # 匹配如 "fit.configural  0.990  0.045" 或 lavaan 格式
        m = re.match(
            r'\s*(fit\.\w+|configural|loadings|intercepts|means|residuals)\s+'
            r'([\d.]+)\s+([\d.]+)',
            line, re.IGNORECASE
        )
        if m:
            name = m.group(1).lower().replace("fit.", "")
            fits[name] = {"cfi": float(m.group(2)), "rmsea": float(m.group(3))}
    return fits


# ---------------------------------------------------------------------------
# 核心判决逻辑
# ---------------------------------------------------------------------------

LEVEL_SEQUENCE = ["configural", "metric", "scalar"]

# 常见别名映射
_ALIAS = {
    "loadings": "metric",
    "weak": "metric",
    "intercepts": "scalar",
    "strong": "scalar",
}


def _normalize_fits(fits: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for k, v in fits.items():
        norm = _ALIAS.get(k, k)
        out[norm] = v
    return out


def compute_verdict(fits: dict[str, dict]) -> dict:
    """
    fits: {level: {cfi, rmsea}} — 至少含 configural
    返回完整判决结构。
    """
    fits = _normalize_fits(fits)
    levels_out: dict = {}
    prev_cfi = prev_rmsea = None
    results: dict[str, bool] = {}

    for lvl in LEVEL_SEQUENCE:
        if lvl not in fits:
            continue
        cfi = fits[lvl].get("cfi")
        rmsea = fits[lvl].get("rmsea")
        entry: dict = {"cfi": cfi, "rmsea": rmsea}

        if prev_cfi is not None and cfi is not None and rmsea is not None:
            # round before threshold comparison: CFI/RMSEA are 3-4 dp values
            dcfi = round(cfi - prev_cfi, 4)
            drmsea = round(rmsea - prev_rmsea, 4)
            entry["delta_cfi"] = dcfi
            entry["delta_rmsea"] = drmsea
            ok = (dcfi >= DELTA_CFI_THRESHOLD) and (drmsea <= DELTA_RMSEA_THRESHOLD)
            results[lvl] = ok
        else:
            results[lvl] = True  # configural 无参照,视为通过

        levels_out[lvl] = entry
        if cfi is not None:
            prev_cfi = cfi
        if rmsea is not None:
            prev_rmsea = rmsea

    metric_ok = results.get("metric", False)
    scalar_ok = results.get("scalar", False)

    if scalar_ok and metric_ok:
        verdict_str = "full_invariance"
        latent_mean_ok = True
        partial = False
    elif metric_ok and not scalar_ok:
        verdict_str = "metric_only"
        latent_mean_ok = False
        partial = True
    elif not metric_ok:
        verdict_str = "configural_only"
        latent_mean_ok = False
        partial = True
    else:
        verdict_str = "unknown"
        latent_mean_ok = False
        partial = False

    return {
        "test": "measurement_invariance",
        "levels": levels_out,
        "metric_invariance": metric_ok,
        "scalar_invariance": scalar_ok,
        "verdict": verdict_str,
        "latent_mean_comparison_ok": latent_mean_ok,
        "partial_invariance_suggested": partial,
        "invariance_tested": True,
        "reference": "Cheung & Rensvold (2002) ΔCFI ≤ −.010 and ΔRMSEA ≤ .015",
    }


# ---------------------------------------------------------------------------
# 格式化报告
# ---------------------------------------------------------------------------

def format_report(result: dict) -> str:
    lines = ["# 测量不变性检验报告", ""]
    verdict = result.get("verdict", "unknown")
    verdict_labels = {
        "full_invariance": "✓ 完全不变性成立 — 可进行潜均值跨组比较",
        "metric_only": "⚠ 仅 metric 不变性 — 可比较潜变量相关，但不可直接比较潜均值",
        "configural_only": "✗ 仅 configural 不变性 — 因子结构相同，但负荷量跨组存在差异",
        "unknown": "? 不变性结论不确定",
    }
    lines.append(verdict_labels.get(verdict, verdict))
    lines.append("")
    lines.append(f"判据: Cheung & Rensvold (2002) — ΔCFI ≤ −.010 且 ΔRMSEA ≤ +.015")
    lines.append("")

    for lvl in LEVEL_SEQUENCE:
        info = result.get("levels", {}).get(lvl)
        if not info:
            continue
        cfi = info.get("cfi")
        rmsea = info.get("rmsea")
        dcfi = info.get("delta_cfi")
        drmsea = info.get("delta_rmsea")
        cfi_s = f"CFI={cfi:.3f}" if cfi is not None else "CFI=?"
        rmsea_s = f"RMSEA={rmsea:.3f}" if rmsea is not None else "RMSEA=?"
        delta_s = ""
        if dcfi is not None:
            cfi_ok = dcfi >= DELTA_CFI_THRESHOLD
            rmsea_ok = drmsea <= DELTA_RMSEA_THRESHOLD
            mark = "✓" if (cfi_ok and rmsea_ok) else "✗"
            delta_s = f"  ΔCFI={dcfi:+.3f} ΔRMSEA={drmsea:+.3f} {mark}"
        lines.append(f"  {lvl:<14} {cfi_s}  {rmsea_s}{delta_s}")

    lines.append("")
    if result.get("partial_invariance_suggested"):
        lines.append("建议: 释放造成不变性失败的截距/负荷项(最多 2 项),")
        lines.append("      采用 partial invariance 模型后报告受限比较结论。")
        if not result.get("latent_mean_comparison_ok"):
            lines.append("  ✗  潜均值跨组比较已被阻断 — 请先达到 scalar 不变性")
            lines.append("     或改用观测分数/截距自由的部分不变性模型。")
    elif result.get("latent_mean_comparison_ok"):
        lines.append("✓  scalar 不变性成立 — 潜均值跨组比较已解锁。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 写 sidecar JSON
# ---------------------------------------------------------------------------

def write_sidecar(result: dict, output_dir: str = "notes") -> Path:
    p = Path(output_dir)
    p.mkdir(parents=True, exist_ok=True)
    out = p / "invariance_check.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_invariance(
    data_path: str,
    model: str,
    group: str,
    *,
    output_dir: str = "notes",
    # 手动拟合指数(R 不可用时)
    cfi_configural: float | None = None,
    rmsea_configural: float | None = None,
    cfi_metric: float | None = None,
    rmsea_metric: float | None = None,
    cfi_scalar: float | None = None,
    rmsea_scalar: float | None = None,
    as_json: bool = False,
) -> int:
    from psyclaw.psych.r_backend import r_available

    manual_fits: dict[str, dict] = {}
    if cfi_configural is not None:
        manual_fits["configural"] = {
            "cfi": cfi_configural, "rmsea": rmsea_configural or 0.0}
    if cfi_metric is not None:
        manual_fits["metric"] = {
            "cfi": cfi_metric, "rmsea": rmsea_metric or 0.0}
    if cfi_scalar is not None:
        manual_fits["scalar"] = {
            "cfi": cfi_scalar, "rmsea": rmsea_scalar or 0.0}

    r_raw = ""
    fits: dict[str, dict] = {}

    if manual_fits:
        fits = manual_fits
    elif r_available():
        print("  [R] 执行 semTools::measurementInvariance() …", flush=True)
        r_raw = _run_r_invariance(data_path, model, group)
        fits = _parse_r_fits(r_raw)
        if not fits:
            # R 跑了但解析失败 — 给出脚本骨架并提示手动录入
            print("  [警告] 无法自动解析 R 输出，请用 --cfi-* / --rmsea-* 手动录入拟合指数。",
                  file=sys.stderr)
    else:
        # R 不可用 — 打印脚本骨架
        from psyclaw.psych.r_backend import invariance as r_inv_script
        print(r_inv_script(data_path, model, group))
        if not manual_fits:
            print("\n[提示] R 未安装，无法自动运行不变性检验。")
            print("  请安装 R 后重试，或用 --cfi-configural/--rmsea-configural 等选项")
            print("  手动录入各层拟合指数以获得门禁判决。")
            return 1

    if not fits:
        if not manual_fits:
            print("[错误] 无拟合指数可用，检验终止。", file=sys.stderr)
            return 1
        fits = manual_fits

    result = compute_verdict(fits)
    result["data_path"] = data_path
    result["group"] = group

    if r_raw:
        # 截取前 3000 字符存档
        result["r_output_excerpt"] = r_raw[:3000]

    sidecar = write_sidecar(result, output_dir)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_report(result))
        print(f"\n  已写 sidecar: {sidecar}")

    if not result.get("latent_mean_comparison_ok"):
        return 1  # 非零 exit → 门禁拦截
    return 0
