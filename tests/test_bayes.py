"""测试贝叶斯因子模块（psyclaw/psych/bayes.py）。

数值参照：
  - BF₁₀ 单调性（|t| 增大 → BF₁₀ 增大）
  - t=0 时 BF₁₀ < 1（H₀ 先验复杂度惩罚）
  - 大 |t| 时 BF₁₀ >> 1（强证据支持 H₁）
  - 与已知近似值（Rouder et al. 2009 图 3 量级）交叉验证
  - BF₁₀ * BF₀₁ ≈ 1（互为倒数）
  - interpret_bf 解读边界正确
  - CSV 主入口：单样本、双样本、配对、相关
  - APA-7 段落含关键字段
"""

import csv
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.psych.bayes import (
    _jzs_prior_g,
    _quad_0_inf_stdlib,
    bf_correlation,
    bf_t_one_sample,
    bf_t_two_sample,
    format_apa_bayes,
    interpret_bf,
    write_bayes_report,
    analyze_bayes,
    _DEFAULT_R_SCALE,
)


# ---------------------------------------------------------------------------
# 先验正则化自检
# ---------------------------------------------------------------------------

def test_jzs_prior_normalizes():
    """∫₀^∞ p_JZS(g; r=0.707) dg ≈ 1（数值验证）。"""
    total = _quad_0_inf_stdlib(lambda g: _jzs_prior_g(g, _DEFAULT_R_SCALE), n_pts=2000)
    assert abs(total - 1.0) < 0.01, f"prior integral = {total}"


def test_jzs_prior_positive():
    """p(g) > 0 for g > 0。"""
    for g in [0.01, 0.1, 1.0, 10.0]:
        assert _jzs_prior_g(g, _DEFAULT_R_SCALE) > 0


def test_jzs_prior_zero_at_boundary():
    """p(0) = 0（奇点在 g=0 需返回 0）。"""
    assert _jzs_prior_g(0.0, _DEFAULT_R_SCALE) == 0.0
    assert _jzs_prior_g(-1.0, _DEFAULT_R_SCALE) == 0.0


# ---------------------------------------------------------------------------
# bf_t_one_sample 单调性 & 量级
# ---------------------------------------------------------------------------

def test_bf_one_sample_null_favors_h0():
    """t=0, n=20 → BF₁₀ < 1（H₀ 得到支持）。"""
    r = bf_t_one_sample(0.0, 20)
    assert r["bf10"] < 1.0, f"expected BF10 < 1 for t=0, got {r['bf10']}"


def test_bf_one_sample_large_t_favors_h1():
    """t=4.0, n=30 → BF₁₀ >> 10（强证据支持 H₁）。"""
    r = bf_t_one_sample(4.0, 30)
    assert r["bf10"] > 10.0, f"expected BF10 > 10, got {r['bf10']}"


def test_bf_one_sample_monotone():
    """|t| 增大 → BF₁₀ 单调递增（n=25 固定）。"""
    t_vals = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0]
    bfs = [bf_t_one_sample(t, 25)["bf10"] for t in t_vals]
    for i in range(len(bfs) - 1):
        assert bfs[i] <= bfs[i + 1], f"非单调: BF₁₀(t={t_vals[i]})={bfs[i]} > BF₁₀(t={t_vals[i+1]})={bfs[i+1]}"


def test_bf_one_sample_reciprocal():
    """BF₁₀ × BF₀₁ ≈ 1。"""
    r = bf_t_one_sample(2.5, 30)
    assert abs(r["bf10"] * r["bf01"] - 1.0) < 0.01


def test_bf_one_sample_symmetric():
    """BF₁₀(t) == BF₁₀(−t)（双尾检验对称）。"""
    r_pos = bf_t_one_sample(2.0, 25)
    r_neg = bf_t_one_sample(-2.0, 25)
    assert abs(r_pos["bf10"] - r_neg["bf10"]) < 0.001


def test_bf_one_sample_n_effect():
    """固定效应量 d=0.5（t=d·√n），n 越大证据越强（BF₁₀ 单调递增）。"""
    import math as _math
    d = 0.5
    bfs = [bf_t_one_sample(d * _math.sqrt(n), n)["bf10"] for n in [20, 50, 100]]
    for i in range(len(bfs) - 1):
        assert bfs[i] < bfs[i + 1], f"BF₁₀ 非单调: {bfs}"


def test_bf_one_sample_known_approx():
    """n=20, t=2.5 → BF₁₀ 约在 1.5–10 范围（数量级合理；Rouder et al. 2009）。"""
    r = bf_t_one_sample(2.5, 20)
    assert 1.5 < r["bf10"] < 10, f"BF₁₀ = {r['bf10']}"


def test_bf_one_sample_very_large_t():
    """t=10, n=30 → BF₁₀ > 100（极强证据）。"""
    r = bf_t_one_sample(10.0, 30)
    assert r["bf10"] > 100


def test_bf_one_sample_small_n():
    """n=3（最小有效）应能正常运行且返回有效值。"""
    r = bf_t_one_sample(2.0, 3)
    assert math.isfinite(r["bf10"]) and r["bf10"] > 0


def test_bf_one_sample_invalid_n():
    """n=1 返回 nan 结果（无效）。"""
    r = bf_t_one_sample(2.0, 1)
    assert not math.isfinite(r["bf10"])


def test_bf_one_sample_r_scale_effect():
    """更宽先验（r_scale 更大）→ 中等 t 下 BF₁₀ 更小（先验更分散）。"""
    r_narrow = bf_t_one_sample(2.0, 30, r_scale=0.3)
    r_default = bf_t_one_sample(2.0, 30, r_scale=_DEFAULT_R_SCALE)
    r_wide = bf_t_one_sample(2.0, 30, r_scale=1.5)
    # 对中等 t：更宽先验不利于 H₁（更难被数据支持）
    assert r_narrow["bf10"] > r_wide["bf10"]


# ---------------------------------------------------------------------------
# bf_t_two_sample
# ---------------------------------------------------------------------------

def test_bf_two_sample_null_favors_h0():
    """t=0, n1=n2=20 → BF₁₀ < 1。"""
    r = bf_t_two_sample(0.0, 20, 20)
    assert r["bf10"] < 1.0


def test_bf_two_sample_large_t():
    """t=3.5, n1=n2=25 → BF₁₀ > 10。"""
    r = bf_t_two_sample(3.5, 25, 25)
    assert r["bf10"] > 10.0


def test_bf_two_sample_monotone():
    """|t| 增大 → BF₁₀ 单调递增（n1=n2=30）。"""
    bfs = [bf_t_two_sample(t, 30, 30)["bf10"] for t in [0.0, 1.0, 2.0, 3.0, 4.0]]
    for i in range(len(bfs) - 1):
        assert bfs[i] <= bfs[i + 1]


def test_bf_two_sample_reciprocal():
    """BF₁₀ × BF₀₁ ≈ 1（双样本）。"""
    r = bf_t_two_sample(2.8, 25, 30)
    assert abs(r["bf10"] * r["bf01"] - 1.0) < 0.01


def test_bf_two_sample_unequal_n():
    """不等样本量可正常运行。"""
    r = bf_t_two_sample(2.0, 15, 40)
    assert r["n"] == 55
    assert r["n1"] == 15
    assert r["n2"] == 40
    assert math.isfinite(r["bf10"])


def test_bf_two_sample_symmetric():
    """BF₁₀(t) == BF₁₀(−t)（对称检验）。"""
    r_pos = bf_t_two_sample(2.0, 25, 25)
    r_neg = bf_t_two_sample(-2.0, 25, 25)
    assert abs(r_pos["bf10"] - r_neg["bf10"]) < 0.001


def test_bf_two_vs_one_sample_differ():
    """独立双样本(n1=n2=20)与单样本(n=20)对同一 t 值返回不同 BF₁₀（df/n_eff 不同）。"""
    r_two = bf_t_two_sample(2.0, 20, 20)
    r_one = bf_t_one_sample(2.0, 20)
    assert abs(r_two["bf10"] - r_one["bf10"]) > 0.01  # 两者不相等（n_eff、df 均不同）


# ---------------------------------------------------------------------------
# bf_correlation
# ---------------------------------------------------------------------------

def test_bf_correlation_null():
    """r=0.0 → 转换为 t=0，BF₁₀ < 1。"""
    r = bf_correlation(0.0, 30)
    assert r["bf10"] < 1.0


def test_bf_correlation_strong():
    """r=0.7, n=30 → BF₁₀ > 10。"""
    r = bf_correlation(0.7, 30)
    assert r["bf10"] > 10.0, f"BF₁₀ = {r['bf10']}"


def test_bf_correlation_monotone():
    """r 绝对值增大 → BF₁₀ 单调递增（n=30）。"""
    bfs = [bf_correlation(r_val, 30)["bf10"] for r_val in [0.0, 0.2, 0.4, 0.6, 0.8]]
    for i in range(len(bfs) - 1):
        assert bfs[i] <= bfs[i + 1]


def test_bf_correlation_negative():
    """r < 0 BF₁₀ = 同绝对值正相关（符号不影响大小）。"""
    r_pos = bf_correlation(0.5, 40)
    r_neg = bf_correlation(-0.5, 40)
    assert abs(r_pos["bf10"] - r_neg["bf10"]) < 0.001


def test_bf_correlation_invalid():
    """r ≥ 1 返回 nan。"""
    r = bf_correlation(1.0, 30)
    assert not math.isfinite(r["bf10"])


def test_bf_correlation_small_n():
    """n=4（最小有效）正常运行。"""
    r = bf_correlation(0.5, 4)
    assert math.isfinite(r["bf10"])


# ---------------------------------------------------------------------------
# interpret_bf
# ---------------------------------------------------------------------------

def test_interpret_bf_extreme_h1():
    assert "极强" in interpret_bf(200.0) and "H₁" in interpret_bf(200.0)


def test_interpret_bf_very_strong_h1():
    interp = interpret_bf(50.0)
    assert "非常强" in interp and "H₁" in interp


def test_interpret_bf_strong_h1():
    interp = interpret_bf(15.0)
    assert "强" in interp and "H₁" in interp


def test_interpret_bf_moderate_h1():
    interp = interpret_bf(5.0)
    assert "中等" in interp and "H₁" in interp


def test_interpret_bf_inconclusive():
    assert "不结论性" in interpret_bf(1.5)
    assert "不结论性" in interpret_bf(0.5)


def test_interpret_bf_moderate_h0():
    interp = interpret_bf(0.15)  # 0.15 在 (1/10, 1/3) 区间 → 中等支持 H₀
    assert "中等" in interp and "H₀" in interp


def test_interpret_bf_strong_h0():
    interp = interpret_bf(0.02)
    assert "强" in interp and "H₀" in interp


def test_interpret_bf_extreme_h0():
    interp = interpret_bf(0.001)
    assert "H₀" in interp


def test_interpret_bf_invalid():
    assert interpret_bf(float("nan")) == "无法解读"
    assert interpret_bf(-1.0) == "无法解读"


# ---------------------------------------------------------------------------
# format_apa_bayes
# ---------------------------------------------------------------------------

def test_format_apa_one_sample():
    r = bf_t_one_sample(2.5, 30)
    text = format_apa_bayes(r)
    assert "JZS" in text or "Cauchy" in text
    assert "BF" in text
    assert "Rouder" in text


def test_format_apa_two_sample():
    r = bf_t_two_sample(2.5, 25, 30)
    text = format_apa_bayes(r)
    assert "n₁" in text
    assert "BF" in text


def test_format_apa_correlation():
    r = bf_correlation(0.4, 50)
    text = format_apa_bayes(r)
    assert "r = " in text
    assert "Ly" in text


def test_format_apa_invalid():
    """无效 BF 时输出可读提示而非崩溃。"""
    r = bf_t_one_sample(2.0, 1)  # 无效 n
    text = format_apa_bayes(r)
    assert "无法计算" in text or len(text) > 10


def test_format_apa_large_bf():
    """BF₁₀ > 100 时格式化为 'BF₁₀ > 100'。"""
    r = bf_t_one_sample(5.0, 50)
    text = format_apa_bayes(r)
    # BF₁₀ 应非常大，含 > 100 字样
    if r["bf10"] > 100:
        assert ">" in text


# ---------------------------------------------------------------------------
# write_bayes_report
# ---------------------------------------------------------------------------

def test_write_report_creates_files():
    r = bf_t_one_sample(2.5, 30)
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path, json_path = write_bayes_report(r, out_dir=tmpdir)
        assert md_path.exists()
        assert json_path.exists()
        md_content = md_path.read_text(encoding="utf-8")
        assert "BF" in md_content
        assert "Rouder" in md_content
        json_data = json.loads(json_path.read_text(encoding="utf-8"))
        assert "bf10" in json_data


def test_write_report_json_valid():
    r = bf_t_two_sample(3.0, 20, 20)
    with tempfile.TemporaryDirectory() as tmpdir:
        _, json_path = write_bayes_report(r, out_dir=tmpdir)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["test_type"] == "two_sample"
        assert data["n1"] == 20
        assert data["n2"] == 20


# ---------------------------------------------------------------------------
# analyze_bayes（CSV 主入口）
# ---------------------------------------------------------------------------

def _make_csv(rows: list[dict], path: str):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_analyze_bayes_one_sample():
    """单样本 t 检验：均值明显偏离 0 时 BF₁₀ > 1。"""
    import random
    random.seed(42)
    rows = [{"score": str(5.0 + random.gauss(0, 1))} for _ in range(30)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_bayes(csv_path, test="ttest", dv="score",
                               out_dir=tmpdir, write_files=True)
        assert result["test_type"] == "one_sample"
        assert math.isfinite(result["bf10"])
        assert result["bf10"] > 1  # 均值 ≈ 5，远离 0
        assert "report_md" in result
        assert Path(result["report_md"]).exists()


def test_analyze_bayes_two_sample():
    """独立双样本：两组差异明显时 BF₁₀ > 1。"""
    rows = [{"score": str(1.0 + i * 0.01), "group": "A"} for i in range(25)]
    rows += [{"score": str(1.0 + i * 0.01 + 2.0), "group": "B"} for i in range(25)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_bayes(csv_path, test="ttest", dv="score", group="group",
                               out_dir=tmpdir, write_files=False)
        assert result["test_type"] == "two_sample"
        assert result["n1"] == 25
        assert result["n2"] == 25
        assert result["bf10"] > 3.0


def test_analyze_bayes_paired():
    """配对检验：后测高于前测时 BF₁₀ > 1。"""
    pre = [3.0 + i * 0.05 for i in range(20)]
    post = [v + 1.5 for v in pre]
    rows = [{"pre": str(pre[i]), "post": str(post[i])} for i in range(20)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_bayes(csv_path, test="paired", dv="pre", group="post",
                               out_dir=tmpdir, write_files=False)
        assert result["test_type"] == "one_sample"
        assert result.get("test_subtype") == "paired"
        assert result["bf10"] > 1.0


def test_analyze_bayes_correlation():
    """相关：两变量线性相关时 BF₁₀ > 1。"""
    xs = [float(i) for i in range(30)]
    ys = [x * 2.0 + 1.0 for x in xs]  # r = 1.0（完美线性）
    # r 接近 1 时 BF 极大
    rows = [{"x": str(xs[i]), "y": str(ys[i] + (i % 3) * 0.1)} for i in range(30)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_bayes(csv_path, test="correlation", dv="x", group="y",
                               out_dir=tmpdir, write_files=False)
        assert result["test_type"] == "correlation"
        assert "r_obs" in result
        assert result["bf10"] > 10.0


def test_analyze_bayes_error_no_dv():
    """缺少 --dv 参数应抛出 ValueError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"x": "1"}], csv_path)
        try:
            analyze_bayes(csv_path, dv=None, write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_bayes_error_too_few_rows():
    """有效数据不足 3 行应抛出 ValueError。"""
    rows = [{"score": "1.0"}, {"score": "2.0"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        try:
            analyze_bayes(csv_path, test="ttest", dv="score", write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_bayes_error_unknown_test():
    """未知检验类型应抛出 ValueError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv([{"x": "1"}, {"x": "2"}, {"x": "3"}], csv_path)
        try:
            analyze_bayes(csv_path, test="anova", dv="x", write_files=False)
            assert False, "应抛出 ValueError"
        except ValueError:
            pass


def test_analyze_bayes_json_output():
    """write_files=True 时 report_json 可反序列化且含必要字段。"""
    rows = [{"val": str(float(i))} for i in range(25)]
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _make_csv(rows, csv_path)
        result = analyze_bayes(csv_path, test="ttest", dv="val",
                               mu0=12.0, out_dir=tmpdir, write_files=True)
        json_path = Path(result["report_json"])
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for key in ("bf10", "bf01", "interpretation", "test_type", "n", "df"):
            assert key in data, f"缺少字段: {key}"


# ---------------------------------------------------------------------------
# 结果字段完整性
# ---------------------------------------------------------------------------

def test_result_fields_one_sample():
    r = bf_t_one_sample(2.0, 30)
    for key in ("test_type", "n", "t", "df", "r_scale", "bf10", "bf01", "log_bf10", "interpretation"):
        assert key in r, f"缺少字段: {key}"


def test_result_fields_two_sample():
    r = bf_t_two_sample(2.0, 20, 20)
    for key in ("n1", "n2", "n", "bf10", "interpretation"):
        assert key in r


def test_result_fields_correlation():
    r = bf_correlation(0.4, 30)
    assert "r_obs" in r


def test_log_bf_consistent():
    """ln(BF₁₀) 与 BF₁₀ 一致。"""
    r = bf_t_one_sample(2.0, 25)
    assert abs(math.log(r["bf10"]) - r["log_bf10"]) < 0.001


def test_bf_bf01_reciprocal_all_tests():
    """所有三种检验 BF₁₀ × BF₀₁ ≈ 1。"""
    for r in [
        bf_t_one_sample(1.5, 20),
        bf_t_two_sample(1.5, 20, 20),
        bf_correlation(0.3, 30),
    ]:
        product = r["bf10"] * r["bf01"]
        assert abs(product - 1.0) < 0.01, f"BF₁₀ × BF₀₁ = {product}"


# ---------------------------------------------------------------------------
# 自跑块（python tests/test_bayes.py 直接可跑）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    _all = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in _all:
        try:
            fn()
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    total = passed + failed
    print(f"\n{passed}/{total} passed", "✓" if failed == 0 else f"  {failed} FAILED")
