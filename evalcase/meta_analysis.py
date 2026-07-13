import numpy as np
from scipy import stats
import csv, sys, json

# --- 读取并筛选数据 ---
rows = []
with open('evalcase/effects.csv', 'r') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

# 过滤：排除 Zhao2019(se=0) 和 Chen2021_T2(重复队列)
exclude_studies = ['Zhao2019', 'Chen2021_T2']
filtered = [r for r in rows if r['study'] not in exclude_studies]

# 提取数值
studies = []
for r in filtered:
    d_val = float(r['d'])
    se_val = float(r['se'])
    n_val = int(r['n'])
    label = r['study']
    is_outlier = (label == 'Wang2020')
    studies.append({
        'label': label,
        'year': int(r['year']),
        'n': n_val,
        'd': d_val,
        'se': se_val,
        'outlier': is_outlier
    })

print("="*60)
print("研究列表（含异常标记）:")
for s in studies:
    flag = " ❗异常" if s['outlier'] else ""
    print(f"  {s['label']} (n={s['n']}, d={s['d']:.3f}, se={s['se']:.3f}){flag}")
print(f"共 {len(studies)} 项独立研究")

# --- 随机效应 Meta 分析 (DerSimonian-Laird) ---
k = len(studies)
d_vals = np.array([s['d'] for s in studies])
se_vals = np.array([s['se'] for s in studies])
w_fixed = 1 / (se_vals**2)

# 固定效应汇总 (用于计算 Q)
d_fixed = np.sum(w_fixed * d_vals) / np.sum(w_fixed)
Q = np.sum(w_fixed * (d_vals - d_fixed)**2)
df = k - 1
p_q = 1 - stats.chi2.cdf(Q, df)

# 异质性 I²
C = np.sum(w_fixed) - np.sum(w_fixed**2) / np.sum(w_fixed)
tau2 = max(0, (Q - df) / C)
I2 = max(0, (Q - df) / Q * 100) if Q > 0 else 0

print("\n--- 异质性 ---")
print(f"Q = {Q:.3f}, df = {df}, p = {p_q:.4f}")
print(f"τ² = {tau2:.4f}, I² = {I2:.1f}%")

# 随机效应权重
w_random = 1 / (se_vals**2 + tau2)
d_random = np.sum(w_random * d_vals) / np.sum(w_random)
se_random = np.sqrt(1 / np.sum(w_random))
z = d_random / se_random
p_z = 2 * (1 - stats.norm.cdf(abs(z)))
ci_lo = d_random - 1.96 * se_random
ci_hi = d_random + 1.96 * se_random

print("\n--- 随机效应主分析 ---")
print(f"汇总 d = {d_random:.3f} (95% CI: {ci_lo:.3f} ~ {ci_hi:.3f})")
print(f"z = {z:.3f}, p = {p_z:.6f}")

# 每个研究的贡献
print("\n—— 各研究权重 (随机效应) ——")
for i, s in enumerate(studies):
    print(f"  {s['label']}: w={w_random[i]:.2f}")

# --- Egger 回归检验 (漏斗不对称) ---
# 以精度(1/se)预测效应量，加权回归
precision = 1 / se_vals
# 加权最小二乘: 效应量 ~ 精度 (截距为 bias)
# 使用随机效应权重
X = np.column_stack((np.ones(k), precision))
W = np.diag(w_random)
beta = np.linalg.inv(X.T @ W @ X) @ (X.T @ W @ d_vals)
residuals = d_vals - X @ beta
MSE = np.sum(w_random * residuals**2) / (k-2)
var_beta = MSE * np.linalg.inv(X.T @ W @ X)
se_beta = np.sqrt(np.diag(var_beta))
t_bias = beta[0] / se_beta[0]
p_egger = 2 * (1 - stats.t.cdf(abs(t_bias), df=k-2))
print("\n--- 漏斗不对称检验 (Egger回归) ---")
print(f"截距 (bias) = {beta[0]:.4f} (SE = {se_beta[0]:.4f})")
print(f"t = {t_bias:.3f}, p = {p_egger:.4f}")

# --- 留一法影响分析 (逐篇剔除) ---
print("\n--- 留一法影响分析 ---")
d_leave_list = []
for leave_idx in range(k):
    idx = [i for i in range(k) if i != leave_idx]
    d_keep = d_vals[idx]
    se_keep = se_vals[idx]
    w_fixed_keep = 1 / (se_keep**2)
    d_fixed_keep = np.sum(w_fixed_keep * d_keep) / np.sum(w_fixed_keep)
    Q_keep = np.sum(w_fixed_keep * (d_keep - d_fixed_keep)**2)
    C_keep = np.sum(w_fixed_keep) - np.sum(w_fixed_keep**2) / np.sum(w_fixed_keep)
    tau2_keep = max(0, (Q_keep - (k-2)) / C_keep)
    w_rand_keep = 1 / (se_keep**2 + tau2_keep)
    d_rand_keep = np.sum(w_rand_keep * d_keep) / np.sum(w_rand_keep)
    se_rand_keep = np.sqrt(1 / np.sum(w_rand_keep))
    d_leave_list.append((studies[leave_idx]['label'], d_rand_keep, se_rand_keep, 
                         d_rand_keep - 1.96*se_rand_keep, d_rand_keep + 1.96*se_rand_keep))
    print(f"  剔除 {studies[leave_idx]['label']}: d = {d_rand_keep:.3f} "
          f"(95% CI: {d_rand_keep - 1.96*se_rand_keep:.3f} ~ {d_rand_keep + 1.96*se_rand_keep:.3f})")

# --- 稳健性1: 固定效应模型 ---
d_fixed_re = d_fixed  # 已算
se_fixed = 1 / np.sqrt(np.sum(w_fixed))
z_fixed = d_fixed / se_fixed
p_fixed = 2 * (1 - stats.norm.cdf(abs(z_fixed)))
ci_lo_fixed = d_fixed - 1.96 * se_fixed
ci_hi_fixed = d_fixed + 1.96 * se_fixed
print("\n--- 稳健性1: 固定效应模型 ---")
print(f"汇总 d = {d_fixed:.3f} (95% CI: {ci_lo_fixed:.3f} ~ {ci_hi_fixed:.3f})")
print(f"z = {z_fixed:.3f}, p = {p_fixed:.6f}")

# --- 稳健性2: 剔除异常值 Wang2020 后的随机效应 ---
normal_studies = [s for s in studies if not s['outlier']]
k_norm = len(normal_studies)
d_norm = np.array([s['d'] for s in normal_studies])
se_norm = np.array([s['se'] for s in normal_studies])
w_fix_norm = 1 / (se_norm**2)
d_fix_norm = np.sum(w_fix_norm * d_norm) / np.sum(w_fix_norm)
Q_norm = np.sum(w_fix_norm * (d_norm - d_fix_norm)**2)
C_norm = np.sum(w_fix_norm) - np.sum(w_fix_norm**2) / np.sum(w_fix_norm)
tau2_norm = max(0, (Q_norm - (k_norm-1)) / C_norm)
w_rand_norm = 1 / (se_norm**2 + tau2_norm)
d_rand_norm = np.sum(w_rand_norm * d_norm) / np.sum(w_rand_norm)
se_rand_norm = np.sqrt(1 / np.sum(w_rand_norm))
z_norm = d_rand_norm / se_rand_norm
p_norm = 2 * (1 - stats.norm.cdf(abs(z_norm)))
ci_lo_norm = d_rand_norm - 1.96 * se_rand_norm
ci_hi_norm = d_rand_norm + 1.96 * se_rand_norm
print("\n--- 稳健性2: 剔除Wang2020异常值后随机效应 ---")
print(f"汇总 d = {d_rand_norm:.3f} (95% CI: {ci_lo_norm:.3f} ~ {ci_hi_norm:.3f})")
print(f"z = {z_norm:.3f}, p = {p_norm:.6f}")
print(f"I² = {max(0, (Q_norm - (k_norm-1)) / Q_norm * 100):.1f}%")

# --- 完整结果JSON输出 (供后续使用) ---
results = {
    'k': k,
    'random': {'d': d_random, 'se': se_random, 'ci_lo': ci_lo, 'ci_hi': ci_hi, 'z': z, 'p': p_z,
               'tau2': tau2, 'I2': I2, 'Q': Q, 'p_Q': p_q},
    'fixed': {'d': d_fixed, 'se': se_fixed, 'ci_lo': ci_lo_fixed, 'ci_hi': ci_hi_fixed, 'z': z_fixed, 'p': p_fixed},
    'no_outlier': {'d': d_rand_norm, 'se': se_rand_norm, 'ci_lo': ci_lo_norm, 'ci_hi': ci_hi_norm, 'z': z_norm, 'p': p_norm},
    'egger': {'bias': beta[0], 'se_bias': se_beta[0], 't': t_bias, 'p': p_egger},
    'leave_one_out': d_leave_list
}
print("\n--- 分析完成 ---")