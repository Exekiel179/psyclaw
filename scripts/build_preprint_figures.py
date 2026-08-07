#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 PsyClaw 预印本的示意图（图1 架构与数据流；图2 三理念协同）。
输出 300 dpi PNG 至 figures/。中文用 macOS 自带 Hiragino/Arial Unicode。
重跑：UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
      uv run --python 3.12 --with matplotlib python scripts/build_preprint_figures.py
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib.font_manager import FontProperties

# ---- 中文字体 ----
_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
_FP = next((FontProperties(fname=p) for p in _CANDIDATES if os.path.exists(p)), FontProperties())
def F(size, weight="normal"):
    fp = _FP.copy(); fp.set_size(size); fp.set_weight(weight); return fp

# ---- 品牌配色 ----
TEAL      = "#0F8B8D"   # 主青
TEAL_D    = "#0A5F61"   # 深青
TEAL_L    = "#D8ECEC"   # 浅青底
INK       = "#22303A"   # 墨
GREY      = "#5B6B75"   # 次要文字
PAPER     = "#FBFCFC"   # 底
BAND      = "#F0F4F5"   # 层带底
GOLD      = "#C7853B"   # 强调（核查/阻断）
GOLD_L    = "#F6EBDA"

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "figures")
os.makedirs(OUT, exist_ok=True)


def _box(ax, x, y, w, h, fc, ec, lw=1.4, r=0.035, z=2):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.0,rounding_size={r}",
                       linewidth=lw, edgecolor=ec, facecolor=fc, zorder=z)
    ax.add_patch(p)
    return p


def _txt(ax, x, y, s, fp, color=INK, ha="center", va="center", z=5):
    ax.text(x, y, s, fontproperties=fp, color=color, ha=ha, va=va, zorder=z)


def _arrow(ax, xy1, xy2, color=TEAL_D, lw=1.6, style="-|>", ms=11, ls="-", rad=0.0, z=4):
    a = FancyArrowPatch(xy1, xy2, arrowstyle=style, mutation_scale=ms, lw=lw,
                        color=color, linestyle=ls, zorder=z,
                        connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2)
    ax.add_patch(a)


# =========================================================================
# 图 1：四层 + 两横切架构与数据流
# =========================================================================
def figure1():
    fig, ax = plt.subplots(figsize=(11.2, 7.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)

    _txt(ax, 50, 96.5, "图 1  PsyClaw 四层加两横切架构与数据流", F(15, "bold"), INK)

    # 用户 / CLI 入口
    _box(ax, 6, 87.5, 66, 6.6, "#FFFFFF", INK, 1.4)
    _txt(ax, 10, 90.8, "研究者", F(11, "bold"), INK, ha="left")
    _txt(ax, 39, 90.8, "自然语言  ·  chat / run / auto", F(10.5), GREY)

    # 横切两条：Harness（左）Memory（右）—— 贯穿四层背景
    band_top, band_bot = 84.0, 12.0
    _box(ax, 4.0, band_bot, 6.4, band_top - band_bot, GOLD_L, GOLD, 1.3, r=0.02, z=1)
    ax.text(7.2, (band_top+band_bot)/2, "Harness 横切\n每步前置检查（失败即阻断）\n机器可读总验收",
            fontproperties=F(9.2, "bold"), color=GOLD, ha="center", va="center",
            rotation=90, zorder=3)
    _box(ax, 89.6, band_bot, 6.4, band_top - band_bot, TEAL_L, TEAL_D, 1.3, r=0.02, z=1)
    ax.text(92.8, (band_top+band_bot)/2, "Memory 横切\n三层记忆\n方法学·期刊·教训",
            fontproperties=F(9.2, "bold"), color=TEAL_D, ha="center", va="center",
            rotation=90, zorder=3)

    # 四层主栈（在两横切之间）
    lx, lw = 11.6, 76.8
    layers = [
        ("L0  路由 Router", "三入口共享路由定义 modes.py：chat（对话）· run（声明式流程）· auto（自主）",
         77.0, 6.4, TEAL, "#FFFFFF"),
        ("L1  流程 Workflow", "每类研究 = 一份纯数据（步骤 + 前置检查）；引擎逐步跑 + HITL + 断点恢复 + 总验收",
         67.6, 6.4, TEAL_L, INK),
        ("L2  子功能 Step", "每步薄封装：可单用（多为 CLI 命令）· 可拆（纯函数）· 可拼（进任意流程）",
         58.2, 6.4, TEAL_L, INK),
        ("L3  实现 Skill + MCP", "既有命令 / 技能 / MCP 后端；统计计算整体落此层",
         48.8, 6.4, TEAL_L, INK),
    ]
    for title, sub, y, h, fc, tc in layers:
        _box(ax, lx, y, lw, h, fc, TEAL_D, 1.5)
        _txt(ax, lx + 2.5, y + h*0.66, title, F(11.5, "bold"), tc, ha="left")
        _txt(ax, lx + 2.5, y + h*0.26, sub, F(8.8), tc if tc != "#FFFFFF" else "#EAF6F6", ha="left")

    # 竖向数据流箭头（逐层）与回流（上行）
    cx = lx + lw*0.30
    for y0, y1 in [(77.0, 74.0), (67.6, 64.6), (58.2, 55.2)]:
        _arrow(ax, (cx, y0), (cx, y1), TEAL_D, 1.8, ms=12)
    ux = lx + lw*0.70
    for y0, y1 in [(55.2, 58.2), (64.6, 67.6), (74.0, 77.0)]:
        _arrow(ax, (ux, y0), (ux, y1), GREY, 1.3, ms=10, ls=(0, (4, 2)))
    _txt(ax, cx - 1.2, 71.0, "逐层委托", F(8.2), TEAL_D, ha="right")
    _txt(ax, ux + 1.2, 71.0, "结果 / 证据回流", F(8.2), GREY, ha="left")

    # L3 之下：外部实现（统计外移）——标题独占一行，库框在下
    _box(ax, lx, 39.6, lw, 7.6, "#FFFFFF", INK, 1.4)
    _txt(ax, lx + lw/2, 46.1, "统计外移 —— 本仓不实现任何统计算法", F(10.5, "bold"), GOLD)
    ext = [("pingouin", 13.5), ("statsmodels", 27.5), ("SciPy", 41.5),
           ("MNE-MCP", 54.5), ("SPSS/Stata/Mplus\n(MCP)", 70.5)]
    for name, x in ext:
        _box(ax, x, 40.4, 12.4, 4.1, TEAL_L, TEAL_D, 1.2, r=0.05)
        _txt(ax, x + 6.2, 42.45, name, F(8.6, "bold"), TEAL_D)
    for x in [19.7, 33.7, 47.7, 60.7, 76.7]:
        _arrow(ax, (x, 48.6), (x, 47.5), TEAL_D, 1.2, ms=9, ls=(0, (3, 2)))

    # 四类声明式流程（L1 展开示例）
    _box(ax, lx, 27.5, lw, 9.5, BAND, GREY, 1.2, r=0.02, z=1)
    _txt(ax, lx + lw/2, 34.7, "L1 的四类声明式研究流程", F(10, "bold"), INK)
    flows = [
        ("文献综述", "clarify → 检索(PRISMA) →\n筛选 → 合成 → 评审"),
        ("元分析", "校验效应量 → 委托\nstatsmodels 随机效应"),
        ("实证分析", "数据画像 → 推荐 →\n委托 pingouin/SciPy"),
        ("质性分析", "转录本 → LLM 辅助\n编码/主题（HITL）"),
    ]
    fw = 17.6
    for i, (nm, desc) in enumerate(flows):
        x = lx + 2.6 + i * (fw + 1.4)
        _box(ax, x, 28.4, fw, 4.9, "#FFFFFF", TEAL_D, 1.2, r=0.05)
        _txt(ax, x + fw/2, 32.4, nm, F(9.3, "bold"), TEAL_D)
        _txt(ax, x + fw/2, 30.2, desc, F(7.6), GREY)

    # 产物
    _box(ax, lx, 13.5, lw, 6.2, GOLD_L, GOLD, 1.4)
    _txt(ax, lx + lw/2, 16.6, "可复现产物", F(10.5, "bold"), GOLD)
    _txt(ax, lx + lw/2, 14.5,
         "等效脚本 + 数据指纹  ·  机器可读总验收 workflow_summary.json  ·  按序号归档",
         F(8.8), INK)

    # 全局竖向主脉：入口→L0→…→产物
    _arrow(ax, (lx + lw*0.5, 87.5), (lx + lw*0.5, 83.5), INK, 1.6, ms=11)
    _arrow(ax, (lx + lw*0.5, 48.8), (lx + lw*0.5, 47.3), INK, 1.4, ms=10)
    _arrow(ax, (lx + lw*0.5, 39.6), (lx + lw*0.5, 37.1), INK, 1.4, ms=10)
    _arrow(ax, (lx + lw*0.5, 27.5), (lx + lw*0.5, 19.8), INK, 1.4, ms=10)

    # gate 标记（Harness 对每层的约束）示意：右向三角，指向各层
    for y in [80.2, 70.8, 61.4, 52.0]:
        ax.plot(10.9, y, marker=">", markersize=9, color=GOLD,
                markeredgecolor=GOLD, zorder=6)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    path = os.path.join(OUT, "psyclaw_fig1_architecture.png")
    fig.savefig(path, dpi=300, facecolor=PAPER)
    plt.close(fig)
    return path


# =========================================================================
# 图 2：三理念协同（声明式流程 · 失败即阻断的核查 · 统计外移）
# =========================================================================
def figure2():
    fig, ax = plt.subplots(figsize=(11.2, 6.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)

    _txt(ax, 50, 95.5, "图 2  三项核心设计理念在一个流程步骤上的协同", F(15, "bold"), INK)

    # 中央：一个「流程步骤」
    _box(ax, 38, 44, 24, 14, TEAL, TEAL_D, 1.8, r=0.06)
    _txt(ax, 50, 53.3, "一个流程步骤", F(12.5, "bold"), "#FFFFFF")
    _txt(ax, 50, 49.6, "Step", F(9.5), "#EAF6F6")
    _txt(ax, 50, 46.4, "（如「分析」「合成」）", F(8.6), "#DCEFEF")

    # 理念一：声明式流程（上）——步骤的来源
    _box(ax, 30, 78, 40, 12.5, TEAL_L, TEAL_D, 1.5, r=0.05)
    _txt(ax, 50, 86.4, "① 声明式研究流程", F(12, "bold"), TEAL_D)
    _txt(ax, 50, 82.7, "流程 = 纯数据（步骤 + 前置检查）；引擎逐步执行，", F(8.9), INK)
    _txt(ax, 50, 80.2, "可重放、可改装、末尾出机器可读总验收", F(8.9), INK)
    _arrow(ax, (50, 78), (50, 58.3), TEAL_D, 2.0, ms=13)
    _txt(ax, 51.5, 68, "定义并驱动", F(8.6), TEAL_D, ha="left")

    # 理念二：失败即阻断的核查（左）——步骤执行前的关卡
    _box(ax, 3.5, 40, 26, 22, GOLD_L, GOLD, 1.6, r=0.05)
    _txt(ax, 16.5, 58.0, "② 学术诚信核查", F(12, "bold"), GOLD)
    for i, s in enumerate([
        "效应量 + CI 必报",
        "区分探索 / 确证",
        "确证须预注册",
        "相关 ≠ 因果",
        "图件完整性",
        "PRISMA · APA7 · 复现脚本",
    ]):
        _txt(ax, 6.0, 53.6 - i*2.55, "•", F(9.5, "bold"), GOLD, ha="left")
        _txt(ax, 8.2, 53.6 - i*2.55, s, F(8.7), INK, ha="left")
    # 核查把关箭头（阻断/放行）
    _arrow(ax, (29.5, 51), (38, 51), GOLD, 2.0, ms=13)
    _txt(ax, 33.5, 53.2, "PASS→放行", F(8.0), TEAL_D)
    _arrow(ax, (35, 47.5), (31, 43), GOLD, 1.8, ms=12, style="-|>", rad=0.3)
    _txt(ax, 36.0, 41.0, "FAIL→阻断 + 修复", F(8.0), GOLD, ha="center")

    # 理念三：统计外移（右）——步骤把计算委托出去
    _box(ax, 70.5, 40, 26, 22, TEAL_L, TEAL_D, 1.6, r=0.05)
    _txt(ax, 83.5, 58.0, "③ 统计外移", F(12, "bold"), TEAL_D)
    _txt(ax, 83.5, 54.6, "本仓不实现任何统计算法", F(8.9, "bold"), GOLD)
    _txt(ax, 83.5, 51.8, "委托成熟库 / MCP 后端：", F(8.6), INK)
    for i, s in enumerate(["pingouin · statsmodels · SciPy",
                           "MNE-MCP · SPSS / Stata / Mplus"]):
        _txt(ax, 83.5, 48.6 - i*2.6, s, F(8.4), TEAL_D)
    _txt(ax, 83.5, 42.7, "数值正确性归外部库承担", F(8.2), GREY)
    _arrow(ax, (62, 51), (70.5, 51), TEAL_D, 2.0, ms=13)
    _txt(ax, 66.2, 53.2, "委托计算", F(8.0), TEAL_D)
    _arrow(ax, (70.5, 47.5), (62, 45), GREY, 1.4, ms=10, ls=(0, (4, 2)), rad=-0.25)
    _txt(ax, 66.2, 43.4, "结果回流", F(7.8), GREY)

    # 底部：三者合力 → 产物
    _box(ax, 22, 12, 56, 12, "#FFFFFF", INK, 1.5, r=0.04)
    _txt(ax, 50, 20.6, "合力产出", F(11.5, "bold"), INK)
    _txt(ax, 50, 17.3, "工作流可复现（等效脚本 + 指纹 + 归档）", F(9.0), TEAL_D)
    _txt(ax, 50, 14.4, "× 内容合规（核查把关）  ×  数值可信（外部库）", F(9.0), GOLD)
    _arrow(ax, (50, 44), (50, 24.2), INK, 1.8, ms=12)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    path = os.path.join(OUT, "psyclaw_fig2_principles.png")
    fig.savefig(path, dpi=300, facecolor=PAPER)
    plt.close(fig)
    return path


if __name__ == "__main__":
    p1 = figure1()
    p2 = figure2()
    print("wrote:", p1)
    print("wrote:", p2)
