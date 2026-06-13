"""OpenCode CLI 执行后端(支持 Go 版与 TS 版,stdlib subprocess)。

OpenCode 是本地 agent CLI(Go 原版 kujtimiihoxha/opencode 与 SST 维护版),
自带 provider/model 配置。把它作为 PsyClaw 的执行后端意味着:
- 模型与 key 由 opencode 自己管理,PsyClaw 不重复配置
- AutoResearchClaw 同款集成路径

调用约定(按可用性自动探测):
  1. `opencode run <prompt>`        (SST 版非交互)
  2. `opencode -p <prompt> -q`      (Go 原版 quiet 模式)
可在 config 里用 `opencode_args` 覆盖参数模板。
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator

from psyclaw.providers.base import Provider


class OpenCodeProvider(Provider):
    name = "opencode"

    def resolve_api_key(self) -> str:
        return "managed-by-opencode"

    def available(self) -> bool:
        return shutil.which("opencode") is not None

    @staticmethod
    def _detect_style(exe: str) -> list:
        """探测 CLI 风格:SST 版有 `run` 子命令;Go 原版用 -p。"""
        try:
            r = subprocess.run([exe, "run", "--help"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return [exe, "run"]
        except Exception:  # noqa: BLE001
            pass
        return [exe, "-q", "-p"]

    def chat(self, messages: list, system: str = "") -> Iterator[str]:
        exe = shutil.which("opencode")
        if not exe:
            yield "[opencode] CLI 不在 PATH。安装:npm i -g opencode-ai(或 Go 版二进制)。"
            return
        # 单轮提示:system + 最近用户消息(opencode 自管上下文与工具)
        last_user = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")
        prompt = (system + "\n\n---\n\n" + last_user) if system else last_user
        cmd = self._detect_style(exe) + [prompt]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace")
            assert proc.stdout is not None
            for line in proc.stdout:
                yield line
            proc.wait(timeout=600)
        except Exception as exc:  # noqa: BLE001
            yield f"\n[opencode 错误] {exc}"

    def describe(self) -> str:
        state = "已安装 ✓" if self.available() else "未安装(npm i -g opencode-ai)"
        return f"opencode(Go/TS CLI) · 模型由 opencode 配置 · {state}"
