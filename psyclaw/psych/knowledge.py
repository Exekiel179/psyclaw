"""知识库浏览:前提假设 / 复杂方法 / 实验设计(JSON,stdlib)。"""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).parent


def _load(name: str, key: str) -> list:
    p = _DIR / name
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get(key, [])


# -- 前提假设 ----------------------------------------------------------------

def print_assumptions(test_id: str | None = None) -> None:
    tests = _load("assumptions.json", "tests")
    if not test_id:
        print("  前提假设知识库(psyclaw assume <id>):")
        for t in tests:
            print(f"    {t['id']:<12} {t['name']}")
        return
    t = next((x for x in tests if x["id"] == test_id.lower()), None)
    if not t:
        print(f"  未收录 {test_id}。可用:{', '.join(x['id'] for x in tests)}")
        return
    print(f"  {t['name']} — 前提假设清单")
    for i, a in enumerate(t["assumptions"], 1):
        print(f"  {i}. {a['name']}")
        print(f"     检查  : {a['check']}")
        print(f"     违反时: {a['violated']}")
    if t.get("modern_default"):
        print(f"  ▶ 现代默认做法: {t['modern_default']}")
    if t.get("psyclaw_runnable"):
        print(f"  ▶ 可直接运行  : {t['psyclaw_runnable']}")


# -- 复杂方法 ----------------------------------------------------------------

def print_method(method_id: str | None = None) -> None:
    methods = _load("methods.json", "methods")
    if not method_id:
        print("  复杂方法目录(psyclaw method <id>):")
        for m in methods:
            print(f"    {m['id']:<12} {m['name']}")
        return
    m = next((x for x in methods if x["id"] == method_id.lower()), None)
    if not m:
        print(f"  未收录 {method_id}。可用:{', '.join(x['id'] for x in methods)}")
        return
    print(f"  {m['name']}")
    print(f"  何时用  : {m['use_when']}")
    print(f"  样本量  : {m['min_n']}")
    print(f"  软件    : {m['software']}")
    print(f"  报告    : {m['report']}")
    print(f"  常见坑  : {m['pitfalls']}")


# -- 方法学背书库 -------------------------------------------------------------

def print_evidence(topic_id: str | None = None) -> None:
    topics = _load("evidence.json", "topics")
    if not topic_id:
        print("  方法学背书库(psyclaw cite <id>)— 每个决策都有文献撑腰:")
        for t in topics:
            print(f"    {t['id']:<24} {t['decision']}")
        return
    t = next((x for x in topics if x["id"] == topic_id.lower()), None)
    if not t:
        # 模糊匹配
        hits = [x for x in topics if topic_id.lower() in x["id"]
                or topic_id in x["decision"]]
        if len(hits) == 1:
            t = hits[0]
        else:
            print(f"  未找到 {topic_id}。" + (f"相近:{', '.join(h['id'] for h in hits)}" if hits else ""))
            return
    print(f"  决策: {t['decision']}")
    print(f"  背书: {t['citation']}")
    print(f"  要点: {t['gist']}")


# -- 实验设计 ----------------------------------------------------------------

def print_design(design_id: str | None = None) -> None:
    designs = _load("designs.json", "designs")
    if not design_id:
        print("  实验设计目录(psyclaw design <id>):")
        for d in designs:
            print(f"    {d['id']:<18} {d['name']}")
        return
    d = next((x for x in designs if x["id"] == design_id.lower()), None)
    if not d:
        print(f"  未收录 {design_id}。可用:{', '.join(x['id'] for x in designs)}")
        return
    print(f"  {d['name']}")
    for label, key in [("结构", "structure"), ("优势", "strengths"),
                       ("效度威胁", "threats"), ("关键实践", "key_practices"),
                       ("分析映射", "analysis")]:
        if d.get(key) and d[key] != "—":
            print(f"  {label:<4}: {d[key]}")
