"""草率作答(careless responding)筛查 — 纯 stdlib 实现。

指标(均为心理测量学标准做法):
- longstring     : 最长连续相同作答长度(Johnson, 2005)
- straightline   : 同一作答占比(直线作答)
- IRV            : 个体内作答标准差(intra-individual response variability;
                   Dunn et al., 2018)— 过低提示无差别作答
- psychsyn/psychant : 同义/反义题对一致性(简化自 Johnson, 2005)
- mahalanobis_d  : 多变量离群值检测(Tabachnick & Fidell, 2019)
- response_time  : Q{N}E 列作答速度标记
- infrequency    : 假词/陷阱词项偏离期望方向计数

阈值默认保守(标记 flag 而非剔除),任何剔除决定都走 HITL 审批门
(notes/decision_request.md),对应门禁 DATA.careless。
"""

from __future__ import annotations

import csv
import math
from pathlib import Path


# ---------------------------------------------------------------------------
# 原有指标
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


# ---------------------------------------------------------------------------
# 新指标 1：psychsyn / psychant 语义一致性
# ---------------------------------------------------------------------------

def psychsyn_score(
    responses: list[float],
    synonym_pairs: list[tuple[int, int]],
    antonym_pairs: list[tuple[int, int]],
    scale_min: float = 1.0,
    scale_max: float = 5.0,
) -> float:
    """语义一致性指数(简化自 Johnson, 2005)。

    对每对题按期望关系计算一致性:
      synonym  → consistency = 1 - |r_i - r_j| / scale_range
      antonym  → consistency = 1 - |r_i + r_j - (scale_min + scale_max)| / scale_range

    返回所有题对一致性均值 [0, 1];高值 = 语义自洽,低值 = 内部矛盾。
    无有效题对时返回 math.nan。
    """
    scale_range = scale_max - scale_min
    if scale_range <= 0:
        return math.nan
    scores: list[float] = []
    for i, j in synonym_pairs:
        if i < len(responses) and j < len(responses):
            scores.append(1.0 - abs(responses[i] - responses[j]) / scale_range)
    for i, j in antonym_pairs:
        if i < len(responses) and j < len(responses):
            mirror = scale_min + scale_max - responses[j]
            scores.append(1.0 - abs(responses[i] - mirror) / scale_range)
    return sum(scores) / len(scores) if scores else math.nan


# ---------------------------------------------------------------------------
# 新指标 2：Mahalanobis D²
# ---------------------------------------------------------------------------

def _mat_inv(m: list[list[float]]) -> list[list[float]]:
    """Gauss-Jordan 矩阵求逆。矩阵奇异时抛出 ValueError。"""
    n = len(m)
    aug = [
        [float(m[i][j]) for j in range(n)] + [float(i == j) for j in range(n)]
        for i in range(n)
    ]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-12:
            raise ValueError(f"协方差矩阵奇异(第 {col} 列),无法求逆")
        scale = aug[col][col]
        aug[col] = [v / scale for v in aug[col]]
        for row in range(n):
            if row != col:
                fac = aug[row][col]
                aug[row] = [aug[row][k] - fac * aug[col][k] for k in range(2 * n)]
    return [[aug[i][n + j] for j in range(n)] for i in range(n)]


def mahalanobis_d(matrix: list[list[float]]) -> list[float]:
    """Mahalanobis D² for each respondent row (纯 stdlib)。

    matrix : n×p 矩阵(n 被试 × p 条目)

    返回 D² 列表(长度 n)。经验阈值: D² > chi2_critical(p, .001) 视为多变量离群值
    (Tabachnick & Fidell, 2019)。
    """
    n = len(matrix)
    if n == 0:
        return []
    p = len(matrix[0])
    if n < p + 2:
        raise ValueError(
            f"Mahalanobis D 需至少 {p + 2} 名被试(当前 {n} 人,{p} 条目)"
        )

    means = [sum(matrix[i][j] for i in range(n)) / n for j in range(p)]

    cov = [[0.0] * p for _ in range(p)]
    for i in range(n):
        diff = [matrix[i][j] - means[j] for j in range(p)]
        for r in range(p):
            for c in range(p):
                cov[r][c] += diff[r] * diff[c]
    cov = [[cov[r][c] / (n - 1) for c in range(p)] for r in range(p)]

    # 微小正则化防止完全奇异
    for k in range(p):
        cov[k][k] += 1e-10

    cov_inv = _mat_inv(cov)

    d2: list[float] = []
    for i in range(n):
        diff = [matrix[i][j] - means[j] for j in range(p)]
        val = sum(
            diff[r] * cov_inv[r][c] * diff[c]
            for r in range(p)
            for c in range(p)
        )
        d2.append(max(0.0, val))
    return d2


def chi2_critical(df: int, alpha: float = 0.001) -> float:
    """chi² 分布上 alpha 分位点(Wilson-Hilferty 近似)。

    用于 Mahalanobis D 离群值阈值:D² > chi2_critical(p, .001)。
    """
    z_map = {0.001: 3.0902, 0.01: 2.3263, 0.05: 1.6449}
    z = z_map.get(alpha, 3.0902)
    h = 2.0 / (9.0 * df)
    return df * ((1.0 - h + z * math.sqrt(h)) ** 3)


# ---------------------------------------------------------------------------
# 新指标 3：作答时间（Q{N}E 列）
# ---------------------------------------------------------------------------

def response_time_flag(
    time_vals: list[float],
    min_seconds_per_item: float = 1.0,
) -> str | None:
    """基于作答时间列的速度标记。

    time_vals              : 每条目对应的秒数列表（来自 Q{N}E 列）
    min_seconds_per_item   : 低于此均速(秒/条目)触发标记
    返回 flag 字符串或 None。
    """
    if not time_vals:
        return None
    mean_t = sum(time_vals) / len(time_vals)
    if mean_t < min_seconds_per_item:
        return f"fast_response={mean_t:.2f}s/item(<{min_seconds_per_item}s)"
    return None


# ---------------------------------------------------------------------------
# 新指标 4：假词法 / infrequency items
# ---------------------------------------------------------------------------

def infrequency_score(
    responses: list,
    infrequency_items: list[tuple[int, int]],
) -> int:
    """计算 infrequency item 偏离期望值的条目数。

    infrequency_items : [(item_index, expected_value), ...]
      expected_value 是几乎所有诚实被试选择的选项(如陷阱词默认值)。
    返回偏离条目数; ≥ 2 通常认为存在草率作答风险。
    """
    count = 0
    for idx, expected in infrequency_items:
        if idx < len(responses):
            try:
                if float(responses[idx]) != float(expected):
                    count += 1
            except (TypeError, ValueError):
                count += 1
    return count


# ---------------------------------------------------------------------------
# 综合标记（单被试）
# ---------------------------------------------------------------------------

def flag_respondent(
    responses: list,
    n_items: int,
    longstring_max: int | None = None,
    irv_min: float = 0.3,
    straightline_max: float = 0.95,
    # psychsyn 参数
    synonym_pairs: list[tuple[int, int]] | None = None,
    antonym_pairs: list[tuple[int, int]] | None = None,
    scale_min: float = 1.0,
    scale_max: float = 5.0,
    psychsyn_min: float = 0.3,
    # infrequency 参数
    infrequency_items: list[tuple[int, int]] | None = None,
    infrequency_max: int = 1,
    # 作答时间参数
    time_vals: list[float] | None = None,
    min_seconds_per_item: float = 1.0,
) -> list:
    """返回该被试触发的 flag 列表(空 = 未见异常)。"""
    if longstring_max is None:
        longstring_max = max(8, n_items // 3)

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

    if synonym_pairs is not None or antonym_pairs is not None:
        ps = psychsyn_score(
            [float(r) for r in responses],
            synonym_pairs or [],
            antonym_pairs or [],
            scale_min=scale_min,
            scale_max=scale_max,
        )
        if not math.isnan(ps) and ps < psychsyn_min:
            flags.append(f"psychsyn={ps:.2f}(<{psychsyn_min})")

    if infrequency_items:
        inf_n = infrequency_score(responses, infrequency_items)
        if inf_n > infrequency_max:
            flags.append(f"infrequency={inf_n}items(>{infrequency_max})")

    if time_vals is not None:
        tf = response_time_flag(time_vals, min_seconds_per_item)
        if tf:
            flags.append(tf)

    return flags


# ---------------------------------------------------------------------------
# CSV 批量筛查
# ---------------------------------------------------------------------------

def _detect_item_cols(fieldnames: list[str], prefix: str, suffix: str) -> list[str]:
    cols = [
        c for c in fieldnames
        if c.startswith(prefix) and c.endswith(suffix)
        and c[len(prefix) : len(c) - len(suffix) if suffix else len(c)].isdigit()
    ]
    cols.sort(key=lambda c: int(c[len(prefix) : len(c) - len(suffix) if suffix else len(c)]))
    return cols


def screen_csv(
    path: str | Path,
    prefix: str = "Q",
    suffix: str = "A",
    compute_mahal: bool = True,
) -> dict:
    """筛查 CSV:取列名形如 {prefix}{N}{suffix} 的条目列(默认 Q1A..QnA)。

    同时自动检测 Q{N}E 时间列并计算作答速度。
    若 compute_mahal=True 且被试数足够,则运行 Mahalanobis D² 全局离群值检测。

    返回 {n_total, n_flagged, items, time_cols, rows:[{row, flags}], mahal(可选)}。
    """
    path = Path(path)
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        fieldnames = reader.fieldnames or []

        item_cols = _detect_item_cols(fieldnames, prefix, suffix)
        # 时间列: Q{N}E, 且不与 item_cols 重叠
        time_cols = [c for c in _detect_item_cols(fieldnames, prefix, "E")
                     if c not in item_cols]

        row_data: list[tuple[int, list[float], list[float]]] = []
        n_total = 0

        for i, row in enumerate(reader, start=2):
            vals: list[float] = []
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

            tvs: list[float] = []
            for c in time_cols:
                raw = (row.get(c) or "").strip()
                try:
                    tvs.append(float(raw))
                except ValueError:
                    pass

            row_data.append((i, vals, tvs))

    # 逐被试标记
    results: list[dict] = []
    for row_i, vals, tvs in row_data:
        flags = flag_respondent(
            vals,
            n_items=len(item_cols),
            time_vals=tvs if tvs else None,
        )
        if flags:
            results.append({"row": row_i, "flags": flags})

    # Mahalanobis D²（全局，需足够被试）
    mahal_info: dict | None = None
    if compute_mahal and row_data:
        p = len(row_data[0][1])
        if len(row_data) >= p + 2:
            try:
                matrix = [v for _, v, _ in row_data]
                d2_vals = mahalanobis_d(matrix)
                threshold = chi2_critical(p, alpha=0.001)
                mahal_outliers = [
                    {"row": row_data[k][0], "d2": round(d2_vals[k], 2)}
                    for k in range(len(d2_vals))
                    if d2_vals[k] > threshold
                ]
                mahal_info = {
                    "threshold": round(threshold, 2),
                    "df": p,
                    "alpha": 0.001,
                    "n_outliers": len(mahal_outliers),
                    "outliers": mahal_outliers,
                }
                existing_rows = {r["row"] for r in results}
                for o in mahal_outliers:
                    flag_str = (
                        f"mahalanobis_D2={o['d2']:.1f}(>{threshold:.1f})"
                    )
                    if o["row"] in existing_rows:
                        for r in results:
                            if r["row"] == o["row"]:
                                r["flags"].append(flag_str)
                    else:
                        results.append({"row": o["row"], "flags": [flag_str]})
            except ValueError:
                pass

    out: dict = {
        "n_total": n_total,
        "n_flagged": len(results),
        "items": item_cols,
        "time_cols": time_cols,
        "rows": sorted(results, key=lambda r: r["row"]),
    }
    if mahal_info is not None:
        out["mahal"] = mahal_info
    return out


def screen_csv_cli(argv: list) -> int:
    """`psyclaw screen data.csv [--prefix Q] [--suffix A] [--no-mahal]` 的实现。"""
    if not argv:
        print("用法:psyclaw screen <data.csv> [--prefix Q] [--suffix A] [--no-mahal]")
        return 1
    path, prefix, suffix = argv[0], "Q", "A"
    compute_mahal = True
    if "--prefix" in argv:
        prefix = argv[argv.index("--prefix") + 1]
    if "--suffix" in argv:
        suffix = argv[argv.index("--suffix") + 1]
        if suffix in ("''", '""'):
            suffix = ""
    if "--no-mahal" in argv:
        compute_mahal = False
    if not Path(path).exists():
        print(f"文件不存在:{path}")
        return 1

    r = screen_csv(path, prefix=prefix, suffix=suffix, compute_mahal=compute_mahal)
    print(f"草率作答筛查 — {path}")
    print(f"  条目列   : {len(r['items'])} 列({prefix}N{suffix} 格式)")
    if not r["items"]:
        print("  未匹配到条目列,请用 --prefix/--suffix 指定列名格式")
        return 1
    if r["time_cols"]:
        print(f"  时间列   : {len(r['time_cols'])} 列({prefix}NE 格式,作答速度检测)")
    print(f"  有效被试 : {r['n_total']}")
    print(f"  标记被试 : {r['n_flagged']}({r['n_flagged'] / max(r['n_total'], 1):.1%})")
    for row in r["rows"][:20]:
        print(f"    行 {row['row']}: {'; '.join(row['flags'])}")
    if len(r["rows"]) > 20:
        print(f"    … 另有 {len(r['rows']) - 20} 行")
    if "mahal" in r:
        m = r["mahal"]
        print(
            f"\n  Mahalanobis D² (df={m['df']}, α={m['alpha']}, "
            f"阈值={m['threshold']:.1f}): {m['n_outliers']} 个多变量离群值"
        )
    print("\n  注意:标记 ≠ 剔除。任何剔除决定须写 notes/decision_request.md 走人工审批")
    print("  (PSYCLAW 门禁 DATA.careless)。")
    return 0
