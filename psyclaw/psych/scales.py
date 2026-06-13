"""量表注册表读取与查询 + 自动计分(stdlib only)。

M-4: 自定义量表支持 — 用户量表 YAML 放 .psyclaw/scales/，与内置库合并；
     相同 id 时用户定义优先覆盖内置。
"""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path

SCALES_FILE = Path(__file__).with_name("scales.yaml")


def _parse_scales(path: Path) -> list:
    """极简解析 scales.yaml(两级缩进约定),避免引入 pyyaml。"""
    scales: list = []
    cur: dict | None = None
    section: str | None = None
    if not path.exists():
        return scales
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if stripped.startswith("- id:"):
            if cur:
                scales.append(cur)
            cur = {"id": stripped.split(":", 1)[1].strip(), "subscales": {}, "reverse": []}
            section = None
        elif cur is None:
            continue
        elif stripped.startswith("subscales:"):
            section = "subscales"
        elif section == "subscales" and indent >= 6 and ":" in stripped:
            k, v = stripped.split(":", 1)
            cur["subscales"][k.strip()] = _parse_intlist(v)
        elif ":" in stripped:
            section = None
            k, v = stripped.split(":", 1)
            k, v = k.strip(), v.strip().strip('"')
            cur[k] = _parse_intlist(v) if k == "reverse" else v
    if cur:
        scales.append(cur)
    return scales


def _parse_intlist(v: str) -> list:
    v = v.strip().strip("[]")
    if not v:
        return []
    out = []
    for part in v.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


# ---------------------------------------------------------------------------
# M-4: 自定义量表加载与合并
# ---------------------------------------------------------------------------

def _user_scales_dir(project_dir: Path | str | None = None) -> Path:
    """返回 .psyclaw/scales/ 目录(相对于 project_dir，默认 CWD)。"""
    base = Path(project_dir) if project_dir is not None else Path.cwd()
    return base / ".psyclaw" / "scales"


def _load_user_scales(project_dir: Path | str | None = None) -> list:
    """从 .psyclaw/scales/*.yaml 加载用户自定义量表。

    文件格式与内置 scales.yaml 相同（每个条目以 `- id:` 开头）。
    加载失败的单个文件仅发警告，不影响其他文件。
    """
    user_dir = _user_scales_dir(project_dir)
    scales: list = []
    if not user_dir.exists():
        return scales
    for yf in sorted(user_dir.glob("*.yaml")):
        try:
            loaded = _parse_scales(yf)
        except Exception as exc:  # noqa: BLE001
            import warnings
            warnings.warn(f"[psyclaw] 跳过损坏的用户量表文件 {yf.name}: {exc}")
            continue
        for s in loaded:
            s["_source"] = yf.name
        scales.extend(loaded)
    return scales


def list_scales(project_dir: Path | str | None = None) -> list:
    """返回合并后的量表列表：内置 + 用户自定义（用户同 id 覆盖内置）。"""
    builtin = _parse_scales(SCALES_FILE)
    for s in builtin:
        s.setdefault("_source", "built-in")
    user = _load_user_scales(project_dir)
    user_ids = {s["id"] for s in user}
    return [s for s in builtin if s["id"] not in user_ids] + user


def get_scale(scale_id: str, project_dir: Path | str | None = None) -> dict | None:
    sid = scale_id.lower().strip()
    for s in list_scales(project_dir):
        if s["id"] == sid:
            return s
    return None


def print_scale(scale_id: str | None = None,
                project_dir: Path | str | None = None) -> None:
    if not scale_id:
        print("  量表库(/scale <id> 查看详情):")
        for s in list_scales(project_dir):
            src_tag = "" if s.get("_source") == "built-in" else f"  [用户:{s.get('_source', '?')}]"
            print(f"    {s['id']:<10} {s.get('name', '')}({s.get('items', '?')} 题){src_tag}")
        user_dir = _user_scales_dir(project_dir)
        print(f"\n  用户量表目录: {user_dir}")
        print("  (在此放置 *.yaml 文件即可扩展量表库，格式同内置 scales.yaml)")
        return
    s = get_scale(scale_id, project_dir)
    if not s:
        print(f"  未收录 {scale_id}。可用:{', '.join(x['id'] for x in list_scales(project_dir))}")
        return
    print(f"  {s.get('name', s['id'])}")
    print(f"  条目数 : {s.get('items', '?')}    计分: {s.get('response', '?')}")
    for sub, items in s.get("subscales", {}).items():
        print(f"  {sub:<18}: {items}")
    if s.get("reverse"):
        print(f"  反向计分: {s['reverse']}")
    if s.get("reliability_ref"):
        print(f"  信度参考: {s['reliability_ref']}")
    if s.get("notes"):
        print(f"  注意    : {s['notes']}")
    src = s.get("_source", "built-in")
    if src != "built-in":
        print(f"  来源    : .psyclaw/scales/{src}")


# ---------------------------------------------------------------------------
# M-1: 量表自动计分
# ---------------------------------------------------------------------------

def _response_range(scale: dict) -> tuple[int, int]:
    """从 response 字段字符串提取 (最小值, 最大值)，如 '0-3 Likert' → (0, 3)。"""
    m = re.search(r'(\d+)-(\d+)', scale.get("response", ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    return (1, 5)


def reverse_item(value: float, lo: int, hi: int) -> float:
    """反向计分：lo+hi - 原值。"""
    return float(lo + hi - value)


def _col_name(prefix: str, item_num: int, suffix: str) -> str:
    return f"{prefix}{item_num}{suffix}"


def score_participant(item_values: dict, scale: dict, method: str = "sum") -> dict:
    """对单个被试的条目应答向量计分。

    item_values: {条目号(1-indexed int): 原始作答(float)}
    method: "sum" 或 "mean"（子量表聚合方式）
    返回 {
      "items": {条目号: 计分后值},      # 含反向翻转
      "subscales": {维度名: 合计/均值},
      "total": float,
      "missing_items": [缺失的条目号],
    }
    """
    lo, hi = _response_range(scale)
    reverse_set = set(scale.get("reverse", []))
    n_items = int(scale.get("items", 0))

    scored: dict[int, float] = {}
    missing: list[int] = []
    for i in range(1, n_items + 1):
        if i in item_values:
            val = item_values[i]
            scored[i] = reverse_item(val, lo, hi) if i in reverse_set else float(val)
        else:
            missing.append(i)

    subscales: dict[str, float] = {}
    for sub_name, sub_items in scale.get("subscales", {}).items():
        vals = [scored[i] for i in sub_items if i in scored]
        if vals:
            subscales[sub_name] = (sum(vals) / len(vals) if method == "mean"
                                   else float(sum(vals)))

    if subscales:
        total = sum(subscales.values())
    elif scored:
        total = float(sum(scored.values()))
    else:
        total = float("nan")

    return {"items": scored, "subscales": subscales, "total": total,
            "missing_items": missing}


def _desc(vals: list[float]) -> dict:
    """单列描述统计（n/mean/sd/min/max）。"""
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "sd": float("nan"),
                "min": float("nan"), "max": float("nan")}
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": m, "sd": sd, "min": min(vals), "max": max(vals)}


def score_datafile(path: str, scale_id: str,
                   prefix: str = "Q", suffix: str = "",
                   method: str = "sum",
                   project_dir: Path | str | None = None) -> dict:
    """对 CSV 全体被试自动计分。

    返回 {
      "scale": scale_def,
      "n": 行数,
      "n_complete": 完整应答行数,
      "participants": [{items, subscales, total, missing_items}],
      "subscale_stats": {维度名: {n,mean,sd,min,max}},
      "total_stats": {n,mean,sd,min,max},
      "missing_items_global": [csv 中完全缺失的条目号],
      "reverse_applied": [已翻转的条目号],
      "warnings": [str],
      "method": method,
    }
    """
    scale = get_scale(scale_id, project_dir)
    if not scale:
        avail = ", ".join(s["id"] for s in list_scales(project_dir))
        return {"error": f"未知量表 {scale_id}。可用: {avail}"}

    fp = Path(path)
    if not fp.exists():
        return {"error": f"文件不存在: {path}"}

    raw = fp.read_bytes().decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    rows = list(reader)
    headers: set[str] = set(reader.fieldnames or [])

    n_items = int(scale.get("items", 0))
    found_cols: dict[int, str] = {
        i: _col_name(prefix, i, suffix)
        for i in range(1, n_items + 1)
        if _col_name(prefix, i, suffix) in headers
    }
    missing_items_global = [i for i in range(1, n_items + 1) if i not in found_cols]

    participants: list[dict] = []
    for row in rows:
        item_values: dict[int, float] = {}
        for item_num, col in found_cols.items():
            v = row.get(col, "").strip()
            try:
                item_values[item_num] = float(v)
            except ValueError:
                pass
        participants.append(score_participant(item_values, scale, method=method))

    # 子量表描述统计
    subscale_stats: dict[str, dict] = {}
    for sub in scale.get("subscales", {}).keys():
        vals = [p["subscales"][sub] for p in participants
                if sub in p["subscales"] and not math.isnan(p["subscales"][sub])]
        subscale_stats[sub] = _desc(vals)

    # 总分描述统计
    totals = [p["total"] for p in participants if not math.isnan(p["total"])]
    total_stats = _desc(totals)

    warnings: list[str] = []
    if missing_items_global:
        warnings.append(
            f"CSV 中缺失条目列: {missing_items_global}（期望列名格式: {prefix}N{suffix}）")

    # D-3: 通用伦理检查（notes 关键词 + 条目级数据感知）
    from psyclaw.psych.ethics import check_scale_ethics, check_item_level_ethics
    ethics_notes_warns = check_scale_ethics(scale)
    ethics_item_warns = check_item_level_ethics(participants, scale)
    warnings.extend(ethics_notes_warns)
    warnings.extend(ethics_item_warns)
    ethics_prompted = bool(ethics_notes_warns or ethics_item_warns)

    # DASS-42 1-4 vs 0-3 歧义提示
    if scale_id.lower() == "dass-42":
        warnings.append(
            "DASS-42：在线版常用 1–4，纸质版为 0–3（总分差 42 分）。"
            "请确认数据计分规则与量表版本一致。")

    reverse_applied = sorted(set(scale.get("reverse", [])) & set(found_cols.keys()))

    reliability = compute_subscale_reliability(participants, scale)

    return {
        "scale": scale,
        "n": len(rows),
        "n_complete": sum(1 for p in participants if not p["missing_items"]),
        "participants": participants,
        "subscale_stats": subscale_stats,
        "total_stats": total_stats,
        "reliability": reliability,
        "missing_items_global": missing_items_global,
        "reverse_applied": reverse_applied,
        "warnings": warnings,
        "method": method,
        "ethics_prompted": ethics_prompted,
    }


# ---------------------------------------------------------------------------
# M-2: 子量表自动信度
# ---------------------------------------------------------------------------

def compute_subscale_reliability(participants: list, scale: dict) -> dict:
    """对每个子量表计算 Cronbach's α（纯 stdlib）。

    participants: score_datafile 返回的 participants 列表（已含反向翻转后条目分）
    返回 {维度名: {alpha, interpretation, n_items, n_obs, alpha_if_deleted}}
    """
    from psyclaw.psych.reliability import cronbach_alpha, alpha_if_deleted, interpret_alpha

    reliability: dict[str, dict] = {}
    for sub_name, sub_items in scale.get("subscales", {}).items():
        # 只用完整应答（对该子量表所有条目都有计分）的被试
        complete = [p for p in participants
                    if all(i in p["items"] for i in sub_items)]
        n_obs = len(complete)
        n_items = len(sub_items)

        if n_obs < 3 or n_items < 2:
            reason = (f"完整观测 < 3（n={n_obs}）" if n_obs < 3
                      else "条目数 < 2，无法计算")
            reliability[sub_name] = {
                "alpha": float("nan"),
                "interpretation": reason,
                "n_items": n_items,
                "n_obs": n_obs,
                "alpha_if_deleted": [],
            }
            continue

        # k × n 矩阵（k 个条目，每条目 n_obs 人）
        item_cols = [[p["items"][i] for p in complete] for i in sub_items]
        a = cronbach_alpha(item_cols)
        aid = alpha_if_deleted(item_cols)

        reliability[sub_name] = {
            "alpha": a,
            "interpretation": interpret_alpha(a),
            "n_items": n_items,
            "n_obs": n_obs,
            "alpha_if_deleted": [(sub_items[idx], av) for idx, (_, av) in enumerate(aid)],
        }
    return reliability


def write_scored_csv(result: dict, out_path: str, original_path: str) -> None:
    """将计分结果追加到原始 CSV 列尾，输出到 out_path。"""
    scale = result["scale"]
    sid = scale["id"].upper().replace("-", "_")
    fp = Path(original_path)
    raw = fp.read_bytes().decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    orig_rows = list(reader)
    fieldnames = list(reader.fieldnames or [])

    sub_keys = list(scale.get("subscales", {}).keys())
    extra_fields = [f"{sid}_{s}" for s in sub_keys] + [f"{sid}_Total"]
    fieldnames = fieldnames + [f for f in extra_fields if f not in fieldnames]

    out_rows = []
    for i, row in enumerate(orig_rows):
        new_row = dict(row)
        if i < len(result["participants"]):
            p = result["participants"][i]
            for sub in sub_keys:
                val = p["subscales"].get(sub, "")
                new_row[f"{sid}_{sub}"] = "" if val == "" or (
                    isinstance(val, float) and math.isnan(val)) else f"{val:.2f}"
            total = p.get("total", float("nan"))
            new_row[f"{sid}_Total"] = "" if math.isnan(total) else f"{total:.2f}"
        out_rows.append(new_row)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)
