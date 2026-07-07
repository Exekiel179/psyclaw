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
import io
import urllib.error
import urllib.request
class _FakeResp:
    """可迭代 + 上下文管理的假 SSE 响应。"""
    def __init__(self, lines, explode_after=None):
        self._lines = list(lines)
        self._explode_after = explode_after
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def __iter__(self):
        for i, ln in enumerate(self._lines):
            if self._explode_after is not None and i >= self._explode_after:
                raise OSError("connection reset mid-stream")
            yield ln
def _http_error(code, body=b'{"error":{"message":"boom"}}'):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))
class TestPostSseRetry:
    def _run(self, monkeypatch, outcomes, lines=(b'data: {"a":1}\n', b"data: [DONE]\n")):
        """outcomes: 每次 urlopen 的行为(异常实例或 'ok')。返回 (yielded, sleeps, calls)。"""
        calls = {"n": 0}
        sleeps: list[float] = []
        def fake_urlopen(req, timeout=0):
            calls["n"] += 1
            out = outcomes[calls["n"] - 1]
            if out == "ok":
                return _FakeResp(lines)
            raise out
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        got = list(Provider._post_sse("http://x", {}, {"m": 1}, _sleep=sleeps.append))
        return got, sleeps, calls["n"]
    def test_success_passthrough_skips_done(self, monkeypatch):
        got, sleeps, n = self._run(monkeypatch, ["ok"])
        assert got == ['{"a":1}'] and sleeps == [] and n == 1
    def test_retries_on_429_then_succeeds(self, monkeypatch):
        got, sleeps, n = self._run(monkeypatch, [_http_error(429), _http_error(429), "ok"])
        assert got == ['{"a":1}'] and n == 3
        assert sleeps == [1.0, 2.0]          # 指数退避
    def test_retries_on_503_and_urlerror(self, monkeypatch):
        got, _, n = self._run(monkeypatch,
                              [urllib.error.URLError("net down"), _http_error(503), "ok"])
        assert got == ['{"a":1}'] and n == 3
    def test_400_no_retry_and_body_in_message(self, monkeypatch):
        with pytest.raises(RuntimeError) as ei:
            self._run(monkeypatch, [_http_error(400)])
        assert "不重试" in str(ei.value) and "boom" in str(ei.value)
        assert "400" in str(ei.value)
    def test_persistent_failure_raises_after_max_attempts(self, monkeypatch):
        errs = [urllib.error.URLError("down")] * 5
        with pytest.raises(RuntimeError) as ei:
            self._run(monkeypatch, errs)
        assert "3/3" in str(ei.value)
    def test_mid_stream_failure_not_retried(self, monkeypatch):
        calls = {"n": 0}
        def fake_urlopen(req, timeout=0):
            calls["n"] += 1
            return _FakeResp([b'data: {"a":1}\n', b'data: {"b":2}\n'], explode_after=1)
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        gen = Provider._post_sse("http://x", {}, {}, _sleep=lambda s: None)
        with pytest.raises(OSError):
            list(gen)
        assert calls["n"] == 1               # 流开始后不重试
