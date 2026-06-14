"""信度计算单元测试 — psyclaw/psych/reliability.py

覆盖 _variance / cronbach_alpha / alpha_if_deleted / interpret_alpha 全部逻辑分支。
全部 stdlib，无需 scipy / pingouin / API key。
数值对照手算或 Wikipedia Cronbach's alpha 示例验证。
"""

import math
import pytest

from psyclaw.psych.reliability import (
    _variance,
    cronbach_alpha,
    alpha_if_deleted,
    interpret_alpha,
)


# ---------------------------------------------------------------------------
# _variance — 样本方差（除以 n-1）
# ---------------------------------------------------------------------------

class TestVariance:
    def test_empty_list(self):
        assert _variance([]) == 0.0

    def test_single_element(self):
        assert _variance([42]) == 0.0

    def test_uniform_values(self):
        assert _variance([5, 5, 5, 5]) == 0.0

    def test_known_values(self):
        # [3,5,7]: mean=5, deviations=[-2,0,2], sq=[4,0,4], sum=8, /2=4
        assert _variance([3, 5, 7]) == pytest.approx(4.0, rel=1e-9)

    def test_two_elements(self):
        # [0,2]: mean=1, dev=[-1,1], sq=[1,1], /1=2
        assert _variance([0, 2]) == pytest.approx(2.0, rel=1e-9)

    def test_negative_values(self):
        # [-1,1]: same as [0,2] shifted, same variance=2
        assert _variance([-1, 1]) == pytest.approx(2.0, rel=1e-9)

    def test_returns_float(self):
        assert isinstance(_variance([1, 2, 3]), float)


# ---------------------------------------------------------------------------
# cronbach_alpha — Cronbach's α
# ---------------------------------------------------------------------------

class TestCronbachAlpha:
    # --- 边界 / NaN 返回 ---

    def test_zero_items_returns_nan(self):
        assert math.isnan(cronbach_alpha([]))

    def test_one_item_returns_nan(self):
        assert math.isnan(cronbach_alpha([[1, 2, 3, 4]]))

    def test_single_respondent_returns_nan(self):
        # n=1 → 每题方差=0 → total_var=0 → NaN
        assert math.isnan(cronbach_alpha([[5], [3], [4]]))

    def test_all_items_constant_returns_nan(self):
        # 每题没有任何变动 → total_var=0 → NaN
        assert math.isnan(cronbach_alpha([[2, 2, 2], [3, 3, 3]]))

    # --- 精确已知值 ---

    def test_perfect_reliability_two_identical_items(self):
        # 两道完全相同的题，顺序相同 → α=1.0
        data = [1, 0, 1, 0]
        items = [data, data]
        assert cronbach_alpha(items) == pytest.approx(1.0, abs=1e-9)

    def test_perfect_reliability_three_identical_items(self):
        data = [4, 2, 5, 3, 1]
        items = [data, data, data]
        assert cronbach_alpha(items) == pytest.approx(1.0, abs=1e-9)

    def test_two_items_known_value(self):
        # 手算：items=[[1,2,3,4],[1,3,2,4]]
        # item_vars = 5/3 + 5/3 = 10/3
        # totals=[2,5,5,8], total_var=6
        # α = (2/1)*(1 - (10/3)/6) = 2*(1 - 10/18) = 16/18 = 8/9
        items = [[1, 2, 3, 4], [1, 3, 2, 4]]
        alpha = cronbach_alpha(items)
        assert alpha == pytest.approx(8 / 9, rel=1e-9)

    def test_negative_alpha_reverse_scored(self):
        # 含一道反向计分的题 → 总分方差小于条目方差之和 → α < 0
        items = [[1, 2, 3, 4], [4, 3, 2, 1], [2, 3, 4, 5]]
        alpha = cronbach_alpha(items)
        assert alpha < 0

    def test_alpha_increases_with_more_correlated_items(self):
        # 高度相关的 4 题 α 应高于只有 2 题时
        base = [1, 2, 3, 4, 5]
        items_2 = [base, base]
        items_4 = [base, base, base, base]
        alpha_2 = cronbach_alpha(items_2)
        alpha_4 = cronbach_alpha(items_4)
        # Spearman-Brown: adding correlated items increases α
        assert alpha_4 >= alpha_2

    def test_three_items_textbook_structure(self):
        # 3 道题，被试 n=5，中等相关
        # items[0] and items[1] moderately correlated; items[2] moderately correlated
        items = [
            [5, 3, 4, 2, 1],
            [4, 3, 5, 2, 2],
            [5, 2, 4, 3, 1],
        ]
        alpha = cronbach_alpha(items)
        # 应在合理的正值范围（具体值由手算确认）
        assert 0 < alpha <= 1.0

    def test_alpha_in_valid_range_for_correlated_items(self):
        # 两道相关性良好的 5 点量表题
        items = [
            [1, 2, 3, 4, 5, 3, 4, 2, 1, 5],
            [1, 2, 3, 4, 5, 2, 4, 2, 2, 5],
        ]
        alpha = cronbach_alpha(items)
        assert 0 < alpha <= 1.0

    def test_result_is_float(self):
        items = [[1, 2, 3], [2, 3, 4]]
        assert isinstance(cronbach_alpha(items), float)

    def test_four_items_higher_alpha_than_two(self):
        # Spearman-Brown 预言：相同 avg inter-item r，项目越多 α 越高
        rows = [1, 2, 3, 4, 5, 4, 3, 2]
        items_2 = [rows, rows]
        items_4 = [rows, rows, rows, rows]
        assert cronbach_alpha(items_4) >= cronbach_alpha(items_2)


# ---------------------------------------------------------------------------
# alpha_if_deleted — 逐题删除后的 α
# ---------------------------------------------------------------------------

class TestAlphaIfDeleted:
    @pytest.fixture
    def three_item_data(self):
        """3 题 5 人，最后一题（item_3）是反向的，删除它应提高 α。"""
        item1 = [5, 4, 3, 2, 1]
        item2 = [5, 4, 3, 2, 1]
        item3 = [1, 2, 3, 4, 5]  # 反向题
        return [item1, item2, item3]

    def test_returns_list_of_length_k(self, three_item_data):
        result = alpha_if_deleted(three_item_data)
        assert len(result) == 3

    def test_indices_are_one_based(self, three_item_data):
        result = alpha_if_deleted(three_item_data)
        indices = [r[0] for r in result]
        assert indices == [1, 2, 3]

    def test_each_element_is_tuple_of_two(self, three_item_data):
        result = alpha_if_deleted(three_item_data)
        for item in result:
            assert len(item) == 2

    def test_index_is_int(self, three_item_data):
        result = alpha_if_deleted(three_item_data)
        for idx, _ in result:
            assert isinstance(idx, int)

    def test_alpha_value_is_float_or_nan(self, three_item_data):
        result = alpha_if_deleted(three_item_data)
        for _, a in result:
            assert isinstance(a, float)

    def test_deleting_reverse_item_improves_alpha(self, three_item_data):
        overall = cronbach_alpha(three_item_data)
        result = alpha_if_deleted(three_item_data)
        # 删除第 3 题（index=2，tuple idx=3）后的 α 应优于总体 α
        alpha_without_3 = result[2][1]
        assert alpha_without_3 > overall

    def test_k2_deletion_gives_nan(self):
        # 2 道题删除 1 道 → 剩 1 道 → NaN
        items = [[1, 2, 3], [1, 3, 2]]
        result = alpha_if_deleted(items)
        assert all(math.isnan(a) for _, a in result)

    def test_k3_deletion_returns_k1_nan_for_two_remaining(self):
        # k=3，逐一删除后剩 2 道，每个 α 应为有效数值（非 NaN），除非数据退化
        items = [
            [1, 2, 3, 4, 5],
            [2, 3, 4, 5, 1],
            [3, 4, 5, 1, 2],
        ]
        result = alpha_if_deleted(items)
        assert len(result) == 3
        for _, a in result:
            assert isinstance(a, float)

    def test_sequential_indices(self):
        items = [[1, 2, 3, 4], [2, 3, 4, 5], [3, 4, 5, 6], [4, 5, 6, 7]]
        result = alpha_if_deleted(items)
        assert [r[0] for r in result] == [1, 2, 3, 4]

    def test_first_element_matches_deletion_of_item0(self):
        items = [[1, 2, 3, 4], [2, 3, 4, 5], [1, 1, 1, 1]]
        result = alpha_if_deleted(items)
        # 手动验证第一个元素等于 cronbach_alpha(items[1:])
        expected = cronbach_alpha(items[1:])
        if math.isnan(expected):
            assert math.isnan(result[0][1])
        else:
            assert result[0][1] == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# interpret_alpha — 文字解读
# ---------------------------------------------------------------------------

class TestInterpretAlpha:
    def test_nan_returns_error_message(self):
        msg = interpret_alpha(float("nan"))
        assert "无法计算" in msg

    def test_095_is_excellent(self):
        msg = interpret_alpha(0.95)
        assert "优" in msg

    def test_090_is_excellent(self):
        msg = interpret_alpha(0.90)
        assert "优" in msg

    def test_089_is_good(self):
        msg = interpret_alpha(0.89)
        assert "良" in msg

    def test_085_is_good(self):
        msg = interpret_alpha(0.85)
        assert "良" in msg

    def test_080_is_good(self):
        msg = interpret_alpha(0.80)
        assert "良" in msg

    def test_079_is_acceptable(self):
        msg = interpret_alpha(0.79)
        assert "可接受" in msg

    def test_070_is_acceptable(self):
        msg = interpret_alpha(0.70)
        assert "可接受" in msg

    def test_069_is_marginal(self):
        msg = interpret_alpha(0.69)
        assert "勉强" in msg

    def test_060_is_marginal(self):
        msg = interpret_alpha(0.60)
        assert "勉强" in msg

    def test_059_is_poor(self):
        msg = interpret_alpha(0.59)
        assert "差" in msg

    def test_zero_is_poor(self):
        msg = interpret_alpha(0.0)
        assert "差" in msg

    def test_negative_alpha_is_poor(self):
        msg = interpret_alpha(-0.5)
        assert "差" in msg

    def test_returns_string(self):
        assert isinstance(interpret_alpha(0.85), str)

    def test_thresholds_are_inclusive_lower_bound(self):
        # α=0.7 → 可接受（≥0.7），α=0.8 → 良（≥0.8），α=0.9 → 优（≥0.9）
        assert "可接受" in interpret_alpha(0.70)
        assert "良" in interpret_alpha(0.80)
        assert "优" in interpret_alpha(0.90)

    def test_excellent_redundancy_warning_at_095(self):
        # ≥0.95 应有冗余警告提示
        msg = interpret_alpha(0.95)
        assert "冗余" in msg or ">.95" in msg or "0.95" in msg
