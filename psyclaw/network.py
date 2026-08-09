"""网络异常归一化为面向用户的短诊断。

只做字符串分类，不主动探测网络；这样离线测试不会产生真实请求，且不会把
普通工具异常误报为网络问题。
"""

from __future__ import annotations

import re


_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("请求超时，服务器没有及时响应", (
        "timed out", "timeout", "time out", "read timeout", "connect timeout",
        "winerror 10060", "响应超时", "请求超时",
    )),
    ("DNS 解析失败，找不到服务器地址", (
        "getaddrinfo failed", "name or service not known", "nodename nor servname",
        "temporary failure in name resolution", "could not resolve host",
        "no such host is known", "socket.gaierror", "dns", "域名解析失败",
    )),
    ("连接被拒绝或网络不可达", (
        "connection refused", "actively refused", "network is unreachable",
        "no route to host", "host is unreachable", "destination host unreachable",
        "connection reset", "connection aborted", "failed to establish a new connection",
        "failed to create underlying connection", "failed to connect", "couldn't connect",
        "econnrefused", "econnreset", "enetunreach", "winerror 10051", "winerror 10061",
        "无法连接", "网络不可达", "连接被拒绝",
    )),
    ("代理或网络隧道连接失败", (
        "proxyerror", "proxy error", "tunnel error", "代理错误", "隧道错误",
        "cannot connect to proxy",
    )),
    ("SSL/TLS 安全连接失败", (
        "certificate verify failed", "sslerror", "ssl error", "tls error",
        "wrong version number", "证书验证失败", "安全连接失败",
    )),
    ("外部依赖下载失败，通常与网络或代理有关", (
        "pypi.org", "pip install", "uvx", "git clone", "git pull",
        "failed to fetch", "could not fetch",
    )),
    ("网络连接失败", (
        "network down", "network dead", "network failure", "network error",
        "remote end closed connection", "remote disconnected",
        "网络连接失败", "网络异常", "网络错误",
    )),
)


def network_error_hint(error: object) -> str | None:
    """返回网络问题的简短原因；无法确认时返回 ``None``。"""
    text = str(error or "")
    lower = text.lower()
    for hint, needles in _RULES:
        if any(needle.lower() in lower for needle in needles):
            return hint
    return None


def _brief_detail(error: object) -> str:
    """从异常/traceback 中取一行短细节，避免把整段堆栈抛给用户。"""
    text = str(error or "").replace("\r", "")
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Traceback") or line.startswith("File "):
            continue
        lines.append(line)
    detail = lines[-1] if lines else text.strip().replace("\n", " ")
    detail = redact_secrets(re.sub(r"\s+", " ", detail))
    return detail[:180]


def redact_secrets(text: str) -> str:
    """脱敏错误文本中的常见凭据形态，防止诊断输出泄漏 Token。"""
    safe = re.sub(
        r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?"
        r"-----END [^-\r\n]*PRIVATE KEY-----",
        "<redacted-private-key>", text, flags=re.I | re.S,
    )
    safe = re.sub(
        r"\b(AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN))"
        r"(\s*[:=]\s*)([^\s;&,]+)",
        r"\1\2<redacted>", safe, flags=re.I,
    )
    safe = re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
                  "<redacted-aws-key-id>", safe)
    safe = re.sub(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\b",
        "<redacted-jwt>", safe,
    )
    safe = re.sub(r"\bKGAT_[A-Za-z0-9._-]+", "KGAT_<redacted>", safe,
                  flags=re.I)
    safe = re.sub(
        r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,})\b",
        "<redacted-token>", safe, flags=re.I,
    )
    safe = re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1<redacted>@", safe,
                  flags=re.I)
    safe = re.sub(
        r"([?&](?:api[_-]?key|access[_-]?token|token|key)=)[^&\s]+",
        r"\1<redacted>", safe, flags=re.I,
    )
    safe = re.sub(
        r"\b(api[_-]?key|access[_-]?token|token|authorization|bearer|password|secret)"
        r"(\s*[:=]\s*|\s+)([^\s;&,]+)",
        r"\1\2<redacted>", safe, flags=re.I,
    )
    return safe


def network_error_message(error: object) -> str | None:
    """生成统一的中文网络错误提示；普通异常返回 ``None``。"""
    hint = network_error_hint(error)
    if hint is None:
        return None
    detail = _brief_detail(error)
    suffix = f"（{detail}）" if detail and detail not in {hint, "网络连接失败"} else ""
    return (f"网络连接失败：{hint}{suffix}。"
            "建议检查网络连接、代理和防火墙，确认后重试。")
