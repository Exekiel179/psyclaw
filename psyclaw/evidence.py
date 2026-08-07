"""统一 Claim-Evidence 账本。

引用核查和 provenance 仍各自保留原有格式；本层提供一个小的、可迁移的
中间结构，避免新流程再次发明一套 claim 字段。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def normalize_claim(claim: dict | str, *, source: str = "", status: str = "unverified") -> dict:
    """Normalize a claim into stable fields; no truth is inferred."""
    if isinstance(claim, str):
        text = claim.strip()
        claim = {}
    else:
        text = str(claim.get("text") or claim.get("claim") or "").strip()
    if not text:
        raise ValueError("claim 不能为空")
    origin = source or str(claim.get("source") or claim.get("evidence") or "").strip()
    state = str(claim.get("status") or status).strip().lower()
    if state not in {"verified", "unverified", "inferred", "unknown"}:
        state = "unknown"
    return {"claim": text, "source": origin, "status": state,
            "locator": str(claim.get("locator") or "").strip(),
            "notes": str(claim.get("notes") or "").strip()}


def build_ledger(claims: Iterable[dict | str]) -> list[dict]:
    out = [normalize_claim(c) for c in claims]
    seen = set()
    deduped = []
    for item in out:
        key = (item["claim"], item["source"], item["locator"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def write_ledger(path: str | Path, claims: Iterable[dict | str]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_ledger(claims), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return out
