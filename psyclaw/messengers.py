"""消息端接入(stdlib only)。

Telegram — 完整双向:
  `psyclaw serve telegram` 长轮询 Bot,任何人在 TG 给 bot 发消息即对话
  (走当前配置的 provider,注入 PSYCLAW 规范)。需 TELEGRAM_BOT_TOKEN
  (找 @BotFather 创建)。HITL 场景:research-loop 的审批提醒会推到 TG,
  回复"批准"即放行。

微信 — 务实方案:
  个人微信没有官方 API(逆向方案随时被封,不做)。支持两条正路:
  1. 企业微信群机器人 webhook(WECOM_WEBHOOK_URL):单向推送通知,
     用于 HITL 审批提醒、跑批完成播报。`psyclaw notify "消息"`。
  2. Telegram 同款双向体验请用 TG;或企业微信自建应用(需公网回调,留 M4)。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

TG_API = "https://api.telegram.org/bot{token}/{method}"
TG_LIMIT = 4000  # 单条消息上限 4096,留余量


def _http_json(url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# 企业微信 webhook(单向通知)
# ---------------------------------------------------------------------------

def send_wecom(text: str, webhook_url: str) -> bool:
    try:
        r = _http_json(webhook_url, {"msgtype": "text", "text": {"content": text[:2000]}})
        return r.get("errcode") == 0
    except Exception as exc:  # noqa: BLE001
        print(f"[wecom] 发送失败:{exc}")
        return False


def notify_cli(message: str) -> int:
    """psyclaw notify — 推送到所有已配置的通知渠道。"""
    import os
    sent = False
    wecom = os.environ.get("WECOM_WEBHOOK_URL", "")
    if wecom:
        ok = send_wecom(message, wecom)
        print(("✓ 企业微信已送达" if ok else "✗ 企业微信失败"))
        sent = sent or ok
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        ok = _tg_send(token, chat_id, message)
        print(("✓ Telegram 已送达" if ok else "✗ Telegram 失败"))
        sent = sent or ok
    if not sent:
        print("未配置通知渠道。设置 WECOM_WEBHOOK_URL 或 "
              "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID(psyclaw config)。")
        return 1
    return 0


# ---------------------------------------------------------------------------
# Telegram 双向 bot
# ---------------------------------------------------------------------------

def _tg_send(token: str, chat_id, text: str) -> bool:
    try:
        for i in range(0, max(len(text), 1), TG_LIMIT):
            _http_json(TG_API.format(token=token, method="sendMessage"),
                       {"chat_id": chat_id, "text": text[i:i + TG_LIMIT]})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] 发送失败:{exc}")
        return False


def serve_telegram() -> int:
    import os
    from psyclaw import config as cfg, ui
    from psyclaw.providers import get_provider

    cfg.load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("缺少 TELEGRAM_BOT_TOKEN(@BotFather 创建后 psyclaw config 配置)。")
        return 1

    conf = cfg.load_config()
    provider = get_provider(conf)
    from psyclaw.repl import _build_system_prompt
    system = _build_system_prompt()
    sessions: dict = {}   # chat_id -> messages
    allowed = os.environ.get("TELEGRAM_CHAT_ID", "")  # 可选白名单

    print(ui.panel("PsyClaw Telegram Bot",
                   f"provider: {provider.describe()}\n"
                   f"白名单: {allowed or '(任何人可对话——建议设置 TELEGRAM_CHAT_ID)'}\n"
                   "Ctrl+C 停止"))
    offset = 0
    while True:
        try:
            r = _http_json(TG_API.format(token=token, method="getUpdates")
                           + f"?timeout=50&offset={offset}", timeout=70)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] 轮询异常,5s 后重试:{exc}")
            time.sleep(5)
            continue
        for upd in r.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if not chat_id or not text:
                continue
            if allowed and chat_id != allowed:
                _tg_send(token, chat_id, "未授权。请联系所有者把你的 chat_id 加入白名单。")
                continue
            print(f"  [{chat_id}] {text[:60]}")
            if text == "/start":
                _tg_send(token, chat_id,
                         "PsyClaw 心理学研究助手已连接。直接提问即可;"
                         "/clear 清空上下文;你的 chat_id 是 " + chat_id)
                continue
            if text == "/clear":
                sessions.pop(chat_id, None)
                _tg_send(token, chat_id, "上下文已清空。")
                continue
            history = sessions.setdefault(chat_id, [])
            history.append({"role": "user", "content": text})
            try:
                reply = "".join(provider.chat(history[-20:], system=system))
            except Exception as exc:  # noqa: BLE001
                reply = f"[provider 错误] {exc}"
            history.append({"role": "assistant", "content": reply})
            _tg_send(token, chat_id, reply or "(空回复)")
