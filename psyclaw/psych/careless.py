"""草率作答(careless responding)筛查 — 纯 stdlib 实现。

指标(均为心理测量学标准做法):
- longstring   : 最长连续相同作答长度(Johnson, 2005)
- straightline : 同一作答占比(直线作答)
- IRV          : 个体内作答标准差(intra-individual response variability;
                 Dunn et al., 2018)— 过低提示无差别作答
- psychsyn 思路的简化版可在 M2 接 ARS-Stat 后补充

阈值默认保守(标记 flag 而非剔除),任何剔除决定都走 HITL 审批门
(notes/decision_request.md),对应门禁 DATA.careless。
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


# ---------------------------------------------------------------------------
# 单被试指标
# ---------------------------------------------------------------------------

def longstring(responses: list) -> int:
    """最长连续相同作答长度。"""
    best = run = 0
    prev = object()
    for r in responses:
        run = run + 1 if r == prev else 1
        prev = r
        best = max(best, run)
    return best


def straightline_pct(responses: list) -> float:
    """众数作答占比(0-1)。1.0 = 完全直线作答。"""
    if not responses:
        return 0.0
    counts: dict = {}
    for r in responses:
        counts[r] = counts.get(r, 0) + 1
    return max(counts.values()) / len(responses)


def irv(responses: list) -> float:
    """个体内作答标准差。过低(如 < 0.3)提示无差别作答。"""
    vals = [float(r) for r in responses]
    n = len(vals)
    if n < 2:
        return 0.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    return math.sqrt(var)


def flag_respondent(responses: list, n_items: int,
                    longstring_max: int | None = None,
                    irv_min: float = 0.3,
                    straightline_max: float = 0.95) -> list:
    """返回该被试触发的 flag 列表(空 = 未见异常)。"""
    if longstring_max is None:
        longstring_max = max(8, n_items // 3)  # 保守默认:1/3 量表长度
    flags = []
    ls = longstring(responses)
    if ls >= longstring_max:
        flags.append(f"longstring={ls}(≥{longstring_max})")
    sp = straightline_pct(responses)
    if sp >= straightline_max:
        flags.append(f"straightline={sp:.0%}")
    v = irv(responses)
    if v < irv_min:
        flags.append(f"IRV={v:.2f}(<{irv_min})")
    return flags


# ---------------------------------------------------------------------------
# CSV 批量筛查
# ---------------------------------------------------------------------------

def screen_csv(path: str | Path, prefix: str = "Q", suffix: str = "A") -> dict:
    """筛查 CSV:取列名形如 {prefix}{N}{suffix} 的条目列(默认 Q1A..QnA,
    即 OpenPsychometrics 格式;TIPI 等可用 prefix=TIPI, suffix='')。

    返回 {n_total, n_flagged, items, rows:[{row, flags}]}。
    """
    path = Path(path)
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        # 自动嗅探分隔符(OpenPsychometrics 用 tab)
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        fieldnames = reader.fieldnames or []
        item_cols = [c for c in fieldnames
                     if c.startswith(prefix) and c.endswith(suffix)
                     and c[len(prefix):len(c) - len(suffix) if suffix else len(c)].isdigit()]
        item_cols.sort(key=lambda c: int(c[len(prefix):len(c) - len(suffix) if suffix else len(c)]))

        results = []
        n_total = 0
        for i, row in enumerate(reader, start=2):  # 行号从 2(含表头)
            vals = []
            ok = True
            for c in item_cols:
                raw = (row.get(c) or "").strip()
                try:
                    vals.append(float(raw))
                except ValueError:
                    ok = False
                    break
            if not ok or not vals:
                continue
            n_total += 1
            flags = flag_respondent(vals, n_items=len(item_cols))
            if flags:
                results.append({"row": i, "flags": flags})

    return {
        "n_total": n_total,
        "n_flagged": len(results),
        "items": item_cols,
        "rows": results,
    }


def screen_csv_cli(argv: list) -> int:
    """`psyclaw screen data.csv [--prefix Q] [--suffix A]` 的实现。"""
    if not argv:
        print("用法:psyclaw screen <data.csv> [--prefix Q] [--suffix A]")
        return 1
    path, prefix, suffix = argv[0], "Q", "A"
    if "--prefix" in argv:
        prefix = argv[argv.index("--prefix") + 1]
    if "--suffix" in argv:
        suffix = argv[argv.index("--suffix") + 1]
        if suffix == "''" or suffix == '""':
            suffix = ""
    if not Path(path).exists():
        print(f"文件不存在:{path}")
        return 1

    r = screen_csv(path, prefix=prefix, suffix=suffix)
    print(f"草率作答筛查 — {path}")
    print(f"  条目列   : {len(r['items'])} 列({prefix}N{suffix} 格式)")
    if not r["items"]:
        print("  未匹配到条目列,请用 --prefix/--suffix 指定列名格式")
        return 1
    print(f"  有效被试 : {r['n_total']}")
    print(f"  标记被试 : {r['n_flagged']}({r['n_flagged'] / max(r['n_total'], 1):.1%})")
    for row in r["rows"][:20]:
        print(f"    行 {row['row']}: {'; '.join(row['flags'])}")
    if len(r["rows"]) > 20:
        print(f"    … 另有 {len(r['rows']) - 20} 行,完整结果建议输出到 outputs/")
    print("\n  注意:标记 ≠ 剔除。任何剔除决定须写 notes/decision_request.md 走人工审批")
    print("  (PSYCLAW 门禁 DATA.careless)。")
    return 0
