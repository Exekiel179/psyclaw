"""质量检查红队测试 — 质量检查是产品核心,这些 fixture 就是它的规格。

运行:python -m pytest tests/ 或 python tests/test_gates.py
原则:违规产物必须被拦(block),缺失产物必须被拦(fail-closed),
合规产物必须放行。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from psyclaw.gates.checker import check_artifact, load_rules  # noqa: E402
from psyclaw.loop import has_decision_request, parse_verdict, snapshot_raw  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _good_sidecar(tmp: Path) -> dict:
    (tmp / "repro_x.py").write_text("# repro", encoding="utf-8")
    return {
        "test": "两组比较",
        "statistics": {"t": 2.31, "df": 41.2, "p": 0.026},
        "effect_size": {"name": "Cohen's d", "value": 0.52, "ci": [0.05, 0.99]},
        "assumptions_checked": [
            {"name": "homogeneity", "method": "Levene(BF)", "p": 0.4},
            {"name": "normality", "method": "skewness"},
            {"name": "independence", "method": "declared"},
        ],
        "robustness": ["Mann-Whitney 对照"],
        "data_fingerprint": "abcd1234efgh5678",
        "repro_script": "repro_x.py",
    }


def _write(tmp: Path, data) -> str:
    p = tmp / "result_x.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _blocked_gates(result: dict) -> set:
    return {b["gate"] for b in result["blocking"]}


# ---------------------------------------------------------------------------
# rules.yaml 解析
# ---------------------------------------------------------------------------

def test_rules_parse():
    rules = load_rules()
    ids = {g["id"] for g in rules}
    assert "STAT.effect_size" in ids and "REPRO.script" in ids
    eff = next(g for g in rules if g["id"] == "STAT.effect_size")
    assert eff["action"] == "block"
    assert "effect_size" in eff["requires"]
    # 跨行 [a, b,\n c] 列表必须完整解析(STAT.rigor 有 5 项 requires)
    rigor = next(g for g in rules if g["id"] == "STAT.rigor")
    assert len(rigor["requires"]) == 5, rigor["requires"]
    assert "step5_robustness_2plus" in rigor["requires"]


# ---------------------------------------------------------------------------
# check_artifact:合规放行 / 违规必拦 / fail-closed
# ---------------------------------------------------------------------------

def test_complete_artifact_passes():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        r = check_artifact(_write(tmp, _good_sidecar(tmp)), "stat")
        assert r["passed"], r["blocking"]


def test_missing_effect_size_blocks():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        del data["effect_size"]
        r = check_artifact(_write(tmp, data), "stat")
        assert not r["passed"]
        assert "STAT.effect_size" in _blocked_gates(r)


def test_missing_ci_blocks():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        data["effect_size"]["ci"] = None
        r = check_artifact(_write(tmp, data), "stat")
        assert not r["passed"]


def test_nan_effect_blocks():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        data["effect_size"]["value"] = float("nan")
        r = check_artifact(_write(tmp, data), "stat")
        assert not r["passed"]


def test_missing_assumptions_blocks():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        data["assumptions_checked"] = []
        r = check_artifact(_write(tmp, data), "stat")
        assert not r["passed"]
        assert "STAT.assumptions" in _blocked_gates(r)


def test_missing_repro_script_file_blocks():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        (tmp / "repro_x.py").unlink()   # 脚本声明了但文件不存在
        r = check_artifact(_write(tmp, data), "stat")
        assert not r["passed"]
        assert "REPRO.script" in _blocked_gates(r)


def test_missing_sidecar_fails_closed():
    r = check_artifact("/nonexistent/result.json", "stat")
    assert not r["passed"]


def test_unparsable_sidecar_fails_closed():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        r = check_artifact(str(p), "stat")
        assert not r["passed"]


def test_stat_kind_not_gated_by_pipeline_rules():
    """单次 stat 不应被 analysis_pipeline 级规则(如 robustness≥2)阻断。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        data["robustness"] = []   # pipeline 级才强制 ≥2
        r = check_artifact(_write(tmp, data), "stat")
        assert r["passed"], r["blocking"]


def test_pipeline_kind_requires_robustness():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        data = _good_sidecar(tmp)
        data["robustness"] = ["只有一项"]
        r = check_artifact(_write(tmp, data), "pipeline")
        assert not r["passed"]
        assert "STAT.rigor" in _blocked_gates(r)


# ---------------------------------------------------------------------------
# loop 控制点:verdict fail-closed / 行首 DECISION_REQUEST
# ---------------------------------------------------------------------------

def test_verdict_pass():
    assert parse_verdict("…审查通过\nVERDICT: PASS") == "PASS"


def test_verdict_block():
    assert parse_verdict("有问题\nVERDICT: BLOCK") == "BLOCK"


def test_verdict_missing_fails_closed():
    # 旧版关键词法在这两类输出上会误判;新版一律 BLOCK
    assert parse_verdict("Blocking Issues: 无,一切正常") == "BLOCK"
    assert parse_verdict("没有阻断问题,通过") == "BLOCK"
    assert parse_verdict("") == "BLOCK"


def test_verdict_takes_last():
    assert parse_verdict("VERDICT: BLOCK\n修复后复核…\nVERDICT: PASS") == "PASS"


def test_verdict_fullwidth_colon():
    assert parse_verdict("VERDICT:PASS") == "PASS"


def test_decision_request_line_start_only():
    assert has_decision_request("分析中…\nDECISION_REQUEST: 需剔除 3 个异常值")
    assert has_decision_request("  DECISION_REQUEST: 缩进也算")
    # 仅提及该词不触发(旧版会误触发)
    assert not has_decision_request("本步无需 DECISION_REQUEST,继续。")
    assert not has_decision_request("")


# ---------------------------------------------------------------------------
# data/raw 快照
# ---------------------------------------------------------------------------

def test_snapshot_detects_mutation():
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        raw = proj / "data" / "raw"
        raw.mkdir(parents=True)
        f = raw / "a.csv"
        f.write_text("x\n1\n", encoding="utf-8")
        s1 = snapshot_raw(proj)
        assert s1 == snapshot_raw(proj)       # 稳定
        f.write_text("x\n1\n2\n", encoding="utf-8")
        assert s1 != snapshot_raw(proj)        # 改动可检出


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {name}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
