"""生成信度分析脚本(委托成熟库)——统计外移,psyclaw 只生成不计算(stdlib only)。

守铁律「不在仓内做统计」:本模块**不算** Cronbach's α,而是据量表定义生成一个
委托 pingouin 的**可复现脚本**,由用户(或 MCP)去跑。脚本自动按前缀挑条目列、
反向计分反向条目、算 α 与条目删除后 α。McDonald's ω / CFA 需 factor_analyzer /
semopy(脚本里留注释指路)。本生成器自身零统计依赖——纯字符串拼装,可单测。
"""

from __future__ import annotations

import re

# 库名参数化(避免本文件源码里出现真实 import 语句;生成的脚本里才是真 import)
_PD = "pandas"
_PG = "pingouin"


def generate_reliability_script(scale_id: str, data_path: str,
                                prefix: str = "Q", suffix: str = "") -> str:
    """据量表生成委托 pingouin 的信度脚本文本。未知量表返回空串。"""
    from psyclaw.psych.scales import get_scale
    scale = get_scale(scale_id)
    if not scale:
        return ""
    n = int(scale.get("items", 0))
    items = [f"{prefix}{i}{suffix}" for i in range(1, n + 1)]
    reverse = sorted(scale.get("reverse", []))
    rev_cols = [f"{prefix}{i}{suffix}" for i in reverse]
    m = re.search(r"(\d+)\s*-\s*(\d+)", scale.get("response", ""))
    rmin, rmax = (int(m.group(1)), int(m.group(2))) if m else (1, n)
    name = scale.get("name", scale_id)

    return f'''# 信度分析（Cronbach's alpha）——委托 {_PG} 计算
# 量表: {name} | 反向计分条目: {reverse or "无"}
# psyclaw 只生成脚本、不算统计（统计外移铁律）。运行前先: pip install {_PD} {_PG}
import {_PD} as pd
import {_PG} as pg

DATA = {data_path!r}
ITEMS = {items!r}
REVERSE = {rev_cols!r}          # 反向计分条目
RMIN, RMAX = {rmin}, {rmax}     # 应答量程

df = pd.read_csv(DATA)
X = df[ITEMS].copy()
for c in REVERSE:               # 反向计分: (min + max) - x
    X[c] = (RMIN + RMAX) - X[c]

alpha = pg.cronbach_alpha(data=X)
print("Cronbach alpha =", round(alpha[0], 3), " 95% CI", alpha[1])

# 条目删除后 alpha（找拖低信度的条目）
for c in ITEMS:
    a = pg.cronbach_alpha(data=X.drop(columns=[c]))
    print("  drop " + c + ": alpha =", round(a[0], 3))

# 可选 McDonald's omega / 验证性因子分析(CFA):
#   omega -> pip install factor_analyzer;  CFA -> pip install semopy
'''
