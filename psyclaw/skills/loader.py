"""Skill 加载器(stdlib only)—— 发现并列出 SKILL.md 技能包。

扫描两类来源,统一解析标准 SKILL.md frontmatter(name/description/category),agentskills.io 兼容:
  ① **内置**:``psyclaw/skills/*/SKILL.md``(PsyClaw 自带,如 ARS)。
  ② **外部**:标准安装根(``.claude/skills`` / ``.opencode/skills``,项目级 + 用户级)
     与环境变量 ``PSYCLAW_SKILLS_PATH``——**AcademicForge / AJS 等第三方技能包 `bash install.sh`
     后即落到这些根目录**,PsyClaw 因而免安装即可发现、`psyclaw skills` 列出、供研究编排参考。

边界(诚实):PsyClaw 只**发现 + 呈现 + 路由指引**这些 Agent Skill(它们是给宿主 Agent 读的
markdown 指令);真正的执行发生在 Claude Code 等宿主读取 SKILL.md 时,不由 PsyClaw 的 Python 跑。
"""

from __future__ import annotations

import os
from pathlib import Path

SKILLS_DIR = Path(__file__).parent
# 外部技能标准根(相对项目 / 相对用户家目录);AcademicForge/AJS 默认装到这里。
_STD_SUBDIRS = (".claude/skills", ".opencode/skills")


def _parse_frontmatter(md: str) -> dict:
    meta: dict[str, str] = {}
    if not md.startswith("---"):
        return meta
    end = md.find("---", 3)
    if end == -1:
        return meta
    for line in md[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def external_skill_roots(project_dir: str = ".") -> list[Path]:
    """返回存在的外部技能根:项目级 + 用户级 .claude/.opencode/skills + PSYCLAW_SKILLS_PATH。"""
    roots: list[Path] = []
    for base in (Path(project_dir), Path.home()):
        for sub in _STD_SUBDIRS:
            roots.append(base / sub)
    env = os.environ.get("PSYCLAW_SKILLS_PATH", "")
    roots += [Path(p) for p in env.split(os.pathsep) if p.strip()]
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def _read_skill(skill_md: Path, source: str) -> dict:
    try:
        # errors="replace":第三方技能包可能含非法 UTF-8,不能让一个坏文件炸掉整份 skills 列表。
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        meta = {}
    return {
        "name": meta.get("name", skill_md.parent.name),
        "category": meta.get("category", "domain"),
        "description": meta.get("description", ""),
        "source": source,
        "path": str(skill_md),
    }


def list_skills(project_dir: str = ".", include_external: bool = True) -> list[dict]:
    """列出技能包(内置 + 外部)。按 name 去重,内置优先。

    外部根下同时扫平铺 ``<skill>/SKILL.md`` 与一层分类嵌套 ``<domain>/<skill>/SKILL.md``
    (AcademicForge 按学科分组,两种布局都能吃到)。
    """
    out: list[dict] = []
    seen: set[str] = set()

    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        s = _read_skill(skill_md, "bundled")
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)

    if include_external:
        for root in external_skill_roots(project_dir):
            found: list[Path] = []
            found += sorted(root.glob("*/SKILL.md"))
            found += sorted(root.glob("*/*/SKILL.md"))
            for skill_md in found:
                s = _read_skill(skill_md, str(root))
                if s["name"] not in seen:
                    seen.add(s["name"])
                    out.append(s)
    return out
