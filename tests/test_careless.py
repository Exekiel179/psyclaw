"""feat: 虚伪作答标记(careless / insufficient-effort responding)——纯数据体检。

守 psyclaw 铁律:这里只做**确定性计数/极值**的数据卫生标记(longstring/漏答/
直入式作答),不算任何统计(无协方差、无分布、无参数估计)。需要协方差的马氏距离、
需要 SD 的 IRV,以及信度 α,一律走外移脚本,不在本模块实现。
"""
from __future__ import annotations

from psyclaw.psych.careless import (
    careless_report,
    longstring,
    missing_rate,
    invariant,
)

_MISS = None


# ---- longstring:最长连续相同应答 --------------------------------------------

def test_longstring_basic():
    assert longstring([1, 1, 1, 2, 3]) == 3
    assert longstring([1, 2, 3, 4]) == 1
    assert longstring([5, 5, 5, 5]) == 4


def test_longstring_empty_and_single():
    assert longstring([]) == 0
    assert longstring([7]) == 1


def test_longstring_missing_breaks_run():
    # 缺失打断连续段:1,1,None,1 → 最长 2
    assert longstring([1, 1, _MISS, 1]) == 2


# ---- 漏答率 -------------------------------------------------------------------

def test_missing_rate():
    assert missing_rate([1, _MISS, 3, _MISS]) == 0.5
    assert missing_rate([1, 2, 3]) == 0.0
    assert missing_rate([_MISS, _MISS]) == 1.0


def test_missing_rate_empty():
    assert missing_rate([]) == 0.0


# ---- 直入式/规律作答(所有非缺失应答相同)-----------------------------------

def test_invariant():
    assert invariant([3, 3, 3, 3]) is True
    assert invariant([3, 3, _MISS, 3]) is True     # 忽略缺失
    assert invariant([1, 2, 3]) is False


def test_invariant_needs_at_least_two():
    assert invariant([4]) is False                 # 单项不算规律作答
    assert invariant([]) is False


# ---- 逐被试报告 + 汇总 --------------------------------------------------------

def test_report_flags_careless_row():
    # 第 0 行全 3(直入式+长串),第 1 行正常
    matrix = [
        [3, 3, 3, 3, 3, 3],
        [2, 4, 1, 5, 3, 2],
    ]
    rep = careless_report(matrix, longstring_cut=5)
    assert rep["rows"][0]["invariant"] is True
    assert rep["rows"][0]["longstring"] == 6
    assert rep["rows"][0]["suspect"] is True
    assert rep["rows"][1]["suspect"] is False
    assert rep["n_suspect"] == 1
    assert rep["n_total"] == 2


def test_report_missing_threshold():
    matrix = [[1, _MISS, _MISS, _MISS, 2, 3]]     # 漏答 50%
    rep = careless_report(matrix, missing_cut=0.4)
    assert rep["rows"][0]["missing_rate"] == 0.5
    assert rep["rows"][0]["suspect"] is True


def test_report_no_stats_dependency():
    """本模块绝不 import 统计库(铁律:数据体检≠统计建模)。"""
    import psyclaw.psych.careless as C
    import inspect
    src = inspect.getsource(C)
    for banned in ("import scipy", "import numpy", "from scipy", "from numpy",
                   "pingouin", "statsmodels"):
        assert banned not in src, f"careless.py 不该依赖统计库:{banned}"


def test_report_empty_matrix():
    rep = careless_report([])
    assert rep["n_total"] == 0 and rep["n_suspect"] == 0 and rep["rows"] == []
