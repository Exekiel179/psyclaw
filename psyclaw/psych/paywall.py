"""付费墙文献 → 唤起浏览器走机构登录取全文(feat-189)。

此前的死路:`fetch_and_save` 遇到付费墙只返回一句「配置机构权限 / 用 Zotero」,
不做任何事。用户看到的就是「❌ 付费墙 ——」,然后没有下一步。

但用户**本人往往是有权限的**(在校/VPN/机构账号),缺的只是「让他在真实浏览器
里登一下」这一步。真实浏览器带着他的 SSO 会话,出版社认的是那个会话——这条路
合法、可靠,且不绕过任何付费墙:**是用户自己的权限,psyclaw 只负责把他送到门口**。

入口优先级(越靠前越可能直接出全文):
1. LibKey  —— 机构配了就直接给到 PDF/全文页,一步到位;
2. EZProxy —— 把出版社链接包一层机构代理,登录后即为校内身份;
3. doi.org —— 兜底:落地到出版社页面,用户自己点机构登录。

psyclaw 不碰用户的账号密码:只打开 URL,登录全程在浏览器里由用户自己完成。
"""

from __future__ import annotations

from pathlib import Path


def resolve_entry(doi: str, landing_url: str | None = None) -> dict:
    """给出该 DOI 的最佳机构入口 → ``{url, channel, note}``。

    纯函数(除读机构配置外无副作用),不打开任何东西,便于单测与预演。
    """
    doi = (doi or "").strip()
    if not doi and not landing_url:
        return {"url": "", "channel": "none", "note": "需要 DOI 或落地页 URL"}

    try:
        from psyclaw.psych import institution
    except Exception:  # noqa: BLE001
        institution = None  # type: ignore

    if institution is not None and doi:
        try:                                   # ① LibKey:配了就最省事
            lk = institution.libkey_fulltext(doi)
            if lk and lk.get("url"):
                return {"url": lk["url"], "channel": "LibKey(机构直达全文)",
                        "note": "机构 LibKey 已解析到全文入口。"}
        except Exception:  # noqa: BLE001
            pass

    target = landing_url or (f"https://doi.org/{doi}" if doi else "")
    if institution is not None and target:
        try:                                   # ② EZProxy:包一层代理 = 校内身份
            ez = institution.ezproxy_url(target)
            if ez:
                return {"url": ez, "channel": "EZProxy(机构代理)",
                        "note": "将跳转到你所在机构的登录页,登录后即以校内身份访问。"}
        except Exception:  # noqa: BLE001
            pass

    return {"url": target, "channel": "出版社页面(doi.org)",
            "note": ("未配置机构权限(psyclaw auth --set 可配 EZProxy/LibKey)。"
                     "将打开出版社页面,你可在页面上选择所在机构登录。")}


def _pdf_dir(project_dir: str = ".") -> Path:
    return Path(project_dir) / "outputs" / "pdfs"


def browser_handoff(doi: str, landing_url: str | None = None,
                    project_dir: str = ".", opener=None) -> dict:
    """打开机构入口,把「登录并取全文」交给用户在真实浏览器里完成。

    返回 ``{ok, url, channel, note, pdf_dir}``。opener 可注入以便测试(不真开浏览器)。
    """
    entry = resolve_entry(doi, landing_url)
    if not entry["url"]:
        return {"ok": False, "url": "", "channel": entry["channel"],
                "note": entry["note"], "pdf_dir": str(_pdf_dir(project_dir))}

    if opener is None:
        try:
            from psyclaw import webbridge
            opener = webbridge.open_in_default_browser
        except Exception:  # noqa: BLE001
            opener = None
    ok = bool(opener(entry["url"])) if opener else False

    out = _pdf_dir(project_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)   # 先建好,用户另存时目录已在
    except Exception:  # noqa: BLE001
        pass
    return {"ok": ok, "url": entry["url"], "channel": entry["channel"],
            "note": entry["note"], "pdf_dir": str(out)}


def handoff_message(res: dict, doi: str) -> str:
    """给用户看的引导文案——每一步都说清楚,别让他猜下一步做什么。"""
    lines = []
    if res.get("ok"):
        lines.append(f"已在你的浏览器打开 · {res['channel']}")
    else:
        lines.append(f"请手动打开 · {res['channel']}")
    lines.append(f"  {res['url']}")
    if res.get("note"):
        lines.append(f"  {res['note']}")
    lines += [
        "",
        "接下来(全程在你自己的浏览器里,psyclaw 不碰你的账号):",
        "  1. 若提示登录,选择你所在机构并用机构账号登录;",
        f"  2. 找到 PDF,另存到:{res.get('pdf_dir')}",
        "  3. 存好后告诉我文件名,我用 read_file 读它继续处理"
        f"(DOI:{doi or '—'})。",
    ]
    return "\n".join(lines)
