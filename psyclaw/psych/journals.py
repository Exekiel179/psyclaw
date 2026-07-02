"""期刊画像层(AJS 思路的心理学落地)——只读知识 + 供 cite-check / provenance 取判据。

每本期刊固化其**引用风格 / 摘要与字数 / 版块 / 报告标准 / 数据可得性 / 退稿红线**
(数据在 journals.json)。AJS 的核心主张是「一套泛泛的学术写作助手学不会期刊间差异」——
本模块把这些差异做成可查、可被门禁取用的结构化画像。纯知识数据,不含任何统计。

用法:
  - 只读浏览:``print_journal([id])``(对齐 knowledge.py 的 method/design 目录风格)。
  - 供门禁取判据:``get_journal(id)`` → 画像 dict;``requires_data_availability`` /
    ``expected_citation_format`` 给 provenance / cite-check 定制判据。
"""

from __future__ import annotations

import json
from pathlib import Path

_JSON = Path(__file__).parent / "journals.json"


def load_journals() -> list[dict]:
    if not _JSON.exists():
        return []
    return json.loads(_JSON.read_text(encoding="utf-8")).get("journals", [])


def get_journal(jid: str | None) -> dict | None:
    """按 id / 别名 / 名称子串匹配期刊画像(大小写不敏感)。找不到返回 None。"""
    if not jid:
        return None
    key = jid.strip().lower()
    journals = load_journals()
    for j in journals:
        if j["id"].lower() == key:
            return j
    for j in journals:
        names = [j["id"], j.get("name", "")] + list(j.get("aliases", []))
        if any(key == n.lower() for n in names) or any(key in n.lower() for n in names):
            return j
    return None


def list_journal_ids() -> list[str]:
    return [j["id"] for j in load_journals()]


def requires_data_availability(profile: dict | None) -> bool:
    """该期刊是否**要求**数据可得性(required)——供 provenance 收紧完整性判据。"""
    return bool(profile) and profile.get("data_availability") == "required"


def expected_citation_format(profile: dict | None) -> str | None:
    """期刊期望的文内引用格式:'author-year' | 'numeric'——供 cite-check 风格核对。"""
    return profile.get("citation_format") if profile else None


def print_journal(jid: str | None = None) -> None:
    journals = load_journals()
    if not jid:
        print("  期刊画像目录(psyclaw journal <id>):")
        for j in journals:
            print(f"    {j['id']:<16} {j['name']}")
        print("  用法:cite-check/provenance 加 --journal <id> 即按该期刊定制判据。")
        return
    j = get_journal(jid)
    if not j:
        print(f"  未收录 {jid}。可用:{', '.join(list_journal_ids())}")
        return
    ab = j.get("abstract", {})
    print(f"  {j['name']}")
    print(f"  学科/语言 : {j.get('discipline')} · {j.get('language')}")
    print(f"  引用风格  : {j.get('citation_style')}  ({j.get('citation_format')})")
    print(f"  摘要      : {ab.get('type', '?')},≤{ab.get('limit_words', '?')} 词")
    print(f"  正文字数  : {j.get('word_limit') or '无硬性上限'}")
    print(f"  版块      : {' · '.join(j.get('sections', []))}")
    print(f"  报告标准  : {', '.join(j.get('reporting_standards', []))}")
    print(f"  数据可得性: {j.get('data_availability')}  ·  预注册: {j.get('preregistration')}")
    print("  退稿红线  :")
    for r in j.get("red_lines", []):
        print(f"    - {r}")
