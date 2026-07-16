"""OpenAI Chat Completions 兼容 provider(stdlib only)。

覆盖:OpenAI 官方、DeepSeek、通义千问(DashScope)、智谱 GLM、Kimi、
Ollama/LM Studio 本地模型、各类中转站。

路径适配:base_url 以版本段结尾(如智谱 /api/paas/v4)→ 直接拼 /chat/completions;
否则按惯例拼 /v1/chat/completions。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator

from psyclaw.providers.base import Provider


class OpenAICompatProvider(Provider):
    name = "openai-compat"

    def __init__(self, model: str = "default", base_url: str = "",
                 key_env: str | None = "OPENAI_API_KEY",
                 display: str = "") -> None:
        self._key_env = key_env
        if display:
            self.name = display
        super().__init__(model=model, base_url=base_url)

    def default_base_url(self) -> str:
        return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")

    def resolve_api_key(self) -> str:
        if self._key_env is None:
            return "psyclaw-local"  # 本地模型:Bearer 占位,服务端忽略
        return os.environ.get(self._key_env, "") or os.environ.get("OPENAI_API_KEY", "")

    def _endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if re.search(r"/v\d+$", base):           # 智谱 /api/paas/v4 等
            return f"{base}/chat/completions"
        if base.endswith("/chat/completions"):   # 用户直接给了完整端点
            return base
        return f"{base}/v1/chat/completions"

    def chat(self, messages: list, system: str = "") -> Iterator[str]:
        model = self.model if self.model != "default" else "gpt-4o"
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload = {"model": model, "stream": True, "messages": msgs}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        self.last_stop_reason = ""
        saw_content = False
        reasoning_buf: list[str] = []       # feat-149:content 全空时的兜底
        for data in self._post_sse(self._endpoint(), headers, payload):
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in ev.get("choices", []):
                delta = choice.get("delta", {}) or {}
                text = delta.get("content")
                if text:
                    saw_content = True
                    yield text
                else:
                    # deepseek 等把推理放 reasoning_content;正文为空时整条回复看着是空
                    rc = delta.get("reasoning_content")
                    if rc:
                        reasoning_buf.append(rc)
                # 捕获停止原因并归一化(OpenAI 系 "length"=截断 → 统一记 "max_tokens")
                reason = choice.get("finish_reason")
                if reason:
                    self.last_stop_reason = ("max_tokens" if reason == "length"
                                             else str(reason))
        if not saw_content and reasoning_buf:   # 正文全空 → 用推理内容兜底,避免空回复
            yield "".join(reasoning_buf)
