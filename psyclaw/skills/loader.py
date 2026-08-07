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
_FRONTMATTER_LIMIT = 64 * 1024
# 外部技能标准根(相对项目 / 相对用户家目录)。Claude Code、Codex、
# agentskills.io/OpenCode 安装的 Skill 均可只读发现，不复制或改写宿主目录。
_STD_SUBDIRS = (".claude/skills", ".codex/skills", ".agents/skills", ".opencode/skills",
                ".cc-switch/skills", ".claude/plugins/cache",
                ".codex/.tmp/marketplaces", ".psyclaw/skill-packs")


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


def _read_frontmatter(path: Path) -> dict:
    """Read only the bounded header needed to discover a Skill.

    Discovery must not turn every third-party/disabled Skill into a full prompt
    read. Standard SKILL.md frontmatter is at the beginning of the file.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(_FRONTMATTER_LIMIT)
        return _parse_frontmatter(raw.decode("utf-8", errors="replace"))
    except OSError:
        return {}


def external_skill_roots(project_dir: str = ".") -> list[Path]:
    """返回存在的外部技能根:项目级 + 用户级 .claude/.opencode/skills + PSYCLAW_SKILLS_PATH。"""
    roots: list[Path] = []
    for base in (Path(project_dir), Path.home()):
        for sub in _STD_SUBDIRS:
            roots.append(base / sub)
    env = os.environ.get("PSYCLAW_SKILLS_PATH", "")
    roots += [Path(p) for p in env.split(os.pathsep) if p.strip()]
    try:
        from psyclaw.skills.packs import pack_skill_roots
        roots += pack_skill_roots(project_dir)
    except Exception:  # noqa: BLE001 — pack 状态损坏不影响核心 Skill
        pass
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def _read_skill(skill_md: Path, source: str, scope: str = "builtin") -> dict:
    # Keep discovery bounded. Full content is retrieved by Registry only after
    # enablement, and by ``skill_get`` for the selected enabled Skill.
    meta = _read_frontmatter(skill_md)
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
        project = Path(project_dir).resolve()
        # Most projects live under the user's home directory. Classify the
        # standard roots generated from *this project* before the home-wide
        # roots, otherwise ``<project>/.claude/skills`` becomes global.
        for subdir in _STD_SUBDIRS:
            project_root = (project / subdir).resolve()
            if r == project_root or project_root in r.parents:
                return "project"
        if r.is_relative_to(Path.home().resolve()):
            return "global"
    except OSError:
        pass
    return "custom"


def _is_legacy_bundled(skill: dict) -> bool:
    return str(skill.get("status", "")).strip().lower() in {"legacy", "hidden", "disabled"}


def _safe_external_skill(path: Path, root: Path) -> Path | None:
    """Resolve an external Skill without following symlinks out of its root."""
    try:
        root_resolved = root.resolve(strict=True)
        candidate = path.resolve(strict=True)
        candidate.relative_to(root_resolved)
    except (OSError, ValueError):
        return None
    if not candidate.is_file() or candidate.name != "SKILL.md":
        return None
    # A symlink anywhere in the path can turn a benign-looking Skill into a
    # prompt-injection/read primitive. Bundled files are trusted separately.
    current = root
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    if ".staging" in relative.parts or ".git" in relative.parts:
        return None
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None
    if candidate.stat().st_size > 2 * 1024 * 1024:
        return None
    return candidate


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
        external_candidates: list[dict] = []
        for root in external_skill_roots(project_dir):
            scope = _root_scope(root, project_dir)
            found: list[Path] = []
            found_keys: set[str] = set()
            found += sorted(root.glob("*/SKILL.md"))
            found += sorted(root.glob("*/*/SKILL.md"))
            found += sorted(root.glob("*/skills/*/SKILL.md"))
            found += sorted(root.glob("*/*/*/SKILL.md"))
            if "plugins" in root.parts or "marketplaces" in root.parts or "skill-packs" in root.parts:
                found += sorted(root.rglob("SKILL.md"))
            for skill_md in found:
                skill_md = _safe_external_skill(skill_md, root)
                if skill_md is None:
                    continue
                key = str(skill_md)
                if key in found_keys:
                    continue
                found_keys.add(key)
                s = _read_skill(skill_md, str(root), scope=scope)
                external_candidates.append(s)
        # A project Skill must not silently replace a global/custom Skill with
        # the same identity. Builtins already won above; ambiguous external
        # identities are omitted until the user resolves the duplicate.
        by_name: dict[str, list[dict]] = {}
        for item in external_candidates:
            by_name.setdefault(item["name"], []).append(item)
        for name, candidates in by_name.items():
            if name in seen or len({c.get("scope") for c in candidates}) > 1:
                continue
            seen.add(name)
            out.append(candidates[0])
    return out


def list_skill_candidates(project_dir: str = ".", include_external: bool = True,
                          include_legacy: bool = False) -> list[dict]:
    """列出未去重候选，供 Registry 展示重复来源；不改变 ``list_skills`` 兼容行为。"""
    out: list[dict] = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        s = _read_skill(skill_md, "bundled", scope="builtin")
        if include_legacy or not _is_legacy_bundled(s):
            out.append(s)
    if not include_external:
        return out
    for root in external_skill_roots(project_dir):
        scope = _root_scope(root, project_dir)
        found = (sorted(root.glob("*/SKILL.md")) + sorted(root.glob("*/*/SKILL.md")) +
                 sorted(root.glob("*/skills/*/SKILL.md")) + sorted(root.glob("*/*/*/SKILL.md")))
        if "plugins" in root.parts or "marketplaces" in root.parts or "skill-packs" in root.parts:
            found += sorted(root.rglob("SKILL.md"))
        found_keys: set[str] = set()
        for skill_md in found:
            safe = _safe_external_skill(skill_md, root)
            if safe is not None:
                key = str(safe)
                if key in found_keys:
                    continue
                found_keys.add(key)
                out.append(_read_skill(safe, str(root), scope=scope))
    return out
