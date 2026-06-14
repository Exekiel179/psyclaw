"""tests/test_providers.py — providers 包单元测试 (P5-E6)。

被测：MockProvider.chat / Provider.describe / get_provider / PRESETS
不需要 API key 或网络——所有用例均离线运行。
"""
from __future__ import annotations

import pytest

from psyclaw.providers import PRESETS, get_provider
from psyclaw.providers.base import Provider
from psyclaw.providers.mock import MockProvider


# ---------------------------------------------------------------------------
# MockProvider.chat
# ---------------------------------------------------------------------------

class TestMockProviderChat:
    def _collect(self, gen) -> str:
        return "".join(gen)

    def test_returns_iterator(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "hello"}]
        it = mp.chat(msgs)
        assert hasattr(it, "__iter__")

    def test_yields_chars(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "hello"}]
        chunks = list(mp.chat(msgs))
        assert all(isinstance(c, str) for c in chunks)

    def test_reply_mentions_message_count(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "test"}]
        reply = self._collect(mp.chat(msgs))
        assert "1" in reply  # "收到 1 条消息"

    def test_reply_includes_preview(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "心理学研究计划"}]
        reply = self._collect(mp.chat(msgs))
        assert "心理学研究计划" in reply

    def test_long_content_truncated_in_preview(self):
        mp = MockProvider()
        long_msg = "A" * 200
        msgs = [{"role": "user", "content": long_msg}]
        reply = self._collect(mp.chat(msgs))
        # preview 截断到 120 字符，reply 不应该含有完整的 200 个 A
        assert long_msg not in reply

    def test_verdict_in_last_msg_triggers_verdict_reply(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "请给出 VERDICT 判断"}]
        reply = self._collect(mp.chat(msgs))
        assert "VERDICT: PASS" in reply

    def test_no_verdict_keyword_no_verdict_appended(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "普通问题"}]
        reply = self._collect(mp.chat(msgs))
        assert "VERDICT: PASS" not in reply

    def test_system_psyclaw_noted(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "q"}]
        reply = self._collect(mp.chat(msgs, system="含 PSYCLAW 规范文本"))
        assert "PSYCLAW" in reply

    def test_system_without_psyclaw_no_note(self):
        mp = MockProvider()
        msgs = [{"role": "user", "content": "q"}]
        reply = self._collect(mp.chat(msgs, system="普通系统提示"))
        assert "(已注入 PSYCLAW 规范)" not in reply

    def test_empty_messages_no_crash(self):
        mp = MockProvider()
        reply = self._collect(mp.chat([]))
        assert isinstance(reply, str)

    def test_multi_turn_uses_last_message(self):
        mp = MockProvider()
        msgs = [
            {"role": "user", "content": "第一条"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "最后一条提问"},
        ]
        reply = self._collect(mp.chat(msgs))
        assert "最后一条提问" in reply
        assert "3" in reply  # 共3条消息

    def test_name_attribute(self):
        assert MockProvider.name == "mock"


# ---------------------------------------------------------------------------
# Provider.describe
# ---------------------------------------------------------------------------

class TestProviderDescribe:
    def test_describe_no_key(self):
        mp = MockProvider(model="test-model")
        desc = mp.describe()
        assert "mock" in desc
        assert "test-model" in desc
        assert "无" in desc  # 无 API key

    def test_describe_returns_str(self):
        mp = MockProvider()
        assert isinstance(mp.describe(), str)

    def test_describe_includes_provider_name(self):
        mp = MockProvider()
        assert mp.name in mp.describe()


# ---------------------------------------------------------------------------
# PRESETS 常量结构
# ---------------------------------------------------------------------------

class TestPresets:
    def test_has_required_providers(self):
        for key in ("anthropic", "openai", "deepseek", "mock", "ollama"):
            assert key in PRESETS

    def test_each_preset_has_required_keys(self):
        required = {"label", "protocol", "base_url", "model", "models", "key_env"}
        for name, preset in PRESETS.items():
            missing = required - set(preset)
            assert not missing, f"Preset {name} 缺少键: {missing}"

    def test_protocol_is_valid(self):
        valid = {"anthropic", "openai", "mock", "opencode"}
        for name, preset in PRESETS.items():
            assert preset["protocol"] in valid, f"{name} 协议 {preset['protocol']} 未知"

    def test_mock_preset_has_no_key_env(self):
        assert PRESETS["mock"]["key_env"] is None

    def test_anthropic_has_claude_model(self):
        assert "claude" in PRESETS["anthropic"]["model"].lower()


# ---------------------------------------------------------------------------
# get_provider
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_mock_returns_mock_provider(self):
        p = get_provider({"provider": "mock"})
        assert isinstance(p, MockProvider)

    def test_empty_conf_returns_mock(self):
        p = get_provider({})
        assert isinstance(p, MockProvider)

    def test_model_override(self):
        p = get_provider({"provider": "mock", "model": "my-model"})
        assert p.model == "my-model"

    def test_no_api_key_falls_back_to_mock(self, monkeypatch):
        """API key 缺失时，anthropic/openai 都应 fallback 到 mock。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        p = get_provider({"provider": "anthropic"})
        # 无 key → fallback mock
        assert isinstance(p, MockProvider)

    def test_unknown_provider_defaults_to_openai_compat_or_mock(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # unknown 映射到 custom preset，key_env=OPENAI_API_KEY，无 key → mock
        p = get_provider({"provider": "unknownxyz"})
        assert isinstance(p, MockProvider)
