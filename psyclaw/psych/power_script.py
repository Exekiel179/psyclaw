"""生成功效分析脚本(委托 statsmodels)——统计外移,psyclaw 只生成不计算(stdlib only)。

守铁律「不在仓内做统计」:样本量/功效分析是统计,psyclaw **不算**,而是据检验类型 +
效应量 + α + power 生成委托 statsmodels.stats.power 的可复现脚本,由用户(或 MCP)跑
解出所需 N,并附敏感性分析(效应量高/低估时的 N)。相关检验用 scipy 的 Fisher-z 公式。
本生成器自身零统计依赖——纯字符串拼装(库名参数化,本文件不出现真 import),可单测。
"""

from __future__ import annotations

# 库名参数化:避免本文件源码出现真实 import 语句;生成的脚本里才是真 import
_SM, _SP, _NP = "statsmodels", "scipy", "numpy"


def generate_power_script(test: str, effect: float | None = None,
                          alpha: float = 0.05, power: float = 0.80,
                          groups: int = 2) -> str:
    """据检验类型生成委托 statsmodels 的功效分析脚本。未知检验返回空串。

    test: t-ind(独立样本 t,效应量 Cohen's d)/ anova(单因素,f)/ correlation(r)。
    """
    e = effect if effect is not None else 0.5
    t = (test or "").strip().lower()

    if t in ("t-ind", "t", "ttest", "independent-t", "t_ind"):
        return f'''# 功效分析——委托 {_SM} 解样本量；psyclaw 只生成不算统计
# 检验：独立样本 t | 效应量 Cohen's d={e} | alpha={alpha} | power={power}
# 运行前: pip install {_SM} {_NP}
import {_NP} as np
from {_SM}.stats.power import TTestIndPower

E, A, P = {e}, {alpha}, {power}
analysis = TTestIndPower()
n = analysis.solve_power(effect_size=E, alpha=A, power=P, alternative="two-sided")
print("每组需要 N ≈", int(np.ceil(n)), " 总样本 ≈", int(np.ceil(n)) * 2)

print("敏感性分析（效应量高/低估时的 N/组）:")
for d in [round(E * 0.7, 3), E, round(E * 1.3, 3)]:
    nn = analysis.solve_power(effect_size=d, alpha=A, power=P)
    print("  d =", d, "-> N/组 ≈", int(np.ceil(nn)))
'''

    if t in ("anova", "f", "oneway", "one-way"):
        return f'''# 功效分析——委托 {_SM} 解样本量（单因素 ANOVA）；psyclaw 只生成不算统计
# 效应量 Cohen's f={e} | 组数 k={groups} | alpha={alpha} | power={power}
# 运行前: pip install {_SM} {_NP}
import {_NP} as np
from {_SM}.stats.power import FTestAnovaPower

E, A, P, K = {e}, {alpha}, {power}, {groups}
analysis = FTestAnovaPower()
n = analysis.solve_power(effect_size=E, alpha=A, power=P, k_groups=K)
print("每组需要 N ≈", int(np.ceil(n)), " 总样本 ≈", int(np.ceil(n)) * K)

print("敏感性分析（f -> N/组）:")
for f in [round(E * 0.7, 3), E, round(E * 1.3, 3)]:
    nn = analysis.solve_power(effect_size=f, alpha=A, power=P, k_groups=K)
    print("  f =", f, "-> N/组 ≈", int(np.ceil(nn)))
'''

    if t in ("correlation", "corr", "r", "pearson"):
        return f'''# 功效分析——相关检验(correlation)样本量；Fisher-z 公式，委托 {_SP}
# 相关系数 r={e} | alpha={alpha}(双侧) | power={power}
# 运行前: pip install {_SP} {_NP}
import {_NP} as np
from {_SP} import stats

R, A, P = {e}, {alpha}, {power}
za = stats.norm.ppf(1 - A / 2)
zb = stats.norm.ppf(P)
C = 0.5 * np.log((1 + R) / (1 - R))          # Fisher z 变换
n = int(np.ceil(((za + zb) / C) ** 2 + 3))
print("相关检验需要 N ≈", n)

print("敏感性分析（r -> N）:")
for r in [round(R * 0.7, 3), R, round(R * 1.3, 3)]:
    c = 0.5 * np.log((1 + r) / (1 - r))
    print("  r =", r, "-> N ≈", int(np.ceil(((za + zb) / c) ** 2 + 3)))
'''

    return ""
