"""Provider 抽象基类(stdlib only)。"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator


class Provider:
    """LLM provider 接口。

    chat() 接收 messages([{role, content}])与 system 提示,
    返回文本块迭代器(流式);非流式实现可一次性 yield。
    """

    name = "base"

    def __init__(self, model: str = "default", base_url: str = "") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else self.default_base_url()
        self.api_key = self.resolve_api_key()
        # 最近一次 chat 的停止原因(归一化:"max_tokens"=被截断)。
        # toolloop 据此区分「真答完」与「输出被砍」——后者若含未闭合 tool 块须续写而非停。
        self.last_stop_reason: str = ""

    # 子类覆盖 ------------------------------------------------------------
    def default_base_url(self) -> str:
        return ""

    def resolve_api_key(self) -> str:
        return ""

    def chat(self, messages: list, system: str = "") -> Iterator[str]:
        raise NotImplementedError

    # 公共工具 ------------------------------------------------------------
    @staticmethod
    def _post_sse(url: str, headers: dict, payload: dict) -> Iterator[str]:
        """POST JSON 并逐行产出 SSE `data:` 载荷(原始 JSON 字符串)。"""
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data and data != "[DONE]":
                    yield data

    def describe(self) -> str:
        key = "已配置" if self.api_key else "无"
        return f"{self.name} · model={self.model} · base_url={self.base_url or '(默认)'} · key={key}"
