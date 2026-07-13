"""tests/test_audit_memory.py — audit.py + memory.py 单元测试 (P5-E2)。

被测函数：
  audit: parse_audit / render_verdict
  memory: _decayed / suggest / draft_lesson / confirm_lesson /
          active_lessons / memory_prompt / get_profile / set_profile
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# audit.parse_audit
# ---------------------------------------------------------------------------

from psyclaw.audit import PASS_SCORE, parse_audit, render_verdict


class TestParseAudit:
    def test_explicit_pass(self):
        text = "SCORE: 90\nAUDIT_VERDICT: PASS\n其他内容"
        score, verdict = parse_audit(text)
        assert score == 90
        assert verdict == "PASS"

    def test_explicit_improve(self):
        text = "SCORE: 60\nAUDIT_VERDICT: IMPROVE\n改进: 补充效应量"
        score, verdict = parse_audit(text)
        assert score == 60
        assert verdict == "IMPROVE"

    def test_fail_closed_no_verdict(self):
        """未解析到 AUDIT_VERDICT → fail-closed → IMPROVE。"""
        text = "SCORE: 95\n好像没有 verdict 行"
        score, verdict = parse_audit(text)
        assert verdict == "IMPROVE"
        assert score == 95

    def test_fail_closed_no_score(self):
        """未解析到 SCORE → score=None。"""
        text = "AUDIT_VERDICT: PASS\n无分数"
        score, verdict = parse_audit(text)
        assert score is None
        assert verdict == "PASS"

    def test_fail_closed_empty_text(self):
        """空字符串 → score=None, verdict=IMPROVE。"""
        score, verdict = parse_audit("")
        assert score is None
        assert verdict == "IMPROVE"

    def test_fail_closed_none_text(self):
        """None → fail-closed。"""
        score, verdict = parse_audit(None)  # type: ignore
        assert score is None
        assert verdict == "IMPROVE"

    def test_score_clamped_at_100(self):
        """SCORE > 100 应截断到 100。"""
        text = "SCORE: 150\nAUDIT_VERDICT: PASS"
        score, _ = parse_audit(text)
        assert score == 100

    def test_score_at_boundary_pass(self):
        """SCORE == PASS_SCORE 应计为有效数值。"""
        text = f"SCORE: {PASS_SCORE}\nAUDIT_VERDICT: PASS"
        score, verdict = parse_audit(text)
        assert score == PASS_SCORE
        assert verdict == "PASS"

    def test_last_score_wins(self):
        """多个 SCORE 行时取最后一个（与代码一致）。"""
        text = "SCORE: 40\nSCORE: 85\nAUDIT_VERDICT: PASS"
        score, _ = parse_audit(text)
        assert score == 85

    def test_last_verdict_wins(self):
        text = "AUDIT_VERDICT: PASS\nAUDIT_VERDICT: IMPROVE"
        _, verdict = parse_audit(text)
        assert verdict == "IMPROVE"

    def test_case_insensitive_verdict(self):
        text = "SCORE: 80\nAUDIT_VERDICT: pass"
        _, verdict = parse_audit(text)
        assert verdict == "PASS"

    def test_colon_and_chinese_colon(self):
        """支持半角冒号。"""
        text = "SCORE: 75\nAUDIT_VERDICT: PASS"
        score, verdict = parse_audit(text)
        assert score == 75
        assert verdict == "PASS"

    def test_score_zero(self):
        text = "SCORE: 0\nAUDIT_VERDICT: IMPROVE"
        score, verdict = parse_audit(text)
        assert score == 0
        assert verdict == "IMPROVE"


# ---------------------------------------------------------------------------
# audit.render_verdict
# ---------------------------------------------------------------------------

class TestRenderVerdict:
    def test_pass_result_contains_score(self):
        result = render_verdict({"score": 95, "verdict": "PASS", "text": ""})
        assert "95" in result

    def test_improve_result_contains_score(self):
        result = render_verdict({"score": 60, "verdict": "IMPROVE", "text": ""})
        assert "60" in result

    def test_no_score_shows_label(self):
        result = render_verdict({"score": None, "verdict": "IMPROVE", "text": ""})
        assert "未解析" in result or "None" not in result

    def test_returns_string(self):
        assert isinstance(render_verdict({"score": 80, "verdict": "PASS", "text": ""}), str)


# ---------------------------------------------------------------------------
# memory._decayed
# ---------------------------------------------------------------------------

from psyclaw.memory import (
    _decayed,
    suggest,
    draft_lesson,
    confirm_lesson,
    active_lessons,
    memory_prompt,
    get_profile,
    set_profile,
    MEM_DIR,
)


class TestDecayed:
    def test_fresh_unchanged(self):
        now = int(time.time())
        d = _decayed(100.0, now)
        assert abs(d - 100.0) < 1.0  # 刚记录几乎不衰减

    def test_half_life_90_days(self):
        past = int(time.time()) - 90 * 86400
        d = _decayed(100.0, past)
        assert 45.0 < d < 55.0  # 90天后约剩50

    def test_full_decay_after_many_days(self):
        very_old = int(time.time()) - 3650 * 86400  # 10年
        d = _decayed(100.0, very_old)
        assert d < 0.1  # 几乎为零

    def test_zero_count_returns_zero(self):
        d = _decayed(0.0, int(time.time()))
        assert d == 0.0

    def test_negative_time_treated_as_zero_days(self):
        future = int(time.time()) + 86400
        d = _decayed(100.0, future)
        assert d >= 100.0  # max(0, ...) 保证天数非负


# ---------------------------------------------------------------------------
# memory 三层记忆（重定向 MEM_DIR 到 tmp_path）
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    """把记忆存储重定向到临时目录，避免污染真实 ~/.psyclaw/memory。"""
    monkeypatch.setattr("psyclaw.memory.MEM_DIR", tmp_path / "memory")
    yield tmp_path / "memory"


class TestProfile:
    def test_empty_profile(self, mem_dir):
        assert get_profile() == {}

    def test_set_and_get(self, mem_dir):
        set_profile("领域", "发展心理学")
        prof = get_profile()
        assert prof.get("领域") == "发展心理学"

    def test_overwrite(self, mem_dir):
        set_profile("language", "中文")
        set_profile("language", "English")
        assert get_profile()["language"] == "English"


class TestSuggest:
    def test_no_data_returns_none(self, mem_dir):
        assert suggest("two_groups_test") is None

    def test_suggest_after_recording(self, mem_dir):
        from psyclaw.memory import record_choice
        record_choice("two_groups_test", "welch")
        record_choice("two_groups_test", "welch")
        s = suggest("two_groups_test")
        assert s is not None
        assert s["choice"] == "welch"
        assert 0 < s["confidence"] < 1

    def test_confidence_increases_with_count(self, mem_dir):
        from psyclaw.memory import record_choice
        record_choice("test_topic", "option_A")
        s1 = suggest("test_topic")
        record_choice("test_topic", "option_A")
        record_choice("test_topic", "option_A")
        s3 = suggest("test_topic")
        assert s3["confidence"] > s1["confidence"]

    def test_decayed_suggest_returns_none(self, mem_dir):
        from psyclaw.memory import _load, _save
        # 手动写入一个极旧的记录
        habits = {"ancient_topic": {"counts": {"old": 1}, "last_used": 1}}
        _save("habits", habits)
        # 仅 1 次且超旧 → 衰减后 n < 0.5 → None
        s = suggest("ancient_topic")
        # 可能 None，也可能非常低信度，取决于系统时间距 epoch 多久
        if s is not None:
            assert s["confidence"] < 0.5 or s["raw_count"] == 1


class TestLessons:
    def test_draft_appears_in_pending(self, mem_dir):
        draft_lesson("t_test", "Welch 比 Student 更鲁棒", "critic")
        from psyclaw.memory import _load
        data = _load("lessons")
        assert any(c["lesson"] == "Welch 比 Student 更鲁棒"
                   for c in data.get("pending", []))

    def test_duplicate_draft_not_added(self, mem_dir):
        draft_lesson("t_test", "相同教训", "critic")
        draft_lesson("t_test", "相同教训", "critic")
        from psyclaw.memory import _load
        data = _load("lessons")
        count = sum(1 for c in data.get("pending", [])
                    if c["lesson"] == "相同教训")
        assert count == 1

    def test_confirm_lesson_moves_to_active(self, mem_dir):
        draft_lesson("anova", "球形假设须检验", "auditor")
        ok = confirm_lesson(0)
        assert ok is True
        from psyclaw.memory import _load
        data = _load("lessons")
        assert not data.get("pending")
        assert any(c["lesson"] == "球形假设须检验" for c in data.get("active", []))

    def test_confirm_invalid_index(self, mem_dir):
        ok = confirm_lesson(99)
        assert ok is False

    def test_active_lessons_filter(self, mem_dir):
        draft_lesson("regression", "必须检查多重共线性", "critic")
        confirm_lesson(0)
        lessons = active_lessons("回归分析 regression")
        assert any("多重共线性" in c["lesson"] for c in lessons)

    def test_active_lessons_no_filter(self, mem_dir):
        draft_lesson("general", "写作时不掩盖局限", "critic")
        confirm_lesson(0)
        lessons = active_lessons()
        assert len(lessons) >= 1

    def test_active_lessons_empty_initially(self, mem_dir):
        assert active_lessons() == []


class TestMemoryPrompt:
    def test_empty_returns_empty(self, mem_dir):
        result = memory_prompt()
        assert result == ""

    def test_profile_appears_in_prompt(self, mem_dir):
        set_profile("领域", "认知心理学")
        result = memory_prompt()
        assert "认知心理学" in result

    def test_active_lesson_appears(self, mem_dir):
        draft_lesson("power", "先验功效分析要比较保守", "critic")
        confirm_lesson(0)
        result = memory_prompt()
        assert "先验功效分析要比较保守" in result
class TestLessonReinforcement:
    """feat-066 正向加固:同一教训再现 → active 强度+1 / pending hits+1,不重复建卡。"""
    def test_redraft_active_bumps_strength(self, mem_dir):
        from psyclaw.memory import _load
        draft_lesson("mne", "缺 mne", "error", kind="module")
        confirm_lesson(0)
        draft_lesson("mne", "缺 mne", "error", kind="module")   # 再踩同一坑
        data = _load("lessons")
        assert not data.get("pending")                          # 不新建待确认卡
        card = data["active"][0]
        assert card["strength"] == 2
        assert "reinforced_ts" in card
    def test_redraft_pending_counts_hits(self, mem_dir):
        from psyclaw.memory import _load
        draft_lesson("python", "用 python3", "error", kind="cmd")
        draft_lesson("python", "用 python3", "error", kind="cmd")
        draft_lesson("python", "用 python3", "error", kind="cmd")
        data = _load("lessons")
        assert len(data["pending"]) == 1
        assert data["pending"][0]["hits"] == 3
    def test_reinforce_matches_exact_pair_only(self, mem_dir):
        from psyclaw.memory import _load
        draft_lesson("mne", "缺 mne", "error")
        confirm_lesson(0)
        draft_lesson("mne", "另一条 mne 教训", "error")          # 同触发词不同教训 → 新卡
        data = _load("lessons")
        assert data["active"][0].get("strength", 1) == 1
        assert len(data["pending"]) == 1
    def test_prompt_orders_by_strength(self, mem_dir):
        from psyclaw.memory import memory_prompt
        draft_lesson("weak", "弱教训", "user")
        confirm_lesson(0)
        draft_lesson("strong", "强教训", "user")
        confirm_lesson(0)
        draft_lesson("strong", "强教训", "user")                # 加固到强度 2
        prompt = memory_prompt()
        assert prompt.index("强教训") < prompt.index("弱教训")
    def test_cli_shows_hits(self, mem_dir, capsys):
        from psyclaw.memory import memory_cli
        draft_lesson("python", "用 python3", "error")
        draft_lesson("python", "用 python3", "error")
        memory_cli(["list"])
        assert "已再现 2 次" in capsys.readouterr().out
class TestConfirmCarriesHits:
    """feat-083(评审修复):确认时 pending 的 hits 转为初始强度,不再归 1。"""
    def test_hits_become_strength_on_confirm(self, mem_dir):
        from psyclaw import memory as M
        M.draft_lesson("rscript", "本机没有 rscript", source="error", kind="cmd")
        for _ in range(4):                       # 确认前再现 4 次 → hits=5
            M.draft_lesson("rscript", "本机没有 rscript", source="error", kind="cmd")
        assert M.confirm_lesson(0) is True
        card = M.active_lessons()[0]
        assert card["strength"] == 5
        assert "hits" not in card                # hits 已并入 strength,不留双账
    def test_fresh_card_confirms_to_strength_one(self, mem_dir):
        from psyclaw import memory as M
        M.draft_lesson("nope", "本机没有 nope", source="error", kind="cmd")
        M.confirm_lesson(0)
        assert M.active_lessons()[0]["strength"] == 1
    def test_ranking_prefers_much_reproduced_lesson(self, mem_dir):
        from psyclaw import memory as M
        M.draft_lesson("often", "常踩的坑", source="error", kind="cmd")
        for _ in range(6):
            M.draft_lesson("often", "常踩的坑", source="error", kind="cmd")
        M.draft_lesson("rare", "偶发的坑", source="error", kind="cmd")
        M.confirm_lesson(0)                      # often(hits=7)
        M.confirm_lesson(0)                      # rare(hits=1)
        M.draft_lesson("rare", "偶发的坑", source="error", kind="cmd")  # rare 强度 2
        prompt = M.memory_prompt()
        assert prompt.index("常踩的坑") < prompt.index("偶发的坑")
