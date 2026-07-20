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


# 方法学背书库(evidence.json)已删除:静态映射既不全也会过时,且"文献支撑"应可核实
# ——需要文献依据走真实检索(psyclaw lit),不再查内置静态库。cite 现做引用保真核查。

# 实验设计目录(designs.json + print_design)已删除:固定 12 类设计卡覆盖太窄,
# 输入真实研究问题只会得到「未收录」,帮倒忙。设计讨论交给对话(模型本就懂设计),
# gates 的 DESIGN.* 质量检查仍在(判据不动)——与"统计外移"同一原则:
# 宁可不内置,也不做半吊子内容库。

