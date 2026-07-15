"""annotate(feat-142)——给代码写注释 + --review 审查,注释密度随协助水平变。

与 feat-141 assist level 同一根设置:novice 逐段注释并解释统计概念,
expert 只注释非显然决策。--review 输出审查意见(正确性/统计规范/风格),
**绝不改文件**。写回(--write)有三重保护:先备份 .bak、输出行数骤减拒写
(防 LLM 把代码弄丢)、mock provider 明确降级指路 psyclaw config。

统计规范审查面与 gates/PSYCLAW.md 同源:效应量+CI、不造数、统计外移。
"""

from __future__ import annotations

from pathlib import Path

_MAX_BYTES = 60_000          # 超大文件拒注释(上下文放不下,截断注释会误导)
_SHRINK_RATIO = 0.5          # 输出行数 < 原来一半 → 疑似丢代码,拒绝写回

_DENSITY = {
    "novice": ("逐段写注释:每个逻辑段落前加中文注释,用白话解释这段在做什么、"
               "为什么;统计函数与关键参数(如 alternative/paired/correction)"
               "顺带解释统计概念含义。"),
    "standard": "在关键步骤(数据处理决策/统计调用/输出解读)加简明中文注释。",
    "expert": ("只注释非显然决策(口径选择/例外处理/易踩的坑),不写逐行显然注释,"
               "注释精简。"),
}


def build_annotate_prompt(code: str, filename: str, level: str,
                          review: bool = False) -> tuple[str, str]:
    """构建注释/审查提示。纯函数,可单测。"""
    if review:
        system = (
            "你是代码审查者,审查一份研究分析代码。只输出**审查意见**,"
            "不要改写代码、不修改原文件。按三个面给出要点(每条带行号/代码片段):\n"
            "① 正确性:逻辑错误、边界条件、可能的运行时错误;\n"
            "② 统计规范:是否报效应量+CI、是否有硬编码统计量/造数嫌疑、"
            "统计计算是否委托成熟库(scipy/pingouin/statsmodels)而非手写算法;\n"
            "③ 可读性与风格:命名、结构、可复现性(随机种子/路径)。\n"
            "没有问题的面明确说「未见问题」,不要为凑数硬找。"
        )
    else:
        density = _DENSITY.get((level or "").strip().lower(), _DENSITY["standard"])
        system = (
            "你是代码注释者。给下面的研究分析代码**添加注释,不改动任何代码逻辑**"
            "(不增删语句、不重命名、不调整顺序)。" + density +
            " 输出完整的加注释后代码,不要省略任何原有行。"
        )
    user = f"文件:{filename}\n\n{code.strip()}"
    return system, user


def _strip_fences(text: str) -> str:
    """剥掉 LLM 常见的 ```lang 围栏(容错:无围栏原样返回)。"""
    s = (text or "").strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip("\n") + "\n"


def run_annotate(path: str, review: bool = False, write: bool = False,
                 provider=None) -> dict:
    """给代码写注释/审查。返回 {"ok", "text", "note"};任何失败不抛。"""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"ok": False, "text": "", "note": f"文件不存在:{p}"}
    try:
        code = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "text": "", "note": f"读取失败:{exc}"}
    if len(code.encode("utf-8")) > _MAX_BYTES:
        return {"ok": False, "text": "",
                "note": f"文件过大(>{_MAX_BYTES // 1000}KB),请拆分后再注释"}

    if provider is None:
        try:
            from psyclaw.config import load_config
            from psyclaw.providers import get_provider
            provider = get_provider(load_config())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "text": "", "note": f"provider 初始化失败:{exc}"}
    if getattr(provider, "name", "") == "mock":
        return {"ok": False, "text": "",
                "note": "annotate 需要真实 LLM——先 psyclaw config 配 provider/API key"}

    from psyclaw.config import load_config as _lc
    try:
        level = str(_lc().get("assist_level", "standard"))
    except Exception:  # noqa: BLE001
        level = "standard"
    system, user = build_annotate_prompt(code, p.name, level, review=review)
    try:
        reply = "".join(provider.chat([{"role": "user", "content": user}],
                                      system=system))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "text": "", "note": f"LLM 调用失败:{exc}"}

    if review:
        return {"ok": True, "text": reply.strip(), "note": "审查意见(未改动文件)"}

    annotated = _strip_fences(reply)
    src_lines = len([ln for ln in code.splitlines() if ln.strip()])
    out_lines = len([ln for ln in annotated.splitlines() if ln.strip()])
    if write:
        if out_lines < src_lines * _SHRINK_RATIO:
            return {"ok": False, "text": annotated,
                    "note": f"输出行数骤减({src_lines}→{out_lines}),疑似丢代码,"
                            "已拒绝写回(原文件未动)"}
        try:
            p.with_suffix(p.suffix + ".bak").write_text(code, encoding="utf-8")
            p.write_text(annotated, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "text": annotated, "note": f"写回失败:{exc}"}
        return {"ok": True, "text": annotated,
                "note": f"已写回 {p}(备份 {p.name}.bak)"}
    return {"ok": True, "text": annotated, "note": "未写回(--write 落盘)"}
