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


def _read_skill(skill_md: Path, source: str, scope: str = "builtin") -> dict:
    try:
        # errors="replace":第三方技能包可能含非法 UTF-8,不能让一个坏文件炸掉整份 skills 列表。
        meta = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        meta = {}
    return {
        "name": meta.get("name", skill_md.parent.name),
        "category": meta.get("category", "domain"),
        "description": meta.get("description", ""),
        "status": meta.get("status", "active"),
        "source": source,
        "scope": scope,       # builtin | project | global | custom(PSYCLAW_SKILLS_PATH)
        "path": str(skill_md),
    }


def _root_scope(root: Path, project_dir: str) -> str:
    """外部技能根归类:项目下=project,家目录下=global,其余(env 自定义)=custom。

    用 ``is_relative_to``(路径组件级)而非字符串前缀——否则 ``F:/proj-data`` 会被
    误判成在 ``F:/proj`` 里。
    """
    try:
        r = root.resolve()
        if r.is_relative_to(Path(project_dir).resolve()):
            return "project"
        if r.is_relative_to(Path.home().resolve()):
            return "global"
    except OSError:
        pass
    return "custom"


def _is_legacy_bundled(skill: dict) -> bool:
    return str(skill.get("status", "")).strip().lower() in {"legacy", "hidden", "disabled"}


def list_skills(project_dir: str = ".", include_external: bool = True,
                include_legacy: bool = False) -> list[dict]:
    """列出技能包(内置 + 外部)。按 name 去重,内置优先。

    外部根下同时扫平铺 ``<skill>/SKILL.md``、一层分类嵌套 ``<domain>/<skill>/SKILL.md``
    (AcademicForge 按学科分组)与 AJS 期刊包三层布局 ``<包>/skills/<技能>/SKILL.md``
    (feat-139 journal install 装入的包)。
    """
    out: list[dict] = []
    seen: set[str] = set()

    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        s = _read_skill(skill_md, "bundled", scope="builtin")
        if not include_legacy and _is_legacy_bundled(s):
            continue
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)

    if include_external:
        for root in external_skill_roots(project_dir):
            scope = _root_scope(root, project_dir)
            found: list[Path] = []
            found += sorted(root.glob("*/SKILL.md"))
            found += sorted(root.glob("*/*/SKILL.md"))
            found += sorted(root.glob("*/skills/*/SKILL.md"))
            for skill_md in found:
                s = _read_skill(skill_md, str(root), scope=scope)
                if s["name"] not in seen:
                    seen.add(s["name"])
                    out.append(s)
    return out
