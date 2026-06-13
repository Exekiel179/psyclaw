"""信度计算 — 纯 stdlib。

Cronbach's α(及逐题删除后 α),供 ARS-Stat 与 MEASURE.reliability 门禁使用。
McDonald's ω 需因子载荷,留给 M2 接 R/lavaan 后实现(ω 通常优于 α,届时默认双报)。
"""

from __future__ import annotations


def _variance(xs: list) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def cronbach_alpha(items: list) -> float:
    """items: 每个元素是一道题的全部被试作答(列表的列表,k 题 × n 人)。"""
    k = len(items)
    if k < 2:
        return float("nan")
    n = len(items[0])
    item_vars = sum(_variance(col) for col in items)
    totals = [sum(items[i][p] for i in range(k)) for p in range(n)]
    total_var = _variance(totals)
    if total_var == 0:
        return float("nan")
    return (k / (k - 1)) * (1 - item_vars / total_var)


def alpha_if_deleted(items: list) -> list:
    """逐题删除后的 α,返回 [(题序, α_without)],用于定位拖后腿条目。"""
    out = []
    for i in range(len(items)):
        rest = items[:i] + items[i + 1:]
        out.append((i + 1, cronbach_alpha(rest)))
    return out


def interpret_alpha(a: float) -> str:
    if a != a:  # NaN
        return "无法计算(条目<2 或总分零方差)"
    if a >= 0.9:
        return "优(注意 >.95 可能提示条目冗余)"
    if a >= 0.8:
        return "良"
    if a >= 0.7:
        return "可接受"
    if a >= 0.6:
        return "勉强(谨慎使用)"
    return "差(不建议合成总分)"
