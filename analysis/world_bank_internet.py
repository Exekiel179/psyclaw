#!/usr/bin/env python
"""可复现实证分析(委托 pingouin/scipy;由 `psyclaw analysis` 生成)。

统计计算外移:运行前装统计栈 —— pip install "psyclaw[stats]"。
推荐分析:correlation —— 两个连续变量 year、value → Pearson 相关
效应量 + 95% CI 由 pingouin 一并给出;前提诊断(正态/方差齐性)随报。
"""
import pandas as pd
import pingouin as pg

df = pd.read_csv(r"C:\Users\Exekiel.000\AppData\Local\Temp\psyclaw-real-analysis-20260814\data\clean\world_bank_internet.csv")

sub = df[["year", "value"]].apply(pd.to_numeric, errors="coerce").dropna()
if len(sub) < len(df):
    print(f"⚠ 剔除 {len(df) - len(sub)} 行(缺失/不可解析)——须如实报告")
print("Pearson 相关:")
print(pg.corr(sub["year"], sub["value"]))   # r / CI95 / p_val
