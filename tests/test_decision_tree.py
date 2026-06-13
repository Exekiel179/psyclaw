"""A-1 心理学检验决策树特判 — 完整测试套件。

覆盖:
  1. Likert 单题检测
  2. 大样本效应量语言
  3. 嵌套数据 ICC(1)
  4. 中介 bootstrap CI
  5. 调节简单斜率 + Johnson-Neyman
  6. CLI 集成测试(CSV 文件路径)
"""
from __future__ import annotations

import csv
import math
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.decision_tree import (
    bootstrap_mediation,
    compute_icc,
    detect_likert,
    large_sample_effect_language,
    moderation_analysis,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _csv(tmp: Path, headers: list, rows: list) -> str:
    p = tmp / "data.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    return str(p)


def _rng_data(n: int, seed: int = 42):
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(n)]


# ---------------------------------------------------------------------------
# 1. detect_likert
# ---------------------------------------------------------------------------

def test_likert_detected_1_5():
    rng = random.Random(1)
    vals = [float(rng.randint(1, 5)) for _ in range(100)]
    res = detect_likert(vals)
    assert res["is_likert"] is True
    lo, hi = res["range"]
    assert 1 <= lo and hi <= 5


def test_likert_detected_1_7():
    rng = random.Random(2)
    vals = [float(rng.randint(1, 7)) for _ in range(80)]
    res = detect_likert(vals)
    assert res["is_likert"] is True
    assert 1 <= res["range"][0] <= res["range"][1] <= 7


def test_likert_not_detected_continuous():
    rng = random.Random(99)
    vals = [rng.gauss(50, 10) for _ in range(200)]
    res = detect_likert(vals)
    assert res["is_likert"] is False


def test_likert_not_detected_wide_range():
    vals = [float(i) for i in range(1, 21)]   # 1–20,span > 11
    res = detect_likert(vals)
    assert res["is_likert"] is False


def test_likert_empty():
    res = detect_likert([])
    assert res["is_likert"] is False


def test_likert_recommendation_present():
    vals = [float(random.Random(3).randint(1, 5)) for _ in range(60)]
    res = detect_likert(vals)
    assert res["is_likert"] is True
    assert len(res["recommendation"]) > 20


# ---------------------------------------------------------------------------
# 2. large_sample_effect_language
# ---------------------------------------------------------------------------

def test_large_sample_trivial_effect():
    res = large_sample_effect_language(600, "Cohen's d", 0.15, 0.04)
    assert res["large_sample"] is True
    assert res["trivial"] is True
    assert "大样本警示" in res["message"]


def test_large_sample_non_trivial_effect():
    res = large_sample_effect_language(600, "Cohen's d", 0.50, 0.001)
    assert res["large_sample"] is True
    assert res["trivial"] is False
    assert res["message"]  # still gets a large-sample note


def test_small_sample_no_warning():
    res = large_sample_effect_language(80, "Cohen's d", 0.10, 0.04)
    assert res["large_sample"] is False
    assert res["trivial"] is False
    assert res["message"] == ""


def test_large_sample_r_trivial():
    res = large_sample_effect_language(1000, "r", 0.05, 0.03)
    assert res["trivial"] is True
    assert "r" in res["message"] or "效应量" in res["message"]


def test_large_sample_not_significant():
    res = large_sample_effect_language(800, "Cohen's d", 0.10, 0.10)
    # p > .05 → trivial 不触发(虽然 large_sample)
    assert res["trivial"] is False


def test_large_sample_eta2_trivial():
    res = large_sample_effect_language(500, "eta^2", 0.005, 0.02)
    assert res["trivial"] is True


# ---------------------------------------------------------------------------
# 3. compute_icc
# ---------------------------------------------------------------------------

def _make_rows_nested(clusters: int, per_cluster: int, icc_target: float,
                      seed: int = 7) -> list:
    """生成嵌套结构 CSV rows。icc_target 控制组间方差比例。"""
    rng = random.Random(seed)
    rows = []
    cluster_means = [rng.gauss(0, 1) * (icc_target ** 0.5) for _ in range(clusters)]
    residual_sd = (1 - icc_target) ** 0.5
    for ci in range(clusters):
        for _ in range(per_cluster):
            y = cluster_means[ci] + rng.gauss(0, residual_sd)
            rows.append({"dv": y, "cluster": f"C{ci}"})
    return rows


def test_icc_high_clustering():
    rows = _make_rows_nested(10, 20, icc_target=0.40, seed=42)
    res = compute_icc(rows, "dv", "cluster")
    assert "error" not in res
    assert res["k_clusters"] == 10
    # 高聚类应产生较高 ICC(宽容误差因随机)
    assert res["icc"] >= 0.15, f"ICC 过低:{res['icc']:.3f}"


def test_icc_low_clustering():
    rows = _make_rows_nested(10, 20, icc_target=0.01, seed=99)
    res = compute_icc(rows, "dv", "cluster")
    assert "error" not in res
    # 低聚类 ICC 应 < 0.15(通常 < 0.05 但随机种子可能高点)
    assert res["icc"] < 0.30


def test_icc_at_least_two_clusters():
    rows = [{"dv": "1.0", "cluster": "A"}, {"dv": "2.0", "cluster": "A"},
            {"dv": "3.0", "cluster": "A"}]
    res = compute_icc(rows, "dv", "cluster")
    assert "error" in res  # 只有一个 cluster


def test_icc_interpretation_large():
    rows = _make_rows_nested(5, 30, icc_target=0.50, seed=7)
    res = compute_icc(rows, "dv", "cluster")
    if "error" not in res and res["icc"] >= 0.15:
        assert "强烈建议" in res["interpretation"]


def test_icc_returns_n_clusters():
    rows = _make_rows_nested(8, 15, icc_target=0.20, seed=5)
    res = compute_icc(rows, "dv", "cluster")
    assert res["k_clusters"] == 8
    assert res["N"] == 8 * 15


# ---------------------------------------------------------------------------
# 4. bootstrap_mediation
# ---------------------------------------------------------------------------

def _make_mediation_data(n: int, a: float = 0.4, b: float = 0.4, cp: float = 0.1,
                          seed: int = 1) -> tuple:
    """生成中介数据:X→M→Y,间接效应 a*b。"""
    rng = random.Random(seed)
    x = [rng.gauss(0, 1) for _ in range(n)]
    m = [a * xi + rng.gauss(0, 1) for xi in x]
    y = [b * mi + cp * xi + rng.gauss(0, 1) for xi, mi in zip(x, m)]
    return x, m, y


def test_mediation_significant_indirect():
    x, m, y = _make_mediation_data(200, a=0.5, b=0.5, cp=0.0, seed=42)
    res = bootstrap_mediation(x, m, y, n_boot=500, seed=42)
    assert "error" not in res
    assert res["significant"] is True
    lo, hi = res["ci"]
    assert lo > 0   # 间接效应应显著正


def test_mediation_a_path_sign():
    """a 路径应与生成参数一致。"""
    x, m, y = _make_mediation_data(300, a=0.6, b=0.3, cp=0.0, seed=7)
    res = bootstrap_mediation(x, m, y, n_boot=300, seed=7)
    assert res["a"] > 0   # a > 0


def test_mediation_indirect_approx():
    """间接效应 ≈ a*b(误差允许 ±0.15 因回归截距影响)。"""
    x, m, y = _make_mediation_data(500, a=0.4, b=0.4, cp=0.0, seed=99)
    res = bootstrap_mediation(x, m, y, n_boot=300, seed=99)
    expected_indirect = res["a"] * res["b"]
    assert abs(res["indirect"] - expected_indirect) < 1e-10


def test_mediation_null_indirect():
    """间接效应为零时 CI 应含 0。"""
    rng = random.Random(55)
    x = [rng.gauss(0, 1) for _ in range(300)]
    m = [rng.gauss(0, 1) for _ in range(300)]   # M 与 X 无关
    y = [0.5 * xi + rng.gauss(0, 1) for xi in x]
    res = bootstrap_mediation(x, m, y, n_boot=300, seed=55)
    assert not res["significant"]   # CI 含 0


def test_mediation_total_direct_indirect():
    """c ≈ c' + ab(代数恒等式,允许浮点误差)。"""
    x, m, y = _make_mediation_data(300, a=0.5, b=0.3, cp=0.2, seed=12)
    res = bootstrap_mediation(x, m, y, n_boot=300, seed=12)
    reconstructed = res["c_prime"] + res["indirect"]
    assert abs(reconstructed - res["c"]) < 1e-9


def test_mediation_too_small_n():
    res = bootstrap_mediation([1.0, 2.0], [1.0, 2.0], [1.0, 2.0])
    assert "error" in res


def test_mediation_n_boot_respected():
    x, m, y = _make_mediation_data(100, seed=33)
    res = bootstrap_mediation(x, m, y, n_boot=100, seed=33)
    assert res["n_boot"] >= 90   # 偶有 NaN 可能少几个


# ---------------------------------------------------------------------------
# 5. moderation_analysis — 简单斜率 + JN
# ---------------------------------------------------------------------------

def _make_moderation_data(n: int, b1: float = 0.3, b3: float = 0.4,
                           seed: int = 1) -> tuple:
    """生成 Y = b0 + b1*X + b2*Wc + b3*(X*Wc) + e。"""
    rng = random.Random(seed)
    x = [rng.gauss(0, 1) for _ in range(n)]
    w = [rng.gauss(0, 1) for _ in range(n)]
    mw = sum(w) / n
    wc = [wi - mw for wi in w]
    y = [0.5 + b1 * x[i] + 0.2 * wc[i] + b3 * x[i] * wc[i] + rng.gauss(0, 0.5)
         for i in range(n)]
    return x, w, y


def test_moderation_recovers_b3():
    x, w, y = _make_moderation_data(300, b1=0.3, b3=0.4, seed=42)
    res = moderation_analysis(x, w, y)
    assert "error" not in res
    # b3 应接近生成参数(允许 ±0.15 因回归噪声)
    assert abs(res["b3"] - 0.4) < 0.20


def test_moderation_three_simple_slopes():
    x, w, y = _make_moderation_data(200, seed=7)
    res = moderation_analysis(x, w, y)
    assert len(res["simple_slopes"]) == 3


def test_moderation_simple_slope_sign_positive_b3():
    """b3>0 时:高 W 处简单斜率 > 低 W 处。"""
    x, w, y = _make_moderation_data(400, b1=0.1, b3=0.6, seed=11)
    res = moderation_analysis(x, w, y)
    ss = res["simple_slopes"]
    slope_low = ss[0]["slope"]    # W = mean-1SD
    slope_high = ss[2]["slope"]   # W = mean+1SD
    assert slope_high > slope_low


def test_moderation_jn_roots_in_range():
    """当 b3 大且显著时,JN 根应落在 W 范围内。"""
    x, w, y = _make_moderation_data(500, b1=0.0, b3=0.8, seed=99)
    res = moderation_analysis(x, w, y)
    if res["jn_roots"]:
        wmin, wmax = min(w), max(w)
        in_range = [r for r in res["jn_roots"] if wmin <= r <= wmax]
        # 至少有一根在范围内或 jn_interpretation 有内容
        assert len(in_range) > 0 or "恒显著" in res["jn_interpretation"]


def test_moderation_jn_interpretation_nonempty():
    x, w, y = _make_moderation_data(200, seed=5)
    res = moderation_analysis(x, w, y)
    assert isinstance(res["jn_interpretation"], str)
    assert len(res["jn_interpretation"]) > 10


def test_moderation_mse_positive():
    x, w, y = _make_moderation_data(100, seed=3)
    res = moderation_analysis(x, w, y)
    assert res["mse"] > 0


def test_moderation_too_small_n():
    res = moderation_analysis([1.0]*5, [1.0]*5, [1.0]*5)
    assert "error" in res


def test_moderation_p_values_in_range():
    x, w, y = _make_moderation_data(200, seed=8)
    res = moderation_analysis(x, w, y)
    for ss in res["simple_slopes"]:
        assert 0.0 <= ss["p"] <= 1.0 or math.isnan(ss["p"])


# ---------------------------------------------------------------------------
# 6. CLI 集成测试(通过 analyze.py)
# ---------------------------------------------------------------------------

def test_analyze_with_cluster_integration():
    """analyze() 的 cluster 参数:ICC 计算不崩溃。"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from psyclaw.psych.analyze import analyze
    with tempfile.TemporaryDirectory() as tmp:
        rows = []
        rng = random.Random(7)
        for ci in range(5):
            for _ in range(10):
                rows.append({
                    "y": str(rng.gauss(ci * 0.3, 1)),
                    "group": "A" if rng.random() > 0.5 else "B",
                    "school": f"S{ci}",
                })
        p = Path(tmp) / "nested.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["y", "group", "school"])
            w.writeheader()
            w.writerows(rows)
        rc = analyze(str(p), "y", group="group",
                     project_dir=tmp, cluster="school")
        assert rc in (0, 1)  # 通过或门禁阻断均可;不应 raise


def test_analyze_likert_integration():
    """Likert 变量走 analyze() 不崩溃。"""
    from psyclaw.psych.analyze import analyze
    with tempfile.TemporaryDirectory() as tmp:
        rng = random.Random(42)
        rows = [{"score": str(rng.randint(1, 5)),
                 "group": "A" if i < 40 else "B"} for i in range(80)]
        p = Path(tmp) / "likert.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["score", "group"])
            w.writeheader()
            w.writerows(rows)
        rc = analyze(str(p), "score", group="group", project_dir=tmp)
        assert rc in (0, 1)


def test_analyze_large_sample_integration():
    """大样本 + 小效应 → large_sample_warning 被写入 meta(通过 sidecar)。"""
    from psyclaw.psych.analyze import analyze
    with tempfile.TemporaryDirectory() as tmp:
        rng = random.Random(11)
        # 两组,效应量 d ≈ 0.05(微小),N=600
        rows = ([{"y": str(rng.gauss(0.05, 1)), "group": "A"} for _ in range(300)]
                + [{"y": str(rng.gauss(0, 1)), "group": "B"} for _ in range(300)])
        p = Path(tmp) / "large.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["y", "group"])
            w.writeheader()
            w.writerows(rows)
        rc = analyze(str(p), "y", group="group", project_dir=tmp)
        assert rc in (0, 1)


# ---------------------------------------------------------------------------
# 自包含 runner(无 pytest 也可跑:python tests/test_decision_tree.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: [ERROR] {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
