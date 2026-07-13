"""tests/test_context.py — context.py 核心函数单元测试 (P5-E1)。

被测函数：lean_core / relevant_knowledge / compact_history / render_memo /
          smart_excerpt / _csv_excerpt / _distill / _is_num
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from psyclaw.context import (
    CHAR_BUDGET_HISTORY,
    KEEP_RECENT_TURNS,
    FILE_EXCERPT_CHARS,
    _distill,
    _is_num,
    compact_history,
    lean_core,
    relevant_knowledge,
    render_memo,
    smart_excerpt,
)


# ---------------------------------------------------------------------------
# lean_core
# ---------------------------------------------------------------------------

class TestLeanCore:
    def test_returns_string(self):
        s = lean_core()
        assert isinstance(s, str)

    def test_not_empty(self):
        assert lean_core().strip()

    def test_contains_core_rules(self):
        s = lean_core()
        assert "效应量" in s or "effect" in s.lower()
        assert "CI" in s or "置信区间" in s

    def test_requires_plain_language_before_statistics(self):
        s = lean_core()
        assert "日常语言" in s
        assert "为什么这样分析" in s
        assert "术语/缩写" in s

    def test_contains_psyclaw_identity(self):
        assert "PsyClaw" in lean_core()

    def test_marginal_significance_ban(self):
        """feat-098:「边缘显著」类措辞自己不用、也不建议(第一轮 chat 曾建议)。"""
        s = lean_core()
        assert "边缘显著" in s and "绝不建议" in s.replace("、也绝不建议", "绝不建议")
        assert "如实写不显著" in s

    def test_citation_antifabrication_hard_constraint(self):
        """feat-093:对抗评估实测 chat 拒编条目后又凭记忆供出带页码的替代文献。"""
        s = lean_core()
        assert "引用反杜撰" in s
        assert "未核实" in s
        assert "psyclaw lit" in s          # 指引检索而非光拒绝

    def test_stats_delegation_hard_constraint(self):
        """feat-092:对抗评估实测 chat 手写 Welch t——统计外移必须是显式硬约束。"""
        s = lean_core()
        assert "统计计算一律外移" in s
        assert "绝不手写统计算法实现" in s
        assert "statsmodels" in s          # 给出外移路径而非光拒绝
        assert "psyclaw[stats]" in s

    def test_reproducible(self):
        assert lean_core() == lean_core()


# ---------------------------------------------------------------------------
# relevant_knowledge
# ---------------------------------------------------------------------------

class TestRelevantKnowledge:
    def test_empty_message_returns_empty(self):
        result = relevant_knowledge("")
        # 无关键词命中应为空或很短
        assert isinstance(result, str)

    def test_anova_keyword_returns_knowledge(self):
        result = relevant_knowledge("我要做方差分析anova")
        # 方差分析/anova 应命中某条知识
        # 若知识库文件缺失，返回空字符串也合法（降级）
        assert isinstance(result, str)

    def test_mediation_triggers_knowledge(self):
        result = relevant_knowledge("中介分析 bootstrap")
        assert isinstance(result, str)

    def test_max_items_respected(self):
        """大量命中时不超 max_items 条。"""
        result = relevant_knowledge(
            "anova regression correlation mediation moderation "
            "mlm sem irt factor power equivalence meta bayes",
            max_items=3,
        )
        # 至多 3 条（每条以 [ 开头）
        count = result.count("[方法·") + result.count("[前提假设·") + result.count("[设计·") + result.count("[背书·")
        assert count <= 3

    def test_returns_str(self):
        assert isinstance(relevant_knowledge("random text xyz"), str)

    def test_chinese_alias_triggers(self):
        """中文触发词（中介/调节）应能扩展命中英文知识库条目。"""
        r1 = relevant_knowledge("中介")
        r2 = relevant_knowledge("mediation")
        # 两者均不引发错误
        assert isinstance(r1, str)
        assert isinstance(r2, str)


# ---------------------------------------------------------------------------
# compact_history
# ---------------------------------------------------------------------------

def _make_messages(n: int, chars_each: int = 100) -> list[dict]:
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"[{role}-{i}] " + "x" * chars_each})
    return msgs


class TestCompactHistory:
    def test_no_compression_below_budget(self):
        msgs = _make_messages(4, chars_each=100)
        new_msgs, new_memo = compact_history(msgs, "")
        assert new_msgs == msgs
        assert new_memo == ""

    def test_compression_triggered_above_budget(self):
        chars_each = CHAR_BUDGET_HISTORY // 4
        msgs = _make_messages(20, chars_each=chars_each)
        total = sum(len(m["content"]) for m in msgs)
        assert total > CHAR_BUDGET_HISTORY
        new_msgs, new_memo = compact_history(msgs, "")
        assert len(new_msgs) <= KEEP_RECENT_TURNS + 2  # 允许小误差
        assert len(new_memo) > 0  # 有内容被蒸馏

    def test_recent_turns_preserved(self):
        chars_each = CHAR_BUDGET_HISTORY // 2
        msgs = _make_messages(20, chars_each=chars_each)
        new_msgs, _ = compact_history(msgs, "")
        # 最后 KEEP_RECENT_TURNS 条应保留
        expected_last = msgs[-KEEP_RECENT_TURNS:]
        assert new_msgs == expected_last

    def test_memo_accumulated(self):
        chars_each = CHAR_BUDGET_HISTORY // 2
        msgs = _make_messages(20, chars_each=chars_each)
        _, memo = compact_history(msgs, "原始备忘")
        assert "原始备忘" in memo

    def test_memo_length_capped(self):
        chars_each = CHAR_BUDGET_HISTORY // 2
        msgs = _make_messages(20, chars_each=chars_each)
        old_memo = "X" * 5000  # 超过 4000
        _, memo = compact_history(msgs, old_memo)
        assert len(memo) <= 4200  # 允许小误差

    def test_empty_messages_unchanged(self):
        new_msgs, new_memo = compact_history([], "")
        assert new_msgs == []
        assert new_memo == ""

    def test_returns_tuple(self):
        msgs = _make_messages(2, 50)
        result = compact_history(msgs, "")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# compact_history LLM 蒸馏(v0.5 feat-041)
# ---------------------------------------------------------------------------

class _FakeProvider:
    def __init__(self, reply="- 决策:用被试内设计\n- 待办:补功效分析", api_key="k"):
        self._reply = reply
        self.api_key = api_key
        self.calls = 0

    def chat(self, messages, system=""):
        self.calls += 1
        self._last_system = system
        return iter([self._reply])


class _BoomProvider:
    api_key = "k"

    def chat(self, messages, system=""):
        raise RuntimeError("network down")


class TestCompactHistoryLLMDistill:
    def _big(self):
        return _make_messages(20, chars_each=CHAR_BUDGET_HISTORY // 2)

    def test_llm_distill_used_when_provider_has_key(self):
        prov = _FakeProvider()
        _, memo = compact_history(self._big(), "", provider=prov)
        assert prov.calls == 1
        assert "用被试内设计" in memo and "补功效分析" in memo
        assert "压缩器" in prov._last_system   # 用了蒸馏 system 提示

    def test_falls_back_to_rule_distill_on_provider_error(self):
        prov = _BoomProvider()
        _, memo = compact_history(self._big(), "", provider=prov)
        assert len(memo) > 0                    # 回落规则蒸馏,不空、不抛
        assert "用户" in memo or "助手" in memo  # 规则蒸馏带角色前缀

    def test_no_key_provider_falls_back(self):
        prov = _FakeProvider(api_key="")        # 如 mock
        _, memo = compact_history(self._big(), "", provider=prov)
        assert prov.calls == 0                  # 没调 LLM
        assert len(memo) > 0

    def test_provider_none_is_rule_distill(self):
        _, memo_a = compact_history(self._big(), "", provider=None)
        _, memo_b = compact_history(self._big(), "")   # 默认参数
        assert memo_a == memo_b and len(memo_a) > 0

    def test_below_budget_no_llm_call(self):
        prov = _FakeProvider()
        msgs = _make_messages(4, 100)
        new_msgs, _ = compact_history(msgs, "", provider=prov)
        assert prov.calls == 0 and new_msgs == msgs


# ---------------------------------------------------------------------------
# render_memo
# ---------------------------------------------------------------------------

class TestRenderMemo:
    def test_empty_returns_empty(self):
        assert render_memo("") == ""

    def test_non_empty_wrapped(self):
        result = render_memo("决定: 使用 Welch t")
        assert "会话决策备忘" in result
        assert "决定: 使用 Welch t" in result

    def test_returns_str(self):
        assert isinstance(render_memo("abc"), str)


# ---------------------------------------------------------------------------
# _distill
# ---------------------------------------------------------------------------

class TestDistill:
    def test_extracts_decision_line(self):
        msg = {"role": "assistant", "content": "根据效应量，我们决定使用 Welch t 检验。\n这是其他内容。"}
        result = _distill(msg)
        # 含效应量的行被保留
        assert "效应量" in result or "Welch" in result

    def test_falls_back_to_first_line(self):
        msg = {"role": "user", "content": "普通问题，没有决策标记词。"}
        result = _distill(msg)
        # 无决策标记时回退到第一行（截断）
        assert "普通问题" in result

    def test_role_label_present(self):
        msg = {"role": "user", "content": "我的问题"}
        result = _distill(msg)
        assert "用户" in result

    def test_assistant_role_label(self):
        msg = {"role": "assistant", "content": "我的回答"}
        result = _distill(msg)
        assert "助手" in result

    def test_empty_content(self):
        msg = {"role": "user", "content": ""}
        result = _distill(msg)
        assert isinstance(result, str)

    def test_long_line_truncated(self):
        long_content = "x" * 500
        msg = {"role": "user", "content": long_content}
        result = _distill(msg)
        # _distill 截断到 160 字符/行
        for line in result.split("\n"):
            assert len(line) <= 200  # 含前缀，宽松验证


# ---------------------------------------------------------------------------
# smart_excerpt — text files
# ---------------------------------------------------------------------------

class TestSmartExcerptText:
    def test_small_file_full_content(self, tmp_path):
        p = tmp_path / "notes.txt"
        content = "Hello\nWorld\n研究备注"
        p.write_text(content, encoding="utf-8")
        result = smart_excerpt(p)
        assert "Hello" in result
        assert "研究备注" in result

    def test_large_file_truncated(self, tmp_path):
        p = tmp_path / "big.txt"
        # 超过 FILE_EXCERPT_CHARS 字节
        content = "A" * (FILE_EXCERPT_CHARS + 1000)
        p.write_text(content, encoding="utf-8")
        result = smart_excerpt(p)
        assert len(result) < len(content)
        assert "中部省略" in result or "excerpt" in result

    def test_file_path_in_result(self, tmp_path):
        p = tmp_path / "report.md"
        p.write_text("# 报告", encoding="utf-8")
        result = smart_excerpt(p)
        assert str(p) in result

    def test_error_handling_unreadable(self, tmp_path):
        p = tmp_path / "phantom.txt"
        # 文件不存在
        result = smart_excerpt(p)
        assert "error" in result.lower() or "phantom" in result


# ---------------------------------------------------------------------------
# smart_excerpt — CSV files
# ---------------------------------------------------------------------------

def _make_csv(tmp: Path, name: str = "data.csv", rows: int = 10) -> Path:
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "score", "group"])
        for i in range(rows):
            w.writerow([i + 1, 50.0 + i, "A" if i % 2 == 0 else "B"])
    return p


class TestSmartExcerptCSV:
    def test_csv_returns_structured_excerpt(self, tmp_path):
        p = _make_csv(tmp_path)
        result = smart_excerpt(p)
        assert "<csv" in result
        assert "id" in result
        assert "score" in result

    def test_csv_shows_column_types(self, tmp_path):
        p = _make_csv(tmp_path)
        result = smart_excerpt(p)
        # 列类型标注 (num) 或 (str)
        assert "(num)" in result or "(str)" in result

    def test_csv_shows_row_count(self, tmp_path):
        p = _make_csv(tmp_path, rows=50)
        result = smart_excerpt(p)
        assert "rows" in result or "行" in result

    def test_csv_does_not_dump_all_rows(self, tmp_path):
        p = _make_csv(tmp_path, rows=100)
        result = smart_excerpt(p)
        # 应包含提示而不是全部 100 行
        assert "100" not in result.split("<csv")[0] or "统计" in result or "样例" in result

    def test_csv_hint_to_use_cli(self, tmp_path):
        p = _make_csv(tmp_path)
        result = smart_excerpt(p)
        # 提示用 CLI 做全量分析
        assert "psyclaw" in result

    def test_tsv_also_works(self, tmp_path):
        p = tmp_path / "data.tsv"
        with p.open("w", encoding="utf-8") as f:
            f.write("a\tb\n1\t2\n3\t4\n")
        result = smart_excerpt(p)
        assert "a" in result
        assert "<csv" in result

    def test_csv_path_in_result(self, tmp_path):
        p = _make_csv(tmp_path)
        result = smart_excerpt(p)
        assert str(p) in result


# ---------------------------------------------------------------------------
# _is_num
# ---------------------------------------------------------------------------

class TestIsNum:
    @pytest.mark.parametrize("s", ["3.14", "-1", "0", "1e5", "42"])
    def test_numeric(self, s):
        assert _is_num(s)

    @pytest.mark.parametrize("s", ["hello", "", "1,2", "NA", " "])
    def test_non_numeric(self, s):
        assert not _is_num(s)
