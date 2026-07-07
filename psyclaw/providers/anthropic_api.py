"""Anthropic Messages API provider(官方或兼容中转,stdlib only)。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

from psyclaw.providers.base import Provider

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider(Provider):
    name = "anthropic"

    def default_base_url(self) -> str:
        return os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    def resolve_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    def chat(self, messages: list, system: str = "") -> Iterator[str]:
        model = self.model if self.model != "default" else DEFAULT_MODEL
        try:
            max_tokens = int(os.environ.get("PSYCLAW_MAX_TOKENS", "8192"))
        except ValueError:
            max_tokens = 8192
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{self.base_url}/v1/messages"
        self.last_stop_reason = ""
        for data in self._post_sse(url, headers, payload):
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
            elif ev.get("type") == "message_delta":
                # 捕获停止原因:max_tokens=输出被截断(toolloop 据此续写而非误判答完)
                reason = (ev.get("delta") or {}).get("stop_reason")
                if reason:
                    self.last_stop_reason = str(reason)
