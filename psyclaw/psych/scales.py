"""量表注册表读取与查询(stdlib only)。"""

from __future__ import annotations

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


def list_scales() -> list:
    return _parse_scales(SCALES_FILE)


def get_scale(scale_id: str) -> dict | None:
    sid = scale_id.lower().strip()
    for s in list_scales():
        if s["id"] == sid:
            return s
    return None


def print_scale(scale_id: str | None = None) -> None:
    if not scale_id:
        print("  量表库(/scale <id> 查看详情):")
        for s in list_scales():
            print(f"    {s['id']:<10} {s.get('name', '')}({s.get('items', '?')} 题)")
        return
    s = get_scale(scale_id)
    if not s:
        print(f"  未收录 {scale_id}。可用:{', '.join(x['id'] for x in list_scales())}")
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
