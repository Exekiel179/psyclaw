"""Deterministic Skill registry and retrieval for Agent callers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from psyclaw.skills.loader import _parse_frontmatter, list_skill_candidates
from psyclaw.plugins_catalog import discover_plugins

REGISTRY_RELATIVE_PATH = ".psyclaw/skill_registry.json"
TAXONOMY = (
    "research_design", "literature", "data_analysis", "qualitative",
    "writing", "review", "evidence", "visualization", "workflow", "memory", "general",
)
_CATEGORY_ALIASES = {
    "lit": "literature", "lit-review": "literature",
    "meta": "evidence", "meta-analysis": "evidence", "method": "research_design",
    "tooling": "data_analysis", "quality": "review", "domain": "general",
    "meta-skill": "memory", "design": "research_design", "analysis": "data_analysis",
    "qual": "qualitative", "figure": "visualization",
}
_CATEGORY_WORDS = {
    "research_design": ("design", "sample", "power", "prereg", "confound", "causal", "研究设计", "样本量"),
    "literature": ("literature", "review", "prisma", "citation", "bibliograph", "文献", "综述"),
    "data_analysis": ("analysis", "statistic", "regression", "anova", "pingouin", "data", "统计", "数据"),
    "qualitative": ("qualitative", "thematic", "interview", "coding", "质性", "访谈", "编码"),
    "writing": ("writing", "manuscript", "paper", "apa", "写作", "论文"),
    "review": ("review", "gate", "peer", "审稿", "质检"),
    "evidence": ("evidence", "effect size", "publication bias", "claim", "证据", "效应量"),
    "visualization": ("figure", "plot", "visual", "图", "可视化"),
    "workflow": ("workflow", "orchestrat", "pipeline", "编排", "流程"),
    "memory": ("context", "trajectory", "skill", "memory", "蒸馏", "记忆"),
}
_RISK_WORDS = {"execute", "shell", "delete", "credential", "secret", "交易", "写盘", "命令执行"}
_STOP = {"做", "并", "和", "的", "要", "一个", "进行", "检查", "研究", "方法", "分析", "变量", "偏倚",
         "use", "when", "the", "for", "with"}
_QUERY_ALIASES = {
    "发表偏倚": "publication bias", "元分析": "meta-analysis", "效应量": "effect size",
    "样本量": "sample size", "功效分析": "power analysis", "混淆变量": "confound",
    "质性研究": "qualitative", "文献综述": "literature review", "预注册": "preregistration",
}


def _state_signature(project_dir: str) -> str:
    from psyclaw.skills.state import _path
    digest = hashlib.sha256()
    for scope in ("global", "project"):
        path = _path(project_dir, scope)
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()


def _scalar_list(value: str | None) -> list[str]:
    if not value:
        return []
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value.replace("'", '"'))
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except (ValueError, TypeError):
            pass
    return [x.strip().strip("'\"") for x in value.strip("[]").split(",") if x.strip()]


def _headings(body: str) -> list[str]:
    headings = [re.sub(r"^#+\s*", "", line).strip() for line in body.splitlines()
            if re.match(r"^#{1,3}\s+", line)][:12]
    # Keep slug-like headings readable and deterministic (``Meta-Bias`` ->
    # ``Meta-bias``), matching frontmatter/name conventions used by Skills.
    return [re.sub(r"(?<=[A-Za-z])-([A-Z])", lambda m: "-" + m.group(1).lower(), h)
            for h in headings]


def _canonical_category(raw: str, text: str) -> str:
    value = (raw or "").strip().lower()
    if value in TAXONOMY:
        return value
    if value in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[value]
    low = text.lower()
    scores = {cat: sum(1 for word in words if word.lower() in low) for cat, words in _CATEGORY_WORDS.items()}
    return max(scores, key=scores.get) if max(scores.values(), default=0) else "general"


def _terms(text: str) -> list[str]:
    found: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]+", text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            found.extend(token[i:i+n] for n in (2, 3, 4) for i in range(max(0, len(token)-n+1)))
        elif token not in _STOP:
            found.append(token)
    return list(dict.fromkeys(found))


def _has_term(value: str, term: str) -> bool:
    if re.fullmatch(r"[a-z][a-z0-9_-]*", term):
        return re.search(rf"(?<![a-z0-9_-]){re.escape(term)}(?![a-z0-9_-])", value) is not None
    return term in value


def _is_pack_source(skill: dict, project_dir: str) -> bool:
    path = Path(str(skill.get("path", "")))
    if not path.is_absolute():
        path = Path(project_dir).resolve() / path
    parts = path.parts
    declared = set(skill.get("packs", []))
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "skill-packs" and parts[index + 1] in declared:
            return True
    return False


def _skill_record(skill: dict, project_dir: str = ".", *, load_body: bool = True) -> dict | None:
    path = Path(str(skill.get("path", "")))
    body = ""
    meta = {
        "name": str(skill.get("name", path.parent.name)),
        "description": str(skill.get("description", "")),
        "category": str(skill.get("category", "")),
        "status": str(skill.get("status", "active")),
    }
    if load_body:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        meta = {**meta, **_parse_frontmatter(body)}
    # A disabled Skill is an inventory item, not an instruction source. Its
    # metadata comes from the bounded discovery pass; do not parse its body.
    text = " ".join((meta.get("name", ""), meta.get("description", ""), body))
    category = _canonical_category(meta.get("category", skill.get("category", "")), text)
    tags = _scalar_list(meta.get("tags"))
    if not tags:
        tags = [category]
        tags.extend(k for k in _CATEGORY_WORDS.get(category, ()) if len(k) > 2 and k.lower() in text.lower())
    capabilities = _scalar_list(meta.get("capabilities")) or _headings(body)[-6:]
    inputs = _scalar_list(meta.get("inputs"))
    outputs = _scalar_list(meta.get("outputs"))
    low = text.lower()
    risk = (meta.get("risk") or ("medium" if any(k in low for k in _RISK_WORDS) else "low")).lower()
    if risk not in {"low", "medium", "high"}:
        risk = "medium"
    evidence = meta.get("evidence_level") or meta.get("evidence") or "unverified"
    try:
        rel = str(path.resolve().relative_to(Path(project_dir).resolve()))
    except (ValueError, OSError):
        rel = str(path)
    parts = {part.lower() for part in path.parts}
    provider = ("cc-switch" if ".cc-switch" in parts else
                "claude-plugin" if ".claude" in parts and "plugins" in parts else
                "codex-plugin" if ".codex" in parts and "marketplaces" in parts else
                "codex" if ".codex" in parts else
                "agents" if ".agents" in parts else "psyclaw")
    return {
        "name": meta.get("name", skill.get("name", path.parent.name)),
        "description": meta.get("description", skill.get("description", "")).strip(),
        "category": category, "tags": list(dict.fromkeys(tags)),
        "capabilities": capabilities, "inputs": inputs, "outputs": outputs,
        "risk": risk, "scope": skill.get("scope", "builtin"),
        "source": skill.get("source", "bundled"), "path": rel,
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest() if load_body else "",
        "status": meta.get("status", skill.get("status", "active")),
        "evidence_level": evidence, "version": meta.get("version", "1"),
        "headings": _headings(body), "search_text": " ".join(_terms(text)),
        "provider": provider,
    }


def build_registry(project_dir: str = ".", include_external: bool = True,
                   include_legacy: bool = False, skills: list[dict] | None = None) -> dict:
    discovered = skills if skills is not None else list_skill_candidates(
        project_dir, include_external=include_external, include_legacy=include_legacy)
    plugins = discover_plugins(project_dir)
    from psyclaw.skills.packs import load_pack_catalog
    from psyclaw.skills.state import resolve_enabled
    pack_defs = load_pack_catalog().get("packs", [])
    records = []
    for candidate in discovered:
        enabled, reason = resolve_enabled(candidate, pack_defs, project_dir)
        record = _skill_record(candidate, project_dir, load_body=enabled)
        if record is not None:
            record["enabled"], record["enable_reason"] = enabled, reason
            records.append(record)
    skills = sorted(records, key=lambda x: x["name"])
    for skill in skills:
        skill["packs"] = [p["id"] for p in pack_defs if skill["name"] in p.get("skills", [])]
        skill_path = Path(skill["path"])
        if not skill_path.is_absolute():
            skill_path = Path(project_dir).resolve() / skill_path
        for plugin in plugins:
            try:
                skill_path.resolve().relative_to(Path(plugin["path"]).resolve())
            except (OSError, ValueError):
                continue
            skill["plugin"] = {"id": plugin["id"], "host": plugin["host"],
                               "version": plugin.get("version", "")}
            break
    groups: dict[str, list[dict]] = {}
    for skill in skills:
        groups.setdefault(skill["name"], []).append(skill)
    priority = {"builtin": 0, "project": 1, "global": 2, "custom": 3}
    duplicates = []
    for name, items in groups.items():
        items.sort(key=lambda x: (priority.get(x.get("scope", "custom"), 9), x.get("path", "")))
        from psyclaw.skills.state import source_preference
        preferred = source_preference(name, project_dir)
        preferred_resolved = str(Path(preferred).expanduser().resolve()) if preferred else ""
        primary = items[0]
        if preferred_resolved:
            primary = next((item for item in items
                            if str((Path(project_dir).resolve() / item["path"]
                                    if not Path(item["path"]).is_absolute()
                                    else Path(item["path"])).resolve()) == preferred_resolved), primary)
        else:
            # A domain pack is an explicit installation/update of a bundled
            # Skill. Once it is active, its sparse checkout must win over the
            # shipped fallback; otherwise pack updates are never observable.
            active_pack_sources = [item for item in items
                                   if item.get("enabled") and _is_pack_source(item, project_dir)]
            if active_pack_sources:
                active_pack_sources.sort(
                    key=lambda item: (priority.get(item.get("scope", "custom"), 9),
                                      item.get("path", "")))
                primary = active_pack_sources[0]
        for item in items:
            item["selected"] = item is primary
            item["duplicate_of"] = name if len(items) > 1 else ""
            item["duplicate_sources"] = [x.get("path", "") for x in items] if len(items) > 1 else []
        if len(items) > 1:
            duplicates.append({"name": name, "count": len(items),
                               "sources": [x.get("path", "") for x in items]})
    return {"schema": 4, "taxonomy": list(TAXONOMY), "skills": skills,
            "state_signature": _state_signature(project_dir),
            "duplicates": sorted(duplicates, key=lambda x: x["name"]), "plugins": plugins}


def registry_path(project_dir: str = ".") -> Path:
    return Path(project_dir).resolve() / REGISTRY_RELATIVE_PATH


def rebuild_registry(project_dir: str = ".", *, include_external: bool = True,
                     include_legacy: bool = False) -> dict:
    registry = build_registry(project_dir, include_external, include_legacy)
    path = registry_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "status": "rebuilt", "path": str(path), "count": len(registry["skills"]), "registry": registry}


def load_registry(project_dir: str = ".", *, rebuild: bool = False) -> dict:
    path = registry_path(project_dir)
    if not rebuild and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (isinstance(data, dict) and isinstance(data.get("skills"), list)
                    and data.get("schema", 0) >= 4
                    and data.get("state_signature") == _state_signature(project_dir)):
                return data
        except (OSError, ValueError):
            pass
    return build_registry(project_dir)


def search_skills(query: str, *, category: str | None = None, tags: Iterable[str] | None = None,
                  scope: str | None = None, top_k: int = 8, project_dir: str = ".",
                  registry: dict | None = None, include_duplicates: bool = False,
                  include_disabled: bool = False) -> list[dict]:
    data = registry or load_registry(project_dir)
    raw_query = (query or "").strip().lower()
    expanded_query = raw_query + " " + " ".join(v for k, v in _QUERY_ALIASES.items() if k in raw_query)
    qterms = _terms(expanded_query)
    phrases = [p for p in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z][a-z0-9_-]+(?:\s+[a-z][a-z0-9_-]+)+", raw_query)
               if p not in _STOP]
    wanted_tags = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
    requested_cat = (category or "").strip().lower()
    cat = _CATEGORY_ALIASES.get(requested_cat, requested_cat)
    scored = []
    for skill in data.get("skills", []):
        if not include_duplicates and skill.get("selected") is False:
            continue
        if not include_disabled and skill.get("enabled") is False:
            continue
        if scope and skill.get("scope") != scope:
            continue
        if cat:
            labels = {skill.get("category", "").lower(), *(str(t).lower() for t in skill.get("tags", []))}
            indexed_text = skill.get("search_text", "")
            meta_match = requested_cat in {"meta", "meta-analysis"} and (
                "meta-analysis" in indexed_text or "元分析" in indexed_text)
            if cat not in labels and not meta_match:
                continue
        skill_tags = {str(t).lower() for t in skill.get("tags", [])}
        if wanted_tags and not wanted_tags.intersection(skill_tags):
            continue
        fields = {"name": skill.get("name", "").lower(), "description": skill.get("description", "").lower(),
                  "category": skill.get("category", "").lower(), "tags": " ".join(skill_tags),
                  "headings": " ".join(skill.get("headings", [])).lower(), "body": skill.get("search_text", "")}
        matched, score = [], 0
        for phrase in phrases:
            if any(_has_term(value, phrase) for value in fields.values()):
                matched.append(phrase)
                score += 8
        for term in qterms:
            if term in phrases or term in _STOP:
                continue
            hits = [key for key, value in fields.items() if _has_term(value, term)]
            if hits:
                matched.append(term)
                score += 8 if "name" in hits else 4 if "description" in hits else 2
        if not qterms and (cat or wanted_tags):
            score = 1
        if score:
            result = {k: v for k, v in skill.items() if k != "search_text"}
            result.update({"score": score, "matched": matched[:12], "executable": False})
            scored.append(result)
    scored.sort(key=lambda x: (-x["score"], x["name"]))
    return scored[:max(1, min(int(top_k), 50))]


def get_skill(name: str, *, project_dir: str = ".", registry: dict | None = None,
              include_body: bool = True, include_duplicates: bool = False,
              include_disabled: bool = False) -> dict | None:
    data = registry or load_registry(project_dir)
    for skill in data.get("skills", []):
        if (skill.get("name") == name and (include_duplicates or skill.get("selected", True))
                and (include_disabled or skill.get("enabled", True))):
            out = dict(skill)
            if not out.get("enabled", True):
                out["body"] = ""
                out["note"] = "Skill 已停用；仅返回元数据"
                return out
            if include_body:
                # Do not trust a user-editable persisted registry as an arbitrary
                # file-read capability. Re-resolve the exact name through loader.
                selected = Path(str(out.get("path", "")))
                if not selected.is_absolute():
                    selected = Path(project_dir).resolve() / selected
                current = next((s for s in list_skill_candidates(project_dir)
                                if s.get("name") == name
                                and Path(str(s.get("path", ""))).resolve() == selected.resolve()), None)
                path = Path(str((current or {}).get("path", "")))
                if path.name != "SKILL.md":
                    out["body"] = ""
                    return out
                try:
                    out["body"] = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    out["body"] = ""
            return out
    return None


def skill_categories(*, project_dir: str = ".", registry: dict | None = None,
                     include_disabled: bool = False) -> list[dict]:
    counts = {cat: 0 for cat in TAXONOMY}
    for skill in (registry or load_registry(project_dir)).get("skills", []):
        if not include_disabled and skill.get("enabled") is False:
            continue
        category = skill.get("category", "general")
        counts[category] = counts.get(category, 0) + 1
    return [{"category": cat, "count": counts.get(cat, 0)} for cat in TAXONOMY if counts.get(cat, 0)]
