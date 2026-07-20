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


def downloads_dir() -> Path:
    """系统下载目录(尊重 XDG 配置,回退 ~/Downloads)。"""
    import os
    xdg = os.environ.get("XDG_DOWNLOAD_DIR")
    if xdg:
        return Path(xdg).expanduser()
    return Path.home() / "Downloads"


def _looks_like_pdf(p: Path) -> bool:
    """靠魔数认 PDF——扩展名会骗人(登录页/错误页也可能存成 .pdf)。"""
    try:
        with p.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def _safe_name(hint: str, doi: str) -> str:
    import re
    base = re.sub(r"[^\w一-鿿.-]+", "-", (hint or "").strip())[:80].strip("-")
    if not base:
        base = "paper-" + re.sub(r"[^\w.-]+", "-", doi or "unknown")[:60]
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def capture_from_downloads(doi: str = "", out_dir: str | Path = "outputs/pdfs",
                           name_hint: str = "", timeout: float = 180.0,
                           poll: float = 2.0, src_dir: Path | None = None,
                           sleeper=None, clock=None) -> dict:
    """盯住系统下载目录,把用户刚下好的 PDF 收进项目并改好名。

    为什么这样做:登录后的会话在**浏览器**里,Python 侧拿不到那个 cookie,所以
    不可能代替用户直接下载。但用户点一下「下载」是最自然的动作——真正多余的是
    让他记住「另存到 outputs/pdfs/、还得起对文件名」。这里把那份麻烦接过来。

    只认**新出现**的文件(先拍快照),且必须过 %PDF 魔数——出版社的登录页/错误页
    常被存成 .pdf,靠扩展名会把垃圾收进来。等 .crdownload/.part 消失才算下完。
    """
    import time
    sleeper = sleeper or time.sleep
    clock = clock or time.monotonic
    src = Path(src_dir) if src_dir else downloads_dir()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not src.is_dir():
        return {"ok": False, "note": f"找不到下载目录 {src};下好后告诉我路径也行。"}

    before = {p.name for p in src.glob("*") if p.is_file()}
    deadline = clock() + timeout
    while clock() < deadline:
        pending = any(p.suffix in (".crdownload", ".part", ".download")
                      for p in src.glob("*") if p.name not in before)
        if not pending:
            fresh = [p for p in src.glob("*.pdf")
                     if p.is_file() and p.name not in before]
            fresh.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for cand in fresh:
                if not _looks_like_pdf(cand):
                    return {"ok": False, "note":
                            f"{cand.name} 不是 PDF(可能存成了登录页/错误页),已跳过;"
                            "请确认在页面上点的是 Download PDF。"}
                target = out / _safe_name(name_hint or cand.stem, doi)
                if target.exists():
                    target = target.with_name(target.stem + "-1" + target.suffix)
                try:
                    import shutil
                    shutil.move(str(cand), str(target))
                except OSError as exc:
                    return {"ok": False, "note": f"移动失败:{exc}(文件仍在 {cand})"}
                kb = max(1, target.stat().st_size // 1024)
                return {"ok": True, "path": str(target), "kb": kb,
                        "note": f"已收下 {target.name}({kb}KB)→ {out}"}
        sleeper(poll)
    return {"ok": False, "timeout": True,
            "note": (f"等了 {int(timeout)} 秒没等到新的 PDF。若已下到别处,"
                     "把文件路径告诉我即可;或重试一次。")}


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
        "  2. 点页面上的 Download PDF——**直接下到你平时的下载目录就行**,"
        "不用另存到别处、也不用改名;",
        f"  3. 然后调 lit_capture_pdf(doi=\"{doi or ''}\") 我来收:"
        "会自动把刚下好的 PDF 收进项目并按 作者_年份_题名 改好名。",
    ]
    return "\n".join(lines)
