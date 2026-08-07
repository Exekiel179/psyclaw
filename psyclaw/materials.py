"""统一资料转换中间层。

研究流程只消费 Markdown，不让每个入口各自解析 PDF、DOCX、HTML 或表格。
MarkItDown 是可选增强后端；纯标准库格式保持离线可用，失败时明确告诉调用者。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain_html(text: str) -> str:
    parser = _HTMLText()
    parser.feed(text)
    return "\n\n".join(parser.parts)


def _stdlib_markdown(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ".text"}:
        return path.read_text(encoding="utf-8")
    if suffix in {".html", ".htm"}:
        return _plain_html(path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n"
    if suffix in {".csv", ".tsv"}:
        delim = "\t" if suffix == ".tsv" else ","
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f, delimiter=delim))
        if not rows:
            return ""
        width = len(rows[0])
        rows = [r[:width] + [""] * max(0, width - len(r)) for r in rows]
        out = ["| " + " | ".join(rows[0]) + " |",
               "| " + " | ".join("---" for _ in rows[0]) + " |"]
        out.extend("| " + " | ".join(r) + " |" for r in rows[1:])
        return "\n".join(out) + "\n"
    return None


def _markitdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError as exc:
        raise RuntimeError(
            f"{path.suffix.lower()} 需要可选 MarkItDown 后端;请安装 `pip install markitdown`"
        ) from exc
    result = MarkItDown().convert(str(path))
    return getattr(result, "text_content", str(result))


def convert_to_markdown(source: str | Path, output: str | Path | None = None) -> dict:
    """Convert one source and write a replayable sidecar audit record."""
    src = Path(source)
    if not src.is_file():
        return {"ok": False, "status": "missing", "source": str(src),
                "note": f"文件不存在:{src}"}
    source_sha256 = hashlib.sha256(src.read_bytes()).hexdigest()
    try:
        text = _stdlib_markdown(src)
        backend = "stdlib" if text is not None else "markitdown"
        if text is None:
            text = _markitdown(src)
        text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        return {"ok": False, "status": "conversion_failed", "source": str(src),
                "source_sha256": source_sha256, "note": str(exc)}
    dest = Path(output) if output else src.with_suffix(".md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    audit = {"source": str(src), "source_sha256": source_sha256,
             "output": str(dest), "output_sha256": hashlib.sha256(text.encode()).hexdigest(),
             "backend": backend, "chars": len(text)}
    sidecar = dest.with_suffix(dest.suffix + ".conversion.json")
    sidecar.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "status": "converted", **audit, "sidecar": str(sidecar)}


def _vtt_text(raw: str) -> str:
    """Extract readable caption lines without treating timestamps as prose."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n\n".join(lines)


def convert_video_url(url: str, output: str | Path | None = None,
                     *, language: str = "zh,en") -> dict:
    """Materialize video metadata and captions when yt-dlp is available.

    This function never claims a full transcript from metadata alone. Caption
    retrieval is best-effort and returns ``partial`` when only metadata exists.
    """
    url = str(url).strip()
    if not re.match(r"https?://", url, re.I):
        return {"ok": False, "status": "invalid_url", "note": "视频地址必须是 http(s) URL"}
    try:
        import yt_dlp
    except ImportError:
        return {"ok": False, "status": "dependency_missing",
                "note": "视频转换需要可选依赖 yt-dlp；未安装时不伪造转录"}
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        title = str(info.get("title") or url)
        lines = [f"# {title}", "", f"- Source: {url}",
                 f"- Uploader: {info.get('uploader') or '(unknown)'}",
                 f"- Date: {info.get('upload_date') or '(unknown)'}",
                 f"- Duration: {info.get('duration_string') or info.get('duration') or '(unknown)'}", ""]
        caption_url = ""
        available = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}
        for lang in [x.strip() for x in language.split(",") if x.strip()]:
            tracks = available.get(lang) or automatic.get(lang)
            if tracks:
                caption_url = tracks[0].get("url", "")
                if caption_url:
                    break
        status = "partial"
        if caption_url:
            try:
                with urllib.request.urlopen(caption_url, timeout=30) as response:
                    captions = _vtt_text(response.read().decode("utf-8", errors="replace"))
                if captions:
                    lines.extend(["## Captions", "", captions, ""])
                    status = "complete"
            except (OSError, UnicodeError) as exc:
                lines.extend(["## Captions", "", f"字幕读取失败: {exc}", ""])
        else:
            lines.extend(["## Captions", "", "未发现可读取字幕；当前产物仅含元数据，不能视为完整转录。", ""])
        text = "\n".join(lines).rstrip() + "\n"
    except Exception as exc:  # yt-dlp raises source-specific exception classes
        return {"ok": False, "status": "error", "source": url, "note": str(exc)}
    dest = Path(output) if output else Path("notes") / f"{_slug_filename(title)}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    audit = {"source": url, "output": str(dest), "status": status,
             "title": title, "caption_language": language,
             "output_sha256": hashlib.sha256(text.encode()).hexdigest()}
    sidecar = dest.with_suffix(dest.suffix + ".conversion.json")
    sidecar.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **audit, "sidecar": str(sidecar)}


def _slug_filename(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text.lower()).strip("-")
    return value or "video-material"
