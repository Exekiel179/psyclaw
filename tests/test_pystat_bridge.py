"""workflow 分析步接 pystat MCP(v0.10 feat-053)——纯映射 + 注入客户端,离线可测。"""
from __future__ import annotations

from psyclaw.workflows import pystat_bridge as PB


# --- rec_to_pystat_call(纯映射) ------------------------------------------------

def test_map_ttest():
    call = PB.rec_to_pystat_call({"analysis": "ttest", "dv": "rt", "group": "cond"}, "d.csv")
    assert call == ("pystat_ttest", {"csv_path": "d.csv", "dv": "rt", "group": "cond"})


def test_map_anova_group_to_between():
    call = PB.rec_to_pystat_call({"analysis": "anova", "dv": "y", "group": "grp"}, "d.csv")
    assert call == ("pystat_anova", {"csv_path": "d.csv", "dv": "y", "between": "grp"})


def test_map_regression_iv_joined():
    call = PB.rec_to_pystat_call({"analysis": "regression", "dv": "y",
                                  "iv": ["x1", "x2", "x3"]}, "d.csv")
    assert call == ("pystat_regression",
                    {"csv_path": "d.csv", "dv": "y", "predictors": "x1,x2,x3"})


def test_map_correlation():
    call = PB.rec_to_pystat_call({"analysis": "correlation", "x": "a", "y": "b"}, "d.csv")
    assert call == ("pystat_correlation", {"csv_path": "d.csv", "x": "a", "y": "b"})


def test_map_descriptives():
    call = PB.rec_to_pystat_call({"analysis": "descriptives"}, "d.csv")
    assert call == ("pystat_describe", {"csv_path": "d.csv"})


def test_map_unknown_returns_none():
    assert PB.rec_to_pystat_call({"analysis": "mystery"}, "d.csv") is None
    assert PB.rec_to_pystat_call({}, "d.csv") is None


# --- run_via_pystat(注入 fake 客户端) -----------------------------------------

class _FakeClient:
    def __init__(self, result="结果文本", boom=False):
        self._result = result
        self._boom = boom
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def call_tool(self, name, args):
        if self._boom:
            raise RuntimeError("mcp down")
        self.calls.append((name, args))
        return self._result


def test_run_via_pystat_calls_correct_tool():
    fc = _FakeClient(result="t=2.1, d=0.5, CI95=[...]")
    out = PB.run_via_pystat({"analysis": "ttest", "dv": "rt", "group": "cond"},
                            "d.csv", client_factory=lambda: fc)
    assert out == "t=2.1, d=0.5, CI95=[...]"
    assert fc.calls == [("pystat_ttest",
                         {"csv_path": "d.csv", "dv": "rt", "group": "cond"})]


def test_run_via_pystat_no_client_returns_none():
    out = PB.run_via_pystat({"analysis": "ttest", "dv": "y", "group": "g"},
                            "d.csv", client_factory=lambda: None)
    assert out is None


def test_run_via_pystat_unmappable_returns_none():
    called = []
    PB.run_via_pystat({"analysis": "mystery"}, "d.csv",
                      client_factory=lambda: called.append(1))
    assert called == []          # 不可映射时根本不建客户端


def test_run_via_pystat_exception_is_swallowed():
    out = PB.run_via_pystat({"analysis": "descriptives"}, "d.csv",
                            client_factory=lambda: _FakeClient(boom=True))
    assert out is None


def test_run_via_pystat_empty_result_is_none():
    out = PB.run_via_pystat({"analysis": "descriptives"}, "d.csv",
                            client_factory=lambda: _FakeClient(result=""))
    assert out is None


# --- step_analysis 端到端(注入桩,tmp 工程) -----------------------------------

def test_step_analysis_writes_result_when_pystat_runs(tmp_path, monkeypatch):
    import types
    from psyclaw.workflows import steps_analysis as SA

    # 造最小 CSV(两组 + 连续列 → 推荐 ttest)
    csv = tmp_path / "d.csv"
    csv.write_text("cond,rt\nA,1.0\nA,1.2\nB,2.0\nB,2.3\n", encoding="utf-8")

    ctx = types.SimpleNamespace(
        data={"data_csv": str(csv)}, artifacts={}, project=tmp_path)
    ctx.data["profile"] = SA.profile_data(str(csv))

    # 注入:pystat 桥直接返回结果(不起真 MCP)
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_via_pystat",
                        lambda rec, path: "PYSTAT 结果:t=..., d=..., CI95=[...]")

    out = SA.step_analysis(ctx)
    assert out["ran_via_pystat"] is True
    res = tmp_path / "outputs" / "analysis_result.txt"
    assert res.exists() and "PYSTAT" in res.read_text(encoding="utf-8")
    assert (tmp_path / "outputs" / "analysis.py").exists()   # 脚本仍照写


def test_step_analysis_survives_pystat_unavailable(tmp_path, monkeypatch):
    import types
    from psyclaw.workflows import steps_analysis as SA

    csv = tmp_path / "d.csv"
    csv.write_text("cond,rt\nA,1.0\nB,2.0\nA,1.1\nB,2.1\n", encoding="utf-8")
    ctx = types.SimpleNamespace(
        data={"data_csv": str(csv)}, artifacts={}, project=tmp_path)
    ctx.data["profile"] = SA.profile_data(str(csv))

    # pystat 不可用 → 返回 None;step 不应报错,脚本照旧
    monkeypatch.setattr("psyclaw.workflows.pystat_bridge.run_via_pystat",
                        lambda rec, path: None)
    out = SA.step_analysis(ctx)
    assert out["ran_via_pystat"] is False
    assert (tmp_path / "outputs" / "analysis.py").exists()
    assert not (tmp_path / "outputs" / "analysis_result.txt").exists()
