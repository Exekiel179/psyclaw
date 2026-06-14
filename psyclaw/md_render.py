"""stdlib-only Markdown → ANSI renderer for PsyClaw terminal output.

Supported block elements:
  # H1  ## H2  ### H3  |  --- (hr)  |  > quote  |  - / * / + list  |  1. list  |  ``` fence

Supported inline elements:
  **bold**  *italic*  `code`

Degraded mode (NO_COLOR=1 / non-TTY / enabled=False):
  Strips all markers, returns clean plain text — never shows raw ** / # / - .

Design note: coloring is driven by the `enabled` parameter, NOT by ui._ENABLED,
so the renderer can be tested with enabled=True even in non-TTY environments.
"""
from __future__ import annotations

import re

# ANSI primitives (mirrors ui._CODES subset we actually need)
_RESET = "\033[0m"
_C = {"bold": "1", "dim": "2", "italic": "3",
      "brmagenta": "95", "bryellow": "93", "brcyan": "96"}

# Compiled once — matches **bold**, *italic*, `code` (no cross-line spans)
_INLINE_PAT = re.compile(r'\*\*(.+?)\*\*|\*([^*\n]+?)\*|`([^`\n]+?)`')


# ---------------------------------------------------------------------------
# Internal ANSI helper (enabled-aware, bypasses ui._ENABLED global)
# ---------------------------------------------------------------------------

def _paint(text: str, *styles: str, enabled: bool) -> str:
    if not enabled or not styles:
        return text
    seq = ";".join(_C[s] for s in styles if s in _C)
    return f"\033[{seq}m{text}{_RESET}" if seq else text


def _rule_line(enabled: bool) -> str:
    from psyclaw.ui import term_width
    w = term_width() - 4
    chars = "─" * max(0, w)
    return _paint(chars, "dim", enabled=enabled)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_md(text: str, *, enabled: bool | None = None) -> str:
    """Render Markdown to ANSI-enriched or clean plain text.

    Args:
        text:    Markdown-formatted string (e.g. an LLM reply).
        enabled: Force color on/off.  None → honour ui._ENABLED.
    """
    if enabled is None:
        from psyclaw.ui import _ENABLED
        enabled = _ENABLED
    return _render(text, enabled=enabled)


# ---------------------------------------------------------------------------
# Block renderer
# ---------------------------------------------------------------------------

def _render(text: str, *, enabled: bool) -> str:
    lines = text.split('\n')
    out: list[str] = []
    in_fence = False

    for raw in lines:
        # ── Code fence open / close ──────────────────────────────────────
        if re.match(r'^(`{3,}|~{3,})', raw):
            in_fence = not in_fence
            if enabled:
                out.append(_paint(raw, "dim", enabled=enabled))
            # plain mode: omit fence marker line entirely
            continue

        if in_fence:
            out.append(_paint(raw, "brcyan", enabled=enabled) if enabled else raw)
            continue

        # ── Heading # / ## / ### ─────────────────────────────────────────
        heading = re.match(r'^(#{1,3})\s+(.*)', raw)
        if heading:
            level = len(heading.group(1))
            content = _inline(heading.group(2), enabled)
            style_map = {1: ("bold", "brmagenta"), 2: ("bold", "bryellow"), 3: ("bold", "brcyan")}
            out.append(_paint(content, *style_map[level], enabled=enabled) if enabled else content)
            continue

        # ── Horizontal rule --- / *** / ___ ──────────────────────────────
        if re.match(r'^[-*_]{3,}\s*$', raw):
            out.append(_rule_line(enabled))
            continue

        # ── Blockquote > ─────────────────────────────────────────────────
        bq = re.match(r'^>\s?(.*)', raw)
        if bq:
            content = _inline(bq.group(1), enabled)
            if enabled:
                out.append(_paint("│ ", "dim", enabled=enabled) + _paint(content, "dim", enabled=enabled))
            else:
                out.append("  " + content)
            continue

        # ── Unordered list: - / * / + ─────────────────────────────────────
        ul = re.match(r'^(\s*)[-*+]\s+(.*)', raw)
        if ul:
            indent, body = ul.group(1), ul.group(2)
            content = _inline(body, enabled)
            bullet = _paint("•", "brcyan", enabled=enabled)
            out.append(indent + bullet + " " + content)
            continue

        # ── Ordered list: 1. ─────────────────────────────────────────────
        ol = re.match(r'^(\s*)(\d+)\.\s+(.*)', raw)
        if ol:
            indent, num, body = ol.group(1), ol.group(2), ol.group(3)
            content = _inline(body, enabled)
            num_str = _paint(num + ".", "brcyan", enabled=enabled)
            out.append(indent + num_str + " " + content)
            continue

        # ── Normal paragraph line ─────────────────────────────────────────
        out.append(_inline(raw, enabled))

    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Inline renderer
# ---------------------------------------------------------------------------

def _inline(text: str, enabled: bool) -> str:
    """Apply inline Markdown (**bold**, *italic*, `code`)."""
    if not text:
        return text

    if not enabled:
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        text = re.sub(r'\*([^*\n]+?)\*', r'\1', text)
        text = re.sub(r'_([^_\n]+?)_', r'\1', text)
        text = re.sub(r'`([^`\n]+?)`', r'\1', text)
        return text

    result: list[str] = []
    last = 0
    for m in _INLINE_PAT.finditer(text):
        result.append(text[last:m.start()])
        if m.group(1) is not None:       # **bold**
            result.append(_paint(m.group(1), "bold", enabled=enabled))
        elif m.group(2) is not None:     # *italic*
            result.append(_paint(m.group(2), "italic", enabled=enabled))
        else:                            # `code`
            result.append(_paint(m.group(3), "brcyan", enabled=enabled))
        last = m.end()
    result.append(text[last:])
    return ''.join(result)
