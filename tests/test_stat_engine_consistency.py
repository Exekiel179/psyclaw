"""双引擎一致性回归门禁 —— 锁死 `stat` 与 `ttest`/`anova` 的数值口径。

背景：`stat`(自动选检验)走 psych.analyze → psych.stats_core；`ttest`/`anova`
等专用命令走各自模块。两条码路曾各自手写检验统计量,存在"改一处忘改另一处"
的数值漂移风险。收敛后两者的 t/F/p 一律取自同一 scipy 原语。

本测试在同一组合成数据上,把 **stats_core(stat 引擎核)**、**专用命令核**、
**scipy 金标准** 三方对照——任一未来回归(某条路径重新手写、换库导致口径变化)
都会让此门禁变红,迫使两侧同步。

需 scipy。本机解释器:C:\\Python314\\python -m pytest。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scipy_stats = pytest.importorskip("scipy.stats")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psyclaw.psych import stats_core as sc  # noqa: E402
from psyclaw.psych import ttest as ttest_mod  # noqa: E402
from psyclaw.psych import anova as anova_mod  # noqa: E402

# 确定性合成数据（三组，组均值递增；不依赖随机种子，跨平台稳定）
G_A = [4.1, 5.2, 4.8, 5.5, 4.4, 5.0, 4.9, 5.3, 4.6, 5.1]
G_B = [5.9, 6.4, 6.0, 6.8, 5.7, 6.2, 6.5, 6.1, 6.3, 5.8]
G_C = [7.2, 7.8, 7.5, 8.1, 7.0, 7.6, 7.9, 7.4, 7.7, 7.3]
# 配对/相关用等长 x,y（y 与 x 正相关但有噪声，差值方差非零）
PX = [3.0, 5.0, 4.0, 6.0, 2.0, 7.0, 4.5, 5.5, 3.5, 6.5]
PY = [1.2, 2.1, 2.0, 3.3, 1.1, 4.0, 2.2, 3.1, 1.4, 3.2]

# 容差：专用命令核对外 round 到 4~6 位，故放宽到该量级
T_TOL = 1e-3      # t/F round(.,4)
DF_TOL = 1e-2     # df round(.,2)
P_TOL = 1e-5      # p round(.,6)
EFF_TOL = 1e-3    # eta²/r round(.,4)


# ── 独立样本 t：stats_core.welch_ttest vs ttest 核 vs scipy ────────────────

def test_welch_t_three_way_consistency():
    core = sc.welch_ttest(G_A, G_B)
    dedicated = ttest_mod.ttest_independent(G_A, G_B, welch=True)
    gold = scipy_stats.ttest_ind(G_A, G_B, equal_var=False)

    assert abs(core["t"] - float(gold.statistic)) < T_TOL
    assert abs(core["df"] - float(gold.df)) < DF_TOL
    assert abs(core["p"] - float(gold.pvalue)) < P_TOL
    # stat 引擎核 ≈ 专用命令核
    assert abs(core["t"] - dedicated["t"]) < T_TOL
    assert abs(core["df"] - dedicated["df"]) < DF_TOL
    assert abs(core["p"] - dedicated["p"]) < P_TOL


def test_student_t_three_way_consistency():
    core = sc.student_ttest(G_A, G_B)
    dedicated = ttest_mod.ttest_independent(G_A, G_B, welch=False)
    gold = scipy_stats.ttest_ind(G_A, G_B, equal_var=True)

    assert abs(core["t"] - float(gold.statistic)) < T_TOL
    assert abs(core["p"] - float(gold.pvalue)) < P_TOL
    assert abs(core["t"] - dedicated["t"]) < T_TOL
    assert abs(core["p"] - dedicated["p"]) < P_TOL


# ── 配对样本 t：stats_core.paired_ttest vs ttest 核 vs scipy ───────────────

def test_paired_t_three_way_consistency():
    core = sc.paired_ttest(PX, PY)
    dedicated = ttest_mod.ttest_paired(PX, PY)
    gold = scipy_stats.ttest_rel(PX, PY)

    assert abs(core["t"] - float(gold.statistic)) < T_TOL
    assert abs(core["p"] - float(gold.pvalue)) < P_TOL
    assert core["df"] == dedicated["df"]
    assert abs(core["t"] - dedicated["t"]) < T_TOL
    assert abs(core["p"] - dedicated["p"]) < P_TOL


# ── Pearson 相关：stats_core.pearson_r vs scipy ───────────────────────────

def test_pearson_r_matches_scipy():
    core = sc.pearson_r(PX, PY)
    gold = scipy_stats.pearsonr(PX, PY)

    assert abs(core["r"] - float(gold.statistic)) < EFF_TOL
    assert abs(core["p"] - float(gold.pvalue)) < P_TOL


# ── 单因素 ANOVA：stats_core(经典 F) vs anova 核 vs scipy ──────────────────

def test_oneway_anova_three_way_consistency():
    core = sc.oneway_anova_full([G_A, G_B, G_C])["classic"]
    dedicated = anova_mod.one_way_anova({"A": G_A, "B": G_B, "C": G_C})
    gold = scipy_stats.f_oneway(G_A, G_B, G_C)

    assert abs(core["F"] - float(gold.statistic)) < T_TOL
    assert abs(core["p"] - float(gold.pvalue)) < P_TOL
    # stat 引擎核 ≈ 专用命令核
    assert abs(core["F"] - dedicated["F"]) < T_TOL
    assert abs(core["p"] - dedicated["p"]) < P_TOL
    assert abs(core["eta2"] - dedicated["eta2"]) < EFF_TOL
