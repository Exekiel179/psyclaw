"""微信 iLink 通道 — Hermes/OpenClaw 同款接法(stdlib only)。

微信 iLink 网关(ilinkai.weixin.qq.com)是 Hermes Agent 与 OpenClaw
原生使用的个人微信 Bot 通道。本模块按同一协议实现 PsyClaw 网关:

  长轮询 ilink/bot/getupdates(带 get_updates_buf 游标)
  → 解析 item_list(文本 + 语音转写)
  → 走当前 provider 生成回复(期间维持"对方正在输入")
  → ilink/bot/sendmessage 回发

两种部署形态:
  A. 独占模式  ILINK_BASE_URL=https://ilinkai.weixin.qq.com
     PsyClaw 是唯一轮询者(同账号不能再跑 Hermes/OpenClaw 网关)
  B. 共存模式  ILINK_BASE_URL=http://127.0.0.1:19999(HermesClaw 代理端口)
     挂在 HermesClaw 后面,与 Hermes/OpenClaw 同账号双开/三开
     (HermesClaw 成为唯一轮询者,见 AaronWong1999/hermesclaw)

token 获取:与 hermesclaw 安装器一致——从已登录的 openclaw-weixin /
hermes gateway 账号文件提取 ILINK_TOKEN;或用 get_bot_qrcode 扫码登录。
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.request

ILINK_VER = "2.1.7"      # channel_version
ILINK_CV = "65547"       # iLink-App-ClientVersion
POLL_SEC = 35
T_TEXT, T_IMG, T_VOICE, T_VIDEO, T_FILE = 1, 2, 3, 4, 5
MAX_FAILS, BACKOFF = 3, 30


def _hdrs(tok: str) -> dict:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "iLink-App-Id": "",
        "iLink-App-ClientVersion": ILINK_CV,
        "Authorization": "Bearer " + tok if tok else "",
    }


def _post(base_url: str, ep: str, body: dict, tok: str, timeout: int = 30) -> dict:
    url = base_url.rstrip("/") + "/" + ep.lstrip("/")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_hdrs(tok), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# iLink 原语
# ---------------------------------------------------------------------------

def get_updates(base_url: str, tok: str, buf: str = "") -> dict:
    try:
        return _post(base_url, "ilink/bot/getupdates",
                     {"get_updates_buf": buf,
                      "base_info": {"channel_version": ILINK_VER}},
                     tok, timeout=POLL_SEC + 5)
    except Exception as exc:  # noqa: BLE001 — 超时属正常长轮询行为
        if "timed out" in str(exc).lower():
            return {"ret": 0, "msgs": [], "get_updates_buf": buf}
        return {"ret": -1, "msgs": [], "get_updates_buf": buf, "_err": str(exc)}


def send_text(base_url: str, tok: str, to_user: str, text: str,
              ctx: str | None = None) -> dict:
    msg = {
        "from_user_id": "",
        "to_user_id": to_user,
        "client_id": "pc-" + secrets.token_hex(8),
        "message_type": 2,
        "message_state": 2,
        "item_list": [{"type": T_TEXT, "text_item": {"text": text}}],
    }
    if ctx:
        msg["context_token"] = ctx
    return _post(base_url, "ilink/bot/sendmessage",
                 {"msg": msg, "base_info": {"channel_version": ILINK_VER}}, tok)


def _typing_keepalive(base_url: str, tok: str, to_user: str,
                      ctx: str | None, stop: threading.Event) -> None:
    """维持"对方正在输入…"直到回复发出。"""
    ticket = ""
    try:
        body = {"ilink_user_id": to_user,
                "base_info": {"channel_version": ILINK_VER}}
        if ctx:
            body["context_token"] = ctx
        ticket = _post(base_url, "ilink/bot/getconfig", body, tok,
                       timeout=10).get("typing_ticket", "")
        if not ticket:
            return
        while not stop.is_set():
            _post(base_url, "ilink/bot/sendtyping",
                  {"ilink_user_id": to_user, "typing_ticket": ticket,
                   "status": 1, "base_info": {"channel_version": ILINK_VER}},
                  tok, timeout=10)
            stop.wait(5)
    except Exception:  # noqa: BLE001
        pass
    finally:
        if ticket:
            try:
                _post(base_url, "ilink/bot/sendtyping",
                      {"ilink_user_id": to_user, "typing_ticket": ticket,
                       "status": 2, "base_info": {"channel_version": ILINK_VER}},
                      tok, timeout=10)
            except Exception:  # noqa: BLE001
                pass


def extract_text(items: list) -> str:
    """文本条目 + 语音转写(iLink 自带转写,与 hermesclaw 同策略)。"""
    parts = []
    for it in items:
        tp = it.get("type", 0)
        if tp == T_TEXT:
            x = it.get("text_item", {}).get("text", "")
            if x:
                parts.append(x)
        elif tp == T_VOICE:
            x = it.get("voice_item", {}).get("text", "")
            if x:
                parts.append(f"[语音转写] {x}")
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# 服务主循环
# ---------------------------------------------------------------------------

def serve_wechat() -> int:
    import os
    from psyclaw import config as cfg, ui
    from psyclaw.providers import get_provider

    cfg.load_env_file()
    token = os.environ.get("ILINK_TOKEN", "")
    base_url = os.environ.get("ILINK_BASE_URL", "https://ilinkai.weixin.qq.com")
    if not token:
        print("缺少 ILINK_TOKEN。两种获取方式:")
        print("  1. 已装 openclaw-weixin / hermes gateway:从其账号文件提取 token")
        print("     (hermesclaw 安装器同款做法)")
        print("  2. 扫码登录:psyclaw serve wechat --login")
        print("共存模式(同账号双开 Hermes/OpenClaw):先装 HermesClaw,")
        print("  再把 ILINK_BASE_URL 指到其代理端口(如 http://127.0.0.1:19999)。")
        return 1

    conf = cfg.load_config()
    provider = get_provider(conf)
    from psyclaw.repl import _build_system_prompt
    system = _build_system_prompt()
    sessions: dict = {}
    allowed = os.environ.get("ILINK_ALLOWED_USER", "")  # 可选白名单

    mode = "共存(经代理)" if "127.0.0.1" in base_url or "localhost" in base_url else "独占(直连 iLink)"
    print(ui.panel("PsyClaw 微信通道(iLink)",
                   f"网关: {base_url}\n模式: {mode}\n"
                   f"provider: {provider.describe()}\n"
                   f"白名单: {allowed or '(任何私聊可对话)'}\nCtrl+C 停止"))

    buf, fails = "", 0
    while True:
        resp = get_updates(base_url, token, buf)
        if resp.get("ret") not in (0, None):
            fails += 1
            print(ui.warn(f"  getupdates 异常({resp.get('_err', resp.get('ret'))}),"
                          f"{BACKOFF if fails >= MAX_FAILS else 2}s 后重试"))
            time.sleep(BACKOFF if fails >= MAX_FAILS else 2)
            if fails >= MAX_FAILS:
                fails = 0
            continue
        fails = 0
        if resp.get("get_updates_buf"):
            buf = resp["get_updates_buf"]
        if not resp.get("msgs"):
            time.sleep(0.5)   # 空轮询节流(真实 iLink 服务端长轮询,这里几乎不触发)
            continue

        for m in resp.get("msgs", []):
            if m.get("message_type", 1) != 1:     # 只处理用户来信
                continue
            uid = m.get("from_user_id", "")
            ctx = m.get("context_token", "")
            text = extract_text(m.get("item_list", []))
            if not uid or not text:
                continue
            if allowed and uid != allowed:
                continue
            print(f"  [{uid[:14]}…] {text[:50]}")

            if text.strip() == "/clear":
                sessions.pop(uid, None)
                send_text(base_url, token, uid, "上下文已清空。", ctx)
                continue
            if text.strip() in ("/whoami", "/start"):
                send_text(base_url, token, uid,
                          f"PsyClaw 心理学研究助手(iLink 通道)\n"
                          f"provider: {provider.name}\n你的 user_id: {uid}\n"
                          f"/clear 清空上下文", ctx)
                continue

            history = sessions.setdefault(uid, [])
            history.append({"role": "user", "content": text})
            stop = threading.Event()
            threading.Thread(target=_typing_keepalive,
                             args=(base_url, token, uid, ctx, stop),
                             daemon=True).start()
            try:
                reply = "".join(provider.chat(history[-20:], system=system))
            except Exception as exc:  # noqa: BLE001
                reply = f"[provider 错误] {exc}"
            finally:
                stop.set()
            history.append({"role": "assistant", "content": reply})
            try:
                send_text(base_url, token, uid, reply or "(空回复)", ctx)
            except Exception as exc:  # noqa: BLE001
                print(ui.err(f"  发送失败:{exc}"))


def login_qrcode() -> int:
    """扫码登录尝试(get_bot_qrcode / get_qrcode_status)。"""
    import os
    base_url = os.environ.get("ILINK_BASE_URL", "https://ilinkai.weixin.qq.com")
    try:
        r = _post(base_url, "ilink/bot/get_bot_qrcode",
                  {"base_info": {"channel_version": ILINK_VER}}, tok="")
        print("get_bot_qrcode 响应(用微信扫码,然后轮询 get_qrcode_status):")
        print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"扫码登录接口不可达:{exc}")
        print("推荐路径:用 openclaw-weixin(clawbot)完成扫码登录,"
              "再从其 accounts/*.json 提取 token 设为 ILINK_TOKEN。")
        return 1
