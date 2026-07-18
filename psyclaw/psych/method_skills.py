"""method 重定位:从"方法词典"到"方法学 skill 路由"(stdlib only)。

用户判断:静态方法词典对比我们更专业的用户没价值;method 改成**路由到结构化 skill**——
让宿主模型按 skill 的既定流程(如样本量功效分析、无关变量控制)做,比裸输出规范。
psyclaw 只发现/匹配/呈现 skill,不执行、不算统计(样本量走 power_script 外移脚本)。

内置方法学 skill = psyclaw/skills/*/SKILL.md 里 category: method 的那些;
本模块复用 skills.loader 的发现,加一层意图匹配(关键词别名)+ 正文读取。
"""

from __future__ import annotations

import re
from pathlib import Path

from psyclaw.skills.loader import list_skills


def _alias_hit(alias: str, q: str) -> bool:
    """别名命中 q。纯 ASCII 别名要求词边界(避免 power 命中 empower);
    含中文的别名用子串(中文无词边界)。"""
    a = alias.lower()
    if a.isascii():
        return re.search(r"\b" + re.escape(a) + r"\b", q) is not None
    return a in q

# 意图别名:用户可能的说法 → skill 名。匹配时按最长别名优先,避免"控制变量"误入样本量。
_ALIASES: dict[str, tuple[str, ...]] = {
    "sample-size": (
        "样本量", "样本大小", "样本数", "功效分析", "功效", "统计功效",
        "效应量", "power analysis", "power", "sample size", "样本",
    ),
    "confound-control": (
        "无关变量", "无关条件", "混淆变量", "混淆", "控制变量", "额外变量",
        "对撞", "中介变量", "第三变量", "confound", "confounder", "control variable",
    ),
}


def list_method_skills(project_dir: str = ".") -> list[dict]:
    """列出内置方法学 skill(category == method),按名排序。发现失败返回 []。"""
    try:
        skills = list_skills(project_dir, include_external=False)
    except Exception:
        return []
    methods = [s for s in skills if (s.get("category") or "").strip() == "method"]
    return sorted(methods, key=lambda s: s.get("name", ""))


def match_method_skill(query: str, project_dir: str = ".") -> dict | None:
    """据用户意图把 query 匹配到一个方法学 skill;匹配不到返回 None。

    先按别名(最长优先),再退回 skill 名/描述的子串命中。
    """
    q = (query or "").strip().lower()
    if not q:
        return None
    skills = {s["name"]: s for s in list_method_skills(project_dir)}

    # 1) 别名命中——按别名长度降序,长词优先(避免"控制变量"被"样本"之类短词抢先)
    hits: list[tuple[int, str]] = []
    for name, aliases in _ALIASES.items():
        if name not in skills:
            continue
        for a in aliases:
            if _alias_hit(a, q):
                hits.append((len(a), name))
    if hits:
        hits.sort(reverse=True)
        return skills[hits[0][1]]

    # 2) 退回:query 直接命中 skill 名或描述
    for name, s in skills.items():
        if name.lower() in q or q in name.lower():
            return s
        if q in (s.get("description") or "").lower():
            return s
    return None


def skill_procedure(name: str, project_dir: str = ".") -> str:
    """读取指定方法学 skill 的正文(去掉 YAML frontmatter)。未知/读失败返回 ""。"""
    for s in list_method_skills(project_dir):
        if s.get("name") == name:
            path = s.get("path")
            if not path:
                return ""
            try:
                text = Path(path).read_text(encoding="utf-8")
            except OSError:
                return ""
            return _strip_frontmatter(text).strip()
    return ""


def _strip_frontmatter(text: str) -> str:
    """去掉开头的 --- ... --- YAML 块,返回正文。无 frontmatter 则原样返回。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            nl = text.find("\n", end + 1)
            return text[nl + 1:] if nl != -1 else ""
    return text
