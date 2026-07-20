"""用 WebBridge 驱动**用户已登录的真实浏览器**直接抓取付费墙全文 PDF(feat-191)。

与 `paywall.capture_from_downloads` 的分工:
- 那条路要用户自己点一下「Download PDF」(零额外安装,永远可用);
- 这条路装了 WebBridge 扩展后**连点都不用**:在用户浏览器里 fetch,
  带着他登录后的 Cookie/会话,拿到字节流直接落盘。

为什么必须在浏览器里 fetch:机构登录后的会话在浏览器进程内,Python 侧拿不到那个
Cookie。所以不是"psyclaw 去下载",而是"让用户自己的浏览器去下载,再把字节交出来"
——用的仍是用户本人的权限,不绕过任何付费墙。

字节流分块回传:一篇 PDF 动辄几 MB,base64 后更大;单次响应会被截断(工具层还有
6000 字符上限)。故先把字节存在页面的 window 变量里,再按 `_CHUNK` 分片取回。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

_CHUNK = 180_000            # 每片原始字节数(base64 后约 240KB,单次响应稳)
_MAX_BYTES = 80 * 1024 * 1024

# 找 PDF 链接:citation_pdf_url 是学术出版社的事实标准,拿不到再退回找链接。
_JS_FIND = """
(() => {
  const m = document.querySelector('meta[name="citation_pdf_url"]');
  if (m && m.content) return m.content;
  const as = Array.from(document.querySelectorAll('a'));
  const hit = as.find(a => /\\.pdf($|\\?)/i.test(a.href || '')) ||
              as.find(a => /download\\s*pdf|view\\s*pdf|full\\s*text\\s*pdf/i
                            .test((a.textContent || '').trim()));
  return hit ? hit.href : '';
})()
"""

_JS_FETCH = """
(async () => {
  const r = await fetch(%s, {credentials: 'include'});
  const buf = new Uint8Array(await r.arrayBuffer());
  window.__psyclaw_pdf = buf;
  return JSON.stringify({ok: r.ok, status: r.status, len: buf.length,
                         type: r.headers.get('content-type') || ''});
})()
"""

_JS_SLICE = """
(() => {
  const b = window.__psyclaw_pdf.subarray(%d, %d);
  let s = '';
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s);
})()
"""


def _result(resp: dict):
    """从守护进程回执里取出 evaluate 的返回值(容忍几种常见外层包装)。"""
    if not isinstance(resp, dict):
        return None
    if resp.get("success") is False:
        return None
    for key in ("result", "value", "data", "output"):
        if key in resp:
            v = resp[key]
            if isinstance(v, dict) and "result" in v:
                return v["result"]
            return v
    return None


def bridge_ready(status_fn=None, bin_fn=None) -> dict:
    """桥是否可用 → ``{ok, note}``。不可用时给出**具体**下一步,而非一句"不可用"。"""
    try:
        from psyclaw import webbridge
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "note": f"webbridge 模块不可用:{exc}"}
    bin_fn = bin_fn or webbridge.binary_installed
    status_fn = status_fn or webbridge.daemon_status
    if not bin_fn():
        return {"ok": False,
                "note": "未装 WebBridge:先跑 `psyclaw webbridge install`(装完再试)。"}
    st = status_fn()
    if not st:
        return {"ok": False,
                "note": "WebBridge 守护进程没在跑:`psyclaw webbridge start` 启动它。"}
    if not st.get("extension_connected"):
        return {"ok": False,
                "note": ("守护进程在跑,但浏览器扩展没连上:"
                         "`psyclaw webbridge install` 会打开扩展安装页,"
                         "在浏览器里点「添加」后即连上。")}
    return {"ok": True, "note": "WebBridge 就绪(扩展已连接)。"}


def fetch_pdf_via_browser(page_url: str, out_path: str | Path,
                          caller=None, pdf_url: str = "") -> dict:
    """在用户已登录的浏览器里抓取 PDF 并落盘 → ``{ok, path, bytes, note}``。

    caller(action, args) 可注入以便离线测试。
    """
    if caller is None:
        from psyclaw import webbridge
        caller = webbridge.call
    out = Path(out_path)

    if not pdf_url:
        caller("navigate", {"url": page_url, "newTab": True})
        found = _result(caller("evaluate", {"code": _JS_FIND}))
        pdf_url = (found or "").strip() if isinstance(found, str) else ""
        if not pdf_url:
            return {"ok": False, "path": "", "bytes": 0,
                    "note": ("页面上没找到 PDF 链接——可能尚未登录、或该刊把全文放在"
                             "另一个入口。请在浏览器里确认已能看到全文,再重试;"
                             "或手动点下载后用 lit_capture_pdf 收。")}

    meta_raw = _result(caller("evaluate", {"code": _JS_FETCH % json.dumps(pdf_url)}))
    try:
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
    except json.JSONDecodeError:
        meta = {}
    if not meta.get("ok"):
        return {"ok": False, "path": "", "bytes": 0,
                "note": f"浏览器取 PDF 失败(HTTP {meta.get('status', '?')});"
                        "多半是没登录或无该刊权限。"}
    total = int(meta.get("len") or 0)
    if total <= 0:
        return {"ok": False, "path": "", "bytes": 0, "note": "取回 0 字节,未落盘。"}
    if total > _MAX_BYTES:
        return {"ok": False, "path": "", "bytes": 0,
                "note": f"文件过大({total // 1048576}MB),拒绝经桥传输;请手动下载。"}

    buf = bytearray()
    for start in range(0, total, _CHUNK):
        piece = _result(caller("evaluate",
                               {"code": _JS_SLICE % (start, min(start + _CHUNK, total))}))
        if not isinstance(piece, str) or not piece:
            return {"ok": False, "path": "", "bytes": 0,
                    "note": f"分片传输中断(已取 {len(buf)}/{total} 字节),未落盘。"}
        try:
            buf.extend(base64.b64decode(piece))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "path": "", "bytes": 0, "note": f"分片解码失败:{exc}"}

    if bytes(buf[:5]) != b"%PDF-":
        # 出版社常把登录页/拦截页当 200 返回——落盘前用魔数拦住,别把 HTML 存成 PDF
        return {"ok": False, "path": "", "bytes": 0,
                "note": ("取回的不是 PDF(多半是登录页/拦截页)。请在浏览器里确认"
                         "已用机构账号登录且能看到全文,再重试。")}
    if len(buf) != total:
        return {"ok": False, "path": "", "bytes": 0,
                "note": f"字节数不符(收到 {len(buf)},应为 {total}),未落盘。"}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(buf))
    kb = max(1, len(buf) // 1024)
    return {"ok": True, "path": str(out), "bytes": len(buf),
            "note": f"已通过浏览器抓取 {out.name}({kb}KB)→ {out.parent}"}
