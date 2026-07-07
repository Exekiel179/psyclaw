"""Provider 抽象基类(stdlib only)。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

# v0.4 feat-036:网络层重试参数。仅对可恢复错误(429/5xx/网络异常)重试,
# 且仅在首字节产出前——流已开始后中断不重试(避免重复消费已产出内容)。
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0   # 秒;第 n 次失败后 sleep BASE * 2^(n-1)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})


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
    def _http_error_detail(exc: "urllib.error.HTTPError") -> str:
        """读 HTTP 错误响应 body(API 的 error JSON 在这里),拼可定位的错误消息。"""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {exc.code} {exc.reason}" + (f" — {body}" if body.strip() else "")

    @staticmethod
    def _post_sse(url: str, headers: dict, payload: dict,
                  _sleep=time.sleep) -> Iterator[str]:
        """POST JSON 并逐行产出 SSE `data:` 载荷(原始 JSON 字符串)。

        v0.4 feat-036 网络健壮性:429/5xx/网络异常在**首字节前**指数退避重试(≤3 次)——
        网络瞬断/限流不再直接杀死整个 agent 长任务;流已开始后中断不重试(防重复消费)。
        4xx(非 429)不重试,带响应 body 显性报错(RuntimeError),调用方能看到 API 错误详情。
        """
        req_bytes = json.dumps(payload).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            req = urllib.request.Request(
                url, data=req_bytes,
                headers={"Content-Type": "application/json", **headers},
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=300)
            except urllib.error.HTTPError as exc:
                detail = Provider._http_error_detail(exc)
                if exc.code not in _RETRYABLE_STATUS:
                    raise RuntimeError(f"provider 请求失败(不重试):{detail}") from exc
                last_err = RuntimeError(
                    f"provider 请求失败(重试 {attempt}/{_MAX_ATTEMPTS}):{detail}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_err = RuntimeError(
                    f"provider 网络异常(重试 {attempt}/{_MAX_ATTEMPTS}):{exc}")
            else:
                with resp:
                    for raw in resp:   # 流开始后异常不再重试,向上传播
                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data and data != "[DONE]":
                            yield data
                return
            if attempt < _MAX_ATTEMPTS:
                _sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
        raise last_err if last_err else RuntimeError("provider 请求失败:未知错误")

    def describe(self) -> str:
        key = "已配置" if self.api_key else "无"
        return f"{self.name} · model={self.model} · base_url={self.base_url or '(默认)'} · key={key}"
