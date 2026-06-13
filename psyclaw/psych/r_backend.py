"""R 后端 — lavaan(CFA/SEM)、lme4(MLM)、psych(omega 信度)。

R 在则真跑(生成 .R 脚本 → Rscript 执行 → 解析输出);
R 不在则返回可运行脚本骨架 + 安装提示(不假装算)。

这些方法 Python 生态薄弱(尤其 lavaan 的 SEM/不变性、lme4 的 MLM),
心理学期刊又常要求,故用 R 作为可选后端。语法内置严谨性默认
(MLR 估计、拟合指数全报、ω 优于 α、中心化提示)。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def r_available() -> str | None:
    return shutil.which("Rscript")


def _run_r(script: str) -> str:
    exe = r_available()
    if not exe:
        return ""
    tmp = Path(tempfile.gettempdir()) / "psyclaw_job.R"
    tmp.write_text(script, encoding="utf-8")
    try:
        r = subprocess.run([exe, "--vanilla", str(tmp)],
                           capture_output=True, text=True, timeout=600)
        return (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
    except Exception as exc:  # noqa: BLE001
        return f"[R 执行失败] {exc}"


def _wrap(method: str, script: str) -> str:
    exe = r_available()
    if exe:
        out = _run_r(script)
        return (f"[R 后端 · {method} · 已执行({exe})]\n"
                f"```r\n{script}\n```\n\n=== R 输出 ===\n{out[:6000]}")
    return (f"[R 未安装 · {method} 脚本骨架(装 R + 对应包后 Rscript 运行)]\n"
            f"安装:R 官网 + install.packages(c('lavaan','lme4','psych','semTools'))\n"
            f"```r\n{script}\n```")


# ---------------------------------------------------------------------------
# CFA / SEM(lavaan)
# ---------------------------------------------------------------------------

def cfa(data_path: str, model: str, ordered: bool = False) -> str:
    """model 例:'F1 =~ q1 + q2 + q3\\nF2 =~ q4 + q5 + q6'"""
    est = "WLSMV" if ordered else "MLR"
    ordered_arg = "ordered = TRUE, " if ordered else ""
    script = f'''library(lavaan)
d <- read.csv("{data_path}")
model <- '
{model}
'
fit <- cfa(model, data = d, {ordered_arg}estimator = "{est}", missing = "fiml")
# 拟合指数全报(不挑好看的)
summary(fit, fit.measures = TRUE, standardized = TRUE)
cat("\\n--- 关键拟合 ---\\n")
print(fitMeasures(fit, c("chisq","df","pvalue","cfi","tli","rmsea",
                         "rmsea.ci.lower","rmsea.ci.upper","srmr")))
# omega 信度(优于 alpha)
library(semTools)
print(reliability(fit))'''
    return _wrap(f"CFA(估计={est})", script)


def sem(data_path: str, model: str) -> str:
    script = f'''library(lavaan)
d <- read.csv("{data_path}")
model <- '
{model}
'
fit <- sem(model, data = d, estimator = "MLR", missing = "fiml", se = "robust")
summary(fit, fit.measures = TRUE, standardized = TRUE, ci = TRUE)
cat("\\n--- 拟合指数 ---\\n")
print(fitMeasures(fit, c("chisq","df","pvalue","cfi","tli","rmsea","srmr")))
cat("\\n注: 横断 SEM 的路径系数非因果; 存在等值模型。\\n")'''
    return _wrap("SEM(MLR 稳健)", script)


def invariance(data_path: str, model: str, group: str) -> str:
    script = f'''library(lavaan); library(semTools)
d <- read.csv("{data_path}")
model <- '
{model}
'
# 逐级不变性: configural -> metric -> scalar
inv <- measurementInvariance(model = model, data = d, group = "{group}",
                             estimator = "MLR")
# 判据: ΔCFI <= .010 且 ΔRMSEA <= .015 视为不变(Cheung & Rensvold 2002)'''
    return _wrap(f"测量不变性(按 {group})", script)


# ---------------------------------------------------------------------------
# MLM(lme4)
# ---------------------------------------------------------------------------

def mlm(data_path: str, formula: str, group: str) -> str:
    """formula 例:'y ~ x + (1 | cluster)'"""
    script = f'''library(lme4); library(lmerTest)  # lmerTest 给 p 值
d <- read.csv("{data_path}")
# 空模型算 ICC
m0 <- lmer({formula.split("~")[0].strip()} ~ 1 + (1 | {group}), data = d, REML = TRUE)
vc <- as.data.frame(VarCorr(m0))
icc <- vc$vcov[1] / sum(vc$vcov)
cat(sprintf("ICC = %.3f (>.05 提示需多层建模)\\n", icc))
# 目标模型
m1 <- lmer({formula}, data = d, REML = TRUE)
print(summary(m1))
cat("\\n注: 报告 ICC、两层 n、估计法(REML)、中心化策略、伪 R^2。\\n")
cat("L1 预测变量建议组均中心化(CWC); 跨层交互须把组均放回 L2。\\n")'''
    return _wrap("多层模型(lme4 + lmerTest)", script)


# ---------------------------------------------------------------------------
# omega 信度(psych)
# ---------------------------------------------------------------------------

def omega(data_path: str, items: list) -> str:
    cols = ", ".join(f'"{c}"' for c in items)
    script = f'''library(psych)
d <- read.csv("{data_path}")
items <- d[, c({cols})]
# McDonald's omega(总分合理性看 omega_h)+ 对照 alpha
om <- omega(items, nfactors = 3, plot = FALSE)
print(om)
cat(sprintf("\\nomega_total = %.3f, omega_h = %.3f\\n", om$omega.tot, om$omega_h))
cat("注: omega_h > .80 才支持把量表当单维总分; omega 优于 alpha(McNeish 2018)。\\n")
print(alpha(items))  # 对照 alpha + 逐题删除'''
    return _wrap("omega 信度(psych)", script)
