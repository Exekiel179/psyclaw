"""clarify CLAR-1：LLM 驱动追问 + fail-safe 降级 的单元测试。

不触真实 provider / 真实 input：用脚本化 provider 与队列 ask 注入。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psyclaw.providers.base import Provider  # noqa: E402
from psyclaw.providers.mock import MockProvider  # noqa: E402
from psyclaw.psych import clarify  # noqa: E402

DV_SLOT = next(s for s in clarify.SLOTS if s[0] == "dv")


class ScriptedProvider(Provider):
    """按队列回放回复;队列空则默认 PASS。记录调用次数。"""

    name = "scripted"

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def chat(self, messages, system=""):
        self.calls += 1
        reply = self._replies.pop(0) if self._replies else "CLARIFY_VERDICT: PASS"
        for ch in reply:
            yield ch


class NoCallProvider(Provider):
    name = "scripted"

    def chat(self, messages, system=""):
        raise AssertionError("降级路径不应调用 provider")


def make_ask(items):
    it = iter(items)

    def ask(_prompt):
        try:
            return next(it)
        except StopIteration:
            return "skip"

    return ask


PROBE = "CLARIFY_VERDICT: PROBE\nFOLLOWUP: 用什么量表测?信度多少?"
PASS = "CLARIFY_VERDICT: PASS"


# --- _parse_eval ----------------------------------------------------------

def test_parse_eval_pass():
    assert clarify._parse_eval("CLARIFY_VERDICT: PASS") == ("PASS", "")


def test_parse_eval_probe_with_followup():
    v, f = clarify._parse_eval(PROBE)
    assert v == "PROBE" and "量表" in f


def test_parse_eval_default_pass_when_unparseable():
    # fail-safe:解析不到裁决一律放行,避免卡住用户
    assert clarify._parse_eval("胡言乱语没有标记") == ("PASS", "")


def test_parse_eval_last_verdict_wins():
    v, _ = clarify._parse_eval("CLARIFY_VERDICT: PROBE\nCLARIFY_VERDICT: PASS")
    assert v == "PASS"


def test_parse_eval_fullwidth_colon():
    assert clarify._parse_eval("CLARIFY_VERDICT： PROBE")[0] == "PROBE"


# --- evaluate_answer ------------------------------------------------------

def test_evaluate_empty_is_skip():
    p = ScriptedProvider([])
    assert clarify.evaluate_answer(p, DV_SLOT, "   ")["verdict"] == "SKIP"
    assert p.calls == 0  # 空回答不触发 LLM 调用


def test_evaluate_pass():
    out = clarify.evaluate_answer(ScriptedProvider([PASS]), DV_SLOT, "PHQ-9 测抑郁,α=.89")
    assert out["verdict"] == "PASS"


def test_evaluate_probe_supplies_default_followup():
    out = clarify.evaluate_answer(ScriptedProvider(["CLARIFY_VERDICT: PROBE"]), DV_SLOT, "问卷")
    assert out["verdict"] == "PROBE" and out["followup"]  # 缺 FOLLOWUP 时补默认追问


def test_evaluate_provider_exception_fails_safe_to_pass():
    out = clarify.evaluate_answer(NoCallProvider(), DV_SLOT, "问卷")  # chat 抛错
    assert out["verdict"] == "PASS"


# --- clarify_one ----------------------------------------------------------

def test_clarify_one_pass_no_probe():
    p = ScriptedProvider([PASS])
    r = clarify.clarify_one(p, DV_SLOT, make_ask(["大学生中正念干预降低4周后焦虑"]),
                            out=lambda *a: None)
    assert r["resolved"] and r["rounds"] == 0 and p.calls == 1


def test_clarify_one_probe_then_accept(capsys):
    p = ScriptedProvider([PROBE, PASS])
    r = clarify.clarify_one(p, DV_SLOT, make_ask(["问卷", "PHQ-9,α=.89"]))
    assert r["resolved"] and r["rounds"] == 1 and p.calls == 2
    assert "问卷" in r["answer"] and "PHQ-9" in r["answer"]
    assert "追问" in capsys.readouterr().out


def test_clarify_one_probe_cap():
    # provider 一直 PROBE,达到 max_probes 即停,答案仍记为 resolved
    p = ScriptedProvider([PROBE, PROBE, PROBE])
    r = clarify.clarify_one(p, DV_SLOT, lambda _p: "再补一点", max_probes=2,
                            out=lambda *a: None)
    assert r["rounds"] == 2 and p.calls == 2 and r["resolved"]


def test_clarify_one_skip_unresolved():
    p = ScriptedProvider([])
    r = clarify.clarify_one(p, DV_SLOT, make_ask(["skip"]), out=lambda *a: None)
    assert not r["resolved"] and r["rounds"] == 0 and p.calls == 0


def test_clarify_one_empty_is_skip():
    r = clarify.clarify_one(ScriptedProvider([]), DV_SLOT, make_ask([""]), out=lambda *a: None)
    assert not r["resolved"]


def test_clarify_one_question_mark_shows_why(capsys):
    r = clarify.clarify_one(ScriptedProvider([PASS]), DV_SLOT,
                            make_ask(["?", "PHQ-9,α=.89"]))
    assert r["resolved"]
    assert "为什么重要" in capsys.readouterr().out


def test_clarify_one_probe_then_skip_keeps_first_answer():
    p = ScriptedProvider([PROBE])
    r = clarify.clarify_one(p, DV_SLOT, make_ask(["问卷", "skip"]), out=lambda *a: None)
    assert r["resolved"] and r["answer"] == "问卷" and r["rounds"] == 1


def test_clarify_one_degrade_no_provider_calls():
    # probing=False:不调用 provider(NoCallProvider.chat 会抛错)
    r = clarify.clarify_one(NoCallProvider(), DV_SLOT, make_ask(["问卷"]),
                            probing=False, out=lambda *a: None)
    assert r["resolved"] and r["rounds"] == 0


# --- run_clarify_interactive ---------------------------------------------

def test_run_all_skip_returns_1(tmp_path):
    rc = clarify.run_clarify_interactive(str(tmp_path), provider=MockProvider(),
                                         ask=lambda _p: "skip")
    assert rc == 1
    card = clarify.check_card(str(tmp_path))
    assert card["exists"] and card["resolved"] == 0
    assert len(card["unresolved"]) == len(clarify.SLOTS)


def test_run_all_answered_returns_0(tmp_path):
    # MockProvider → probing 关闭,每槽一问一答全 resolved
    rc = clarify.run_clarify_interactive(str(tmp_path), provider=MockProvider(),
                                         ask=lambda _p: "具体且可检验的答案")
    assert rc == 0
    assert clarify.check_card(str(tmp_path))["resolved"] == len(clarify.SLOTS)


def test_run_mock_provider_disables_probing(tmp_path, capsys):
    clarify.run_clarify_interactive(str(tmp_path), provider=MockProvider(),
                                    ask=lambda _p: "答案")
    assert "降级为照单收集" in capsys.readouterr().out


def test_run_probing_enabled_banner(tmp_path, capsys):
    clarify.run_clarify_interactive(str(tmp_path), provider=ScriptedProvider([]),
                                    ask=lambda _p: "具体可检验答案")
    assert "已启用 LLM 追问" in capsys.readouterr().out
