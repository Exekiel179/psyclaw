"""复现溯源 (provenance bundle) — 给生成的可复现脚本/图打包「谁、用什么、怎么来的」。

`analysis`/`meta` 流程把统计外移成可复现脚本(``outputs/analysis.py`` /
``outputs/meta_analysis.py``),但脚本本身**不记录产出它的环境与决策轨迹**——几个月后想复跑,
往往缺 Python/库版本、数据指纹、当初为何这么分析。本模块补上 Claude Science 式的**溯源包**:
每个产物旁落一份 ``<产物>.provenance.json``,含四要素——

  ① 确切代码(code + sha256)   ② 运行环境(python + 平台 + 统计库版本)
  ③ 自然语言说明(这脚本做了什么)  ④ 决策轨迹(plan/design/研究准备清单/workflow_summary 指针)

设计纪律(对齐项目铁律):
- **不算统计**:只做元数据采集(sha256/版本号/路径),不 import 也不运行任何统计库。
- **不碰 data/raw**:数据指纹只对 data/clean 与项目根的数据文件按需哈希(单向,不入库内容);
  受保护的 ``data/raw`` 一律只记路径、不哈希。也可由调用方直接传入已算好的 ``data_fingerprint``。
- **确定性、可单测**:纯 stdlib(hashlib / importlib.metadata / platform / sys)。

对接质量检查:``REPRO.provenance``(trigger ``provenance_check``)据 ``provenance_complete``
(代码 + 环境 + 说明齐备)把缺项的溯源包 block 掉。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

# 采集版本的统计栈(只读 dist 元数据,不 import 这些库 → 不触发任何统计计算)。
_STAT_PACKAGES = ("pingouin", "scipy", "statsmodels", "pandas", "numpy", "lifelines")

# 决策轨迹候选(存在才纳入指针;仅路径,不内联内容)。
_HISTORY_CANDIDATES = (
    "notes/plan.md", "notes/design.md", "notes/clarification.md",
    "notes/workflow_summary.json", "notes/autoloop_state.json",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _is_protected_raw(path: str) -> bool:
    """路径是否落在受保护的 data/raw 下(此时只记路径、绝不哈希内容)。"""
    parts = [p.lower() for p in Path(path).parts]
    return "raw" in parts and "data" in parts


def capture_environment() -> dict:
    """采集运行环境:Python 版本 + 平台 + 统计库版本(缺失记 None)。不 import 统计库。"""
    from importlib.metadata import PackageNotFoundError, version
    packages: dict[str, str | None] = {}
    for name in _STAT_PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
    }


def _describe_from_code(code: str) -> str:
    """产物无显式说明时,从脚本模块 docstring 的头两行拼一个自然语言说明。"""
    import re
    m = re.search(r'"""(.*?)"""', code, re.S)
    if not m:
        return ""
    lines = [ln.strip() for ln in m.group(1).strip().splitlines() if ln.strip()]
    return " ".join(lines[:2])[:300]


def _data_fingerprint(data_path: str | None, provided: str | None) -> dict | None:
    """数据指纹:优先用调用方给的;否则对非 data/raw 的数据文件按需哈希(单向)。"""
    if not data_path and not provided:
        return None
    entry: dict = {"path": data_path}
    if provided:
        entry["sha256"] = provided
        entry["note"] = "调用方提供的指纹"
        return entry
    if _is_protected_raw(data_path or ""):
        entry["sha256"] = None
        entry["note"] = "受保护的 data/raw,只记路径不哈希"
        return entry
    p = Path(data_path)
    entry["sha256"] = _sha256_file(p) if p.exists() else None
    entry["note"] = "data/clean 或项目根数据文件的单向指纹(不入库内容)" if entry["sha256"] \
        else "数据文件不存在,指纹缺失"
    return entry


def _history_pointers(project_dir: str) -> list[str]:
    project = Path(project_dir)
    return [rel for rel in _HISTORY_CANDIDATES if (project / rel).exists()]


def build_replication_declaration(prov: dict) -> dict:
    """replication-package 声明(feat-074):清点复现材料并生成可放进稿件
    「数据可得性声明」节的确定性文本。

    complete = 分析脚本 + 数据指纹都在(环境清单随溯源包必有)。
    期刊画像 data_availability=required 时,质量检查 REPRO.replication_package
    据 sidecar 的 ``replication_package_declared`` 强制这份声明;非强制期刊
    也照常生成(作者仍可自愿附上),只是不作质量检查判据。
    """
    items: list[dict] = []
    missing: list[str] = []
    if prov.get("code_present"):
        items.append({"kind": "analysis_script", "path": prov.get("artifact"),
                      "sha256": prov.get("artifact_sha256")})
    else:
        missing.append("分析脚本(产物读不到)")
    data = prov.get("data") or {}
    if data.get("sha256"):
        items.append({"kind": "data", "path": data.get("path"),
                      "sha256": data["sha256"]})
    else:
        missing.append("数据指纹(--data 指向数据文件,或 --fingerprint 传入)")
    env = prov.get("environment") or {}
    pkgs = {k: v for k, v in (env.get("packages") or {}).items() if v}
    items.append({"kind": "environment",
                  "python": env.get("python"), "packages": pkgs})

    complete = not missing
    if complete:
        pkg_note = ", ".join(f"{k}={v}" for k, v in pkgs.items()) or "见溯源包"
        statement = (
            "本研究提供复现材料包(replication package):"
            f"分析脚本 {prov.get('artifact')}(sha256 {str(prov.get('artifact_sha256'))[:16]}…)、"
            f"数据文件 {data.get('path') or '(指纹由调用方提供)'}"
            f"(sha256 {str(data.get('sha256'))[:16]}…)、"
            f"运行环境 Python {env.get('python')}({pkg_note})。"
            f"完整溯源清单见 {prov.get('artifact')}.provenance.json。")
    else:
        statement = ""
    return {"items": items, "missing": missing,
            "complete": complete, "statement": statement}


def build_provenance(artifact_path: str, description: str = "",
                     project_dir: str = ".", data_path: str | None = None,
                     data_fingerprint: str | None = None,
                     created: str | None = None, journal: str | None = None) -> dict:
    """构造溯源包 dict(纯函数,不落盘)。fail-safe:产物读不到时 code/sha 记 None。

    ``journal`` 给定且该期刊**要求**数据可得性(data_availability=required)时,溯源完整性
    额外要求带数据指纹(否则复现受阻)——AJS 式期刊定制:让 provenance 判据随期刊收紧。
    """
    ap = Path(artifact_path)
    code = ap.read_text(encoding="utf-8") if ap.exists() else ""
    env = capture_environment()
    desc = (description or "").strip() or _describe_from_code(code)
    history = _history_pointers(project_dir)
    data = _data_fingerprint(data_path, data_fingerprint)

    prov = {
        "artifact": artifact_path,
        "artifact_sha256": _sha256_text(code) if code else None,
        "code_present": bool(code),
        "description": desc,
        "environment": env,
        "data": data,
        "history": history,
        "has_history": bool(history),
        "created": created or _now(),
    }

    # 质量检查判据:确切代码 + 环境 + 自然语言说明三要素齐(决策轨迹尽力采集、不作硬判据)。
    complete = bool(code) and bool(env.get("python")) and bool(desc)
    data_required = False
    if journal:
        from psyclaw.psych.journals import get_journal, requires_data_availability
        profile = get_journal(journal)
        prov["journal"] = profile["name"] if profile else None
        data_required = requires_data_availability(profile)
    prov["data_availability_required"] = data_required
    data_ok = (not data_required) or bool(data and data.get("sha256"))
    prov["data_availability_ok"] = data_ok
    # feat-074:replication-package 声明照常生成(非强制期刊也可自愿附);
    # 但只有 data_availability=required 时才由质量检查 REPRO.replication_package 强制。
    decl = build_replication_declaration(prov)
    prov["replication_package"] = decl
    prov["replication_package_declared"] = decl["complete"]
    prov["provenance_complete"] = complete and data_ok
    return prov


def _render_md(prov: dict) -> str:
    env = prov["environment"]
    pkgs = ", ".join(f"{k}={v}" for k, v in env["packages"].items() if v) or "(无已装统计库)"
    lines = [
        f"# 复现溯源 — {prov['artifact']}", "",
        f"- 生成时间:{prov['created']}",
        f"- 代码指纹 sha256:{prov['artifact_sha256'] or '(读不到产物)'}",
        f"- 说明:{prov['description'] or '(无)'}",
        f"- 环境:Python {env['python']} · {env['platform']}",
        f"- 统计库:{pkgs}",
    ]
    if prov.get("data"):
        d = prov["data"]
        lines.append(f"- 数据:{d.get('path')} · sha256={d.get('sha256') or '—'}({d.get('note')})")
    lines.append(f"- 决策轨迹:{', '.join(prov['history']) or '(无)'}")
    if prov.get("journal"):
        req = "要求(必须带数据指纹)" if prov.get("data_availability_required") else "非强制"
        lines.append(f"- 期刊定制:{prov['journal']} · 数据可得性 {req}")
    decl = prov.get("replication_package") or {}
    if decl.get("complete"):
        lines += ["", "## Replication package 声明(可直接放进稿件数据可得性节)", "",
                  decl["statement"]]
    elif prov.get("data_availability_required"):
        lines += ["", "## Replication package 声明", "",
                  "⚠ 该期刊强制 replication-package 声明,当前缺:"
                  + ";".join(decl.get("missing", []))]
    lines.append("")
    if prov["provenance_complete"]:
        lines.append("✓ 溯源完整")
    elif prov.get("data_availability_required") and not prov.get("data_availability_ok"):
        lines.append("⚠ 溯源不完整:该期刊要求数据可得性,但缺数据指纹(--data 指向数据文件)")
    else:
        lines.append("⚠ 溯源不完整(缺代码/环境/说明)")
    return "\n".join(lines) + "\n"


def write_provenance(artifact_path: str, description: str = "",
                     project_dir: str = ".", data_path: str | None = None,
                     data_fingerprint: str | None = None,
                     created: str | None = None, journal: str | None = None) -> dict:
    """构造并落盘溯源包:``<产物>.provenance.json`` + 同名 ``.provenance.md``。返回 prov dict。"""
    prov = build_provenance(artifact_path, description, project_dir,
                            data_path, data_fingerprint, created, journal)
    ap = Path(artifact_path)
    sidecar = ap.with_suffix(ap.suffix + ".provenance.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")
    ap.with_suffix(ap.suffix + ".provenance.md").write_text(_render_md(prov), encoding="utf-8")
    prov["_sidecar"] = str(sidecar)
    return prov
