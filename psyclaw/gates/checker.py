"""门禁执行器 — 真实校验实现(stdlib only,v0.2)。

机制原则:
1. **产出方不自证** —— analyze/loop 产出结构化 sidecar JSON(机器读),
   由本模块独立校验;APA 文本只给人读,门禁不解析散文。
2. **fail-closed** —— sidecar 缺失或不可解析,一律 blocking,不放行。
3. **规则驱动** —— 门禁定义解析自 rules.yaml(最小行解析器,不依赖 pyyaml);
   gate 的 trigger 与产出物 kind 匹配才执行;requirement 有已注册的
   校验函数则机器判定,没有则降级为"需人工核"warning(显式、不静默)。

公开接口:
  run_gates_selfcheck(verbose)      自检(文件存在 + 规则可解析)
  load_rules()                      → [gate dict]
  check_artifact(path, kind)        → {passed, blocking: [...], warnings: [...]}
  format_report(result)             → 人读报告文本

sidecar JSON 契约(kind="stat"):
  {
    "test": "Welch 独立样本 t",
    "statistics": {"t": 2.31, "df": 41.2, "p": 0.026},
    "effect_size": {"name": "Cohen's d", "value": 0.52, "ci": [0.05, 0.99]},
    "assumptions_checked": [{"name": "homogeneity", "method": "Levene(BF)", ...},
                            {"name": "normality", "method": "skewness", ...},
                            {"name": "independence", "method": "declared", ...}],
    "robustness": ["..."],
    "data_fingerprint": "abcd1234...",
    "repro_script": "outputs/repro_xxx.py"
  }
"""

from __future__ import annotations

import json
from pathlib import Path

GATES_DIR = Path(__file__).parent
RULES = GATES_DIR / "rules.yaml"
FIGSTYLE = GATES_DIR / "figure_style.yaml"
SPEC = GATES_DIR / "PSYCLAW.md"

# 产出物 kind → 该 kind 触发哪些 gate trigger
KIND_TRIGGERS = {
    "stat": {"stat_output", "before_test", "stat_conclusion"},
    "pipeline": {"analysis_pipeline", "research_start", "data_screening",
                 "stat_output", "before_test", "stat_conclusion"},
    "design": {"experiment_design", "confirmatory_study", "design_decision"},
    "paper": {"paper_output"},
    "figure": {"figure_output"},
    "literature": {"literature_review"},
    "scale": {"scale_score_used"},
}


# ---------------------------------------------------------------------------
# rules.yaml 最小解析(格式受限但真实驱动校验,不再只数行)
# ---------------------------------------------------------------------------

def _parse_value(raw: str):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [v.strip() for v in raw[1:-1].split(",") if v.strip()]
    return raw


def load_rules(path: Path = RULES) -> list:
    """解析 rules.yaml → [{id, trigger, action, requires, ...}]。"""
    if not path.exists():
        return []
    gates: list = []
    cur: dict | None = None
    pending_key: str | None = None
    bracket_key: str | None = None     # 跨行 [a, b,\n c] 列表
    bracket_buf = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.split("#", 1)[0].rstrip()
        if not s.strip():
            continue
        st = s.strip()
        if bracket_key is not None:                    # 续接跨行列表
            bracket_buf += " " + st
            if st.endswith("]"):
                cur[bracket_key] = _parse_value(bracket_buf)
                bracket_key, bracket_buf = None, ""
            continue
        if st.startswith("- id:"):
            cur = {"id": st.split(":", 1)[1].strip()}
            gates.append(cur)
            pending_key = None
            continue
        if cur is None:
            continue
        if pending_key and st.startswith("- "):       # 多行 "-" 列表项
            cur.setdefault(pending_key, []).append(st[2:].strip())
            continue
        if ":" in st:
            k, _, v = st.partition(":")
            k = k.strip()
            v = v.strip()
            if not v:
                pending_key = k
                cur[k] = []
            elif v.startswith("[") and not v.endswith("]"):
                bracket_key, bracket_buf = k, v        # 列表跨行,继续收
            else:
                pending_key = None
                cur[k] = _parse_value(v)
    return gates


# ---------------------------------------------------------------------------
# requirement → 校验函数注册表
# 返回 True(过) / False(不过) / None(本 checker 无法自动判定 → 显式 warning)
# ---------------------------------------------------------------------------

def _effect(d: dict):
    e = d.get("effect_size") or {}
    return bool(e.get("name")) and e.get("value") is not None \
        and e.get("value") == e.get("value")  # 排除 NaN


def _ci(d: dict):
    e = d.get("effect_size") or {}
    ci = e.get("ci")
    return (isinstance(ci, (list, tuple)) and len(ci) == 2
            and all(v is not None and v == v for v in ci))


def _assumption(name: str):
    def chk(d: dict):
        names = {a.get("name") for a in d.get("assumptions_checked", [])
                 if isinstance(a, dict)}
        return name in names
    return chk


def _repro_script(d: dict, base: Path):
    rel = d.get("repro_script")
    if not rel:
        return False
    p = Path(rel)
    return (p if p.is_absolute() else base / p).exists() or (base / Path(rel).name).exists()


def _fingerprint(d: dict):
    fp = d.get("data_fingerprint")
    return isinstance(fp, str) and len(fp) >= 8


def _robustness2(d: dict):
    return len(d.get("robustness") or []) >= 2


REQUIREMENT_CHECKS = {
    "effect_size": lambda d, base: _effect(d),
    "confidence_interval": lambda d, base: _ci(d),
    "normality_check": lambda d, base: _assumption("normality")(d),
    "homogeneity_check": lambda d, base: _assumption("homogeneity")(d),
    "independence_check": lambda d, base: _assumption("independence")(d),
    "repro_script": _repro_script,
    "data_fingerprint": lambda d, base: _fingerprint(d),
    "step5_robustness_2plus": lambda d, base: _robustness2(d),
    "step1_data_quality": lambda d, base: bool(d.get("data_quality")),
    "step2_descriptives": lambda d, base: bool(d.get("descriptives")),
    "step4_diagnostics": lambda d, base: bool(d.get("assumptions_checked")),
    "clarification_card_all_resolved":
        lambda d, base: d.get("clarification_resolved") is True,
    # 其余 requirement(apa7_*、prisma_flow、harking 等)暂无自动校验
    # → check_artifact 会显式输出"需人工核"warning,绝不静默放行。
}


# ---------------------------------------------------------------------------
# 核心:check_artifact
# ---------------------------------------------------------------------------

def check_artifact(artifact_path: str, kind: str) -> dict:
    """对结构化产出物(sidecar JSON)跑与 kind 匹配的全部门禁。

    fail-closed:文件缺失/不可解析 → blocking。
    返回 {passed, blocking: [{gate, requirement, msg, fix}], warnings: [...]}。
    """
    p = Path(artifact_path)
    blocking: list = []
    warnings: list = []

    if not p.exists():
        return {"passed": False, "warnings": [],
                "blocking": [{"gate": "GATE.artifact", "requirement": "sidecar_json",
                              "msg": f"产出物缺失:{artifact_path}(fail-closed,不放行)",
                              "fix": "产出方必须落结构化 sidecar JSON"}]}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "warnings": [],
                "blocking": [{"gate": "GATE.artifact", "requirement": "sidecar_json",
                              "msg": f"产出物不可解析:{exc}(fail-closed,不放行)",
                              "fix": "检查 JSON 格式"}]}

    base = p.parent
    triggers = KIND_TRIGGERS.get(kind, set())
    for gate in load_rules():
        if gate.get("trigger") not in triggers:
            continue
        action = gate.get("action", "block")
        sink = blocking if action == "block" else warnings

        reqs = gate.get("requires") or []
        if isinstance(reqs, str):
            reqs = [reqs]
        for req in reqs:
            fn = REQUIREMENT_CHECKS.get(req)
            if fn is None:
                warnings.append({"gate": gate["id"], "requirement": req,
                                 "msg": f"无自动校验实现,需人工核:{req}",
                                 "fix": gate.get("fix", "")})
                continue
            if not fn(data, base):
                sink.append({"gate": gate["id"], "requirement": req,
                             "msg": f"未满足:{req}",
                             "fix": gate.get("fix", "")})

        one_of = gate.get("requires_one_of") or []
        if one_of:
            results = [REQUIREMENT_CHECKS[r](data, base)
                       for r in one_of if r in REQUIREMENT_CHECKS]
            if results and not any(results):
                sink.append({"gate": gate["id"],
                             "requirement": " | ".join(one_of),
                             "msg": "requires_one_of 全部未满足",
                             "fix": gate.get("fix", "")})
            elif not results:
                warnings.append({"gate": gate["id"],
                                 "requirement": " | ".join(one_of),
                                 "msg": "requires_one_of 均无自动校验实现,需人工核",
                                 "fix": gate.get("fix", "")})
        # forbids 类(no_phack 等)无法从单个产物自动判定 → 显式人工核
        forbids = gate.get("forbids") or []
        if forbids:
            warnings.append({"gate": gate["id"],
                             "requirement": ", ".join(forbids),
                             "msg": "禁止项需流程级审计(critic/人工核)",
                             "fix": gate.get("fix", "")})

    return {"passed": not blocking, "blocking": blocking, "warnings": warnings}


def format_report(result: dict) -> str:
    lines = []
    status = "✓ 门禁通过" if result["passed"] else "✗ 门禁阻断"
    lines.append(f"{status}(blocking {len(result['blocking'])} · "
                 f"warning {len(result['warnings'])})")
    for b in result["blocking"]:
        lines.append(f"  ✗ [{b['gate']}] {b['msg']}"
                     + (f" → {b['fix']}" if b.get("fix") else ""))
    for w in result["warnings"]:
        lines.append(f"  ⚠ [{w['gate']}] {w['msg']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def run_gates_selfcheck(verbose: bool = False) -> bool:
    spec_ok = SPEC.exists()
    rules = load_rules()
    fig_ok = FIGSTYLE.exists()
    n_impl = sum(1 for g in rules for r in (g.get("requires") or [])
                 if r in REQUIREMENT_CHECKS)

    print(f"  PSYCLAW.md 规范        : {'存在 ✓' if spec_ok else '缺失 ✗'}")
    print(f"  rules.yaml 门禁规则     : {len(rules)} 条已解析"
          + (" ✓" if rules else " ✗"))
    print(f"  figure_style.yaml      : {'存在 ✓' if fig_ok else '缺失 ✗'}")
    print(f"  requirement 自动校验   : {n_impl} 项已实现(未实现项显式标'人工核')")

    ok = spec_ok and bool(rules) and fig_ok

    if verbose and ok:
        print("\n  已注册门禁:")
        for g in rules:
            reqs = g.get("requires") or g.get("requires_one_of") or g.get("forbids") or []
            auto = all(r in REQUIREMENT_CHECKS for r in reqs) if reqs else False
            tag = "自动" if auto else "部分/人工"
            print(f"    · {g['id']:<22} [{g.get('action', '?'):<5}] 校验:{tag}")
    return ok
