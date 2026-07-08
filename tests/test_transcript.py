"""对话导出测试 —— render_conversation / render_full / default_path(纯函数)。"""

from __future__ import annotations

from psyclaw.transcript import (default_path, render_conversation, render_full)

MSGS = [
    {"role": "user", "content": "帮我设计一个实验"},
    {"role": "assistant", "content": "先澄清你的研究问题。"},
]


def test_conversation_has_both_turns():
    out = render_conversation(MSGS)
    assert "# PsyClaw 对话导出" in out
    assert "🧑 用户" in out and "🤖 PsyClaw" in out
    assert "帮我设计一个实验" in out
    assert "先澄清你的研究问题。" in out


def test_conversation_omits_hidden_context():
    """当前对话导出不含 system 提示/备忘——那是 --full 才摊开的隐藏上下文。"""
    out = render_conversation(MSGS)
    assert "隐藏上下文" not in out
    assert "系统提示" not in out


def test_conversation_meta_header():
    meta = {"session_id": "20260708-1200", "provider": "mock", "turns": 1}
    out = render_conversation(MSGS, meta=meta)
    assert "20260708-1200" in out
    assert "mock" in out


def test_conversation_empty():
    out = render_conversation([])
    assert "暂无对话" in out


def test_full_includes_system_memo_and_conventions():
    out = render_full(MSGS, system="你是心理学研究编排助手",
                      memo="决策:采用被试内设计",
                      conventions="# 键盘选择器约定…")
    assert "隐藏上下文" in out
    assert "你是心理学研究编排助手" in out
    assert "决策:采用被试内设计" in out
    assert "键盘选择器约定" in out
    # 对话本体仍在
    assert "帮我设计一个实验" in out


def test_full_empty_hidden_fields_render_placeholder():
    out = render_full(MSGS, system="", memo="")
    assert "系统提示" in out
    assert "_（空）_" in out


def test_render_handles_non_string_content():
    """content 非字符串(异常态)也不崩,稳妥转字符串。"""
    out = render_conversation([{"role": "user", "content": None},
                               {"role": "assistant", "content": 42}])
    assert "42" in out


def test_render_unknown_role():
    out = render_conversation([{"role": "tool", "content": "结果"}])
    assert "tool" in out and "结果" in out


def test_default_path():
    assert default_path("20260708-1200") == "outputs/chat_20260708-1200.md"
    assert default_path("20260708-1200", full=True) == "outputs/chat_20260708-1200.full.md"
    # 空会话 ID 兜底
    assert default_path("") == "outputs/chat_session.md"


# -- /dump 命令端到端(写盘 + 护栏)----------------------------------------
from pathlib import Path

from psyclaw.repl import ReplSession


class _FakeProvider:
    def describe(self) -> str:
        return "mock · test-model"


def _make_session():
    """跳过重构造函数,只装 _cmd_dump 需要的属性(单测命令处理 + 写盘 + 护栏)。"""
    s = ReplSession.__new__(ReplSession)
    s.messages = list(MSGS)
    s.session_id = "20260708-1200"
    s.session_name = None
    s.provider = _FakeProvider()
    s.system = "你是心理学研究编排助手"
    s.memo = ""
    s.file_access = "open"
    s.plan_mode = False
    return s


def test_cmd_dump_conversation(tmp_path):
    s = _make_session()
    out = tmp_path / "chat.md"
    s._cmd_dump(str(out))
    text = out.read_text(encoding="utf-8")
    assert "帮我设计一个实验" in text
    assert "隐藏上下文" not in text          # 非 --full 不含隐藏上下文


def test_cmd_dump_full_includes_system(tmp_path):
    s = _make_session()
    out = tmp_path / "chat.full.md"
    s._cmd_dump(f"--full {out}")
    text = out.read_text(encoding="utf-8")
    assert "隐藏上下文" in text
    assert "你是心理学研究编排助手" in text   # system 提示摊开
    assert "键盘选择器" in text              # 每轮约定片段(_CHOICES_SYSTEM)


def test_cmd_dump_refuses_protected_raw(tmp_path, capsys):
    s = _make_session()
    target = tmp_path / "data" / "raw" / "leak.md"
    s._cmd_dump(str(target))
    assert not target.exists()               # 铁律:绝不写 data/raw
    assert "拒绝" in capsys.readouterr().out


def test_cmd_dump_empty_conversation(tmp_path, capsys):
    s = _make_session()
    s.messages = []
    s._cmd_dump(str(tmp_path / "x.md"))
    assert "暂无对话" in capsys.readouterr().out
    assert not (tmp_path / "x.md").exists()
