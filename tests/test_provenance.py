"""复现溯源包测试 — 环境采集 / 构造 / 落盘 / data-raw 边界 / 门禁对接。"""

from __future__ import annotations

import json

from psyclaw import provenance as P


# ---------------------------------------------------------------------------
# capture_environment
# ---------------------------------------------------------------------------

def test_capture_environment_shape():
    env = P.capture_environment()
    assert env["python"] and "." in env["python"]
    assert env["platform"]
    # 统计库键恒在(值可能为 None,取决于本机是否装了 [stats])
    for name in ("pingouin", "scipy", "statsmodels", "pandas", "numpy"):
        assert name in env["packages"]


# ---------------------------------------------------------------------------
# build_provenance
# ---------------------------------------------------------------------------

def test_build_complete_from_script(tmp_path):
    art = tmp_path / "outputs" / "analysis.py"
    art.parent.mkdir(parents=True)
    art.write_text('"""可复现实证分析(委托 pingouin)。\n推荐分析:ttest。\n"""\nimport pandas\n',
                   encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path))
    assert prov["provenance_complete"] is True
    assert prov["code_present"] is True
    assert prov["artifact_sha256"]
    # 无显式说明 → 从脚本 docstring 派生
    assert "可复现" in prov["description"]


def test_build_incomplete_when_artifact_missing(tmp_path):
    prov = P.build_provenance(str(tmp_path / "nope.py"), description="",
                              project_dir=str(tmp_path))
    assert prov["provenance_complete"] is False
    assert prov["code_present"] is False


def test_explicit_description_wins(tmp_path):
    art = tmp_path / "s.py"
    art.write_text('"""doc"""\n', encoding="utf-8")
    prov = P.build_provenance(str(art), description="独立样本 t 检验",
                              project_dir=str(tmp_path))
    assert prov["description"] == "独立样本 t 检验"


# ---------------------------------------------------------------------------
# 数据指纹 + data/raw 边界
# ---------------------------------------------------------------------------

def test_data_fingerprint_hashes_clean(tmp_path):
    art = tmp_path / "s.py"
    art.write_text('"""d"""', encoding="utf-8")
    clean = tmp_path / "data" / "clean"
    clean.mkdir(parents=True)
    dcsv = clean / "scores.csv"
    dcsv.write_text("a,b\n1,2\n", encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path), data_path=str(dcsv))
    assert prov["data"]["sha256"] and len(prov["data"]["sha256"]) == 64


def test_data_raw_is_never_hashed(tmp_path):
    art = tmp_path / "s.py"
    art.write_text('"""d"""', encoding="utf-8")
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    rcsv = raw / "secret.csv"
    rcsv.write_text("x\n1\n", encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path), data_path=str(rcsv))
    assert prov["data"]["sha256"] is None
    assert "data/raw" in prov["data"]["note"]


def test_provided_fingerprint_used_verbatim(tmp_path):
    art = tmp_path / "s.py"
    art.write_text('"""d"""', encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path),
                              data_path="data/clean/x.csv", data_fingerprint="abc123")
    assert prov["data"]["sha256"] == "abc123"


# ---------------------------------------------------------------------------
# 决策轨迹指针
# ---------------------------------------------------------------------------

def test_history_collects_existing_pointers(tmp_path):
    art = tmp_path / "s.py"
    art.write_text('"""d"""', encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "plan.md").write_text("plan", encoding="utf-8")
    (notes / "workflow_summary.json").write_text("{}", encoding="utf-8")
    prov = P.build_provenance(str(art), project_dir=str(tmp_path))
    assert "notes/plan.md" in prov["history"]
    assert "notes/workflow_summary.json" in prov["history"]
    assert prov["has_history"] is True


# ---------------------------------------------------------------------------
# write_provenance 落盘
# ---------------------------------------------------------------------------

def test_write_provenance_creates_sidecars(tmp_path):
    art = tmp_path / "outputs" / "analysis.py"
    art.parent.mkdir(parents=True)
    art.write_text('"""可复现分析。"""\n', encoding="utf-8")
    prov = P.write_provenance(str(art), project_dir=str(tmp_path))
    sidecar = art.with_suffix(".py.provenance.json")
    assert sidecar.exists()
    assert art.with_suffix(".py.provenance.md").exists()
    loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert loaded["provenance_complete"] is True


# ---------------------------------------------------------------------------
# 门禁对接:REPRO.provenance (trigger provenance_check, kind "provenance")
# ---------------------------------------------------------------------------

def test_gate_blocks_incomplete_provenance(tmp_path):
    from psyclaw.gates.checker import check_artifact
    sc = tmp_path / "analysis.py.provenance.json"
    sc.write_text(json.dumps({"provenance_complete": False}), encoding="utf-8")
    res = check_artifact(str(sc), "provenance")
    assert res["passed"] is False
    assert any(b["gate"] == "REPRO.provenance" for b in res["blocking"])


def test_gate_passes_complete_provenance(tmp_path):
    from psyclaw.gates.checker import check_artifact
    sc = tmp_path / "analysis.py.provenance.json"
    sc.write_text(json.dumps({"provenance_complete": True}), encoding="utf-8")
    res = check_artifact(str(sc), "provenance")
    assert res["passed"] is True
def _script_and_data(tmp_path):
    art = tmp_path / "outputs" / "analysis.py"
    art.parent.mkdir(parents=True)
    art.write_text('"""可复现分析(委托 pingouin)。"""\n', encoding="utf-8")
    data = tmp_path / "data" / "clean" / "study.csv"
    data.parent.mkdir(parents=True)
    data.write_text("cond,score\nA,1\nB,2\n", encoding="utf-8")
    return art, data
class TestReplicationDeclaration:
    def test_complete_declaration_with_statement(self, tmp_path):
        art, data = _script_and_data(tmp_path)
        prov = P.build_provenance(str(art), project_dir=str(tmp_path),
                                  data_path=str(data), journal="psych-science")
        decl = prov["replication_package"]
        assert prov["data_availability_required"] is True
        assert prov["replication_package_declared"] is True
        assert decl["complete"] and not decl["missing"]
        assert "replication package" in decl["statement"]
        assert prov["artifact_sha256"][:16] in decl["statement"]
        kinds = {i["kind"] for i in decl["items"]}
        assert kinds == {"analysis_script", "data", "environment"}
    def test_required_journal_without_data_not_declared(self, tmp_path):
        art, _ = _script_and_data(tmp_path)
        prov = P.build_provenance(str(art), project_dir=str(tmp_path),
                                  journal="psych-science")
        assert prov["replication_package_declared"] is False
        assert prov["provenance_complete"] is False
        assert any("数据指纹" in m for m in prov["replication_package"]["missing"])
        assert prov["replication_package"]["statement"] == ""
    def test_encouraged_journal_declaration_optional(self, tmp_path):
        """非强制期刊:声明照常生成(可自愿附),但不影响溯源完整性。"""
        art, _ = _script_and_data(tmp_path)
        prov = P.build_provenance(str(art), project_dir=str(tmp_path),
                                  journal="xinlixuebao")
        assert prov["data_availability_required"] is False
        assert prov["replication_package_declared"] is False   # 没数据 → 声明不完整
        assert prov["provenance_complete"] is True             # 但非强制,不拦
    def test_md_renders_statement_or_missing(self, tmp_path):
        art, data = _script_and_data(tmp_path)
        P.write_provenance(str(art), project_dir=str(tmp_path),
                           data_path=str(data), journal="psych-science")
        md = art.with_suffix(".py.provenance.md").read_text(encoding="utf-8")
        assert "Replication package 声明" in md and "replication package" in md
        art2 = tmp_path / "outputs" / "meta.py"
        art2.write_text('"""元分析脚本。"""\n', encoding="utf-8")
        P.write_provenance(str(art2), project_dir=str(tmp_path),
                           journal="psych-science")
        md2 = art2.with_suffix(".py.provenance.md").read_text(encoding="utf-8")
        assert "强制 replication-package 声明" in md2 and "数据指纹" in md2
class TestReplicationGate:
    def test_gate_blocks_required_but_undeclared(self, tmp_path):
        from psyclaw.gates.checker import check_artifact
        sc = tmp_path / "analysis.py.provenance.json"
        sc.write_text(json.dumps({"provenance_complete": True,
                                  "data_availability_required": True,
                                  "replication_package_declared": False}),
                      encoding="utf-8")
        res = check_artifact(str(sc), "provenance")
        assert res["passed"] is False
        assert any(b["gate"] == "REPRO.replication_package" for b in res["blocking"])
    def test_gate_passes_required_and_declared(self, tmp_path):
        from psyclaw.gates.checker import check_artifact
        sc = tmp_path / "analysis.py.provenance.json"
        sc.write_text(json.dumps({"provenance_complete": True,
                                  "data_availability_required": True,
                                  "replication_package_declared": True}),
                      encoding="utf-8")
        res = check_artifact(str(sc), "provenance")
        assert res["passed"] is True
    def test_gate_passes_not_required(self, tmp_path):
        """非强制期刊 / 无期刊定制的旧 sidecar:不因缺声明被拦(不破坏既有契约)。"""
        from psyclaw.gates.checker import check_artifact
        sc = tmp_path / "analysis.py.provenance.json"
        sc.write_text(json.dumps({"provenance_complete": True}), encoding="utf-8")
        res = check_artifact(str(sc), "provenance")
        assert res["passed"] is True
    def test_end_to_end_required_journal(self, tmp_path):
        """write_provenance(required 期刊+数据) → 真 sidecar 过全部 provenance 门禁。"""
        from psyclaw.gates.checker import check_artifact
        art, data = _script_and_data(tmp_path)
        prov = P.write_provenance(str(art), project_dir=str(tmp_path),
                                  data_path=str(data), journal="psych-science")
        res = check_artifact(prov["_sidecar"], "provenance")
        assert res["passed"] is True, res["blocking"]
