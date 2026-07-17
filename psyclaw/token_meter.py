"""token 计量(feat-155,stdlib only)——CJK 感知估算 + 累计 + 诚实省量页。

诚实纪律(与学术诚信铁律同源):不编造跨产品对比数字。展示两类**有据**数据:
- 本会话**实测**(按 CJK 感知启发式估算,标注为估算);
- psyclaw 省 token 机制的**真实**节省:滚动压缩实际丢弃的历史、相关性路由避免的
  全量知识注入——「相较朴素全量注入」基线是 psyclaw 若不做 feat-111/112/113 就会
  发送的量,明确标注为估算口径,不是友商实测。
"""

from __future__ import annotations

from pathlib import Path

# CJK 汉字 token 密度远高于 ASCII:字符/4 会严重低估中文。启发式:
# 汉字 ≈ 0.6 tok/字,ASCII/其他 ≈ 0.25 tok/字(≈4 字符/token)。仅为估算。
_CJK_TOK = 0.6
_ASCII_TOK = 0.25


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF


def estimate_tokens(text: str) -> int:
    """CJK 感知 token 估算(比字符/4 对中文准)。纯函数,仅为量级估算。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if _is_cjk(c))
    other = len(text) - cjk
    return round(cjk * _CJK_TOK + other * _ASCII_TOK)


def naive_baseline_tokens(project_dir: str = ".") -> int:
    """朴素全量注入基线:若每轮把完整知识库(psych/*.json)全塞进上下文的 token 量。

    psyclaw 靠相关性路由(feat-111 教训 / 112 瘦核心 / 113 工具目录)只注入相关子集,
    避免了这份全量。这是「省下多少」的诚实上界口径,非跨产品实测。
    """
    total = 0
    try:
        for f in (Path(project_dir) / "psyclaw" / "psych").glob("*.json"):
            total += estimate_tokens(f.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        pass
    return total


class TokenMeter:
    """会话 token 累计。in/out 按 CJK 感知估算;省量记真实压缩丢弃。"""

    def __init__(self) -> None:
        self.in_tokens = 0
        self.out_tokens = 0
        self.turns = 0
        self.saved_compaction_tokens = 0

    def record_turn(self, system: str, user: str, reply: str) -> None:
        self.in_tokens += estimate_tokens(system) + estimate_tokens(user)
        self.out_tokens += estimate_tokens(reply)
        self.turns += 1

    def record_compaction(self, dropped_chars: int) -> None:
        """滚动压缩真实丢弃的历史字符 → 计入省量(真实,非估算基线)。"""
        self.saved_compaction_tokens += estimate_tokens("字" * max(0, dropped_chars))

    @property
    def total_tokens(self) -> int:
        return self.in_tokens + self.out_tokens


def _fmt(n: int) -> str:
    return f"{n:,}"


def render_token_report(meter: TokenMeter, project_dir: str = ".") -> str:
    """详细 token 消耗页:本会话实测 + 真实省量 + 相较朴素全量注入(估算)+ 趣味换算。"""
    from psyclaw import ui
    m = meter
    lines = [ui.title("  Token 消耗 · 本会话")]
    per = (m.total_tokens // m.turns) if m.turns else 0
    lines.append(f"  轮数 {m.turns} · 输入 ≈{_fmt(m.in_tokens)} · 输出 ≈{_fmt(m.out_tokens)}"
                 f" · 合计 ≈{_fmt(m.total_tokens)} tok"
                 + ui.dim("(CJK 感知估算)"))
    if m.turns:
        lines.append(ui.dim(f"  每轮均 ≈{_fmt(per)} tok"))

    # 真实省量:滚动压缩丢弃的历史(不做压缩就要一直带着)
    lines.append("")
    lines.append(ui.label("  psyclaw 省 token(真实机制):"))
    lines.append(f"  · 滚动压缩丢弃历史 ≈ 省 {_fmt(m.saved_compaction_tokens)} tok"
                 + ui.dim("(否则每轮都要重带)"))

    # 相较朴素全量注入(诚实估算,基线口径写明)
    naive_per = naive_baseline_tokens(project_dir)
    if naive_per and m.turns:
        from psyclaw.context import lean_core
        lean = estimate_tokens(lean_core())
        avoided = (naive_per - lean) * m.turns
        lines.append(f"  · 相关性路由避免全量知识注入 ≈ 省 {_fmt(max(0, avoided))} tok")
        lines.append(ui.dim(f"    (基线估算:朴素 Agent 每轮塞完整知识库 ≈{_fmt(naive_per)} tok,"
                            f"psyclaw 只注瘦核心 ≈{_fmt(lean)} tok + 按需相关项;非友商实测)"))

    # 趣味换算:一页 A4 中文 ≈ 500 字 ≈ 300 tok
    pages = m.total_tokens / 300 if m.total_tokens else 0
    lines.append("")
    lines.append(ui.info(f"  本会话信息量 ≈ {pages:.1f} 页 A4 中文正文"
                         + (f" · 已省的 token 够再聊约 {m.saved_compaction_tokens // max(1, per)} 轮"
                            if per and m.saved_compaction_tokens else "")))
    lines.append(ui.dim("  注:token 为按字符启发式估算(CJK 0.6/字、ASCII 0.25/字),"
                        "非计费实测;真实计费以 provider 为准。"))
    return "\n".join(lines)
