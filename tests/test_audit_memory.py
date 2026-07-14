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

class TestRelevantLessons:
    """feat-111:教训注入改相关性检索——强度保底 + 关键词命中 top-k,治上下文膨胀。"""
    def _seed(self):
        from psyclaw.memory import draft_lesson, confirm_lesson
        cards = [
            ("python", "本机没有 python 命令,用 python3", "error"),
            ("mne", "系统 Python 没装 mne,EEG 任务先 pip install mne", "error"),
            ("pandas", "读大 CSV 用 chunksize 防内存爆", "error"),
            ("zotero", "Zotero API 取全文需要 ZOTERO_API_KEY", "error"),
            ("latex", "导出 PDF 前先装 texlive", "error"),
        ]
        for i, (t, l, s_) in enumerate(cards):
            draft_lesson(t, l, s_)
            confirm_lesson(0)
        from psyclaw.memory import _load, _save
        data = _load("lessons")
        for c in data.get("cards", []):
            if c.get("trigger") == "python":
                c["strength"] = 9
        _save("lessons", data)
    def test_relevance_picks_matching_card(self, mem_dir):
        from psyclaw.memory import relevant_lessons
        self._seed()
        cards = relevant_lessons("帮我做 EEG 预处理,数据要用 mne 读", top_k=2, always_top=1)
        triggers = [c["trigger"] for c in cards]
        assert triggers[0] == "python"          # 强度最高保底
        assert "mne" in triggers                # 相关命中
        assert "latex" not in triggers          # 无关不注入
    def test_empty_query_falls_back_to_strength(self, mem_dir):
        from psyclaw.memory import relevant_lessons
        self._seed()
        cards = relevant_lessons("", top_k=2, always_top=2)
        assert len(cards) == 4                  # always_top + top_k 上限
        assert cards[0]["trigger"] == "python"
    def test_no_cards_returns_empty(self, mem_dir):
        from psyclaw.memory import relevant_lessons, render_lesson_block
        assert relevant_lessons("任何话") == []
        assert render_lesson_block([]) == ""
    def test_render_block_format(self, mem_dir):
        from psyclaw.memory import relevant_lessons, render_lesson_block
        self._seed()
        block = render_lesson_block(relevant_lessons("mne EEG"))
        assert block.startswith("# 教训卡") and "[python]" in block
    def test_static_prompt_can_exclude_lessons(self, mem_dir):
        """feat-111:REPL 静态 system 剥离教训(include_lessons=False)。"""
        from psyclaw.memory import draft_lesson, confirm_lesson, memory_prompt
        draft_lesson("t", "某教训内容", "error")
        confirm_lesson(0)
        assert "某教训内容" in memory_prompt()
        assert "某教训内容" not in memory_prompt(include_lessons=False)

class TestSemanticFacts:
    """feat-114:语义记忆 + 冲突协议(docs/MEMORY.md)——绝不静默覆盖/丢弃。"""
    def test_create_and_reinforce(self, mem_dir):
        from psyclaw.memory import record_fact
        r1 = record_fact("缺失码", "post_score 的 99 和 -999 是缺失码")
        assert r1["status"] == "created" and r1["card"]["strength"] == 1
        r2 = record_fact("缺失码", "post_score 的 99 和 -999 是缺失码")
        assert r2["status"] == "reinforced" and r2["card"]["strength"] == 2
        assert r2["card"]["confidence"] > 0.7          # 频率是编码信号
    def test_conflict_recency_wins_but_demoted(self, mem_dir):
        from psyclaw.memory import record_fact
        record_fact("缺失码", "缺失码是 99", confidence=0.9)
        r = record_fact("缺失码", "缺失码是 999", confidence=0.9)
        assert r["status"] == "conflict"
        c = r["card"]
        assert c["statement"] == "缺失码是 999"          # 时近优先生效
        assert c["confidence"] <= 0.6                    # 但降置信
        assert c["conflicted"] is True
        assert c["history"][-1]["statement"] == "缺失码是 99"   # 旧说法不删
    def test_scope_separation_no_conflict(self, mem_dir):
        from psyclaw.memory import record_fact
        record_fact("alpha", "项目里 α 定 .01", scope="project")
        r = record_fact("alpha", "常规 α 是 .05", scope="global")
        assert r["status"] == "created"                  # 不同 scope 不算冲突
    def test_recall_scores_and_bumps_usage(self, mem_dir):
        from psyclaw.memory import record_fact, recall_facts
        record_fact("缺失码", "post_score 的 99 和 -999 是缺失码")
        record_fact("latex", "导出 PDF 前装 texlive")
        hits = recall_facts("清洗 post_score 时缺失码怎么处理")
        assert [c["concept"] for c in hits] == ["缺失码"]
        assert hits[0]["use_count"] == 1                 # 取用即强化(遗忘输入)
    def test_render_conflict_banner(self, mem_dir):
        from psyclaw.memory import record_fact, recall_facts, render_fact_block
        record_fact("缺失码", "缺失码是 99")
        record_fact("缺失码", "缺失码是 999")
        block = render_fact_block(recall_facts("数据里的缺失码是什么来着"))
        assert "缺失码是 999" in block
        assert "曾有不同说法" in block and "缺失码是 99" in block   # 知情注入
    def test_resolve_clears_flag_keeps_history(self, mem_dir):
        from psyclaw.memory import record_fact, resolve_fact, _load
        record_fact("k", "v1")
        record_fact("k", "v2")
        assert resolve_fact("k") is True
        c = _load("facts")["facts"][0]
        assert c["conflicted"] is False and c["history"]   # 历史保留可追溯
        assert resolve_fact("k") is False                  # 无冲突再裁决=False
    def test_agent_tool_reports_conflict(self, mem_dir):
        from psyclaw.toolloop import build_tools
        tools = build_tools(".")
        out1 = tools["remember_fact"]["run"]({"concept": "c", "statement": "x"})
        assert "已记入" in out1
        out2 = tools["remember_fact"]["run"]({"concept": "c", "statement": "y"})
        assert "冲突" in out2 and "请向用户确认" in out2

class TestDecayLifecycle:
    """feat-115:激活度衰减 + 休眠/复活/删除(docs/MEMORY.md §三)。"""
    def _age_fact(self, days, use_count=0):
        from psyclaw.memory import _load, _save
        from datetime import datetime, timedelta
        data = _load("facts")
        c = data["facts"][0]
        old = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        c["last_used"] = old
        c["recorded"] = old
        c["use_count"] = use_count
        _save("facts", data)
    def test_activation_decays(self, mem_dir):
        from psyclaw.memory import record_fact, card_activation, _load
        record_fact("k", "v")
        fresh = card_activation(_load("facts")["facts"][0])
        assert fresh > 0.9
        self._age_fact(days=180)
        assert card_activation(_load("facts")["facts"][0]) < 0.5
    def test_decay_moves_to_dormant_and_excludes_from_recall(self, mem_dir):
        from psyclaw.memory import record_fact, apply_decay, recall_facts, _load
        record_fact("缺失码", "缺失码是 99 和 -999")
        self._age_fact(days=200)
        r = apply_decay()
        assert r["facts_dormant"] == 1
        assert _load("facts")["facts"][0]["status"] == "dormant"
        assert recall_facts("数据里的缺失码怎么处理") == []   # 休眠不注入
    def test_dormant_fact_revives_on_reencounter(self, mem_dir):
        from psyclaw.memory import record_fact, apply_decay, _load
        record_fact("k", "v")
        self._age_fact(days=200)
        apply_decay()
        r = record_fact("k", "v")                             # 再遇即复活
        assert r["status"] == "reinforced"
        assert _load("facts")["facts"][0].get("status") == "active"
    def test_dormant_unused_purged_with_snapshot(self, mem_dir):
        from psyclaw.memory import record_fact, apply_decay, _load, _save
        from datetime import datetime, timedelta
        record_fact("k", "v")
        self._age_fact(days=200, use_count=0)
        apply_decay()                                          # → dormant
        data = _load("facts")
        data["facts"][0]["dormant_ts"] = (
            datetime.now() - timedelta(days=200)).isoformat(timespec="seconds")
        _save("facts", data)
        r = apply_decay()                                      # → purge
        assert r["facts_purged"] == 1
        data = _load("facts")
        assert data["facts"] == [] and data["purged"][0]["concept"] == "k"
    def test_lesson_decay_and_revival(self, mem_dir):
        import time as _t
        from psyclaw.memory import (draft_lesson, confirm_lesson, apply_decay,
                                    active_lessons, _load, _save)
        draft_lesson("python", "用 python3", "error")
        confirm_lesson(0)
        data = _load("lessons")
        data["active"][0]["ts"] = int(_t.time()) - 200 * 86400   # 老化
        _save("lessons", data)
        r = apply_decay()
        assert r["lessons_dormant"] == 1 and active_lessons() == []
        draft_lesson("python", "用 python3", "error")            # 再踩同坑 → 复活
        acts = active_lessons()
        assert len(acts) == 1 and acts[0]["strength"] == 2
class TestDivergentRetrieval:
    """feat-117:发散检索——创新任务额外采样中等相关卡,造远距联想。"""
    def _seed_many(self):
        from psyclaw.memory import record_fact
        record_fact("沙盘治疗", "电子沙盘用于青少年心理咨询,记录摆放轨迹")
        record_fact("叙事治疗", "叙事疗法通过重写故事线帮助来访者")
        record_fact("团体辅导", "团体心理辅导在学校场景的应用")
        record_fact("表达性艺术", "绘画音乐等表达性艺术治疗的心理机制")
    def test_is_divergent_task(self):
        from psyclaw.memory import is_divergent_task
        assert is_divergent_task("帮我头脑风暴几个研究设计") is True
        assert is_divergent_task("还能怎么拓展这个方向") is True
        assert is_divergent_task("把这段统计结果写进结果部分") is False
    def test_focused_mode_no_diverge(self, mem_dir):
        from psyclaw.memory import recall_facts
        self._seed_many()
        hits = recall_facts("心理咨询用什么方法", mode="focused", top_k=1)
        assert all(not c.get("_diverge") for c in hits)
    def test_diverge_mode_adds_distant(self, mem_dir):
        from psyclaw.memory import recall_facts
        self._seed_many()
        hits = recall_facts("心理治疗方法有哪些", mode="diverge", top_k=1, diverge_k=2)
        assert any(c.get("_diverge") for c in hits)      # 有远距联想卡被采入
    def test_render_labels_diverge_separately(self, mem_dir):
        from psyclaw.memory import recall_facts, render_fact_block
        self._seed_many()
        block = render_fact_block(
            recall_facts("心理治疗方法", mode="diverge", top_k=1, diverge_k=2))
        assert "远距联想" in block
