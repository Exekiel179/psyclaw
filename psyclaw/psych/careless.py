"""虚伪作答标记(careless / insufficient-effort responding)——纯数据体检(stdlib only)。

守 psyclaw 铁律「不在仓内做统计计算」:本模块只做**确定性计数/极值**的数据卫生
标记,不算任何统计——
  · longstring:最长连续相同应答(纯计数)
  · missing_rate:漏答率(纯计数)
  · invariant:直入式/规律作答,所有非缺失应答相同(纯极值 min==max)

**不实现**任何需要统计的指标:马氏距离(要协方差求逆)、IRV(个体内 SD)、
心理测量同义/反义项相关——这些连同信度 α/ω、CFA 一律走**外移脚本**
(委托外部成熟统计库),不在本模块。纯函数,可单测。
"""

from __future__ import annotations


def _clean(responses: list) -> list:
    """去掉缺失(None / 空串),其余原样。"""
    return [r for r in responses if r is not None and r != ""]


def longstring(responses: list) -> int:
    """最长连续相同应答的长度。缺失打断连续段。空序列返回 0。"""
    longest = 0
    run = 0
    prev = _SENTINEL = object()
    for r in responses:
        if r is None or r == "":          # 缺失打断
            run = 0
            prev = _SENTINEL
            continue
        if r == prev:
            run += 1
        else:
            run = 1
            prev = r
        if run > longest:
            longest = run
    return longest


def missing_rate(responses: list) -> float:
    """漏答率 = 缺失数 / 总项数。空序列返回 0.0。"""
    if not responses:
        return 0.0
    miss = sum(1 for r in responses if r is None or r == "")
    return miss / len(responses)


def invariant(responses: list) -> bool:
    """直入式/规律作答:去缺失后 ≥2 项且全部相同(min==max)。"""
    vals = _clean(responses)
    return len(vals) >= 2 and len(set(vals)) == 1


def careless_report(matrix: list, *, longstring_cut: int | None = None,
                    missing_cut: float = 0.5) -> dict:
    """对逐被试的项目应答矩阵做数据体检。

    matrix: list[row];每 row 是一名被试在各项目上的应答(缺失用 None/空串)。
    longstring_cut: 长串阈值(达到即标记);None → 取 max(5, 该被试项数的一半)。
    missing_cut: 漏答率阈值(超过即标记)。
    返回 {rows:[{row,longstring,missing_rate,invariant,suspect}], n_total, n_suspect}。
    suspect = 三类标记任一命中(纯规则,不做统计判定)。
    """
    rows = []
    for i, resp in enumerate(matrix):
        n = len(resp)
        ls = longstring(resp)
        mr = missing_rate(resp)
        inv = invariant(resp)
        cut = longstring_cut if longstring_cut is not None else max(5, n // 2)
        suspect = inv or (ls >= cut) or (mr > missing_cut)
        rows.append({"row": i, "longstring": ls, "missing_rate": mr,
                     "invariant": inv, "suspect": suspect})
    n_suspect = sum(1 for r in rows if r["suspect"])
    return {"rows": rows, "n_total": len(rows), "n_suspect": n_suspect}
