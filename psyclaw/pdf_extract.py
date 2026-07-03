"""PDF 正文抽取(best-effort,只读不改写)。

PsyClaw 核为纯 stdlib,但研究工具要能读论文 PDF。策略三级:
① 可选库 pypdf / pdfplumber(装了效果最好,正确处理字体编码)——非硬依赖;
② 纯 stdlib 兜底:zlib 解 FlateDecode 流 + 正则抽文本操作符(覆盖多数未加密、非 CID 字体的 PDF);
③ 质量门:抽出来若不像正文(扫描件/图片型、加密、CID/Type0 字体 → 一堆乱码),**诚实**返回
   ok=False + 提示(装 pypdf 或粘贴文本/OCR),**绝不把二进制乱码塞进 LLM 上下文**(这正是此前的 bug)。
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path

_MAX_CHARS = 20000


def extract_pdf_text(path, max_chars: int = _MAX_CHARS) -> dict:
    """抽取 PDF 正文。返回 {ok, text, method, note}。抽不到 ok=False 且 note 给出原因/建议。"""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        return {"ok": False, "text": "", "method": "", "note": f"读取失败:{exc}"}
    if data[:5] != b"%PDF-":
        return {"ok": False, "text": "", "method": "",
                "note": "不是有效的 PDF(缺 %PDF- 文件头)。"}

    text, method = _via_lib(p)
    if not (text and text.strip()):
        text, method = _via_stdlib(data)

    text = _clean(text)
    if not _looks_like_text(text):
        return {"ok": False, "text": "", "method": method or "-",
                "note": ("抽不到可读正文——多半是扫描件/图片型 PDF、加密文件,或用了 CID/Type0 字体。"
                         "可 `pip install pypdf` 后重试,或直接把方法部分文本粘贴给我 / 先做 OCR。")}
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + f"\n…(已截断,原文共约 {len(text)} 字符)"
    return {"ok": True, "text": text, "method": method, "note": ""}


# ---------------------------------------------------------------------------
# ① 可选库
# ---------------------------------------------------------------------------

def _via_lib(path: Path):
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        parts = []
        for pg in reader.pages:
            try:
                parts.append(pg.extract_text() or "")
            except Exception:  # noqa: BLE001
                pass
        txt = "\n".join(parts)
        if txt.strip():
            return txt, f"pypdf·{len(reader.pages)}页"
    except Exception:  # noqa: BLE001  # 未装或解析失败 → 兜底
        pass
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            txt = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        if txt.strip():
            return txt, f"pdfplumber·{len(pdf.pages)}页"
    except Exception:  # noqa: BLE001
        pass
    return "", ""


# ---------------------------------------------------------------------------
# ② 纯 stdlib 兜底(zlib + 文本操作符正则)
# ---------------------------------------------------------------------------

_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
# 换行定位操作符(Td/TD/T*/'/"):字符串已由手写扫描器逐个抽出,这里只用于插入换行。
_OP_AT = re.compile(rb"(?:Td|TD|T\*|'|\")")
_ESC = {ord("n"): "\n", ord("r"): "\r", ord("t"): "\t", ord("b"): "\b",
        ord("f"): "\f", ord("("): "(", ord(")"): ")", ord("\\"): "\\"}


def _via_stdlib(data: bytes):
    chunks: list[str] = []
    for m in _STREAM_RE.finditer(data):
        raw = m.group(1)
        try:
            content = zlib.decompress(raw)
        except zlib.error:
            content = raw  # 未压缩或非 Flate → 原样试抽
        piece = _extract_ops(content)
        if piece.strip():
            chunks.append(piece)
    txt = "\n".join(chunks)
    return txt, ("stdlib·zlib" if txt.strip() else "")


def _read_literal(content: bytes, start: int) -> tuple[int, str]:
    """从 content[start]=='(' 读一个 PDF 字面量字符串(**平衡括号** + 反斜杠转义)。

    返回 (下一个位置, 解码后文本)。PDF 字面量里成对括号可不转义,故必须按深度扫描,
    不能用普通正则(此前 (p < .05) 这类嵌套括号导致外层文本抽丢)。
    """
    j, n, depth = start + 1, len(content), 1
    buf = bytearray()
    while j < n and depth > 0:
        cc = content[j]
        if cc == 0x5C and j + 1 < n:          # 反斜杠:连同下一字节原样留给 _decode_literal
            buf.append(cc)
            buf.append(content[j + 1])
            j += 2
            continue
        if cc == 0x28:                        # 嵌套 '('
            depth += 1
            buf.append(cc)
        elif cc == 0x29:                      # ')'
            depth -= 1
            if depth == 0:
                j += 1
                break
            buf.append(cc)
        else:
            buf.append(cc)
        j += 1
    return j, _decode_literal(bytes(buf))


def _extract_ops(content: bytes) -> str:
    """手写扫描:抽 (字面量)/<十六进制> 文本,遇定位操作符插换行。"""
    out: list[str] = []
    i, n = 0, len(content)
    while i < n:
        c = content[i]
        if c == 0x28:                         # '(' 字面量
            i, s = _read_literal(content, i)
            out.append(s)
            continue
        if c == 0x3C:                         # '<'
            if i + 1 < n and content[i + 1] == 0x3C:
                i += 2                        # '<<' 字典开头,跳过
                continue
            end = content.find(b">", i + 1)
            if end != -1:
                out.append(_decode_hex(content[i + 1:end]))
                i = end + 1
                continue
            i += 1
            continue
        if c in (0x54, 0x27, 0x22):           # 'T' / ' / "  可能是定位操作符
            m = _OP_AT.match(content, i)
            if m and (i == 0 or content[i - 1:i].isspace()
                      or content[i - 1] in b"]>)"):
                out.append("\n")
                i = m.end()
                continue
        i += 1
    return "".join(out)


def _decode_literal(b: bytes) -> str:
    out = bytearray()
    i, n = 0, len(b)
    while i < n:
        c = b[i]
        if c == 0x5C and i + 1 < n:              # 反斜杠转义
            nxt = b[i + 1]
            if nxt in _ESC:
                out.extend(_ESC[nxt].encode("latin-1"))
                i += 2
                continue
            oct_m = re.match(rb"[0-7]{1,3}", b[i + 1:i + 4])
            if oct_m:                            # 八进制 \ddd
                out.append(int(oct_m.group(0), 8) & 0xFF)
                i += 1 + len(oct_m.group(0))
                continue
            i += 1                               # 其它 \x → 丢反斜杠
            continue
        out.append(c)
        i += 1
    return _bytes_to_str(bytes(out))


def _decode_hex(b: bytes) -> str:
    hx = re.sub(rb"\s+", b"", b)
    if len(hx) % 2:
        hx += b"0"
    try:
        return _bytes_to_str(bytes.fromhex(hx.decode("ascii")))
    except ValueError:
        return ""


def _bytes_to_str(bs: bytes) -> str:
    if bs[:2] == b"\xfe\xff":                    # UTF-16 BE BOM
        return bs[2:].decode("utf-16-be", errors="replace")
    return bs.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# ③ 清洗 + 质量门
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_TEXTY = set(".,;:!?()[]{}\"'-—–/%&@#*+=…、，。；:！？（）《》“”‘’【】")
_WORDISH = re.compile(r"[A-Za-z]{3,}|[一-鿿]{2,}")


def _looks_like_text(text: str) -> bool:
    """判抽取结果是否像正文:太短 / 可读占比低 / 无词形结构(乱码)→ False。

    评审修复:latin-1 解码的随机二进制约 66% 字节是"字母数字",旧 0.6 阈值会放行
    纯乱码(非 Flate 流如 DCT 图像)。改为双门:占比 ≥0.75 **且** 至少 5 个词形
    token(≥3 个连续拉丁字母 或 ≥2 个连续汉字)——真正文轻松通过,随机字节几乎不可能。
    """
    if len(text) < 40:
        return False
    good = sum(1 for c in text if c.isalnum() or c.isspace() or c in _TEXTY)
    if good / len(text) < 0.75:
        return False
    return len(_WORDISH.findall(text[:8000])) >= 5
