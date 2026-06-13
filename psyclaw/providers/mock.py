"""Mock provider — 离线回显,保证无 key 也能完整体验 REPL 链路。"""

from __future__ import annotations

from collections.abc import Iterator

from psyclaw.providers.base import Provider


class MockProvider(Provider):
    name = "mock"

    def chat(self, messages: list, system: str = "") -> Iterator[str]:
        last = messages[-1]["content"] if messages else ""
        preview = last if len(last) <= 120 else last[:120] + "…"
        sys_note = "(已注入 PSYCLAW 规范)" if "PSYCLAW" in system else ""
        reply = (
            f"[mock provider] 收到 {len(messages)} 条消息{sys_note}。\n"
            f"最后一条:{preview}\n"
            f"配置真实 provider 后此处为 LLM 流式回复:`psyclaw config` "
            f"或设置 ANTHROPIC_API_KEY / OPENAI_API_KEY。"
        )
        # 协议遵从:任务要求输出 VERDICT 裁决时,mock 按要求给出
        # (真实 provider 不照做会被 loop 按 BLOCK 处理,fail-closed)。
        if "VERDICT" in last:
            reply += "\n\nVERDICT: PASS"
        # 模拟流式
        for ch in reply:
            yield ch
