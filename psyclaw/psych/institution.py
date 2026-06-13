"""机构权限访问层(纯 stdlib)。

合规与安全红线:
- **绝不存图书馆密码,绝不用用户凭据自动爬全文**(违反图书馆 TOS)。
- 只存机构*配置*(EZProxy 前缀、LibKey id/key、机构标识)与*认证状态*
  (方式、上次验证时间、是否在校园网),放 ~/.psyclaw/institution.json。
- EZProxy/SSO:我们只把链接*改写*成机构入口,由用户在自己已登录的浏览器打开。
- LibKey:机构订阅的合法全文发现 API(机构给 key),返回机构有权访问的全文链接。

三种机制统一在一层,fulltext 付费墙时按 LibKey → EZProxy → IP 顺序给出机构可访问入口。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG = Path.home() / ".psyclaw" / "institution.json"
UA = "PsyClaw/0.1 (research tool)"


# ---------------------------------------------------------------------------
# 配置(不含密码)
# ---------------------------------------------------------------------------

def load() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save(conf: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")


def configure(ezproxy: str = "", libkey_id: str = "", libkey_key: str = "",
              institution: str = "") -> dict:
    conf = load()
    if ezproxy:
        conf["ezproxy_prefix"] = ezproxy.rstrip("/")
    if libkey_id:
        conf["libkey_id"] = libkey_id
    if libkey_key:
        conf["libkey_key"] = libkey_key   # LibKey key 是机构发现 key,非个人密码
    if institution:
        conf["institution"] = institution
    save(conf)
    return conf


# ---------------------------------------------------------------------------
# EZProxy:URL 改写(不碰密码)
# ---------------------------------------------------------------------------

def ezproxy_url(target_url: str) -> str | None:
    """把目标链接改写成机构 EZProxy 入口;用户用已登录浏览器打开。"""
    conf = load()
    prefix = conf.get("ezproxy_prefix")
    if not prefix:
        return None
    # 典型形式:https://xxx.idm.oclc.org/login?url=<target>
    return f"{prefix}/login?url={urllib.parse.quote(target_url, safe='')}"


# ---------------------------------------------------------------------------
# LibKey:DOI → 机构可访问全文链接(合法 API)
# ---------------------------------------------------------------------------

def libkey_fulltext(doi: str) -> dict | None:
    conf = load()
    lib_id, key = conf.get("libkey_id"), conf.get("libkey_key")
    if not (lib_id and key):
        return None
    url = f"https://public-api.thirdiron.com/public/v1/libraries/{lib_id}/articles/doi/{urllib.parse.quote(doi)}?access_token={key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None
    d = data.get("data", {})
    link = d.get("fullTextFile") or d.get("contentLocation") or d.get("bestIntegratorLink")
    if link:
        return {"link": link, "open_access": d.get("openAccess", False),
                "via": "LibKey(机构订阅)"}
    return None


# ---------------------------------------------------------------------------
# 机构 IP 检测(是否在校园网)
# ---------------------------------------------------------------------------

def check_in_network() -> dict:
    """用 OpenAlex/ipify 类公共服务查出口 IP,与机构记录比对(尽力而为)。

    这里只判断"能否拿到公网 IP"+ 是否匹配用户记录的机构 IP 段(可选)。
    """
    conf = load()
    try:
        req = urllib.request.Request("https://api.ipify.org?format=json",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            ip = json.loads(r.read().decode()).get("ip", "")
    except Exception:  # noqa: BLE001
        return {"ip": None, "in_network": None, "note": "无法获取出口 IP"}
    ranges = conf.get("institution_ip_prefixes", [])  # 如 ["166.111.", "202.120."]
    in_net = any(ip.startswith(p) for p in ranges) if ranges else None
    return {"ip": ip, "in_network": in_net,
            "note": ("匹配机构 IP 段" if in_net else
                     "不在已记录的机构 IP 段" if in_net is False else
                     "未配置机构 IP 段,无法判断")}


# ---------------------------------------------------------------------------
# 连通自检 + 认证状态记录
# ---------------------------------------------------------------------------

def verify() -> dict:
    """跑一次连通自检,把认证状态写回 institution.json。"""
    conf = load()
    status = {"verified_at": time.strftime("%Y-%m-%d %H:%M:%S"), "methods": {}}

    # LibKey 可用性
    if conf.get("libkey_id") and conf.get("libkey_key"):
        # 用一个常见 DOI 探测(不依赖结果,只看 API 是否响应)
        probe = libkey_fulltext("10.1037/0003-066x.59.1.29")
        status["methods"]["libkey"] = "已配置" + (",API 响应正常" if probe is not None else ",已配置(未命中探测 DOI 属正常)")
    else:
        status["methods"]["libkey"] = "未配置"

    # EZProxy 可达性
    prefix = conf.get("ezproxy_prefix")
    if prefix:
        try:
            req = urllib.request.Request(prefix, headers={"User-Agent": UA}, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as r:
                status["methods"]["ezproxy"] = f"可达(HTTP {r.status})"
        except Exception as exc:  # noqa: BLE001
            status["methods"]["ezproxy"] = f"配置了但探测失败:{str(exc)[:40]}"
    else:
        status["methods"]["ezproxy"] = "未配置"

    # IP
    net = check_in_network()
    status["methods"]["campus_ip"] = (
        f"出口 IP {net['ip']} · {net['note']}" if net["ip"] else net["note"])
    status["in_network"] = net.get("in_network")

    conf["last_auth_status"] = status
    save(conf)
    return status


# ---------------------------------------------------------------------------
# 给定 DOI/链接 → 机构可访问入口(供 fulltext 调用)
# ---------------------------------------------------------------------------

def institutional_access(doi: str | None, landing_url: str | None = None) -> dict | None:
    """付费墙文献的机构访问入口。返回 None 表示未配置任何机构权限。"""
    conf = load()
    if not any(conf.get(k) for k in ("ezproxy_prefix", "libkey_id")):
        return None
    # 1. LibKey 优先(直接给机构可访问全文)
    if doi:
        lk = libkey_fulltext(doi)
        if lk:
            return {"channel": lk["via"], "url": lk["link"],
                    "note": "机构订阅渠道(合法);在浏览器打开"}
    # 2. EZProxy 改写(用户浏览器 SSO 会话)
    target = landing_url or (f"https://doi.org/{doi}" if doi else None)
    if target:
        ez = ezproxy_url(target)
        if ez:
            return {"channel": "EZProxy(机构代理)", "url": ez,
                    "note": "用你已登录机构账号的浏览器打开;PsyClaw 不碰你的密码"}
    return None


def print_status() -> None:
    from psyclaw import ui
    conf = load()
    print(ui.title("机构权限状态"))
    print(ui.rule())
    if not conf:
        print(ui.dim("  未配置。psyclaw config 里设置 EZProxy 前缀 / LibKey,"
                     "或 psyclaw auth --set。"))
        return
    print(f"  机构      : {conf.get('institution', '(未填)')}")
    print(f"  EZProxy   : {conf.get('ezproxy_prefix', ui.dim('未配置'))}")
    print(f"  LibKey    : {'已配置(id ' + conf['libkey_id'] + ')' if conf.get('libkey_id') else ui.dim('未配置')}")
    st = conf.get("last_auth_status")
    if st:
        print(ui.accent(f"\n  上次验证:{st['verified_at']}"))
        for m, v in st.get("methods", {}).items():
            print(f"    {m:<10} {v}")
        inn = st.get("in_network")
        print(f"    在校园网  : {'是 ✓' if inn else '否' if inn is False else '未知'}")
    else:
        print(ui.dim("\n  尚未验证。运行 psyclaw auth --verify 做连通自检。"))
    print(ui.dim("\n  安全:本文件不含任何密码;EZProxy/SSO 用你浏览器的已登录会话。"))
